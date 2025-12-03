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
from src.history import AnalysisHistory, RegressionInfo
from src.flaky_detector import (
    FlakyDetector,
    FlakyAnalysisReport,
    FlakinessSeverity,
    format_flaky_report_console,
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
    REGRESSION_DETECTED = 6  # Regresión detectada (nuevos fallos)
    CRITICAL_FLAKY = 7       # Tests flaky críticos detectados


def determine_exit_code(
    analysis: str, 
    total_failures: int,
    config: AnalyzerConfig,
    regression_info: Optional[RegressionInfo] = None,
    flaky_report: Optional[FlakyAnalysisReport] = None
) -> int:
    """
    Determina el código de salida basado en el análisis y configuración.
    
    Args:
        analysis: Texto del análisis generado por el LLM
        total_failures: Número total de fallos encontrados
        config: Configuración del analizador
        regression_info: Información de regresión (opcional)
        flaky_report: Reporte de flaky tests (opcional)
        
    Returns:
        Código de salida apropiado
    """
    if total_failures == 0:
        return ExitCode.SUCCESS
    
    # Verificar flaky críticos si está configurado
    if flaky_report and config.flaky.fail_on_critical_flaky:
        if flaky_report.critical_count > 0:
            return ExitCode.CRITICAL_FLAKY
    
    # Verificar regresiones si hay info histórica
    if regression_info and not regression_info.is_first_run:
        if regression_info.new_failures and config.ci.fail_on_critical:
            # Nuevos fallos = posible regresión
            return ExitCode.REGRESSION_DETECTED
    
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


def print_flaky_summary(report: FlakyAnalysisReport):
    """Muestra resumen de tests flaky en consola."""
    console.print()
    console.print("[bold magenta]🎲 Detección de Tests Flaky[/bold magenta]")
    console.print(f"   • Ejecuciones analizadas: [cyan]{report.runs_analyzed}[/cyan]")
    
    if report.runs_analyzed < 3:
        console.print("   [dim]Se necesitan al menos 3 ejecuciones para detectar flaky tests[/dim]")
        console.print()
        return
    
    if report.total_flaky_tests == 0:
        console.print("   [green]✓ No se detectaron tests flaky significativos[/green]")
        console.print()
        return
    
    console.print(f"   • Tests flaky detectados: [yellow]{report.total_flaky_tests}[/yellow]")
    console.print(f"   • Score promedio: [cyan]{report.avg_flakiness_score}/100[/cyan]")
    
    # Mostrar conteo por severidad
    severity_parts = []
    if report.critical_count > 0:
        severity_parts.append(f"[red]{report.critical_count} críticos[/red]")
    if report.high_count > 0:
        severity_parts.append(f"[orange1]{report.high_count} altos[/orange1]")
    if report.medium_count > 0:
        severity_parts.append(f"[yellow]{report.medium_count} medios[/yellow]")
    if report.low_count > 0:
        severity_parts.append(f"[green]{report.low_count} bajos[/green]")
    
    if severity_parts:
        console.print(f"   • Severidad: {', '.join(severity_parts)}")
    
    console.print()
    
    # Mostrar top 3 tests más flaky
    if report.flaky_tests:
        console.print("   [dim]Tests más inestables:[/dim]")
        for i, test in enumerate(report.flaky_tests[:3], 1):
            severity_color = {
                FlakinessSeverity.CRITICAL: "red",
                FlakinessSeverity.HIGH: "orange1",
                FlakinessSeverity.MEDIUM: "yellow",
                FlakinessSeverity.LOW: "green"
            }
            color = severity_color.get(test.severity, "white")
            status = "❌" if test.currently_failing else "✅"
            console.print(
                f"      {i}. [{color}]{test.test_name[:45]}[/{color}] "
                f"- Score: {test.flakiness_score} - {test.failure_rate}% fallo {status}"
            )
        
        if report.total_flaky_tests > 3:
            console.print(f"      [dim]... y {report.total_flaky_tests - 3} más[/dim]")
    
    console.print()


def print_history_summary(regression_info: RegressionInfo):
    """Muestra resumen del histórico en consola."""
    console.print()
    console.print("[bold blue]📊 Comparación Histórica[/bold blue]")
    
    if regression_info.is_first_run:
        console.print("   [dim]Primera ejecución - no hay datos históricos[/dim]")
        console.print()
        return
    
    # Mostrar tendencia
    trend_display = {
        "improving": ("✅ MEJORANDO", "green"),
        "degrading": ("⚠️  EMPEORANDO", "red"),
        "stable": ("➡️  ESTABLE", "yellow")
    }
    trend_text, trend_color = trend_display.get(
        regression_info.trend, 
        ("? DESCONOCIDO", "white")
    )
    console.print(f"   • Tendencia: [{trend_color}]{trend_text}[/{trend_color}]")
    
    # Mostrar cambios
    if regression_info.new_failures:
        console.print(f"   • Nuevos fallos: [red]{len(regression_info.new_failures)}[/red] (⚠️  posibles regresiones)")
    if regression_info.fixed_failures:
        console.print(f"   • Fallos corregidos: [green]{len(regression_info.fixed_failures)}[/green]")
    if regression_info.persistent_failures:
        console.print(f"   • Fallos persistentes: [yellow]{len(regression_info.persistent_failures)}[/yellow]")
    
    # Mostrar info de run anterior
    if regression_info.previous_run:
        prev = regression_info.previous_run
        console.print(f"   • Run anterior: {prev.total_failures} fallos ")
        if prev.git_commit:
            console.print(f"      [dim]Commit: {prev.git_commit}[/dim]")
    
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
        ExitCode.REGRESSION_DETECTED: ("🚨 REGRESSION", "red", "Regresión detectada (nuevos fallos)"),
        ExitCode.CRITICAL_FLAKY: ("🎲 CRITICAL FLAKY", "red", "Tests flaky críticos detectados"),
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
    
    # === Opciones de histórico ===
    history_group = parser.add_argument_group('Histórico y regresiones')
    history_group.add_argument(
        "--enable-history", action="store_true",
        help="Habilitar tracking de histórico para detectar regresiones"
    )
    history_group.add_argument(
        "--no-history", action="store_true",
        help="Desactivar histórico (override de config)"
    )
    history_group.add_argument(
        "--history-db", type=str, default=None,
        help="Path a la base de datos de histórico (default: .analyzer_history.db)"
    )
    
    # === Opciones de Flaky Detection ===
    flaky_group = parser.add_argument_group('Detección de tests flaky')
    flaky_group.add_argument(
        "--enable-flaky", action="store_true",
        help="Habilitar detección de tests flaky (requiere histórico)"
    )
    flaky_group.add_argument(
        "--no-flaky", action="store_true",
        help="Desactivar detección de flaky (override de config)"
    )
    flaky_group.add_argument(
        "--flaky-window", type=int, default=None,
        help="Número de ejecuciones a analizar para flaky (default: 20)"
    )
    flaky_group.add_argument(
        "--flaky-min-score", type=float, default=None,
        help="Score mínimo para considerar un test como flaky (default: 20.0)"
    )
    flaky_group.add_argument(
        "--flaky-report-only", action="store_true",
        help="Solo generar reporte de flaky tests (sin análisis LLM)"
    )
    flaky_group.add_argument(
        "--fail-on-critical-flaky", action="store_true",
        help="Exit code 7 si hay tests flaky críticos"
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
        
        # Overrides de histórico
        if args.enable_history:
            config.analysis.enable_historical = True
        if args.no_history:
            config.analysis.enable_historical = False
        if args.history_db:
            config.analysis.history_db_path = Path(args.history_db)
        
        # Overrides de flaky
        if args.enable_flaky:
            config.flaky.enable_flaky_detection = True
            # Flaky requiere histórico
            config.analysis.enable_historical = True
        if args.no_flaky:
            config.flaky.enable_flaky_detection = False
        if args.flaky_window:
            config.flaky.window_size = args.flaky_window
        if args.flaky_min_score:
            config.flaky.min_flakiness_score = args.flaky_min_score
        if args.fail_on_critical_flaky:
            config.flaky.fail_on_critical_flaky = True
            
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
    all_grouped = {}
    current_fingerprints = []
    
    if config.analysis.enable_fingerprinting:
        # Agrupar todos los fallos por fingerprint
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
        
        current_fingerprints = list(all_grouped.keys())
        fingerprint_summary = get_pattern_summary(all_grouped)
        
        if not args.quiet:
            print_fingerprint_summary(fingerprint_summary)

    # === Histórico y Regresión ===
    regression_info = None
    history = None
    
    if config.analysis.enable_historical:
        try:
            history = AnalysisHistory(config.analysis.history_db_path)
            
            # Obtener info de regresión antes de registrar el run actual
            regression_info = history.get_regression_info(current_fingerprints)
            
            if not args.quiet:
                print_history_summary(regression_info)
                
        except Exception as e:
            if not args.quiet:
                console.print(f"[yellow]⚠️  Error al acceder al histórico: {e}[/yellow]")
                console.print("   [dim]Continuando sin datos históricos...[/dim]")
                console.print()

    # === Detección de Flaky Tests ===
    flaky_report = None
    flaky_prompt_text = ""
    
    if config.flaky.enable_flaky_detection and config.analysis.enable_historical:
        try:
            flaky_detector = FlakyDetector(config.analysis.history_db_path)
            
            flaky_report = flaky_detector.analyze(
                window_size=config.flaky.window_size,
                days=config.flaky.window_days,
                min_appearances=config.flaky.min_appearances,
                min_flakiness_score=config.flaky.min_flakiness_score,
                current_fingerprints=current_fingerprints
            )
            
            if not args.quiet:
                print_flaky_summary(flaky_report)
            
            # Generar texto para el prompt del LLM
            if config.flaky.include_in_analysis and flaky_report.total_flaky_tests > 0:
                flaky_prompt_text = flaky_detector.get_flaky_summary_for_prompt(
                    flaky_report, max_tests=5
                )
                
        except Exception as e:
            if not args.quiet:
                console.print(f"[yellow]⚠️  Error en detección de flaky: {e}[/yellow]")
                console.print()

    # === Modo --flaky-report-only ===
    if args.flaky_report_only:
        if not args.quiet:
            if flaky_report:
                console.print()
                console.print(Panel(
                    "[bold magenta]🎲 Reporte de Tests Flaky[/bold magenta]",
                    border_style="magenta"
                ))
                console.print()
                console.print(format_flaky_report_console(flaky_report))
                console.print()
                
                # Mostrar recomendaciones generales
                if flaky_report.general_recommendations:
                    console.print("[bold]Recomendaciones:[/bold]")
                    for rec in flaky_report.general_recommendations:
                        console.print(f"   • {rec}")
                    console.print()
            else:
                console.print("[yellow]No hay suficientes datos para generar reporte de flaky tests.[/yellow]")
                console.print("[dim]Se necesitan al menos 3 ejecuciones con histórico habilitado.[/dim]")
        
        # Determinar exit code para modo flaky-only
        exit_code = ExitCode.SUCCESS
        if flaky_report and config.flaky.fail_on_critical_flaky:
            if flaky_report.critical_count > 0:
                exit_code = ExitCode.CRITICAL_FLAKY
        
        if args.show_exit_code:
            print_exit_code_info(exit_code)
        
        return exit_code

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
            regression_info=regression_info,
            flaky_summary=flaky_prompt_text if flaky_prompt_text else None,
        )
    except Exception as e:
        console.print(f"[bold red]❌ Error durante el análisis:[/bold red] {str(e)}")
        if args.show_exit_code:
            print_exit_code_info(ExitCode.ANALYSIS_ERROR)
        return ExitCode.ANALYSIS_ERROR

    # === Registrar en histórico (después del análisis exitoso) ===
    if history and config.analysis.enable_historical:
        try:
            failures_dict = {
                'junit': junit_failures,
                'cucumber': cucumber_failures,
                'playwright': playwright_failures
            }
            # Extraer primeras líneas del análisis como resumen
            analysis_summary = analysis_markdown[:500] if analysis_markdown else ""
            
            history.record_run(
                failures=failures_dict,
                fingerprints=current_fingerprints,
                fingerprint_details=all_grouped,
                analysis_summary=analysis_summary
            )
            if not args.quiet:
                console.print("[dim]✓ Ejecución registrada en histórico[/dim]")
        except Exception as e:
            if not args.quiet:
                console.print(f"[yellow]⚠️  Error al guardar en histórico: {e}[/yellow]")

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
    exit_code = determine_exit_code(
        analysis_markdown, 
        total_failures, 
        config,
        regression_info=regression_info,
        flaky_report=flaky_report
    )

    # === Mensaje final ===
    if not args.quiet:
        if exit_code == ExitCode.CRITICAL_FAILURES:
            console.print(Panel.fit(
                "[bold red]⚠️  Se detectaron fallos críticos[/bold red]",
                border_style="red"
            ))
        elif exit_code == ExitCode.REGRESSION_DETECTED:
            console.print(Panel.fit(
                "[bold red]🚨 Se detectaron regresiones (nuevos fallos)[/bold red]",
                border_style="red"
            ))
        elif exit_code == ExitCode.CRITICAL_FLAKY:
            console.print(Panel.fit(
                "[bold red]🎲 Se detectaron tests flaky críticos[/bold red]",
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