import argparse
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.loaders.junit_loader import load_junit_failures
from src.loaders.cucumber_loader import load_cucumber_failures
from src.loaders.playwright_loader import load_playwright_failures
from src.analyzer import analyze_failures
from src.exporters import export_to_markdown, export_to_html

console = Console()


def print_summary(junit_count: int, cucumber_count: int, playwright_count: int):
    """Muestra un resumen visual de los tests fallidos encontrados."""
    table = Table(title="📊 Resumen de Tests Fallidos", show_header=True, header_style="bold magenta")
    table.add_column("Tipo de Reporte", style="cyan", width=20)
    table.add_column("Tests Fallidos", justify="right", style="yellow")
    
    table.add_row("JUnit", str(junit_count))
    table.add_row("Cucumber", str(cucumber_count))
    table.add_row("Playwright", str(playwright_count))
    table.add_row("", "")
    table.add_row("TOTAL", str(junit_count + cucumber_count + playwright_count), style="bold green")
    
    console.print(table)
    console.print()


def main():
    parser = argparse.ArgumentParser(
        description="🔍 AI Test Failure Analyzer using Ollama",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos de uso:
  python src/cli.py
  python src/cli.py --junit mi-junit.xml --cucumber mi-cucumber.json
  python src/cli.py --playwright playwright-report.json --model mistral
  python src/cli.py --output-html output/mi-reporte.html
        """
    )
    
    # Argumentos de entrada
    parser.add_argument("--junit", type=str, default="junit-report.xml",
                        help="Path to JUnit XML report")
    parser.add_argument("--cucumber", type=str, default="cucumber-report.json",
                        help="Path to Cucumber JSON report")
    parser.add_argument("--playwright", type=str, default=None,
                        help="Path to Playwright JSON report")
    
    # Configuración del modelo
    parser.add_argument("--model", type=str, default="llama3",
                        help="Ollama model name (e.g. llama3, mistral, codellama)")
    
    # Opciones de exportación
    parser.add_argument("--output-md", type=str, default=None,
                        help="Export analysis to Markdown file (default: output/analysis-{timestamp}.md)")
    parser.add_argument("--output-html", type=str, default=None,
                        help="Export analysis to HTML file (default: output/analysis-{timestamp}.html)")
    parser.add_argument("--no-export", action="store_true",
                        help="Don't auto-export to files (only print to console)")

    args = parser.parse_args()

    # Banner de inicio
    console.print(Panel.fit(
        "[bold cyan]🤖 AI Test Failure Analyzer[/bold cyan]\n"
        "[dim]Powered by Ollama[/dim]",
        border_style="cyan"
    ))
    console.print()

    # Paths
    junit_path = Path(args.junit)
    cucumber_path = Path(args.cucumber)
    playwright_path = Path(args.playwright) if args.playwright else None

    # Cargar reportes
    console.print("[bold yellow]📂 Cargando reportes de tests...[/bold yellow]")
    
    junit_failures = load_junit_failures(junit_path)
    if junit_path.exists():
        console.print(f"   ✓ JUnit: [green]{len(junit_failures)} tests fallidos[/green] en {junit_path}")
    else:
        console.print(f"   ⚠️  JUnit: [dim]archivo no encontrado ({junit_path})[/dim]")
    
    cucumber_failures = load_cucumber_failures(cucumber_path)
    if cucumber_path.exists():
        console.print(f"   ✓ Cucumber: [green]{len(cucumber_failures)} escenarios fallidos[/green] en {cucumber_path}")
    else:
        console.print(f"   ⚠️  Cucumber: [dim]archivo no encontrado ({cucumber_path})[/dim]")
    
    playwright_failures = []
    if playwright_path:
        playwright_failures = load_playwright_failures(playwright_path)
        if playwright_path.exists():
            console.print(f"   ✓ Playwright: [green]{len(playwright_failures)} tests fallidos[/green] en {playwright_path}")
        else:
            console.print(f"   ⚠️  Playwright: [dim]archivo no encontrado ({playwright_path})[/dim]")
    
    console.print()

    # Validar que hay tests fallidos
    total_failures = len(junit_failures) + len(cucumber_failures) + len(playwright_failures)
    
    if total_failures == 0:
        console.print("[bold green]🎉 ¡Excelente! Todos los tests pasaron correctamente.[/bold green]")
        return

    # Mostrar resumen
    print_summary(len(junit_failures), len(cucumber_failures), len(playwright_failures))

    # Analizar con IA
    console.print(f"[bold cyan]🧠 Iniciando análisis con modelo: {args.model}[/bold cyan]")
    console.print()
    
    try:
        analysis_markdown = analyze_failures(
            junit_failures=junit_failures,
            cucumber_failures=cucumber_failures,
            playwright_failures=playwright_failures,
            model=args.model,
        )
    except Exception as e:
        console.print(f"[bold red]❌ Error durante el análisis:[/bold red] {str(e)}")
        return

    # Mostrar análisis en consola
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

    # Exportar resultados
    if not args.no_export:
        console.print("[bold cyan]💾 Exportando resultados...[/bold cyan]")
        
        # Exportar a Markdown
        if args.output_md:
            md_path = Path(args.output_md)
        else:
            md_path = None
        
        md_file = export_to_markdown(analysis_markdown, md_path)
        console.print(f"   ✓ Markdown guardado en: [green]{md_file}[/green]")
        
        # Exportar a HTML
        if args.output_html:
            html_path = Path(args.output_html)
        else:
            html_path = None
        
        html_file = export_to_html(analysis_markdown, html_path)
        console.print(f"   ✓ HTML guardado en: [green]{html_file}[/green]")
        console.print()

    # Mensaje final
    console.print(Panel.fit(
        "[bold green]✨ Análisis finalizado con éxito[/bold green]",
        border_style="green"
    ))


if __name__ == "__main__":
    main()
