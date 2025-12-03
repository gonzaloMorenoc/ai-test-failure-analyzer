"""
CLI principal del AI Test Failure Analyzer.

Características:
- Exit codes para integración CI/CD
- Soporte de configuración externa (YAML + env vars)
- Fingerprinting de errores
- Múltiples formatos de exportación
"""

import argparse
import sys
from pathlib import Path
from typing import Optional, Dict, Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.loaders.junit_loader import load_junit_failures
from src.loaders.cucumber_loader import load_cucumber_failures
from src.loaders.playwright_loader import load_playwright_failures
from src.analyzer import analyze_failures
from src.exporters import export_to_markdown, export_to_html
from src.config import load_config, AnalyzerConfig
from src.fingerprint import (
    group_failures_by_fingerprint,
    get_pattern_summary,
)

console = Console()


# ============================================================================
# EXIT CODES para CI/CD
# ============================================================================
class ExitCode:
    """Códigos de salida para integración con pipelines CI/CD."""
    SUCCESS = 0              # Todo OK, sin fallos
    FAILURES_FOUND = 1       # Hay fallos pero ninguno crítico
    CRITICAL_FAILURES = 2    # Hay fallos críticos
    ANALYSIS_ERROR = 3       # Error durante el análisis
    CONFIG_ERROR = 4         # Error de configuración
    NO_REPORTS_FOUND = 5     # No se encontraron reportes para analizar


def determine_exit_code(
    analysis: str, 
    total_failures: int,
    config: AnalyzerConfig
) -> int:
    """
    Determina el código de salida basado en el análisis y configuración.
    
    Args:
        analysis: Texto del análisis generado por el LLM
        total_failures: Número total de fallos encontrados
        config: Configuración del analizador
        
    Returns:
        Código de salida apropiado
    """
    if total_failures == 0:
        return ExitCode.SUCCESS
    
    # Si está configurado para fallar con cualquier fallo
    if config.ci.fail_on_any_failure:
        return ExitCode.FAILURES_FOUND
    
    # Buscar indicadores de criticidad en el análisis
    if config.ci.fail_on_critical:
        analysis_lower = analysis.lower()
        
        # Patrones que indican problemas críticos
        critical_indicators = [
            'crítico',
            'critical', 
            '🔴',
            'resolver inmediatamente',
            'alta prioridad',
            'bloqueante',
            'blocking'
        ]
        
        critical_count = sum(
            1 for indicator in critical_indicators 
            if indicator in analysis_lower
        )
        
        # Si hay suficientes indicadores críticos
        if critical_count >= config.ci.critical_threshold:
            return ExitCode.CRITICAL_FAILURES
    
    return ExitCode.FAILURES_FOUND


def print_summary(junit_count: int, cucumber_count: int, playwright_count: int):
    """Muestra un resumen visual de los tests fallidos encontrados."""
    table = Table(
        title="📊 Resumen de Tests Fallidos", 
        show_header=True, 
        header_style="bold magenta"
    )
    table.add_column("Tipo de Reporte", style="cyan", width=20)
    table.add_column("Tests Fallidos", justify="right", style="yellow")
    
    table.add_row("JUnit", str(junit_count))
    table.add_row("Cucumber", str(cucumber_count))
    table.add_row("Playwright", str(playwright_count))
    table.add_row("", "")
    table.add_row(
        "TOTAL", 
        str(junit_count + cucumber_count + playwright_count), 
        style="bold green"
    )
    
    console.print(table)
    console.print()


def print_fingerprint_summary(summary: Dict[str, Any]):
    """Muestra resumen de fingerprinting en consola."""
    if summary['unique_patterns'] == 0:
        return
    
    console.print()
    console.print("[bold cyan]🔍 Análisis de Patrones (Fingerprinting)[/bold cyan]")
    console.print(f"   • Patrones únicos: [yellow]{summary['unique_patterns']}[/yellow]")
    console.print(f"   • Reducción de ruido: [green]{summary['noise_reduction_percent']}%[/green]")
    
    if summary['repeated_patterns']:
        console.print(f"   • Patrones repetidos: [red]{summary['repeated_patterns_count']}[/red]")
        console.print()
        console.print("   [dim]Errores que aparecen múltiples veces:[/dim]")
        for pattern in summary['repeated_patterns'][:3]:  # Mostrar top 3
            console.print(f"      [{pattern['count']}x] {pattern['normalized_error'][:60]}...")
    
    console.print()


def print_exit_code_info(exit_code: int):
    """Muestra información sobre el código de salida."""
    code_info = {
        ExitCode.SUCCESS: ("✅ SUCCESS", "green", "Sin fallos detectados"),
        ExitCode.FAILURES_FOUND: ("⚠️  FAILURES", "yellow", "Fallos encontrados (no críticos)"),
        ExitCode.CRITICAL_FAILURES: ("❌ CRITICAL", "red", "Fallos críticos detectados"),
        ExitCode.ANALYSIS_ERROR: ("💥 ERROR", "red", "Error durante el análisis"),
        ExitCode.CONFIG_ERROR: ("⚙️  CONFIG ERROR", "red", "Error de configuración"),
        ExitCode.NO_REPORTS_FOUND: ("📭 NO REPORTS", "yellow", "No se encontraron reportes"),
    }
    
    label, color, description = code_info.get(
        exit_code, 
        ("❓ UNKNOWN", "white", "Código desconocido")
    )
    
    console.print()
    console.print(Panel(
        f"[bold {color}]{label}[/bold {color}] (exit code: {exit_code})\n"
        f"[dim]{description}[/dim]",
        title="Estado CI/CD",
        border_style=color
    ))


def create_argument_parser() -> argparse.ArgumentParser:
    """Crea el parser de argumentos CLI."""
    parser = argparse.ArgumentParser(
        description="🔍 AI Test Failure Analyzer - Análisis inteligente de fallos de tests",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos de uso:
  %(prog)s
  %(prog)s --junit mi-junit.xml --cucumber mi-cucumber.json
  %(prog)s --playwright playwright-report.json --model mistral
  %(prog)s --output-html output/mi-reporte.html
  %(prog)s --config mi-config.yaml
  %(prog)s --fail-on-critical --no-fingerprint

Variables de entorno:
  ANALYZER_LLM_PROVIDER   Provider LLM (ollama, openai, anthropic)
  ANALYZER_LLM_MODEL      Modelo a usar (llama3, gpt-4o-mini, etc.)
  ANALYZER_LLM_URL        URL del servicio LLM
  ANALYZER_API_KEY        API key para OpenAI/Anthropic
  ANALYZER_OUTPUT_DIR     Directorio de salida
  ANALYZER_LANGUAGE       Idioma del análisis (es, en)

Exit codes:
  0 - Success (sin fallos)
  1 - Fallos encontrados (no críticos)
  2 - Fallos críticos detectados
  3 - Error durante el análisis
  4 - Error de configuración
  5 - No se encontraron reportes
        """
    )
    
    # === Argumentos de entrada ===
    input_group = parser.add_argument_group('Archivos de entrada')
    input_group.add_argument(
        "--junit", type=str, default="junit-report.xml",
        help="Path al reporte JUnit XML (default: junit-report.xml)"
    )
    input_group.add_argument(
        "--cucumber", type=str, default="cucumber-report.json",
        help="Path al reporte Cucumber JSON (default: cucumber-report.json)"
    )
    input_group.add_argument(
        "--playwright", type=str, default=None,
        help="Path al reporte Playwright JSON"
    )
    
    # === Configuración ===
    config_group = parser.add_argument_group('Configuración')
    config_group.add_argument(
        "--config", type=str, default=None,
        help="Path al archivo de configuración YAML"
    )
    config_group.add_argument(
        "--model", type=str, default=None,
        help="Modelo LLM a usar (override de config)"
    )
    config_group.add_argument(
        "--provider", type=str, choices=['ollama', 'openai', 'anthropic'],
        default=None, help="Provider LLM (override de config)"
    )
    
    # === Opciones de exportación ===
    export_group = parser.add_argument_group('Exportación')
    export_group.add_argument(
        "--output-md", type=str, default=None,
        help="Exportar análisis a Markdown"
    )
    export_group.add_argument(
        "--output-html", type=str, default=None,
        help="Exportar análisis a HTML"
    )
    export_group.add_argument(
        "--no-export", action="store_true",
        help="No auto-exportar (solo mostrar en consola)"
    )
    
    # === Opciones CI/CD ===
    ci_group = parser.add_argument_group('Integración CI/CD')
    ci_group.add_argument(
        "--fail-on-critical", action="store_true",
        help="Exit code 2 solo si hay fallos críticos"
    )
    ci_group.add_argument(
        "--fail-on-any", action="store_true",
        help="Exit code 1 si hay cualquier fallo"
    )
    ci_group.add_argument(
        "--quiet", "-q", action="store_true",
        help="Modo silencioso (solo errores)"
    )
    ci_group.add_argument(
        "--show-exit-code", action="store_true",
        help="Mostrar información del exit code al final"
    )
    
    # === Opciones de análisis ===
    analysis_group = parser.add_argument_group('Opciones de análisis')
    analysis_group.add_argument(
        "--no-fingerprint", action="store_true",
        help="Desactivar fingerprinting de errores"
    )
    analysis_group.add_argument(
        "--max-failures", type=int, default=None,
        help="Máximo de fallos a analizar (para limitar tokens)"
    )
    
    return parser


def main() -> int:
    """
    Función principal del CLI.
    
    Returns:
        Código de salida para el sistema
    """
    parser = create_argument_parser()
    args = parser.parse_args()

    # === Cargar configuración ===
    try:
        config_path = Path(args.config) if args.config else None
        config = load_config(config_path)
        
        # Aplicar overrides de CLI
        if args.model:
            config.llm.model = args.model
        if args.provider:
            config.llm.provider = args.provider
        if args.fail_on_critical:
            config.ci.fail_on_critical = True
        if args.fail_on_any:
            config.ci.fail_on_any_failure = True
        if args.no_fingerprint:
            config.analysis.enable_fingerprinting = False
        if args.max_failures:
            config.analysis.max_failures_to_analyze = args.max_failures
            
    except Exception as e:
        console.print(f"[bold red]❌ Error de configuración:[/bold red] {str(e)}")
        return ExitCode.CONFIG_ERROR

    # === Banner de inicio ===
    if not args.quiet:
        console.print(Panel.fit(
            "[bold cyan]🤖 AI Test Failure Analyzer[/bold cyan]\n"
            f"[dim]Provider: {config.llm.provider} | Model: {config.llm.model}[/dim]",
            border_style="cyan"
        ))
        console.print()

    # === Paths de entrada ===
    junit_path = Path(args.junit)
    cucumber_path = Path(args.cucumber)
    playwright_path = Path(args.playwright) if args.playwright else None

    # === Cargar reportes ===
    if not args.quiet:
        console.print("[bold yellow]📂 Cargando reportes de tests...[/bold yellow]")
    
    junit_failures = load_junit_failures(junit_path)
    if not args.quiet:
        if junit_path.exists():
            console.print(
                f"   ✓ JUnit: [green]{len(junit_failures)} tests fallidos[/green] "
                f"en {junit_path}"
            )
        else:
            console.print(f"   ⚠️  JUnit: [dim]archivo no encontrado ({junit_path})[/dim]")
    
    cucumber_failures = load_cucumber_failures(cucumber_path)
    if not args.quiet:
        if cucumber_path.exists():
            console.print(
                f"   ✓ Cucumber: [green]{len(cucumber_failures)} escenarios fallidos[/green] "
                f"en {cucumber_path}"
            )
        else:
            console.print(f"   ⚠️  Cucumber: [dim]archivo no encontrado ({cucumber_path})[/dim]")
    
    playwright_failures = []
    if playwright_path:
        playwright_failures = load_playwright_failures(playwright_path)
        if not args.quiet:
            if playwright_path.exists():
                console.print(
                    f"   ✓ Playwright: [green]{len(playwright_failures)} tests fallidos[/green] "
                    f"en {playwright_path}"
                )
            else:
                console.print(
                    f"   ⚠️  Playwright: [dim]archivo no encontrado ({playwright_path})[/dim]"
                )
    
    if not args.quiet:
        console.print()

    # === Validar que hay tests fallidos ===
    total_failures = len(junit_failures) + len(cucumber_failures) + len(playwright_failures)
    
    if total_failures == 0:
        if not args.quiet:
            console.print(
                "[bold green]🎉 ¡Excelente! Todos los tests pasaron correctamente.[/bold green]"
            )
        if args.show_exit_code:
            print_exit_code_info(ExitCode.SUCCESS)
        return ExitCode.SUCCESS

    # === Limitar fallos si está configurado ===
    max_failures = config.analysis.max_failures_to_analyze
    if total_failures > max_failures:
        if not args.quiet:
            console.print(
                f"[yellow]⚠️  Limitando análisis a {max_failures} fallos "
                f"(de {total_failures} totales)[/yellow]"
            )
        # Truncar proporcionalmente
        ratio = max_failures / total_failures
        junit_failures = junit_failures[:int(len(junit_failures) * ratio) or len(junit_failures)]
        cucumber_failures = cucumber_failures[:int(len(cucumber_failures) * ratio) or len(cucumber_failures)]
        playwright_failures = playwright_failures[:int(len(playwright_failures) * ratio) or len(playwright_failures)]

    # === Fingerprinting ===
    fingerprint_summary = None
    if config.analysis.enable_fingerprinting:
        # Agrupar todos los fallos por fingerprint
        all_grouped = {}
        
        junit_grouped = group_failures_by_fingerprint(junit_failures, "junit")
        cucumber_grouped = group_failures_by_fingerprint(cucumber_failures, "cucumber")
        playwright_grouped = group_failures_by_fingerprint(playwright_failures, "playwright")
        
        # Merge de grupos
        for grouped in [junit_grouped, cucumber_grouped, playwright_grouped]:
            for fp, data in grouped.items():
                if fp in all_grouped:
                    all_grouped[fp]['count'] += data['count']
                    all_grouped[fp]['failures'].extend(data['failures'])
                    all_grouped[fp]['source_types'] = list(
                        set(all_grouped[fp]['source_types']) | set(data['source_types'])
                    )
                else:
                    all_grouped[fp] = data
        
        fingerprint_summary = get_pattern_summary(all_grouped)
        
        if not args.quiet:
            print_fingerprint_summary(fingerprint_summary)

    # === Mostrar resumen ===
    if not args.quiet:
        print_summary(len(junit_failures), len(cucumber_failures), len(playwright_failures))

    # === Analizar con IA ===
    if not args.quiet:
        console.print(f"[bold cyan]🧠 Iniciando análisis con {config.llm.model}...[/bold cyan]")
        console.print()
    
    try:
        analysis_markdown = analyze_failures(
            junit_failures=junit_failures,
            cucumber_failures=cucumber_failures,
            playwright_failures=playwright_failures,
            model=config.llm.model,
            fingerprint_summary=fingerprint_summary,
        )
    except Exception as e:
        console.print(f"[bold red]❌ Error durante el análisis:[/bold red] {str(e)}")
        if args.show_exit_code:
            print_exit_code_info(ExitCode.ANALYSIS_ERROR)
        return ExitCode.ANALYSIS_ERROR

    # === Mostrar análisis ===
    if not args.quiet:
        console.print()
        console.print(Panel(
            "[bold green]✅ Análisis Completado[/bold green]",
            border_style="green"
        ))
        console.print()
        console.print("[bold]📝 Resultado del análisis:[/bold]")
        console.print("─" * 80)
        console.print(analysis_markdown)
        console.print("─" * 80)
        console.print()

    # === Exportar resultados ===
    if not args.no_export:
        if not args.quiet:
            console.print("[bold cyan]💾 Exportando resultados...[/bold cyan]")
        
        # Markdown
        md_path = Path(args.output_md) if args.output_md else None
        md_file = export_to_markdown(analysis_markdown, md_path)
        if not args.quiet:
            console.print(f"   ✓ Markdown guardado en: [green]{md_file}[/green]")
        
        # HTML
        html_path = Path(args.output_html) if args.output_html else None
        html_file = export_to_html(analysis_markdown, html_path)
        if not args.quiet:
            console.print(f"   ✓ HTML guardado en: [green]{html_file}[/green]")
        
        if not args.quiet:
            console.print()

    # === Determinar exit code ===
    exit_code = determine_exit_code(analysis_markdown, total_failures, config)

    # === Mensaje final ===
    if not args.quiet:
        if exit_code == ExitCode.CRITICAL_FAILURES:
            console.print(Panel.fit(
                "[bold red]⚠️  Se detectaron fallos críticos[/bold red]",
                border_style="red"
            ))
        else:
            console.print(Panel.fit(
                "[bold green]✨ Análisis finalizado[/bold green]",
                border_style="green"
            ))
    
    if args.show_exit_code:
        print_exit_code_info(exit_code)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())