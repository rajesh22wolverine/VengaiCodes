"""Normalize pytest-json-report output (backend-results.json) and the Jest/Vitest
JSON reporter output (frontend-results.json, same shape for both — Vitest's
"json" reporter is modeled after Jest's) into one merged test-results.json:

  {"passed": int, "failed": int, "total": int,
   "failures": [{"file": str, "test_name": str, "message": str}]}

Run from the repo root, after whichever of backend-results.json/
frontend-results.json exist have been produced.
"""
import json
import os

passed = 0
failed = 0
total = 0
failures = []

if os.path.exists("backend-results.json"):
    try:
        with open("backend-results.json", "r", encoding="utf-8") as f:
            backend = json.load(f)
        summary = backend.get("summary", {})
        passed += summary.get("passed", 0)
        failed += summary.get("failed", 0)
        total += summary.get("total", 0)
        for test in backend.get("tests", []):
            if test.get("outcome") != "failed":
                continue
            nodeid = test.get("nodeid", "")
            file_path = nodeid.split("::")[0] if "::" in nodeid else nodeid
            test_name = nodeid.split("::")[-1] if "::" in nodeid else nodeid
            longrepr = (test.get("call") or {}).get("longrepr", "") or ""
            failures.append({
                "file": file_path,
                "test_name": test_name,
                "message": str(longrepr)[:2000],
            })
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        print(f"Warning: could not parse backend-results.json: {e}")

if os.path.exists("frontend-results.json"):
    try:
        with open("frontend-results.json", "r", encoding="utf-8") as f:
            frontend = json.load(f)
        passed += frontend.get("numPassedTests", 0)
        failed += frontend.get("numFailedTests", 0)
        total += frontend.get("numTotalTests", 0)
        for file_result in frontend.get("testResults", []):
            file_path = file_result.get("name", "")
            for assertion in file_result.get("assertionResults", []):
                if assertion.get("status") != "failed":
                    continue
                messages = assertion.get("failureMessages", [])
                failures.append({
                    "file": file_path,
                    "test_name": assertion.get("fullName") or assertion.get("title", ""),
                    "message": "\n".join(messages)[:2000],
                })
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        print(f"Warning: could not parse frontend-results.json: {e}")

result = {"passed": passed, "failed": failed, "total": total, "failures": failures}

with open("test-results.json", "w", encoding="utf-8") as f:
    json.dump(result, f, indent=2)

print(f"Merged results: {passed} passed, {failed} failed, {total} total, {len(failures)} failure(s) recorded")
