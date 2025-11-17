from typing import List, Dict, Any
import textwrap
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn

from src.llm.ollama_client import OllamaClient

console = Console()

SYSTEM_PROMPT = """
Eres un analista experto en fallos de testing automatizado.

Tu trabajo es analizar los tests fallidos y proporcionar:
1) Un resumen ejecutivo breve y claro
2) Causas raíz agrupadas por tipo (errores de red, timeouts, bugs funcionales, problemas de infraestructura, etc.)
3) Identificar qué tests podrían ser intermitentes (fallan aleatoriamente) vs fallos consistentes
4) Priorización de problemas (críticos, importantes, menores)

USA ESTE FORMATO OBLIGATORIO:

# Resumen Ejecutivo
[Un párrafo conciso del estado general]

# Análisis de Fallos

## [Categoría 1 - ejemplo: Timeouts de Red]
**Gravedad:** Alta/Media/Baja
**Cantidad:** X tests afectados

**Tests afectados:**
- Test 1: descripción del problema
- Test 2: descripción del problema

**Causa probable:**
[Explicación clara y técnica]

**Evidencia:**
[Citas específicas de los errores]

---

## [Categoría 2 - ejemplo: Errores de Validación]
[Mismo formato]

# Recomendaciones Priorizadas

**🔴 Crítico (resolver inmediatamente):**
- [Acción específica]

**🟡 Importante (resolver pronto):**
- [Acción específica]

**🟢 Menor (revisar cuando sea posible):**
- [Acción específica]

NOTAS IMPORTANTES:
- Responde SIEMPRE en español
- Usa lenguaje técnico pero claro
- NO inventes información
- Si algo no está claro en los datos, dilo
- Sé específico con nombres de tests, endpoints, errores
""".strip()


def build_user_prompt(
    junit_failures: List[Dict[str, Any]],
    cucumber_failures: List[Dict[str, Any]],
    playwright_failures: List[Dict[str, Any]],
) -> str:
    """Build the user prompt with a concise but rich representation of failures."""
    lines = []

    lines.append("# Contexto de ejecución")
    lines.append("")
    lines.append(f"- Total fallos JUnit: {len(junit_failures)}")
    lines.append(f"- Total fallos Cucumber: {len(cucumber_failures)}")
    lines.append(f"- Total fallos Playwright: {len(playwright_failures)}")
    lines.append("")
    
    # JUnit
    lines.append("## Detalle de fallos JUnit")
    if not junit_failures:
        lines.append("_No hay fallos JUnit en este run._")
    else:
        for i, f in enumerate(junit_failures, start=1):
            lines.append(f"### JUnit #{i}")
            lines.append(f"- Suite: `{f.get('suite')}`")
            lines.append(f"- Test: `{f.get('name')}`")
            if f.get("classname"):
                lines.append(f"- Class: `{f.get('classname')}`")
            if f.get("failure_message"):
                lines.append(f"- Failure message: `{f.get('failure_message')}`")
            if f.get("failure_type"):
                lines.append(f"- Failure type: `{f.get('failure_type')}`")
            if f.get("failure_text"):
                truncated = f.get("failure_text")[:1500]
                lines.append("")
                lines.append("```text")
                lines.append(truncated)
                lines.append("```")
            lines.append("")

    # Cucumber
    lines.append("## Detalle de fallos Cucumber")
    if not cucumber_failures:
        lines.append("_No hay fallos Cucumber en este run._")
    else:
        for i, f in enumerate(cucumber_failures, start=1):
            lines.append(f"### Cucumber #{i}")
            lines.append(f"- Feature: `{f.get('feature')}`")
            lines.append(f"- Scenario: `{f.get('scenario')}`")
            lines.append(f"- Step: `{f.get('step')}`")
            if f.get("error_message"):
                truncated = f.get("error_message")[:1500]
                lines.append("")
                lines.append("```text")
                lines.append(truncated)
                lines.append("```")
            lines.append("")

    # Playwright
    lines.append("## Detalle de fallos Playwright")
    if not playwright_failures:
        lines.append("_No hay fallos Playwright en este run._")
    else:
        for i, f in enumerate(playwright_failures, start=1):
            lines.append(f"### Playwright #{i}")
            lines.append(f"- Suite: `{f.get('suite')}`")
            lines.append(f"- Spec: `{f.get('spec')}`")
            lines.append(f"- Test: `{f.get('test')}`")
            lines.append(f"- Status: `{f.get('status')}`")
            if f.get("test_status"):
                lines.append(f"- Test Status: `{f.get('test_status')}`")
            if f.get("error_message"):
                lines.append(f"- Error: `{f.get('error_message')}`")
            if f.get("stack_trace"):
                truncated = f.get("stack_trace")[:1500]
                lines.append("")
                lines.append("```text")
                lines.append(truncated)
                lines.append("```")
            lines.append("")

    lines.append(
        textwrap.dedent(
            """
            ### Tu tarea

            - Agrupa los fallos por causas raíz (problemas de red, timeouts, regresión funcional, infraestructura, datos incorrectos, etc.)
            - Identifica patrones: mismo endpoint, mismo error, mismo servicio
            - Distingue entre fallos intermitentes (aparecen aleatoriamente) y fallos consistentes (siempre fallan)
            - Prioriza por impacto: crítico, importante, menor
            - Sé específico y técnico, usa los datos reales de los errores
            """
        ).strip()
    )

    return "\n".join(lines)


def analyze_failures(
    junit_failures: List[Dict[str, Any]],
    cucumber_failures: List[Dict[str, Any]],
    playwright_failures: List[Dict[str, Any]],
    model: str = "llama3",
) -> str:
    """
    Analiza los fallos usando Ollama con progress bar.
    
    Returns:
        Análisis en formato Markdown
    """
    
    total_failures = len(junit_failures) + len(cucumber_failures) + len(playwright_failures)
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        
        # Task 1: Preparando datos
        task1 = progress.add_task(
            f"[cyan]Preparando {total_failures} tests fallidos para análisis...", 
            total=100
        )
        progress.update(task1, advance=30)
        
        client = OllamaClient(model=model)
        user_prompt = build_user_prompt(junit_failures, cucumber_failures, playwright_failures)
        
        progress.update(task1, advance=70, description="[green]✓ Datos preparados")
        progress.remove_task(task1)
        
        # Task 2: Analizando con IA
        task2 = progress.add_task(
            f"[cyan]Analizando con {model}... (esto puede tardar 30-60s)", 
            total=None  # Indeterminate
        )
        
        result = client.chat(SYSTEM_PROMPT, user_prompt)
        
        progress.update(task2, description="[green]✓ Análisis completado")
        progress.remove_task(task2)
    
    return result
