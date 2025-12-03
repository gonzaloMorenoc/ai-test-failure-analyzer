"""
Módulo de histórico para detectar tendencias y regresiones.

Almacena información de ejecuciones anteriores en SQLite para:
- Comparar con ejecuciones previas
- Detectar tests nuevos vs persistentes
- Identificar tests intermitentes (flaky)
- Mostrar tendencias de mejora/degradación
"""

import sqlite3
import json
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional, Set
from dataclasses import dataclass, asdict


@dataclass
class RunSummary:
    """Resumen de una ejecución de análisis."""
    id: int
    timestamp: str
    total_failures: int
    junit_failures: int
    cucumber_failures: int
    playwright_failures: int
    unique_fingerprints: int
    git_commit: Optional[str]
    git_branch: Optional[str]
    trend: Optional[str]  # improving, stable, degrading


@dataclass
class RegressionInfo:
    """Información de regresión comparando con ejecuciones anteriores."""
    is_first_run: bool
    previous_run: Optional[RunSummary]
    new_failures: List[str]  # Fingerprints nuevos
    fixed_failures: List[str]  # Fingerprints que desaparecieron
    persistent_failures: List[str]  # Fingerprints que siguen
    trend: str  # improving, stable, degrading
    trend_emoji: str
    consecutive_failures: Dict[str, int]  # fingerprint -> número de runs consecutivos
    flaky_candidates: List[Dict[str, Any]]  # Tests que aparecen intermitentemente


class AnalysisHistory:
    """
    Gestiona el histórico de análisis para detectar tendencias y regresiones.
    
    Usa SQLite para persistencia local sin dependencias externas.
    """
    
    def __init__(self, db_path: Path = Path(".analyzer_history.db")):
        """
        Inicializa el histórico.
        
        Args:
            db_path: Path a la base de datos SQLite
        """
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        """Crea las tablas si no existen."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    total_failures INTEGER NOT NULL,
                    junit_failures INTEGER DEFAULT 0,
                    cucumber_failures INTEGER DEFAULT 0,
                    playwright_failures INTEGER DEFAULT 0,
                    unique_fingerprints INTEGER DEFAULT 0,
                    fingerprints_json TEXT,
                    analysis_summary TEXT,
                    git_commit TEXT,
                    git_branch TEXT,
                    metadata_json TEXT
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS fingerprint_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fingerprint TEXT NOT NULL,
                    first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL,
                    total_occurrences INTEGER DEFAULT 1,
                    consecutive_runs INTEGER DEFAULT 1,
                    test_name TEXT,
                    error_preview TEXT,
                    source_type TEXT
                )
            """)
            
            # Índices para búsquedas rápidas
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_runs_timestamp 
                ON runs(timestamp DESC)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_fingerprint 
                ON fingerprint_history(fingerprint)
            """)
            
            conn.commit()
    
    def _get_git_info(self) -> Dict[str, Optional[str]]:
        """Obtiene información del commit y branch actual de Git."""
        git_info = {"commit": None, "branch": None}
        
        try:
            # Obtener commit hash
            result = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                git_info["commit"] = result.stdout.strip()
            
            # Obtener branch
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                git_info["branch"] = result.stdout.strip()
                
        except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
            pass  # Git no disponible o no es un repo
        
        return git_info
    
    def record_run(
        self,
        failures: Dict[str, List[Dict[str, Any]]],
        fingerprints: List[str],
        fingerprint_details: Dict[str, Dict[str, Any]],
        analysis_summary: str = ""
    ) -> int:
        """
        Registra una ejecución de análisis.
        
        Args:
            failures: Dict con listas de fallos por tipo (junit, cucumber, playwright)
            fingerprints: Lista de fingerprints únicos en esta ejecución
            fingerprint_details: Detalles de cada fingerprint
            analysis_summary: Resumen del análisis (primeras líneas)
            
        Returns:
            ID del run registrado
        """
        git_info = self._get_git_info()
        timestamp = datetime.now().isoformat()
        
        with sqlite3.connect(self.db_path) as conn:
            # Insertar run
            cursor = conn.execute("""
                INSERT INTO runs (
                    timestamp, total_failures, junit_failures, cucumber_failures,
                    playwright_failures, unique_fingerprints, fingerprints_json,
                    analysis_summary, git_commit, git_branch
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                timestamp,
                sum(len(v) for v in failures.values()),
                len(failures.get('junit', [])),
                len(failures.get('cucumber', [])),
                len(failures.get('playwright', [])),
                len(fingerprints),
                json.dumps(fingerprints),
                analysis_summary[:2000] if analysis_summary else "",
                git_info.get('commit'),
                git_info.get('branch')
            ))
            run_id = cursor.lastrowid
            
            # Actualizar histórico de fingerprints
            for fp in fingerprints:
                details = fingerprint_details.get(fp, {})
                
                # Verificar si el fingerprint ya existe
                existing = conn.execute(
                    "SELECT id, consecutive_runs, total_occurrences FROM fingerprint_history WHERE fingerprint = ?",
                    (fp,)
                ).fetchone()
                
                if existing:
                    # Actualizar existente
                    conn.execute("""
                        UPDATE fingerprint_history 
                        SET last_seen = ?, 
                            consecutive_runs = consecutive_runs + 1,
                            total_occurrences = total_occurrences + 1
                        WHERE fingerprint = ?
                    """, (timestamp, fp))
                else:
                    # Insertar nuevo
                    representative = details.get('representative', {})
                    test_name = (
                        representative.get('name') or 
                        representative.get('test') or 
                        representative.get('scenario') or 
                        'unknown'
                    )
                    conn.execute("""
                        INSERT INTO fingerprint_history (
                            fingerprint, first_seen, last_seen, 
                            test_name, error_preview, source_type
                        ) VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                        fp,
                        timestamp,
                        timestamp,
                        test_name[:200],
                        details.get('normalized_error', '')[:500],
                        ','.join(details.get('source_types', ['unknown']))
                    ))
            
            # Resetear contador consecutivo de fingerprints que NO aparecieron
            if fingerprints:
                placeholders = ','.join('?' * len(fingerprints))
                conn.execute(f"""
                    UPDATE fingerprint_history 
                    SET consecutive_runs = 0 
                    WHERE fingerprint NOT IN ({placeholders})
                """, fingerprints)
            
            conn.commit()
            
        return run_id
    
    def get_regression_info(
        self, 
        current_fingerprints: List[str]
    ) -> RegressionInfo:
        """
        Compara los fingerprints actuales con el histórico.
        
        Args:
            current_fingerprints: Lista de fingerprints de la ejecución actual
            
        Returns:
            RegressionInfo con comparación detallada
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            
            # Obtener último run
            last_run_row = conn.execute(
                "SELECT * FROM runs ORDER BY timestamp DESC LIMIT 1"
            ).fetchone()
            
            if not last_run_row:
                return RegressionInfo(
                    is_first_run=True,
                    previous_run=None,
                    new_failures=current_fingerprints,
                    fixed_failures=[],
                    persistent_failures=[],
                    trend="unknown",
                    trend_emoji="🆕",
                    consecutive_failures={},
                    flaky_candidates=[]
                )
            
            # Parsear fingerprints del run anterior
            previous_fps: Set[str] = set(
                json.loads(last_run_row['fingerprints_json'] or '[]')
            )
            current_fps: Set[str] = set(current_fingerprints)
            
            # Calcular diferencias
            new_failures = list(current_fps - previous_fps)
            fixed_failures = list(previous_fps - current_fps)
            persistent_failures = list(current_fps & previous_fps)
            
            # Determinar tendencia
            if len(current_fps) < len(previous_fps):
                trend = "improving"
                trend_emoji = "📈"
            elif len(current_fps) > len(previous_fps):
                trend = "degrading"
                trend_emoji = "📉"
            else:
                trend = "stable"
                trend_emoji = "➡️"
            
            # Obtener contadores consecutivos
            consecutive = {}
            if current_fingerprints:
                placeholders = ','.join('?' * len(current_fingerprints))
                rows = conn.execute(f"""
                    SELECT fingerprint, consecutive_runs 
                    FROM fingerprint_history 
                    WHERE fingerprint IN ({placeholders})
                """, current_fingerprints).fetchall()
                consecutive = {row['fingerprint']: row['consecutive_runs'] for row in rows}
            
            # Detectar flaky candidates (aparecen intermitentemente)
            flaky_candidates = self._detect_flaky_tests(conn, current_fingerprints)
            
            previous_run = RunSummary(
                id=last_run_row['id'],
                timestamp=last_run_row['timestamp'],
                total_failures=last_run_row['total_failures'],
                junit_failures=last_run_row['junit_failures'],
                cucumber_failures=last_run_row['cucumber_failures'],
                playwright_failures=last_run_row['playwright_failures'],
                unique_fingerprints=last_run_row['unique_fingerprints'],
                git_commit=last_run_row['git_commit'],
                git_branch=last_run_row['git_branch'],
                trend=None
            )
            
            return RegressionInfo(
                is_first_run=False,
                previous_run=previous_run,
                new_failures=new_failures,
                fixed_failures=fixed_failures,
                persistent_failures=persistent_failures,
                trend=trend,
                trend_emoji=trend_emoji,
                consecutive_failures=consecutive,
                flaky_candidates=flaky_candidates
            )
    
    def _detect_flaky_tests(
        self, 
        conn: sqlite3.Connection, 
        current_fingerprints: List[str],
        window_size: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Detecta tests que podrían ser flaky (intermitentes).
        
        Un test es candidato a flaky si:
        - Ha aparecido y desaparecido en las últimas N ejecuciones
        - Tiene un ratio de aparición entre 20% y 80%
        """
        flaky = []
        
        # Obtener últimos N runs
        runs = conn.execute("""
            SELECT fingerprints_json FROM runs 
            ORDER BY timestamp DESC LIMIT ?
        """, (window_size,)).fetchall()
        
        if len(runs) < 3:
            return []  # No hay suficientes datos
        
        # Contar apariciones de cada fingerprint
        fingerprint_appearances: Dict[str, int] = {}
        for run in runs:
            fps = json.loads(run['fingerprints_json'] or '[]')
            for fp in fps:
                fingerprint_appearances[fp] = fingerprint_appearances.get(fp, 0) + 1
        
        # Identificar flaky (aparece entre 20% y 80% de las veces)
        total_runs = len(runs)
        for fp, appearances in fingerprint_appearances.items():
            ratio = appearances / total_runs
            if 0.2 <= ratio <= 0.8:
                # Obtener detalles del fingerprint
                details = conn.execute("""
                    SELECT test_name, error_preview, source_type 
                    FROM fingerprint_history 
                    WHERE fingerprint = ?
                """, (fp,)).fetchone()
                
                flaky.append({
                    'fingerprint': fp,
                    'appearances': appearances,
                    'total_runs': total_runs,
                    'ratio': round(ratio * 100, 1),
                    'test_name': details['test_name'] if details else 'unknown',
                    'currently_failing': fp in current_fingerprints
                })
        
        # Ordenar por ratio (más intermitentes primero)
        flaky.sort(key=lambda x: abs(x['ratio'] - 50), reverse=False)
        
        return flaky[:10]  # Limitar a top 10
    
    def get_recent_runs(self, limit: int = 10) -> List[RunSummary]:
        """Obtiene los últimos N runs."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT * FROM runs ORDER BY timestamp DESC LIMIT ?
            """, (limit,)).fetchall()
            
            return [
                RunSummary(
                    id=row['id'],
                    timestamp=row['timestamp'],
                    total_failures=row['total_failures'],
                    junit_failures=row['junit_failures'],
                    cucumber_failures=row['cucumber_failures'],
                    playwright_failures=row['playwright_failures'],
                    unique_fingerprints=row['unique_fingerprints'],
                    git_commit=row['git_commit'],
                    git_branch=row['git_branch'],
                    trend=None
                )
                for row in rows
            ]
    
    def get_persistent_failures(self, min_consecutive: int = 3) -> List[Dict[str, Any]]:
        """
        Obtiene fallos que han persistido por N ejecuciones consecutivas.
        
        Args:
            min_consecutive: Mínimo de runs consecutivos para considerar persistente
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT * FROM fingerprint_history 
                WHERE consecutive_runs >= ?
                ORDER BY consecutive_runs DESC
            """, (min_consecutive,)).fetchall()
            
            return [dict(row) for row in rows]
    
    def get_statistics(self) -> Dict[str, Any]:
        """Obtiene estadísticas generales del histórico."""
        with sqlite3.connect(self.db_path) as conn:
            # Total de runs
            total_runs = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
            
            if total_runs == 0:
                return {"total_runs": 0, "message": "No hay datos históricos"}
            
            # Promedio de fallos
            avg_failures = conn.execute(
                "SELECT AVG(total_failures) FROM runs"
            ).fetchone()[0]
            
            # Fingerprints únicos totales
            unique_fps = conn.execute(
                "SELECT COUNT(DISTINCT fingerprint) FROM fingerprint_history"
            ).fetchone()[0]
            
            # Tendencia últimos 5 runs
            recent = conn.execute("""
                SELECT total_failures FROM runs 
                ORDER BY timestamp DESC LIMIT 5
            """).fetchall()
            
            trend_values = [r[0] for r in recent]
            if len(trend_values) >= 2:
                if trend_values[0] < trend_values[-1]:
                    overall_trend = "improving"
                elif trend_values[0] > trend_values[-1]:
                    overall_trend = "degrading"
                else:
                    overall_trend = "stable"
            else:
                overall_trend = "unknown"
            
            return {
                "total_runs": total_runs,
                "avg_failures": round(avg_failures, 1) if avg_failures else 0,
                "unique_fingerprints_ever": unique_fps,
                "recent_trend": overall_trend,
                "recent_failures": trend_values
            }
    
    def cleanup_old_data(self, days: int = 90):
        """Elimina datos más antiguos que N días."""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM runs WHERE timestamp < ?", (cutoff,))
            conn.execute(
                "DELETE FROM fingerprint_history WHERE last_seen < ?", 
                (cutoff,)
            )
            conn.commit()


def format_regression_report(regression_info: RegressionInfo) -> str:
    """
    Formatea la información de regresión para incluir en el prompt del LLM.
    
    Args:
        regression_info: Información de regresión
        
    Returns:
        String formateado en Markdown
    """
    if regression_info.is_first_run:
        return """
## 📊 Histórico de Ejecuciones

**Esta es la primera ejecución registrada.** No hay datos históricos para comparar.
Los datos de esta ejecución se guardarán para futuras comparaciones.
"""
    
    lines = []
    lines.append("## 📊 Comparación con Ejecución Anterior")
    lines.append("")
    
    # Tendencia
    trend_desc = {
        "improving": "✅ **MEJORANDO** - Hay menos fallos que en la ejecución anterior",
        "degrading": "⚠️ **EMPEORANDO** - Hay más fallos que en la ejecución anterior", 
        "stable": "➡️ **ESTABLE** - Mismo número de fallos que antes"
    }
    lines.append(f"### Tendencia: {trend_desc.get(regression_info.trend, 'Desconocida')}")
    lines.append("")
    
    # Resumen numérico
    prev = regression_info.previous_run
    if prev:
        lines.append(f"- **Ejecución anterior:** {prev.total_failures} fallos "
                    f"({prev.timestamp[:16].replace('T', ' ')})")
        if prev.git_commit:
            lines.append(f"- **Commit anterior:** `{prev.git_commit}` ({prev.git_branch or 'unknown'})")
    
    lines.append("")
    
    # Nuevos fallos
    if regression_info.new_failures:
        lines.append(f"### 🆕 Nuevos Fallos ({len(regression_info.new_failures)})")
        lines.append("Estos errores **NO existían** en la ejecución anterior:")
        lines.append("")
        for fp in regression_info.new_failures[:5]:
            lines.append(f"- `{fp}`")
        if len(regression_info.new_failures) > 5:
            lines.append(f"- ... y {len(regression_info.new_failures) - 5} más")
        lines.append("")
    
    # Fallos corregidos
    if regression_info.fixed_failures:
        lines.append(f"### ✅ Fallos Corregidos ({len(regression_info.fixed_failures)})")
        lines.append("Estos errores **ya no aparecen**:")
        lines.append("")
        for fp in regression_info.fixed_failures[:5]:
            lines.append(f"- `{fp}`")
        if len(regression_info.fixed_failures) > 5:
            lines.append(f"- ... y {len(regression_info.fixed_failures) - 5} más")
        lines.append("")
    
    # Fallos persistentes
    if regression_info.persistent_failures:
        lines.append(f"### 🔄 Fallos Persistentes ({len(regression_info.persistent_failures)})")
        lines.append("Estos errores **siguen apareciendo**:")
        lines.append("")
        
        # Mostrar con contador de runs consecutivos
        for fp in regression_info.persistent_failures[:5]:
            consecutive = regression_info.consecutive_failures.get(fp, 1)
            if consecutive >= 3:
                lines.append(f"- `{fp}` ⚠️ ({consecutive} ejecuciones consecutivas)")
            else:
                lines.append(f"- `{fp}`")
        
        if len(regression_info.persistent_failures) > 5:
            lines.append(f"- ... y {len(regression_info.persistent_failures) - 5} más")
        lines.append("")
    
    # Tests flaky
    if regression_info.flaky_candidates:
        lines.append("### 🎲 Posibles Tests Intermitentes (Flaky)")
        lines.append("Estos tests aparecen de forma inconsistente entre ejecuciones:")
        lines.append("")
        for flaky in regression_info.flaky_candidates[:3]:
            status = "❌ fallando" if flaky['currently_failing'] else "✅ pasando"
            lines.append(
                f"- **{flaky['test_name']}** - {flaky['ratio']}% de aparición "
                f"({flaky['appearances']}/{flaky['total_runs']} runs) - Ahora: {status}"
            )
        lines.append("")
    
    return "\n".join(lines)
