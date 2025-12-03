"""
Módulo de detección de tests intermitentes (flaky).

Un test flaky es aquel que produce resultados inconsistentes:
- A veces pasa, a veces falla, sin cambios en el código
- Causas comunes: race conditions, dependencias de tiempo, estado compartido

Este módulo analiza el histórico de ejecuciones para:
- Identificar tests con comportamiento intermitente
- Calcular métricas de estabilidad (flakiness score)
- Detectar patrones temporales
- Generar recomendaciones para estabilización
"""

import sqlite3
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import statistics


class FlakinessSeverity(Enum):
    """Severidad del comportamiento flaky."""
    LOW = "low"           # 10-30% flakiness - ocasionalmente falla
    MEDIUM = "medium"     # 30-50% flakiness - frecuentemente inestable
    HIGH = "high"         # 50-70% flakiness - muy inestable
    CRITICAL = "critical" # 70-90% flakiness - casi aleatorio


@dataclass
class FlakyTestResult:
    """Resultado del análisis de un test flaky."""
    fingerprint: str
    test_name: str
    source_type: str
    error_preview: str
    
    # Métricas de flakiness
    flakiness_score: float          # 0-100, qué tan flaky es
    failure_rate: float             # Porcentaje de veces que falla
    appearances: int                # Veces que apareció (falló)
    total_runs: int                 # Total de ejecuciones analizadas
    
    # Patrones
    transitions: int                # Veces que cambió de estado (pass<->fail)
    max_consecutive_failures: int   # Máximo de fallos consecutivos
    max_consecutive_passes: int     # Máximo de pases consecutivos
    
    # Temporal
    first_seen: str
    last_seen: str
    currently_failing: bool
    
    # Severidad calculada
    severity: FlakinessSeverity
    
    # Patrón detectado
    pattern: str                    # "random", "degrading", "improving", "periodic"
    pattern_description: str
    
    # Recomendaciones
    recommendations: List[str] = field(default_factory=list)


@dataclass
class FlakyAnalysisReport:
    """Reporte completo de análisis de flaky tests."""
    analysis_timestamp: str
    runs_analyzed: int
    window_days: int
    
    # Resumen
    total_flaky_tests: int
    critical_count: int
    high_count: int
    medium_count: int
    low_count: int
    
    # Tests flaky ordenados por severidad
    flaky_tests: List[FlakyTestResult]
    
    # Estadísticas generales
    avg_flakiness_score: float
    most_unstable_test: Optional[FlakyTestResult]
    
    # Recomendaciones generales
    general_recommendations: List[str]


class FlakyDetector:
    """
    Detector avanzado de tests flaky basado en análisis histórico.
    
    Algoritmo:
    1. Obtiene el historial de N ejecuciones
    2. Para cada fingerprint, analiza su patrón de apariciones
    3. Calcula métricas: transitions, streaks, failure_rate
    4. Determina flakiness_score combinando métricas
    5. Clasifica por severidad y genera recomendaciones
    """
    
    def __init__(self, db_path: Path = Path(".analyzer_history.db")):
        """
        Inicializa el detector.
        
        Args:
            db_path: Path a la base de datos de histórico
        """
        self.db_path = db_path
    
    def _get_run_history(
        self, 
        conn: sqlite3.Connection,
        window_size: int = 20,
        days: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Obtiene el historial de ejecuciones."""
        query = """
            SELECT id, timestamp, fingerprints_json, git_commit, git_branch
            FROM runs 
        """
        params = []
        
        if days:
            cutoff = (datetime.now() - timedelta(days=days)).isoformat()
            query += " WHERE timestamp >= ? "
            params.append(cutoff)
        
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(window_size)
        
        rows = conn.execute(query, params).fetchall()
        
        return [
            {
                'id': row[0],
                'timestamp': row[1],
                'fingerprints': set(json.loads(row[2] or '[]')),
                'git_commit': row[3],
                'git_branch': row[4]
            }
            for row in rows
        ]
    
    def _calculate_transitions(self, appearances: List[bool]) -> int:
        """
        Calcula el número de transiciones (cambios de estado).
        
        Una alta cantidad de transiciones indica comportamiento flaky.
        """
        if len(appearances) < 2:
            return 0
        
        transitions = 0
        for i in range(1, len(appearances)):
            if appearances[i] != appearances[i-1]:
                transitions += 1
        
        return transitions
    
    def _calculate_max_streak(self, appearances: List[bool], value: bool) -> int:
        """Calcula la racha máxima consecutiva de un valor."""
        max_streak = 0
        current_streak = 0
        
        for app in appearances:
            if app == value:
                current_streak += 1
                max_streak = max(max_streak, current_streak)
            else:
                current_streak = 0
        
        return max_streak
    
    def _calculate_flakiness_score(
        self,
        failure_rate: float,
        transitions: int,
        total_runs: int,
        max_consecutive_failures: int,
        max_consecutive_passes: int
    ) -> float:
        """
        Calcula el score de flakiness (0-100).
        
        Factores:
        - Failure rate cercano a 50% = más flaky
        - Más transiciones = más flaky
        - Rachas cortas = más flaky
        """
        if total_runs < 3:
            return 0.0
        
        # Factor 1: Qué tan cerca está del 50% (máxima incertidumbre)
        # 50% failure rate = score 100, 0% o 100% = score 0
        distance_from_50 = abs(failure_rate - 50)
        rate_score = max(0, 100 - (distance_from_50 * 2))
        
        # Factor 2: Transiciones normalizadas
        # Máximo teórico de transiciones = total_runs - 1
        max_possible_transitions = total_runs - 1
        if max_possible_transitions > 0:
            transition_ratio = transitions / max_possible_transitions
            transition_score = transition_ratio * 100
        else:
            transition_score = 0
        
        # Factor 3: Rachas cortas indican inestabilidad
        avg_streak = (max_consecutive_failures + max_consecutive_passes) / 2
        max_possible_streak = total_runs
        streak_ratio = avg_streak / max_possible_streak if max_possible_streak > 0 else 0
        # Rachas más cortas = más flaky, invertimos el score
        streak_score = (1 - streak_ratio) * 100
        
        # Combinar factores con pesos
        # Rate score es el más importante para determinar flakiness
        final_score = (
            rate_score * 0.5 +
            transition_score * 0.35 +
            streak_score * 0.15
        )
        
        return round(min(100, max(0, final_score)), 1)
    
    def _determine_severity(self, flakiness_score: float) -> FlakinessSeverity:
        """Determina la severidad basada en el score."""
        if flakiness_score >= 70:
            return FlakinessSeverity.CRITICAL
        elif flakiness_score >= 50:
            return FlakinessSeverity.HIGH
        elif flakiness_score >= 30:
            return FlakinessSeverity.MEDIUM
        else:
            return FlakinessSeverity.LOW
    
    def _detect_pattern(
        self,
        appearances: List[bool],
        transitions: int
    ) -> Tuple[str, str]:
        """
        Detecta el patrón de comportamiento del test.
        
        Returns:
            (pattern_name, description)
        """
        if len(appearances) < 3:
            return "unknown", "Datos insuficientes para determinar patrón"
        
        total = len(appearances)
        failures_first_half = sum(appearances[:total//2])
        failures_second_half = sum(appearances[total//2:])
        
        # Calcular tendencia
        if failures_second_half > failures_first_half + 1:
            return "degrading", "El test está fallando más frecuentemente con el tiempo"
        elif failures_first_half > failures_second_half + 1:
            return "improving", "El test está mejorando (menos fallos recientes)"
        
        # Verificar si es aleatorio (muchas transiciones)
        expected_transitions = total * 0.3  # ~30% de transiciones esperadas para aleatorio
        if transitions > expected_transitions:
            return "random", "Comportamiento aleatorio - falla sin patrón predecible"
        
        # Verificar periodicidad básica
        # (simplificado - un análisis real usaría FFT o autocorrelación)
        alternating_count = 0
        for i in range(1, len(appearances)):
            if appearances[i] != appearances[i-1]:
                alternating_count += 1
        
        if alternating_count >= total * 0.7:
            return "periodic", "Posible patrón periódico - falla de forma alternada"
        
        return "inconsistent", "Comportamiento inconsistente sin patrón claro"
    
    def _generate_recommendations(
        self,
        pattern: str,
        severity: FlakinessSeverity,
        failure_rate: float,
        source_type: str,
        error_preview: str
    ) -> List[str]:
        """Genera recomendaciones específicas para el test flaky."""
        recs = []
        
        # Recomendaciones por patrón
        pattern_recs = {
            "random": [
                "Revisar race conditions y problemas de sincronización",
                "Verificar timeouts - considerar aumentarlos o hacerlos dinámicos",
                "Buscar dependencias de estado global o compartido"
            ],
            "degrading": [
                "Posible degradación de rendimiento - revisar recursos del sistema",
                "Verificar si hay memory leaks acumulativos",
                "Comprobar logs del sistema durante las ejecuciones"
            ],
            "improving": [
                "El test parece estabilizarse - monitorear unas ejecuciones más",
                "Verificar si hubo cambios recientes que mejoraron la estabilidad"
            ],
            "periodic": [
                "Revisar jobs programados que puedan interferir",
                "Verificar si hay limpieza de datos/caché periódica",
                "Buscar dependencias con servicios externos con mantenimiento programado"
            ],
            "inconsistent": [
                "Ejecutar el test en aislamiento para descartar interferencias",
                "Revisar fixtures y setup/teardown del test"
            ]
        }
        recs.extend(pattern_recs.get(pattern, []))
        
        # Recomendaciones por severidad
        if severity == FlakinessSeverity.CRITICAL:
            recs.insert(0, "⚠️ URGENTE: Este test es casi aleatorio y debe ser estabilizado o desactivado")
            recs.append("Considerar marcar como @flaky o skip temporal mientras se investiga")
        elif severity == FlakinessSeverity.HIGH:
            recs.insert(0, "Alta prioridad: Este test necesita atención inmediata")
        
        # Recomendaciones por tipo de error (análisis básico del preview)
        error_lower = error_preview.lower()
        if 'timeout' in error_lower:
            recs.append("Timeout detectado - revisar tiempos de espera y rendimiento del sistema")
        if 'connection' in error_lower or 'network' in error_lower:
            recs.append("Problema de red - verificar estabilidad de conexiones y reintentos")
        if 'element' in error_lower and ('not found' in error_lower or 'visible' in error_lower):
            recs.append("Elemento no encontrado - agregar waits explícitos o mejorar selectores")
        if 'assert' in error_lower:
            recs.append("Assertion fallida - verificar si los datos esperados son determinísticos")
        
        # Recomendaciones por source type
        if 'playwright' in source_type.lower():
            recs.append("Para Playwright: usar auto-waiting y retry assertions")
        if 'selenium' in source_type.lower() or 'junit' in source_type.lower():
            recs.append("Considerar usar WebDriverWait con condiciones explícitas")
        
        return recs[:6]  # Limitar a 6 recomendaciones
    
    def analyze(
        self,
        window_size: int = 20,
        days: Optional[int] = None,
        min_appearances: int = 3,
        min_flakiness_score: float = 20.0,
        current_fingerprints: Optional[List[str]] = None
    ) -> FlakyAnalysisReport:
        """
        Ejecuta el análisis completo de flaky tests.
        
        Args:
            window_size: Número máximo de ejecuciones a analizar
            days: Limitar a los últimos N días (opcional)
            min_appearances: Mínimo de apariciones para considerar
            min_flakiness_score: Score mínimo para reportar como flaky
            current_fingerprints: Fingerprints de la ejecución actual (para marcar estado)
            
        Returns:
            FlakyAnalysisReport con el análisis completo
        """
        current_fps = set(current_fingerprints or [])
        
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            
            # Obtener historial
            runs = self._get_run_history(conn, window_size, days)
            
            if len(runs) < 3:
                return FlakyAnalysisReport(
                    analysis_timestamp=datetime.now().isoformat(),
                    runs_analyzed=len(runs),
                    window_days=days or 0,
                    total_flaky_tests=0,
                    critical_count=0,
                    high_count=0,
                    medium_count=0,
                    low_count=0,
                    flaky_tests=[],
                    avg_flakiness_score=0,
                    most_unstable_test=None,
                    general_recommendations=[
                        "Se necesitan al menos 3 ejecuciones para detectar tests flaky",
                        f"Actualmente hay {len(runs)} ejecución(es) registrada(s)"
                    ]
                )
            
            # Recopilar todas las apariciones de cada fingerprint
            # runs está ordenado de más reciente a más antiguo
            # Invertimos para tener orden cronológico
            runs_chrono = list(reversed(runs))
            
            fingerprint_data: Dict[str, List[bool]] = {}
            all_fingerprints: set = set()
            
            for run in runs_chrono:
                all_fingerprints.update(run['fingerprints'])
            
            # Para cada fingerprint, registrar si apareció en cada run
            for fp in all_fingerprints:
                fingerprint_data[fp] = [
                    fp in run['fingerprints'] for run in runs_chrono
                ]
            
            # Obtener detalles de fingerprints
            fp_details = {}
            if all_fingerprints:
                placeholders = ','.join('?' * len(all_fingerprints))
                details_rows = conn.execute(f"""
                    SELECT fingerprint, test_name, error_preview, source_type,
                           first_seen, last_seen
                    FROM fingerprint_history 
                    WHERE fingerprint IN ({placeholders})
                """, list(all_fingerprints)).fetchall()
                
                for row in details_rows:
                    fp_details[row['fingerprint']] = {
                        'test_name': row['test_name'] or 'unknown',
                        'error_preview': row['error_preview'] or '',
                        'source_type': row['source_type'] or 'unknown',
                        'first_seen': row['first_seen'],
                        'last_seen': row['last_seen']
                    }
            
            # Analizar cada fingerprint
            flaky_tests: List[FlakyTestResult] = []
            
            for fp, appearances in fingerprint_data.items():
                total_runs = len(appearances)
                appearances_count = sum(appearances)
                
                # Filtrar por mínimo de apariciones
                if appearances_count < min_appearances:
                    continue
                
                # Calcular métricas
                failure_rate = (appearances_count / total_runs) * 100
                transitions = self._calculate_transitions(appearances)
                max_failures = self._calculate_max_streak(appearances, True)
                max_passes = self._calculate_max_streak(appearances, False)
                
                # Solo considerar como flaky si no es 100% consistente
                if failure_rate == 0 or failure_rate == 100:
                    continue
                
                # Calcular flakiness score
                flakiness_score = self._calculate_flakiness_score(
                    failure_rate, transitions, total_runs,
                    max_failures, max_passes
                )
                
                # Filtrar por score mínimo
                if flakiness_score < min_flakiness_score:
                    continue
                
                # Obtener detalles
                details = fp_details.get(fp, {})
                
                # Determinar severidad y patrón
                severity = self._determine_severity(flakiness_score)
                pattern, pattern_desc = self._detect_pattern(appearances, transitions)
                
                # Generar recomendaciones
                recommendations = self._generate_recommendations(
                    pattern, severity, failure_rate,
                    details.get('source_type', ''),
                    details.get('error_preview', '')
                )
                
                flaky_test = FlakyTestResult(
                    fingerprint=fp,
                    test_name=details.get('test_name', 'unknown'),
                    source_type=details.get('source_type', 'unknown'),
                    error_preview=details.get('error_preview', '')[:200],
                    flakiness_score=flakiness_score,
                    failure_rate=round(failure_rate, 1),
                    appearances=appearances_count,
                    total_runs=total_runs,
                    transitions=transitions,
                    max_consecutive_failures=max_failures,
                    max_consecutive_passes=max_passes,
                    first_seen=details.get('first_seen', ''),
                    last_seen=details.get('last_seen', ''),
                    currently_failing=fp in current_fps,
                    severity=severity,
                    pattern=pattern,
                    pattern_description=pattern_desc,
                    recommendations=recommendations
                )
                
                flaky_tests.append(flaky_test)
            
            # Ordenar por flakiness score (más flaky primero)
            flaky_tests.sort(key=lambda x: x.flakiness_score, reverse=True)
            
            # Contar por severidad
            critical = sum(1 for t in flaky_tests if t.severity == FlakinessSeverity.CRITICAL)
            high = sum(1 for t in flaky_tests if t.severity == FlakinessSeverity.HIGH)
            medium = sum(1 for t in flaky_tests if t.severity == FlakinessSeverity.MEDIUM)
            low = sum(1 for t in flaky_tests if t.severity == FlakinessSeverity.LOW)
            
            # Calcular promedio
            avg_score = (
                statistics.mean(t.flakiness_score for t in flaky_tests)
                if flaky_tests else 0
            )
            
            # Generar recomendaciones generales
            general_recs = []
            if critical > 0:
                general_recs.append(
                    f"⚠️ Hay {critical} test(s) con flakiness crítico que requieren atención urgente"
                )
            if len(flaky_tests) > 5:
                general_recs.append(
                    "Considerar implementar un sistema de retry automático para tests flaky"
                )
            if any(t.pattern == "random" for t in flaky_tests):
                general_recs.append(
                    "Se detectaron tests con comportamiento aleatorio - revisar infraestructura de tests"
                )
            if not general_recs:
                if flaky_tests:
                    general_recs.append(
                        "Los tests flaky detectados tienen severidad manejable"
                    )
                else:
                    general_recs.append(
                        "No se detectaron tests flaky significativos - ¡buen trabajo!"
                    )
            
            return FlakyAnalysisReport(
                analysis_timestamp=datetime.now().isoformat(),
                runs_analyzed=len(runs),
                window_days=days or 0,
                total_flaky_tests=len(flaky_tests),
                critical_count=critical,
                high_count=high,
                medium_count=medium,
                low_count=low,
                flaky_tests=flaky_tests,
                avg_flakiness_score=round(avg_score, 1),
                most_unstable_test=flaky_tests[0] if flaky_tests else None,
                general_recommendations=general_recs
            )
    
    def get_flaky_summary_for_prompt(
        self,
        report: FlakyAnalysisReport,
        max_tests: int = 5
    ) -> str:
        """
        Genera un resumen de flaky tests para incluir en el prompt del LLM.
        
        Args:
            report: Reporte de análisis flaky
            max_tests: Máximo de tests a incluir en detalle
            
        Returns:
            String formateado en Markdown
        """
        if report.total_flaky_tests == 0:
            return ""
        
        lines = []
        lines.append("## 🎲 Tests Intermitentes (Flaky) Detectados")
        lines.append("")
        lines.append(f"Se analizaron **{report.runs_analyzed} ejecuciones** y se detectaron "
                    f"**{report.total_flaky_tests} tests flaky**:")
        lines.append("")
        
        # Resumen por severidad
        if report.critical_count > 0:
            lines.append(f"- 🔴 **Críticos:** {report.critical_count}")
        if report.high_count > 0:
            lines.append(f"- 🟠 **Altos:** {report.high_count}")
        if report.medium_count > 0:
            lines.append(f"- 🟡 **Medios:** {report.medium_count}")
        if report.low_count > 0:
            lines.append(f"- 🟢 **Bajos:** {report.low_count}")
        
        lines.append("")
        lines.append(f"**Score promedio de flakiness:** {report.avg_flakiness_score}/100")
        lines.append("")
        
        # Detalle de los más problemáticos
        lines.append("### Tests más inestables:")
        lines.append("")
        
        for i, test in enumerate(report.flaky_tests[:max_tests], 1):
            severity_emoji = {
                FlakinessSeverity.CRITICAL: "🔴",
                FlakinessSeverity.HIGH: "🟠",
                FlakinessSeverity.MEDIUM: "🟡",
                FlakinessSeverity.LOW: "🟢"
            }
            emoji = severity_emoji.get(test.severity, "⚪")
            status = "❌ FALLANDO" if test.currently_failing else "✅ pasando"
            
            lines.append(f"**{i}. {test.test_name}** {emoji}")
            lines.append(f"   - Flakiness Score: **{test.flakiness_score}/100**")
            lines.append(f"   - Tasa de fallo: {test.failure_rate}% ({test.appearances}/{test.total_runs} runs)")
            lines.append(f"   - Patrón: {test.pattern_description}")
            lines.append(f"   - Estado actual: {status}")
            lines.append(f"   - Fingerprint: `{test.fingerprint}`")
            lines.append("")
        
        if report.total_flaky_tests > max_tests:
            lines.append(f"... y {report.total_flaky_tests - max_tests} más")
            lines.append("")
        
        # Recomendaciones
        if report.general_recommendations:
            lines.append("### Recomendaciones generales:")
            for rec in report.general_recommendations:
                lines.append(f"- {rec}")
            lines.append("")
        
        return "\n".join(lines)


def format_flaky_report_console(report: FlakyAnalysisReport) -> str:
    """
    Formatea el reporte de flaky tests para la consola (Rich).
    
    Returns:
        String con formato para Rich console
    """
    if report.total_flaky_tests == 0:
        return "[green]✓ No se detectaron tests flaky significativos[/green]"
    
    lines = []
    lines.append(f"[bold]Análisis de {report.runs_analyzed} ejecuciones[/bold]")
    lines.append("")
    
    # Resumen
    lines.append(f"Total tests flaky: [yellow]{report.total_flaky_tests}[/yellow]")
    
    severity_counts = []
    if report.critical_count > 0:
        severity_counts.append(f"[red]{report.critical_count} críticos[/red]")
    if report.high_count > 0:
        severity_counts.append(f"[orange1]{report.high_count} altos[/orange1]")
    if report.medium_count > 0:
        severity_counts.append(f"[yellow]{report.medium_count} medios[/yellow]")
    if report.low_count > 0:
        severity_counts.append(f"[green]{report.low_count} bajos[/green]")
    
    if severity_counts:
        lines.append(f"Severidad: {', '.join(severity_counts)}")
    
    lines.append(f"Score promedio: [cyan]{report.avg_flakiness_score}/100[/cyan]")
    lines.append("")
    
    # Top 5 tests
    if report.flaky_tests:
        lines.append("[bold]Top tests más inestables:[/bold]")
        for i, test in enumerate(report.flaky_tests[:5], 1):
            status = "❌" if test.currently_failing else "✅"
            severity_color = {
                FlakinessSeverity.CRITICAL: "red",
                FlakinessSeverity.HIGH: "orange1",
                FlakinessSeverity.MEDIUM: "yellow",
                FlakinessSeverity.LOW: "green"
            }
            color = severity_color.get(test.severity, "white")
            
            lines.append(
                f"  {i}. [{color}]{test.test_name[:40]}[/{color}] "
                f"- Score: {test.flakiness_score} - {test.failure_rate}% fallo {status}"
            )
    
    return "\n".join(lines)
