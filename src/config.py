"""
Módulo de configuración externa para AI Test Failure Analyzer.

Soporta:
- Archivo YAML de configuración
- Variables de entorno (override)
- Valores por defecto sensatos
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Dict, Any

# Intentar importar yaml, si no está disponible usar solo env vars
try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False


@dataclass
class LLMConfig:
    """Configuración del proveedor LLM."""
    provider: str = "ollama"  # ollama, openai, anthropic
    model: str = "llama3"
    base_url: str = "http://localhost:11434"
    api_key: Optional[str] = None
    timeout: int = 300
    temperature: float = 0.3


@dataclass
class OutputConfig:
    """Configuración de exportación de resultados."""
    directory: Path = field(default_factory=lambda: Path("output"))
    formats: list = field(default_factory=lambda: ["html", "md"])
    include_raw: bool = True


@dataclass
class AnalysisConfig:
    """Configuración del análisis."""
    language: str = "es"
    max_failures_to_analyze: int = 50  # Limitar para no saturar contexto del LLM
    enable_fingerprinting: bool = True
    enable_historical: bool = False
    history_db_path: Path = field(default_factory=lambda: Path(".analyzer_history.db"))


@dataclass 
class CIConfig:
    """Configuración para integración CI/CD."""
    fail_on_critical: bool = True
    fail_on_any_failure: bool = False
    critical_threshold: int = 1  # Número de críticos para fallar el build


@dataclass
class AnalyzerConfig:
    """Configuración principal del analizador."""
    llm: LLMConfig = field(default_factory=LLMConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    analysis: AnalysisConfig = field(default_factory=AnalysisConfig)
    ci: CIConfig = field(default_factory=CIConfig)


def _deep_merge(base: Dict, override: Dict) -> Dict:
    """Merge profundo de diccionarios."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _apply_env_overrides(config: AnalyzerConfig) -> AnalyzerConfig:
    """Aplica overrides desde variables de entorno."""
    
    # LLM Config
    if env_val := os.getenv("ANALYZER_LLM_PROVIDER"):
        config.llm.provider = env_val
    if env_val := os.getenv("ANALYZER_LLM_MODEL"):
        config.llm.model = env_val
    if env_val := os.getenv("ANALYZER_LLM_URL"):
        config.llm.base_url = env_val
    if env_val := os.getenv("ANALYZER_API_KEY"):
        config.llm.api_key = env_val
    if env_val := os.getenv("ANALYZER_LLM_TIMEOUT"):
        config.llm.timeout = int(env_val)
    
    # Output Config
    if env_val := os.getenv("ANALYZER_OUTPUT_DIR"):
        config.output.directory = Path(env_val)
    
    # Analysis Config
    if env_val := os.getenv("ANALYZER_LANGUAGE"):
        config.analysis.language = env_val
    if env_val := os.getenv("ANALYZER_MAX_FAILURES"):
        config.analysis.max_failures_to_analyze = int(env_val)
    if env_val := os.getenv("ANALYZER_ENABLE_FINGERPRINT"):
        config.analysis.enable_fingerprinting = env_val.lower() in ("true", "1", "yes")
    
    # CI Config
    if env_val := os.getenv("ANALYZER_FAIL_ON_CRITICAL"):
        config.ci.fail_on_critical = env_val.lower() in ("true", "1", "yes")
    if env_val := os.getenv("ANALYZER_FAIL_ON_ANY"):
        config.ci.fail_on_any_failure = env_val.lower() in ("true", "1", "yes")
    
    return config


def _config_from_dict(data: Dict[str, Any]) -> AnalyzerConfig:
    """Construye AnalyzerConfig desde un diccionario."""
    config = AnalyzerConfig()
    
    # LLM
    if llm_data := data.get("llm"):
        config.llm.provider = llm_data.get("provider", config.llm.provider)
        config.llm.model = llm_data.get("model", config.llm.model)
        config.llm.base_url = llm_data.get("base_url", config.llm.base_url)
        config.llm.api_key = llm_data.get("api_key", config.llm.api_key)
        config.llm.timeout = llm_data.get("timeout", config.llm.timeout)
        config.llm.temperature = llm_data.get("temperature", config.llm.temperature)
    
    # Output
    if output_data := data.get("output"):
        if output_dir := output_data.get("directory"):
            config.output.directory = Path(output_dir)
        config.output.formats = output_data.get("formats", config.output.formats)
        config.output.include_raw = output_data.get("include_raw", config.output.include_raw)
    
    # Analysis
    if analysis_data := data.get("analysis"):
        config.analysis.language = analysis_data.get("language", config.analysis.language)
        config.analysis.max_failures_to_analyze = analysis_data.get(
            "max_failures", config.analysis.max_failures_to_analyze
        )
        config.analysis.enable_fingerprinting = analysis_data.get(
            "enable_fingerprinting", config.analysis.enable_fingerprinting
        )
        config.analysis.enable_historical = analysis_data.get(
            "enable_historical", config.analysis.enable_historical
        )
        if history_path := analysis_data.get("history_db_path"):
            config.analysis.history_db_path = Path(history_path)
    
    # CI
    if ci_data := data.get("ci"):
        config.ci.fail_on_critical = ci_data.get("fail_on_critical", config.ci.fail_on_critical)
        config.ci.fail_on_any_failure = ci_data.get("fail_on_any_failure", config.ci.fail_on_any_failure)
        config.ci.critical_threshold = ci_data.get("critical_threshold", config.ci.critical_threshold)
    
    return config


def load_config(config_path: Optional[Path] = None) -> AnalyzerConfig:
    """
    Carga configuración con la siguiente prioridad:
    1. Valores por defecto
    2. Archivo YAML (si existe)
    3. Variables de entorno (override final)
    
    Args:
        config_path: Path al archivo de configuración YAML.
                    Si es None, busca 'analyzer.yaml' o 'analyzer.yml' en el directorio actual.
    
    Returns:
        AnalyzerConfig con la configuración final.
    """
    config = AnalyzerConfig()
    
    # Buscar archivo de configuración
    if config_path is None:
        for filename in ["analyzer.yaml", "analyzer.yml", "config.yaml", "config.yml"]:
            candidate = Path(filename)
            if candidate.exists():
                config_path = candidate
                break
    
    # Cargar desde YAML si existe y está disponible
    if config_path and config_path.exists():
        if not YAML_AVAILABLE:
            import warnings
            warnings.warn(
                f"Archivo de configuración encontrado ({config_path}) pero PyYAML no está instalado. "
                "Instala con: pip install pyyaml"
            )
        else:
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    yaml_data = yaml.safe_load(f) or {}
                config = _config_from_dict(yaml_data)
            except Exception as e:
                import warnings
                warnings.warn(f"Error al cargar configuración desde {config_path}: {e}")
    
    # Aplicar overrides de variables de entorno
    config = _apply_env_overrides(config)
    
    # Asegurar que el directorio de output existe
    config.output.directory.mkdir(parents=True, exist_ok=True)
    
    return config


# Singleton para acceso global (opcional)
_global_config: Optional[AnalyzerConfig] = None


def get_config() -> AnalyzerConfig:
    """Obtiene la configuración global (lazy loading)."""
    global _global_config
    if _global_config is None:
        _global_config = load_config()
    return _global_config


def reset_config():
    """Resetea la configuración global (útil para tests)."""
    global _global_config
    _global_config = None