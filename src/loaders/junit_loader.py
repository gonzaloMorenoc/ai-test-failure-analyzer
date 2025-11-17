import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Dict, Any

def load_junit_failures(path: Path) -> List[Dict[str, Any]]:
    """
    Parse a JUnit XML report and extract failed test cases.

    Returns a list of dicts with:
      - suite
      - name
      - classname
      - failure_message
      - failure_type
      - failure_text (stacktrace or detailed info)
    """
    failures = []
    if not path.exists():
        return failures

    tree = ET.parse(path)
    root = tree.getroot()

    # Works for both <testsuite> root and <testsuites> root
    testsuites = []
    if root.tag == "testsuite":
        testsuites = [root]
    elif root.tag == "testsuites":
        testsuites = root.findall("testsuite")

    for suite in testsuites:
        suite_name = suite.attrib.get("name", "unknown_suite")
        for testcase in suite.findall("testcase"):
            failure_elem = testcase.find("failure")
            error_elem = testcase.find("error")

            if failure_elem is None and error_elem is None:
                continue

            elem = failure_elem if failure_elem is not None else error_elem
            failure_message = elem.attrib.get("message", "")
            failure_type = elem.attrib.get("type", "")
            failure_text = (elem.text or "").strip()

            failures.append(
                {
                    "suite": suite_name,
                    "name": testcase.attrib.get("name", "unknown_test"),
                    "classname": testcase.attrib.get("classname", ""),
                    "failure_message": failure_message,
                    "failure_type": failure_type,
                    "failure_text": failure_text,
                }
            )
    return failures