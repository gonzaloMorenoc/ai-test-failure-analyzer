"""
Módulo de fingerprinting para identificar y agrupar errores similares.

El fingerprinting normaliza los mensajes de error eliminando:
- Timestamps
- UUIDs y correlation IDs
- Números de línea específicos
- Paths absolutos
- IDs dinámicos

Esto permite identificar patrones de error que son esencialmente el mismo problema
aunque tengan diferentes valores dinámicos.
"""

import hashlib
import re
from typing import Dict, Any, List, Tuple
from dataclasses import dataclass


@dataclass
class FingerPrintResult:
    """Resultado del fingerprinting de un error."""
    fingerprint: str
    normalized_error: str
    original_error: str
    confidence: float  # 0.0 - 1.0, qué tan seguro estamos de la normalización


# Patrones de normalización ordenados por especificidad
NORMALIZATION_PATTERNS: List[Tuple[re.Pattern, str, str]] = [
    # Timestamps ISO
    (re.compile(r'\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?'), 
     '<TIMESTAMP>', 'timestamp'),
    
    # Timestamps Unix epoch (milisegundos)
    (re.compile(r'\b1[0-9]{12}\b'), '<EPOCH_MS>', 'epoch'),
    
    # UUIDs (todas las variantes)
    (re.compile(r'[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}'), 
     '<UUID>', 'uuid'),
    
    # Correlation IDs y Request IDs comunes
    (re.compile(r'(?:correlation[_-]?id|request[_-]?id|trace[_-]?id|span[_-]?id)["\s:=]+["\']?[\w-]+["\']?', re.IGNORECASE), 
     'correlation_id: <ID>', 'correlation'),
    
    # Session IDs y tokens
    (re.compile(r'(?:session[_-]?id|token|bearer)["\s:=]+["\']?[\w.-]+["\']?', re.IGNORECASE), 
     'session: <TOKEN>', 'session'),
    
    # Números de línea en stack traces (Java style)
    (re.compile(r'\.java:\d+'), '.java:<LINE>', 'java_line'),
    
    # Números de línea en stack traces (JS/TS style)  
    (re.compile(r'\.(js|ts|jsx|tsx):\d+:\d+'), r'.\1:<LINE>:<COL>', 'js_line'),
    
    # Números de línea en stack traces (Python style)
    (re.compile(r'\.py", line \d+'), '.py", line <LINE>', 'py_line'),
    
    # Números de línea genéricos
    (re.compile(r'(?:line|línea|row|fila)\s*:?\s*\d+', re.IGNORECASE), 
     'line: <LINE>', 'generic_line'),
    
    # Paths absolutos Unix
    (re.compile(r'/(?:home|usr|var|tmp|opt|app|src|node_modules)/[\w/.@-]+'), 
     '<PATH>', 'unix_path'),
    
    # Paths absolutos Windows
    (re.compile(r'[A-Z]:\\[\w\\.-]+'), '<PATH>', 'windows_path'),
    
    # IPs y puertos
    (re.compile(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(?::\d+)?\b'), 
     '<IP>', 'ip_address'),
    
    # URLs con IDs dinámicos
    (re.compile(r'(https?://[^\s]+?)/\d+(?=/|$|\s)'), r'\1/<ID>', 'url_id'),
    
    # Números de puerto
    (re.compile(r'(?:port|puerto)\s*:?\s*\d+', re.IGNORECASE), 
     'port: <PORT>', 'port'),
    
    # Durations/timeouts específicos
    (re.compile(r'\b\d+\s*(?:ms|milliseconds?|seconds?|s|minutes?|min)\b', re.IGNORECASE), 
     '<DURATION>', 'duration'),
    
    # IDs numéricos largos (probablemente auto-generados)
    (re.compile(r'\b\d{10,}\b'), '<LONG_ID>', 'long_id'),
    
    # Hashes hexadecimales largos
    (re.compile(r'\b[a-fA-F0-9]{32,}\b'), '<HASH>', 'hash'),
]


def normalize_error_message(error_text: str) -> Tuple[str, List[str]]:
    """
    Normaliza un mensaje de error eliminando elementos dinámicos.
    
    Args:
        error_text: El mensaje de error original
        
    Returns:
        Tupla de (mensaje_normalizado, lista_de_patrones_aplicados)
    """
    if not error_text:
        return "", []
    
    normalized = error_text
    patterns_applied = []
    
    for pattern, replacement, pattern_name in NORMALIZATION_PATTERNS:
        if pattern.search(normalized):
            normalized = pattern.sub(replacement, normalized)
            patterns_applied.append(pattern_name)
    
    # Normalización adicional: colapsar espacios múltiples
    normalized = re.sub(r'\s+', ' ', normalized).strip()
    
    return normalized, patterns_applied


def generate_fingerprint(failure: Dict[str, Any]) -> FingerPrintResult:
    """
    Genera un fingerprint único para un fallo de test.
    
    El fingerprint se basa en:
    1. El mensaje de error normalizado
    2. El tipo de error (si está disponible)
    3. El nombre del test (parcialmente, sin parámetros)
    
    Args:
        failure: Diccionario con información del fallo
        
    Returns:
        FingerPrintResult con el fingerprint y metadata
    """
    # Extraer mensaje de error (diferentes formatos según el loader)
    error_text = (
        failure.get("error_message") or 
        failure.get("failure_message") or 
        failure.get("failure_text") or 
        ""
    )
    
    # Extraer tipo de error si existe
    error_type = failure.get("failure_type", "")
    
    # Normalizar
    normalized_error, patterns_applied = normalize_error_message(error_text)
    normalized_type, _ = normalize_error_message(error_type)
    
    # Calcular confianza basada en cuántos patrones se aplicaron
    # Más patrones = más normalización = menos confianza en la unicidad
    confidence = max(0.3, 1.0 - (len(patterns_applied) * 0.1))
    
    # Construir string para hash
    hash_input = f"{normalized_type}|{normalized_error}"
    
    # Generar hash MD5 truncado (12 caracteres es suficiente para identificar)
    fingerprint = hashlib.md5(hash_input.encode('utf-8')).hexdigest()[:12]
    
    return FingerPrintResult(
        fingerprint=fingerprint,
        normalized_error=normalized_error[:500],  # Truncar para no guardar demasiado
        original_error=error_text[:500],
        confidence=round(confidence, 2)
    )


def group_failures_by_fingerprint(
    failures: List[Dict[str, Any]], 
    source_type: str = "unknown"
) -> Dict[str, Dict[str, Any]]:
    """
    Agrupa una lista de fallos por su fingerprint.
    
    Args:
        failures: Lista de fallos (del formato de cualquier loader)
        source_type: Tipo de fuente (junit, cucumber, playwright)
        
    Returns:
        Diccionario donde:
        - key: fingerprint
        - value: {
            'count': número de ocurrencias,
            'failures': lista de fallos con este fingerprint,
            'representative': el primer fallo (como ejemplo),
            'normalized_error': error normalizado,
            'confidence': confianza promedio
        }
    """
    groups: Dict[str, Dict[str, Any]] = {}
    
    for failure in failures:
        # Añadir source_type al failure para tracking
        failure['_source_type'] = source_type
        
        fp_result = generate_fingerprint(failure)
        failure['_fingerprint'] = fp_result.fingerprint
        failure['_normalized_error'] = fp_result.normalized_error
        
        if fp_result.fingerprint not in groups:
            groups[fp_result.fingerprint] = {
                'count': 0,
                'failures': [],
                'representative': failure,
                'normalized_error': fp_result.normalized_error,
                'confidence': fp_result.confidence,
                'source_types': set()
            }
        
        groups[fp_result.fingerprint]['count'] += 1
        groups[fp_result.fingerprint]['failures'].append(failure)
        groups[fp_result.fingerprint]['source_types'].add(source_type)
        
        # Actualizar confianza promedio
        current_confidence = groups[fp_result.fingerprint]['confidence']
        count = groups[fp_result.fingerprint]['count']
        groups[fp_result.fingerprint]['confidence'] = round(
            (current_confidence * (count - 1) + fp_result.confidence) / count, 2
        )
    
    # Convertir sets a listas para serialización
    for fp in groups:
        groups[fp]['source_types'] = list(groups[fp]['source_types'])
    
    return groups


def get_pattern_summary(
    grouped_failures: Dict[str, Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Genera un resumen de los patrones encontrados.
    
    Args:
        grouped_failures: Resultado de group_failures_by_fingerprint
        
    Returns:
        Resumen con estadísticas y patrones destacados
    """
    total_failures = sum(g['count'] for g in grouped_failures.values())
    unique_patterns = len(grouped_failures)
    
    # Ordenar por número de ocurrencias (descendente)
    sorted_patterns = sorted(
        grouped_failures.items(),
        key=lambda x: x[1]['count'],
        reverse=True
    )
    
    # Identificar patrones repetidos (más de 1 ocurrencia)
    repeated_patterns = [
        (fp, data) for fp, data in sorted_patterns if data['count'] > 1
    ]
    
    # Calcular reducción de ruido
    noise_reduction = 0
    if total_failures > 0:
        noise_reduction = round((1 - unique_patterns / total_failures) * 100, 1)
    
    return {
        'total_failures': total_failures,
        'unique_patterns': unique_patterns,
        'repeated_patterns_count': len(repeated_patterns),
        'noise_reduction_percent': noise_reduction,
        'top_patterns': [
            {
                'fingerprint': fp,
                'count': data['count'],
                'normalized_error': data['normalized_error'][:200],
                'source_types': data['source_types']
            }
            for fp, data in sorted_patterns[:5]  # Top 5 patrones
        ],
        'repeated_patterns': [
            {
                'fingerprint': fp,
                'count': data['count'],
                'normalized_error': data['normalized_error'][:200]
            }
            for fp, data in repeated_patterns
        ]
    }


def format_fingerprint_report(summary: Dict[str, Any]) -> str:
    """
    Formatea el resumen de fingerprints para incluir en el prompt del LLM.
    
    Args:
        summary: Resultado de get_pattern_summary
        
    Returns:
        String formateado en Markdown
    """
    lines = []
    
    lines.append("## Análisis de Patrones de Error (Fingerprinting)")
    lines.append("")
    lines.append(f"- **Total de fallos:** {summary['total_failures']}")
    lines.append(f"- **Patrones únicos:** {summary['unique_patterns']}")
    lines.append(f"- **Reducción de ruido:** {summary['noise_reduction_percent']}%")
    lines.append("")
    
    if summary['repeated_patterns']:
        lines.append("### ⚠️ Patrones Repetidos Detectados")
        lines.append("")
        lines.append("Estos errores aparecen múltiples veces, lo que sugiere un problema sistémico:")
        lines.append("")
        
        for pattern in summary['repeated_patterns']:
            lines.append(f"- **[{pattern['count']}x]** `{pattern['fingerprint']}`: {pattern['normalized_error'][:100]}...")
        
        lines.append("")
    
    if summary['top_patterns']:
        lines.append("### Top 5 Patrones de Error")
        lines.append("")
        
        for i, pattern in enumerate(summary['top_patterns'], 1):
            sources = ", ".join(pattern['source_types'])
            lines.append(f"{i}. **{pattern['count']} ocurrencia(s)** [{sources}]")
            lines.append(f"   - Fingerprint: `{pattern['fingerprint']}`")
            lines.append(f"   - Error: {pattern['normalized_error'][:150]}...")
            lines.append("")
    
    return "\n".join(lines)