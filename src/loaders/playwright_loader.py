import json
from pathlib import Path
from typing import List, Dict, Any


def load_playwright_failures(path: Path) -> List[Dict[str, Any]]:
    """
    Parse a Playwright JSON report and extract failed tests.

    Playwright JSON format example:
    {
      "suites": [
        {
          "title": "suite name",
          "specs": [
            {
              "title": "test name",
              "tests": [
                {
                  "status": "expected|unexpected|flaky|skipped",
                  "results": [
                    {
                      "status": "passed|failed|timedOut|interrupted",
                      "error": {
                        "message": "Error message",
                        "stack": "Stack trace"
                      }
                    }
                  ]
                }
              ]
            }
          ]
        }
      ]
    }

    Returns a list of dicts with:
      - suite
      - spec (test file/spec name)
      - test
      - status
      - error_message
      - stack_trace
    """
    failures: List[Dict[str, Any]] = []
    
    if not path.exists():
        return failures

    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        print(f"⚠️  Error al leer Playwright JSON: {e}")
        return failures

    # Navegar por la estructura de Playwright
    suites = data.get("suites", [])
    
    for suite in suites:
        suite_title = suite.get("title", "unknown_suite")
        
        # Procesar specs (archivos de test)
        for spec in suite.get("specs", []):
            spec_title = spec.get("title", "unknown_spec")
            
            # Procesar tests
            for test in spec.get("tests", []):
                test_status = test.get("status", "")
                
                # Procesar resultados (puede haber múltiples intentos/retries)
                for result in test.get("results", []):
                    result_status = result.get("status", "")
                    
                    # Considerar como fallo: failed, timedOut, interrupted
                    if result_status in ["failed", "timedOut", "interrupted"]:
                        error_info = result.get("error", {})
                        error_message = error_info.get("message", "")
                        stack_trace = error_info.get("stack", "")
                        
                        failures.append({
                            "suite": suite_title,
                            "spec": spec_title,
                            "test": spec.get("title", "unknown_test"),
                            "status": result_status,
                            "test_status": test_status,
                            "error_message": error_message.strip(),
                            "stack_trace": stack_trace.strip(),
                        })

    return failures
