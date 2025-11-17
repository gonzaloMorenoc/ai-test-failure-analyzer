import json
from pathlib import Path
from typing import List, Dict, Any

def load_cucumber_failures(path: Path) -> List[Dict[str, Any]]:
    """
    Parse a Cucumber JSON report and extract failed scenarios and steps.

    Returns a list of dicts with:
      - feature
      - scenario
      - step
      - status
      - error_message
    """
    failures: List[Dict[str, Any]] = []
    if not path.exists():
        return failures

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    for feature in data:
        feature_name = feature.get("name", "unknown_feature")
        for element in feature.get("elements", []):
            scenario_name = element.get("name", "unknown_scenario")
            for step in element.get("steps", []):
                result = step.get("result", {})
                status = result.get("status", "")
                if status != "failed":
                    continue
                failures.append(
                    {
                        "feature": feature_name,
                        "scenario": scenario_name,
                        "step": step.get("name", ""),
                        "status": status,
                        "error_message": result.get("error_message", "").strip(),
                    }
                )
    return failures