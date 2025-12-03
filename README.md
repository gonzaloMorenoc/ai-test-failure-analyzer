# 🤖 AI Test Failure Analyzer

Analizador inteligente de fallos de tests automatizados usando LLM (Ollama, OpenAI, Anthropic).

## ✨ Características

- **Multi-formato**: Soporta JUnit XML, Cucumber JSON y Playwright JSON
- **Análisis IA**: Usa LLM para identificar causas raíz y priorizar acciones
- **Fingerprinting**: Agrupa errores similares automáticamente para reducir ruido
- **Histórico y Regresiones**: Detecta nuevos fallos vs fallos persistentes
- **Detección de Flaky Tests**: Identifica tests intermitentes con métricas de estabilidad
- **Exit codes CI/CD**: Integración nativa con pipelines de CI/CD
- **Configuración flexible**: YAML + variables de entorno
- **Exportación**: HTML dashboard profesional + Markdown

## 🚀 Instalación

```bash
# Clonar repositorio
git clone https://github.com/tu-usuario/ai-test-analyzer.git
cd ai-test-analyzer

# Instalar dependencias
pip install -r requirements.txt

# (Opcional) Instalar Ollama
# https://ollama.ai/download
ollama pull llama3
```

## 📖 Uso Básico

```bash
# Análisis con archivos por defecto
python -m src.cli

# Especificar archivos
python -m src.cli --junit results/junit.xml --cucumber results/cucumber.json

# Con Playwright
python -m src.cli --playwright playwright-report.json

# Usar modelo diferente
python -m src.cli --model mistral

# Análisis completo con histórico y detección de flaky
python -m src.cli --enable-history --enable-flaky --show-exit-code
```

## 🔧 Configuración

### Archivo YAML

Copia `analyzer.example.yaml` a `analyzer.yaml`:

```yaml
llm:
  provider: ollama
  model: llama3
  base_url: http://localhost:11434
  timeout: 300

analysis:
  language: es
  max_failures: 50
  enable_fingerprinting: true
  enable_historical: true
  history_db_path: .analyzer_history.db

ci:
  fail_on_critical: true
  fail_on_any_failure: false
  critical_threshold: 1

flaky:
  enable_flaky_detection: true
  window_size: 20
  min_appearances: 3
  min_flakiness_score: 20.0
  fail_on_critical_flaky: false
  include_in_analysis: true
```

### Variables de Entorno

```bash
# LLM
export ANALYZER_LLM_PROVIDER=ollama
export ANALYZER_LLM_MODEL=llama3
export ANALYZER_LLM_URL=http://localhost:11434
export ANALYZER_API_KEY=sk-...  # Para OpenAI/Anthropic
export ANALYZER_LLM_TIMEOUT=300

# Salida
export ANALYZER_OUTPUT_DIR=./output
export ANALYZER_LANGUAGE=es

# Análisis
export ANALYZER_MAX_FAILURES=50
export ANALYZER_ENABLE_FINGERPRINT=true

# CI/CD
export ANALYZER_FAIL_ON_CRITICAL=true
export ANALYZER_FAIL_ON_ANY=false

# Flaky Detection
export ANALYZER_ENABLE_FLAKY=true
export ANALYZER_FLAKY_WINDOW_SIZE=20
export ANALYZER_FLAKY_WINDOW_DAYS=30
export ANALYZER_FLAKY_MIN_SCORE=20.0
export ANALYZER_FAIL_ON_CRITICAL_FLAKY=false
```

## 🔄 Integración CI/CD

### Exit Codes

| Código | Constante | Significado |
|--------|-----------|-------------|
| 0 | `SUCCESS` | ✅ Sin fallos |
| 1 | `FAILURES_FOUND` | ⚠️ Fallos encontrados (no críticos) |
| 2 | `CRITICAL_FAILURES` | ❌ Fallos críticos detectados |
| 3 | `ANALYSIS_ERROR` | 💥 Error durante el análisis |
| 4 | `CONFIG_ERROR` | ⚙️ Error de configuración |
| 5 | `NO_REPORTS_FOUND` | 📭 No se encontraron reportes |
| 6 | `REGRESSION_DETECTED` | 🚨 Regresión detectada (nuevos fallos) |
| 7 | `CRITICAL_FLAKY` | 🎲 Tests flaky críticos detectados |

### GitHub Actions

```yaml
- name: Run Test Analysis
  run: |
    python -m src.cli \
      --junit test-results/junit.xml \
      --enable-history \
      --enable-flaky \
      --fail-on-critical \
      --show-exit-code
  continue-on-error: false

- name: Upload Analysis Report
  if: always()
  uses: actions/upload-artifact@v3
  with:
    name: test-analysis
    path: |
      output/
      .analyzer_history.db
```

### GitLab CI

```yaml
analyze_tests:
  script:
    - pip install -r requirements.txt
    - python -m src.cli --junit junit.xml --enable-history --fail-on-critical
  artifacts:
    when: always
    paths:
      - output/
      - .analyzer_history.db
  cache:
    paths:
      - .analyzer_history.db
```

### Jenkins

```groovy
stage('Analyze Tests') {
    steps {
        sh '''
            python -m src.cli \
                --junit target/surefire-reports/*.xml \
                --enable-history \
                --enable-flaky \
                --fail-on-critical \
                --output-html reports/analysis.html
        '''
    }
    post {
        always {
            archiveArtifacts artifacts: 'output/**, .analyzer_history.db'
            publishHTML([
                reportName: 'Test Analysis',
                reportDir: 'output',
                reportFiles: '*.html'
            ])
        }
    }
}
```

## 🔍 Fingerprinting

El sistema de fingerprinting agrupa automáticamente errores similares eliminando:

- Timestamps y epochs
- UUIDs y correlation IDs
- Números de línea (Java, Python, JS/TS)
- Paths absolutos (Unix y Windows)
- IPs y puertos
- IDs dinámicos y hashes

**Beneficios:**
- Reduce el "ruido" en el análisis
- Identifica problemas sistémicos (mismo error en múltiples tests)
- Mejora la calidad de las recomendaciones del LLM
- Permite tracking de errores entre ejecuciones

```bash
# Desactivar fingerprinting si es necesario
python -m src.cli --no-fingerprint
```

## 📊 Histórico y Detección de Regresiones

El sistema mantiene un histórico de ejecuciones en SQLite para:

- **Detectar regresiones**: Identificar nuevos fallos que no existían antes
- **Tracking de correcciones**: Ver qué fallos se han resuelto
- **Fallos persistentes**: Identificar tests que llevan muchas ejecuciones fallando
- **Tendencias**: Ver si la calidad está mejorando o empeorando

### Uso

```bash
# Habilitar histórico
python -m src.cli --enable-history

# Especificar base de datos
python -m src.cli --enable-history --history-db ./my-history.db

# Desactivar histórico (si está habilitado en config)
python -m src.cli --no-history
```

### Salida de Ejemplo

```
📊 Comparación Histórica
   • Tendencia: ⚠️  EMPEORANDO
   • Nuevos fallos: 2 (⚠️  posibles regresiones)
   • Fallos corregidos: 1
   • Fallos persistentes: 3
   • Run anterior: 4 fallos
      Commit: abc1234
```

## 🎲 Detección de Tests Flaky

Un test **flaky** (intermitente) es aquel que produce resultados inconsistentes: a veces pasa, a veces falla, sin cambios en el código.

### Características

- **Flakiness Score (0-100)**: Métrica que indica qué tan inestable es un test
- **Detección de patrones**: random, degrading, improving, periodic
- **Severidades**: LOW (<30), MEDIUM (30-50), HIGH (50-70), CRITICAL (>70)
- **Recomendaciones específicas**: Basadas en el patrón y tipo de error

### Uso

```bash
# Habilitar detección de flaky (requiere histórico)
python -m src.cli --enable-history --enable-flaky

# Con ventana de 30 ejecuciones y score mínimo de 30
python -m src.cli --enable-history --enable-flaky \
    --flaky-window 30 --flaky-min-score 30

# Solo reporte de flaky tests (sin análisis LLM)
python -m src.cli --enable-history --flaky-report-only

# Fallar build si hay flaky críticos
python -m src.cli --enable-history --enable-flaky \
    --fail-on-critical-flaky --show-exit-code
```

### Algoritmo de Flakiness Score

El score se calcula combinando:

1. **Rate Score (50%)**: Qué tan cerca está del 50% de fallo (máxima incertidumbre)
2. **Transition Score (35%)**: Número de cambios de estado (pass↔fail)
3. **Streak Score (15%)**: Rachas cortas indican más inestabilidad

### Patrones Detectados

| Patrón | Descripción | Causa Probable |
|--------|-------------|----------------|
| `random` | Falla sin patrón predecible | Race conditions, sincronización |
| `degrading` | Empeorando con el tiempo | Memory leaks, degradación |
| `improving` | Mejorando recientemente | Fix parcial aplicado |
| `periodic` | Falla de forma alternada | Jobs programados, caché |

### Salida de Ejemplo

```
🎲 Detección de Tests Flaky
   • Ejecuciones analizadas: 15
   • Tests flaky detectados: 3
   • Score promedio: 45.2/100
   • Severidad: 1 críticos, 1 altos, 1 medios

   Tests más inestables:
      1. should_filter_products - Score: 72.3 - 48.5% fallo ❌
      2. should_add_to_cart - Score: 55.1 - 35.0% fallo ✅
      3. should_login_fast - Score: 32.8 - 28.0% fallo ❌
```

## 📈 Ejemplo de Salida Completa

```
🤖 AI Test Failure Analyzer
Provider: ollama | Model: llama3

📂 Cargando reportes de tests...
   ✓ JUnit: 2 tests fallidos en junit-report.xml
   ✓ Cucumber: 2 escenarios fallidos en cucumber-report.json

🔍 Análisis de Patrones (Fingerprinting)
   • Patrones únicos: 3
   • Reducción de ruido: 25%
   • Patrones repetidos: 1

📊 Comparación Histórica
   • Tendencia: ✅ MEJORANDO
   • Nuevos fallos: 0
   • Fallos corregidos: 2
   • Fallos persistentes: 2

🎲 Detección de Tests Flaky
   • Ejecuciones analizadas: 12
   • Tests flaky detectados: 1
   • Score promedio: 35.5/100

📊 Resumen de Tests Fallidos
┌──────────────────┬──────────────────┐
│ Tipo de Reporte  │ Tests Fallidos   │
├──────────────────┼──────────────────┤
│ JUnit            │                2 │
│ Cucumber         │                2 │
│ Playwright       │                0 │
│ TOTAL            │                4 │
└──────────────────┴──────────────────┘

🧠 Iniciando análisis con llama3...

✅ Análisis Completado
✓ Ejecución registrada en histórico

💾 Exportando resultados...
   ✓ Markdown guardado en: output/analysis-20240115_103000.md
   ✓ HTML guardado en: output/analysis-20240115_103000.html

Estado CI/CD
╭─────────────────────────────────────╮
│ ⚠️  FAILURES (exit code: 1)          │
│ Fallos encontrados (no críticos)    │
╰─────────────────────────────────────╯
```

## 🛠️ Opciones CLI Completas

```
usage: python -m src.cli [options]

Archivos de entrada:
  --junit PATH           Path al reporte JUnit XML (default: junit-report.xml)
  --cucumber PATH        Path al reporte Cucumber JSON (default: cucumber-report.json)
  --playwright PATH      Path al reporte Playwright JSON

Configuración:
  --config PATH          Path al archivo YAML de configuración
  --model MODEL          Modelo LLM (llama3, mistral, gpt-4o-mini...)
  --provider PROVIDER    Provider LLM (ollama, openai, anthropic)

Exportación:
  --output-md PATH       Exportar a Markdown
  --output-html PATH     Exportar a HTML
  --no-export            No auto-exportar

CI/CD:
  --fail-on-critical     Exit code 2 solo si hay críticos
  --fail-on-any          Exit code 1 con cualquier fallo
  --quiet, -q            Modo silencioso
  --show-exit-code       Mostrar info del exit code

Análisis:
  --no-fingerprint       Desactivar fingerprinting
  --max-failures N       Máximo de fallos a analizar

Histórico y regresiones:
  --enable-history       Habilitar tracking de histórico
  --no-history           Desactivar histórico (override de config)
  --history-db PATH      Path a la base de datos SQLite

Detección de tests flaky:
  --enable-flaky         Habilitar detección (requiere histórico)
  --no-flaky             Desactivar detección
  --flaky-window N       Número de ejecuciones a analizar (default: 20)
  --flaky-min-score N    Score mínimo para reportar (default: 20.0)
  --flaky-report-only    Solo generar reporte de flaky (sin análisis LLM)
  --fail-on-critical-flaky  Exit code 7 si hay flaky críticos
```

## 📁 Estructura del Proyecto

```
ai-test-analyzer/
├── src/
│   ├── __init__.py
│   ├── cli.py               # CLI principal
│   ├── analyzer.py          # Motor de análisis con LLM
│   ├── config.py            # Configuración (YAML + env)
│   ├── fingerprint.py       # Fingerprinting de errores
│   ├── history.py           # Histórico y regresiones (SQLite)
│   ├── flaky_detector.py    # Detección de tests flaky
│   ├── exporters.py         # Exportadores HTML/Markdown
│   ├── loaders/
│   │   ├── junit_loader.py
│   │   ├── cucumber_loader.py
│   │   └── playwright_loader.py
│   └── llm/
│       └── ollama_client.py
├── analyzer.yaml            # Configuración activa
├── analyzer.example.yaml    # Configuración de ejemplo
├── requirements.txt
├── .gitignore
└── README.md
```

## 🗺️ Roadmap

### ✅ Implementado

- [x] Análisis multi-formato (JUnit, Cucumber, Playwright)
- [x] Fingerprinting de errores
- [x] Exit codes para CI/CD
- [x] Configuración externa (YAML + env vars)
- [x] Histórico y detección de regresiones
- [x] Detección de tests flaky
- [x] Exportación HTML/Markdown

### 🔜 Próximas Mejoras

- [ ] Multi-Provider LLM (OpenAI, Anthropic, Azure)
- [ ] Exportación JSON
- [ ] Notificaciones Slack/Teams
- [ ] API REST

## 📝 Licencia

MIT License
