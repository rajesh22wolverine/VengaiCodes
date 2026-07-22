"""Normalize every test recipe's raw result output into one merged
test-results.json:

  {"passed": int, "failed": int, "total": int,
   "failures": [{"file": str, "test_name": str, "message": str}]}

Run from the repo root, after run-tests.yml's backend/frontend test steps
have produced whichever raw result file(s) apply to this project's actual
recipes (BACKEND_RECIPE/FRONTEND_RECIPE env vars, from
app.ai.testing_recipes's recipe keys — duplicated here as a small format
lookup table rather than importing the full backend app, since this script
runs in a minimal CI environment with none of that installed).
"""
import glob
import json
import os
import re
import xml.etree.ElementTree as ET

passed = 0
failed = 0
total = 0
failures = []

BACKEND_RECIPE = os.environ.get("BACKEND_RECIPE", "")
FRONTEND_RECIPE = os.environ.get("FRONTEND_RECIPE", "")

# Keep in sync with app.ai.testing_recipes.py's TestRecipe.result_format —
# duplicated as plain strings here since this script can't import the
# backend app (no dependencies installed in this minimal CI job).
JSON_RESULT_RECIPES = {"pytest", "unittest", "pytest_django"}
JEST_RESULT_RECIPES = {"jest_rtl", "vitest_rtl", "vitest_vtu", "vitest_svelte", "vitest_jsdom", "jest_supertest", "jest_nestjs"}


def add(p, f, t, fails):
    global passed, failed, total
    passed += p
    failed += f
    total += t
    failures.extend(fails)


# ─── pytest-json (pytest-json-report format) ───
def parse_pytest_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    summary = data.get("summary", {})
    fails = []
    for test in data.get("tests", []):
        if test.get("outcome") != "failed":
            continue
        nodeid = test.get("nodeid", "")
        file_path = nodeid.split("::")[0] if "::" in nodeid else nodeid
        test_name = nodeid.split("::")[-1] if "::" in nodeid else nodeid
        longrepr = (test.get("call") or {}).get("longrepr", "") or ""
        fails.append({"file": file_path, "test_name": test_name, "message": str(longrepr)[:2000]})
    return summary.get("passed", 0), summary.get("failed", 0), summary.get("total", 0), fails


# ─── Jest/Vitest --json reporter (same shape for both) ───
def parse_jest_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    fails = []
    for file_result in data.get("testResults", []):
        file_path = file_result.get("name", "")
        for assertion in file_result.get("assertionResults", []):
            if assertion.get("status") != "failed":
                continue
            messages = assertion.get("failureMessages", [])
            fails.append({
                "file": file_path,
                "test_name": assertion.get("fullName") or assertion.get("title", ""),
                "message": "\n".join(messages)[:2000],
            })
    return data.get("numPassedTests", 0), data.get("numFailedTests", 0), data.get("numTotalTests", 0), fails


# ─── JUnit XML (shared by Spring Boot/Maven surefire, PHPUnit, Gradle unit
# tests, karma-junit-reporter) — accepts a glob so callers with multiple
# report files (Maven/Gradle) can pass all of them at once. ───
def parse_junit_xml(paths: list[str]):
    p = f = t = 0
    fails = []
    for path in paths:
        try:
            root = ET.parse(path).getroot()
        except ET.ParseError as e:
            print(f"Warning: could not parse {path}: {e}")
            continue
        suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
        for suite in suites:
            suite_failed = int(suite.get("failures", 0)) + int(suite.get("errors", 0))
            suite_total = int(suite.get("tests", 0))
            t += suite_total
            f += suite_failed
            p += suite_total - suite_failed
            for case in suite.findall("testcase"):
                failure_el = case.find("failure")
                error_el = case.find("error")
                bad = failure_el if failure_el is not None else error_el
                if bad is None:
                    continue
                fails.append({
                    "file": case.get("classname", path),
                    "test_name": case.get("name", "?"),
                    "message": (bad.get("message", "") + "\n" + (bad.text or ""))[:2000],
                })
    return p, f, t, fails


# ─── RSpec's own --format json ───
def parse_rspec_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    summary = data.get("summary", {})
    fails = []
    for ex in data.get("examples", []):
        if ex.get("status") != "failed":
            continue
        exception = ex.get("exception") or {}
        fails.append({
            "file": ex.get("file_path", ""),
            "test_name": ex.get("full_description") or ex.get("description", ""),
            "message": str(exception.get("message", ""))[:2000],
        })
    example_count = summary.get("example_count", 0)
    failure_count = summary.get("failure_count", 0)
    return example_count - failure_count, failure_count, example_count, fails


# ─── go test -json (JSON Lines) ───
def parse_go_jsonl(path: str):
    tests: dict[str, dict] = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            test_name = event.get("Test")
            if not test_name:
                continue  # package-level event, not a per-test result
            entry = tests.setdefault(test_name, {"output": [], "result": None})
            action = event.get("Action")
            if action == "output":
                entry["output"].append(event.get("Output", ""))
            elif action in ("pass", "fail", "skip"):
                entry["result"] = action

    p = f = 0
    fails = []
    for name, entry in tests.items():
        if entry["result"] == "pass":
            p += 1
        elif entry["result"] == "fail":
            f += 1
            fails.append({"file": "", "test_name": name, "message": "".join(entry["output"])[:2000]})
    return p, f, p + f, fails


# ─── flutter test --machine (JSON Lines) ───
def parse_flutter_jsonl(path: str):
    test_names: dict[int, str] = {}
    errors: dict[int, list[str]] = {}
    results: dict[int, str] = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or not line.startswith("{"):
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            event_type = event.get("type")
            if event_type == "testStart":
                test = event.get("test", {})
                test_names[test.get("id")] = test.get("name", "?")
            elif event_type == "error":
                errors.setdefault(event.get("testID"), []).append(
                    f"{event.get('error', '')}\n{event.get('stackTrace', '')}"
                )
            elif event_type == "testDone":
                results[event.get("testID")] = "failure" if not event.get("result") == "success" or event.get("hidden") else event.get("result", "success")

    p = f = 0
    fails = []
    for test_id, result in results.items():
        if result == "success":
            p += 1
        else:
            f += 1
            fails.append({
                "file": "",
                "test_name": test_names.get(test_id, f"test #{test_id}"),
                "message": "\n".join(errors.get(test_id, []))[:2000],
            })
    return p, f, p + f, fails


# ─── .trx (Visual Studio Test Results, dotnet test's own XML schema —
# distinct from JUnit XML) ───
def parse_trx(path: str):
    ns = {"vs": "http://microsoft.com/schemas/VisualStudio/TeamTest/2010"}
    root = ET.parse(path).getroot()
    counters = root.find(".//vs:ResultSummary/vs:Counters", ns)
    if counters is None:
        counters = root.find(".//ResultSummary/Counters")  # some trx files omit the default namespace
    p_count = int(counters.get("passed", 0)) if counters is not None else 0
    f_count = int(counters.get("failed", 0)) if counters is not None else 0
    t_count = int(counters.get("total", 0)) if counters is not None else 0

    fails = []
    results = root.findall(".//vs:UnitTestResult", ns) or root.findall(".//UnitTestResult")
    for r in results:
        if r.get("outcome") != "Failed":
            continue
        # NOTE: `find() or find()` is unreliable here — an Element with no
        # children (like a plain-text <Message>) is falsy via __len__(),
        # so `or` would wrongly fall through to the second lookup even
        # when the first one found the real element. Must check `is None`.
        message_el = r.find(".//vs:Output/vs:ErrorInfo/vs:Message", ns)
        if message_el is None:
            message_el = r.find(".//Output/ErrorInfo/Message")
        fails.append({
            "file": "",
            "test_name": r.get("testName", "?"),
            "message": (message_el.text or "")[:2000] if message_el is not None else "",
        })
    return p_count, f_count, t_count, fails


# ─── cargo test's plain-text summary (stable Rust has no built-in JSON
# test output — see run-tests.yml's module docstring for why this MVP
# uses regex over the human-readable output instead of an extra
# cargo2junit/cargo-nextest install) ───
def parse_cargo_text(path: str):
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    fails = []
    for match in re.finditer(r"^test (\S+) \.\.\. (ok|FAILED)\s*$", content, re.MULTILINE):
        name, outcome = match.groups()
        if outcome == "FAILED":
            # Best-effort: cargo prints a "---- {name} stdout ----" block
            # with the panic message for each failed test, after the
            # summary line. Not guaranteed present for every failure mode.
            block_match = re.search(
                rf"---- {re.escape(name)} stdout ----\n(.*?)(?=\n---- |\nfailures:|\Z)",
                content, re.DOTALL,
            )
            fails.append({
                "file": "",
                "test_name": name,
                "message": (block_match.group(1).strip() if block_match else "")[:2000],
            })

    summary_match = re.search(
        r"test result: \w+\. (\d+) passed; (\d+) failed;", content
    )
    if summary_match:
        p, f = int(summary_match.group(1)), int(summary_match.group(2))
    else:
        p, f = len(fails) * 0, len(fails)  # no summary line found — fall back to counted failures only
    return p, f, p + f, fails


# ══════════════════════════════════════════════════════════════
#  Dispatch — exactly one backend recipe and one frontend recipe
#  apply per run, matched against whichever raw output file(s)
#  that recipe's run-tests.yml step actually produced.
# ══════════════════════════════════════════════════════════════
try:
    if BACKEND_RECIPE in JSON_RESULT_RECIPES and os.path.exists("backend-results.json"):
        add(*parse_pytest_json("backend-results.json"))
    elif BACKEND_RECIPE in ("jest_supertest", "jest_nestjs") and os.path.exists("backend-results.json"):
        add(*parse_jest_json("backend-results.json"))
    elif BACKEND_RECIPE == "rspec" and os.path.exists("backend-results.json"):
        add(*parse_rspec_json("backend-results.json"))
    elif BACKEND_RECIPE == "phpunit" and os.path.exists("backend-results.xml"):
        add(*parse_junit_xml(["backend-results.xml"]))
    elif BACKEND_RECIPE == "junit_spring":
        reports = glob.glob("project/backend/target/surefire-reports/TEST-*.xml")
        if reports:
            add(*parse_junit_xml(reports))
    elif BACKEND_RECIPE == "xunit_aspnet" and os.path.exists("backend-results.trx"):
        add(*parse_trx("backend-results.trx"))
    elif BACKEND_RECIPE == "cargo_test" and os.path.exists("backend-cargo-output.txt"):
        add(*parse_cargo_text("backend-cargo-output.txt"))
    elif BACKEND_RECIPE == "go_test" and os.path.exists("backend-results.jsonl"):
        add(*parse_go_jsonl("backend-results.jsonl"))
except (json.JSONDecodeError, KeyError, TypeError, ET.ParseError, OSError) as e:
    print(f"Warning: could not parse backend results ({BACKEND_RECIPE}): {e}")

try:
    if FRONTEND_RECIPE in JEST_RESULT_RECIPES and os.path.exists("frontend-results.json"):
        add(*parse_jest_json("frontend-results.json"))
    elif FRONTEND_RECIPE == "karma_jasmine" and os.path.exists("frontend-results.xml"):
        add(*parse_junit_xml(["frontend-results.xml"]))
    elif FRONTEND_RECIPE == "flutter_test" and os.path.exists("frontend-results.jsonl"):
        add(*parse_flutter_jsonl("frontend-results.jsonl"))
    elif FRONTEND_RECIPE == "gradle_unit_test":
        reports = glob.glob("project/frontend/app/build/test-results/*/TEST-*.xml")
        if reports:
            add(*parse_junit_xml(reports))
except (json.JSONDecodeError, KeyError, TypeError, ET.ParseError, OSError) as e:
    print(f"Warning: could not parse frontend results ({FRONTEND_RECIPE}): {e}")

# Fallback for legacy runs / local testing without BACKEND_RECIPE set —
# preserves the exact behavior this script had before recipes existed.
if not BACKEND_RECIPE and os.path.exists("backend-results.json"):
    add(*parse_pytest_json("backend-results.json"))
if not FRONTEND_RECIPE and os.path.exists("frontend-results.json"):
    add(*parse_jest_json("frontend-results.json"))

result = {"passed": passed, "failed": failed, "total": total, "failures": failures}

with open("test-results.json", "w", encoding="utf-8") as f:
    json.dump(result, f, indent=2)

print(f"Merged results: {passed} passed, {failed} failed, {total} total, {len(failures)} failure(s) recorded")
