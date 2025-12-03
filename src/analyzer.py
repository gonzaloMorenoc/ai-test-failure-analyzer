"""
Módulo de análisis de fallos usando LLM.

Características:
- Integración con fingerprinting para agrupar errores similares
- Integración con histórico para detectar regresiones
- Progress bar visual con Rich
- Prompt optimizado para análisis en español
"""

from typing import List, Dict, Any, Optional
import textwrap

from rich.console import Console
from rich.progress import (
    Progress, 
    SpinnerColumn, 
    TextColumn, 
    BarColumn, 
    TimeElapsedColumn
)

from src.llm.ollama_client import OllamaClient
from src.fingerprint import format_fingerprint_report

# Import condicional para evitar dependencia circular
try:
    from src.history import RegressionInfo, format_regression_report
except ImportError:
    RegressionInfo = None
    format_regression_report = None

console = Console()

SYSTEM_PROMPT = """
Eres un analista experto en fallos de testing automatizado con más de 10 años de experiencia.

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
- PRESTA ATENCIÓN al análisis de fingerprinting si está presente - los errores con el mismo fingerprint son esencialmente el mismo problema
- Si hay información de REGRESIÓN/HISTÓRICO, úsala para priorizar:
  - Los NUEVOS fallos (que no existían antes) son probablemente regresiones recientes y deben ser CRÍTICOS
  - Los fallos PERSISTENTES que llevan muchas ejecuciones sin resolverse merecen atención
  - Los tests INTERMITENTES (flaky) deben identificarse claramente
- Si hay información de TESTS FLAKY:
  - Los tests con flakiness score ALTO (>70) son críticos y afectan la confiabilidad del pipeline
  - Prioriza estabilizar tests flaky antes de añadir nuevos tests
  - Menciona el patrón detectado (random, degrading, periodic) y sugiere acciones específicas
  - Tests flaky con patrón "random" suelen indicar race conditions o problemas de sincronización
  - Tests flaky con patrón "degrading" pueden indicar problemas de rendimiento acumulativos
""".strip()


def build_user_prompt(
    junit_failures: List[Dict[str, Any]],
    cucumber_failures: List[Dict[str, Any]],
    playwright_failures: List[Dict[str, Any]],
    fingerprint_summary: Optional[Dict[str, Any]] = None,
    regression_info: Optional['RegressionInfo'] = None,
    flaky_summary: Optional[str] = None,
) -> str:
    """
    Construye el prompt de usuario con representación concisa de los fallos.
    
    Args:
        junit_failures: Lista de fallos JUnit
        cucumber_failures: Lista de fallos Cucumber
        playwright_failures: Lista de fallos Playwright
        fingerprint_summary: Resumen de fingerprinting (opcional)
        regression_info: Información de regresión (opcional)
        flaky_summary: Resumen de tests flaky formateado (opcional)
        
    Returns:
        Prompt formateado en Markdown
    """
    lines = []

    # === Contexto de ejecución ===
    lines.append("# Contexto de ejecución")
    lines.append("")
    lines.append(f"- Total fallos JUnit: {len(junit_failures)}")
    lines.append(f"- Total fallos Cucumber: {len(cucumber_failures)}")
    lines.append(f"- Total fallos Playwright: {len(playwright_failures)}")
    lines.append(f"- **Total general: {len(junit_failures) + len(cucumber_failures) + len(playwright_failures)}**")
    lines.append("")
    
    # === Información de Regresión (si está disponible) ===
    if regression_info and format_regression_report:
        lines.append(format_regression_report(regression_info))
        lines.append("")
        lines.append("---")
        lines.append("")
    
    # === Información de Flaky Tests (si está disponible) ===
    if flaky_summary:
        lines.append(flaky_summary)
        lines.append("")
        lines.append("---")
        lines.append("")
    
    # === Fingerprinting (si está disponible) ===
    if fingerprint_summary:
        lines.append(format_fingerprint_report(fingerprint_summary))
        lines.append("")
        lines.append("---")
        lines.append("")
    
    # === JUnit ===
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
            
            # Incluir fingerprint si existe
            if f.get("_fingerprint"):
                fp = f.get("_fingerprint")
                lines.append(f"- Fingerprint: `{fp}`")
                
                # Marcar si es nuevo o persistente
                if regression_info and not regression_info.is_first_run:
                    if fp in regression_info.new_failures:
                        lines.append("- **⚠️ NUEVO:** Este error no existía en la ejecución anterior")
                    elif fp in regression_info.persistent_failures:
                        consecutive = regression_info.consecutive_failures.get(fp, 0)
                        if consecutive >= 3:
                            lines.append(f"- **🔄 PERSISTENTE:** Lleva {consecutive} ejecuciones fallando")
            
            if f.get("failure_text"):
                truncated = f.get("failure_text")[:1500]
                lines.append("")
                lines.append("```text")
                lines.append(truncated)
                lines.append("```")
            lines.append("")

    # === Cucumber ===
    lines.append("## Detalle de fallos Cucumber")
    if not cucumber_failures:
        lines.append("_No hay fallos Cucumber en este run._")
    else:
        for i, f in enumerate(cucumber_failures, start=1):
            lines.append(f"### Cucumber #{i}")
            lines.append(f"- Feature: `{f.get('feature')}`")
            lines.append(f"- Scenario: `{f.get('scenario')}`")
            lines.append(f"- Step: `{f.get('step')}`")
            
            # Incluir fingerprint si existe
            if f.get("_fingerprint"):
                fp = f.get("_fingerprint")
                lines.append(f"- Fingerprint: `{fp}`")
                
                # Marcar si es nuevo o persistente
                if regression_info and not regression_info.is_first_run:
                    if fp in regression_info.new_failures:
                        lines.append("- **⚠️ NUEVO:** Este error no existía en la ejecución anterior")
                    elif fp in regression_info.persistent_failures:
                        consecutive = regression_info.consecutive_failures.get(fp, 0)
                        if consecutive >= 3:
                            lines.append(f"- **🔄 PERSISTENTE:** Lleva {consecutive} ejecuciones fallando")
            
            if f.get("error_message"):
                truncated = f.get("error_message")[:1500]
                lines.append("")
                lines.append("```text")
                lines.append(truncated)
                lines.append("```")
            lines.append("")

    # === Playwright ===
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
            
            # Incluir fingerprint si existe
            if f.get("_fingerprint"):
                fp = f.get("_fingerprint")
                lines.append(f"- Fingerprint: `{fp}`")
                
                # Marcar si es nuevo o persistente
                if regression_info and not regression_info.is_first_run:
                    if fp in regression_info.new_failures:
                        lines.append("- **⚠️ NUEVO:** Este error no existía en la ejecución anterior")
                    elif fp in regression_info.persistent_failures:
                        consecutive = regression_info.consecutive_failures.get(fp, 0)
                        if consecutive >= 3:
                            lines.append(f"- **🔄 PERSISTENTE:** Lleva {consecutive} ejecuciones fallando")
            
            if f.get("error_message"):
                lines.append(f"- Error: `{f.get('error_message')}`")
            if f.get("stack_trace"):
                truncated = f.get("stack_trace")[:1500]
                lines.append("")
                lines.append("```text")
                lines.append(truncated)
                lines.append("```")
            lines.append("")

    # === Instrucciones para el LLM ===
    task_instructions = """
### Tu tarea

Analiza los fallos proporcionados siguiendo estas directrices:

1. **Agrupa los fallos por causas raíz:**
   - Problemas de red/conectividad
   - Timeouts y problemas de rendimiento
   - Regresiones funcionales (bugs en el código)
   - Problemas de infraestructura/entorno
   - Datos de prueba incorrectos o inconsistentes
   - Problemas de sincronización/race conditions

2. **Identifica patrones:**
   - ¿Múltiples tests fallan en el mismo endpoint/servicio?
   - ¿Hay errores con el mismo fingerprint? (indica el mismo problema raíz)
   - ¿Los errores sugieren un problema sistémico o aislado?

3. **Usa la información de regresión (si está disponible):**
   - Los fallos marcados como **NUEVO** son probablemente regresiones recientes - prioridad ALTA
   - Los fallos **PERSISTENTES** por muchas ejecuciones necesitan atención urgente
   - Los tests **INTERMITENTES** (flaky) deben ser estabilizados

4. **Distingue entre tipos de fallo:**
   - **Intermitentes:** Aparecen aleatoriamente, posibles race conditions o problemas de infraestructura
   - **Consistentes:** Siempre fallan, probablemente bugs o regresiones

5. **Prioriza por impacto:**
   - 🔴 **Crítico:** Bloquea funcionalidad core, afecta a usuarios, ES NUEVO (regresión)
   - 🟡 **Importante:** Afecta funcionalidad secundaria, debe resolverse pronto
   - 🟢 **Menor:** Bajo impacto, puede esperar

6. **Sé específico:**
   - Usa los nombres reales de tests, endpoints y errores
   - Cita evidencia directa de los mensajes de error
   - No inventes información que no esté en los datos
"""
    
    lines.append(textwrap.dedent(task_instructions).strip())

    return "\n".join(lines)


def analyze_failures(
    junit_failures: List[Dict[str, Any]],
    cucumber_failures: List[Dict[str, Any]],
    playwright_failures: List[Dict[str, Any]],
    model: str = "llama3",
    fingerprint_summary: Optional[Dict[str, Any]] = None,
    regression_info: Optional['RegressionInfo'] = None,
    flaky_summary: Optional[str] = None,
) -> str:
    """
    Analiza los fallos usando Ollama con progress bar visual.
    
    Args:
        junit_failures: Lista de fallos JUnit
        cucumber_failures: Lista de fallos Cucumber
        playwright_failures: Lista de fallos Playwright
        model: Nombre del modelo Ollama a usar
        fingerprint_summary: Resumen de fingerprinting (opcional)
        regression_info: Información de regresión del histórico (opcional)
        flaky_summary: Resumen de tests flaky formateado (opcional)
    
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
        user_prompt = build_user_prompt(
            junit_failures, 
            cucumber_failures, 
            playwright_failures,
            fingerprint_summary,
            regression_info,
            flaky_summary
        )
        
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
