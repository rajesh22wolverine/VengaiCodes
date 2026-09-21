"""Real tests for every parser in merge_test_results.py.

None of these parsers had test coverage before this file — the script
executed its dispatch logic unconditionally at import time, which is
exactly what made it untestable (see merge_test_results.main()'s
docstring note). Every fixture below matches the REAL output format of
the underlying tool, confirmed by fetching each tool's own source/docs
(RSpec's json_formatter.rb, Go's test2json.go, dart-lang/test's
json_reporter.md, a real .trx file with a failing UnitTestResult) rather
than guessed from memory — see this test file's git history for exactly
what was checked.

Uses only the standard library (unittest), matching merge_test_results.py's
own zero-dependency design — this needs to run in the same minimal CI
environment that script's own module docstring describes.

Run: python3 .github/scripts/test_merge_test_results.py
"""
import json
import os
import tempfile
import unittest
from pathlib import Path

import merge_test_results as mtr


class TmpFileMixin:
    def write(self, name: str, content: str) -> str:
        path = os.path.join(self._tmpdir.name, name)
        Path(path).write_text(content, encoding="utf-8")
        return path

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self._tmpdir.cleanup()


class TestPytestJson(TmpFileMixin, unittest.TestCase):
    """Real pytest-json-report shape (the plugin run-tests.yml installs)."""

    def test_mixed_pass_and_fail(self):
        path = self.write("r.json", json.dumps({
            "summary": {"passed": 2, "failed": 1, "total": 3},
            "tests": [
                {"nodeid": "backend/tests/test_x.py::test_ok", "outcome": "passed"},
                {"nodeid": "backend/tests/test_x.py::test_ok2", "outcome": "passed"},
                {
                    "nodeid": "backend/tests/test_x.py::test_bad",
                    "outcome": "failed",
                    "call": {"longrepr": "AssertionError: 1 != 2"},
                },
            ],
        }))
        p, f, t, fails = mtr.parse_pytest_json(path)
        self.assertEqual((p, f, t), (2, 1, 3))
        self.assertEqual(len(fails), 1)
        self.assertEqual(fails[0]["file"], "backend/tests/test_x.py")
        self.assertEqual(fails[0]["test_name"], "test_bad")
        self.assertIn("AssertionError", fails[0]["message"])

    def test_all_passed_has_no_failures(self):
        path = self.write("r.json", json.dumps({
            "summary": {"passed": 1, "failed": 0, "total": 1},
            "tests": [{"nodeid": "t.py::test_ok", "outcome": "passed"}],
        }))
        p, f, t, fails = mtr.parse_pytest_json(path)
        self.assertEqual((p, f, t, fails), (1, 0, 1, []))


class TestJestJson(TmpFileMixin, unittest.TestCase):
    """Real Jest/Vitest --json reporter shape."""

    def test_mixed_pass_and_fail(self):
        path = self.write("r.json", json.dumps({
            "numPassedTests": 1,
            "numFailedTests": 1,
            "numTotalTests": 2,
            "testResults": [{
                "name": "frontend/src/screens/Home.test.jsx",
                "assertionResults": [
                    {"status": "passed", "fullName": "renders ok"},
                    {
                        "status": "failed",
                        "fullName": "Home shows error banner",
                        "failureMessages": ["Expected banner to be visible"],
                    },
                ],
            }],
        }))
        p, f, t, fails = mtr.parse_jest_json(path)
        self.assertEqual((p, f, t), (1, 1, 2))
        self.assertEqual(fails[0]["file"], "frontend/src/screens/Home.test.jsx")
        self.assertEqual(fails[0]["test_name"], "Home shows error banner")
        self.assertIn("Expected banner", fails[0]["message"])


class TestJunitXml(TmpFileMixin, unittest.TestCase):
    """Shared by Spring/Maven surefire, PHPUnit, Gradle, karma-junit-reporter."""

    def test_single_testsuite_root_with_failure(self):
        path = self.write("r.xml", """<?xml version="1.0"?>
<testsuite name="ApiControllerTest" tests="2" failures="1" errors="0">
  <testcase classname="com.vengaicode.ApiControllerTest" name="testCreate" time="0.01"/>
  <testcase classname="com.vengaicode.ApiControllerTest" name="testDelete" time="0.01">
    <failure message="expected 204 but got 500">java.lang.AssertionError at ApiControllerTest.java:42</failure>
  </testcase>
</testsuite>
""")
        p, f, t, fails = mtr.parse_junit_xml([path])
        self.assertEqual((p, f, t), (1, 1, 2))
        self.assertEqual(fails[0]["test_name"], "testDelete")
        self.assertIn("expected 204", fails[0]["message"])

    def test_testsuites_wrapper_root_with_error(self):
        # PHPUnit and some other tools wrap multiple <testsuite> under a
        # <testsuites> root instead of emitting one bare <testsuite>.
        path = self.write("r.xml", """<?xml version="1.0"?>
<testsuites>
  <testsuite name="Feature\\TaskTest" tests="1" failures="0" errors="1">
    <testcase classname="Feature\\TaskTest" name="test_it_errors">
      <error message="Undefined array key">RuntimeException</error>
    </testcase>
  </testsuite>
</testsuites>
""")
        p, f, t, fails = mtr.parse_junit_xml([path])
        self.assertEqual((p, f, t), (0, 1, 1))
        self.assertEqual(fails[0]["test_name"], "test_it_errors")

    def test_multiple_report_files_are_summed(self):
        p1 = self.write("r1.xml", '<testsuite tests="1" failures="0" errors="0"><testcase classname="A" name="a"/></testsuite>')
        p2 = self.write("r2.xml", '<testsuite tests="1" failures="1" errors="0"><testcase classname="B" name="b"><failure message="x">x</failure></testcase></testsuite>')
        p, f, t, fails = mtr.parse_junit_xml([p1, p2])
        self.assertEqual((p, f, t), (1, 1, 2))
        self.assertEqual(len(fails), 1)

    def test_malformed_xml_is_skipped_not_fatal(self):
        bad = self.write("bad.xml", "<not><valid xml")
        p, f, t, fails = mtr.parse_junit_xml([bad])
        self.assertEqual((p, f, t, fails), (0, 0, 0, []))


class TestRspecJson(TmpFileMixin, unittest.TestCase):
    """Real RSpec --format json shape, confirmed against rspec-core's
    own json_formatter.rb source (summary.example_count/failure_count,
    examples[].status/file_path/full_description, exception.message)."""

    def test_mixed_pass_and_fail(self):
        path = self.write("r.json", json.dumps({
            "summary": {"example_count": 2, "failure_count": 1},
            "examples": [
                {"status": "passed", "file_path": "./spec/tasks_spec.rb", "full_description": "lists tasks"},
                {
                    "status": "failed",
                    "file_path": "./spec/tasks_spec.rb",
                    "full_description": "TasksController deletes a task",
                    "exception": {"message": "expected: 204\n     got: 500"},
                },
            ],
        }))
        p, f, t, fails = mtr.parse_rspec_json(path)
        self.assertEqual((p, f, t), (1, 1, 2))
        self.assertEqual(fails[0]["file"], "./spec/tasks_spec.rb")
        self.assertEqual(fails[0]["test_name"], "TasksController deletes a task")
        self.assertIn("expected: 204", fails[0]["message"])


class TestGoJsonl(TmpFileMixin, unittest.TestCase):
    """Real `go test -json` shape, confirmed against Go's own
    src/cmd/internal/test2json/test2json.go event struct (Action, Test,
    Output fields; actions run/pass/fail/skip/output)."""

    def test_mixed_pass_and_fail(self):
        lines = [
            {"Action": "run", "Test": "TestGetTasks"},
            {"Action": "pass", "Test": "TestGetTasks"},
            {"Action": "run", "Test": "TestCreateTask"},
            {"Action": "output", "Test": "TestCreateTask", "Output": "    handlers_test.go:10: expected 201, got 500\n"},
            {"Action": "fail", "Test": "TestCreateTask"},
            {"Action": "output", "Package": "tigerapp/handlers", "Output": "FAIL\n"},  # package-level, no Test key
        ]
        path = self.write("r.jsonl", "\n".join(json.dumps(x) for x in lines))
        p, f, t, fails = mtr.parse_go_jsonl(path)
        self.assertEqual((p, f, t), (1, 1, 2))
        self.assertEqual(fails[0]["test_name"], "TestCreateTask")
        self.assertIn("expected 201, got 500", fails[0]["message"])

    def test_skip_is_not_counted_as_pass_or_fail(self):
        lines = [
            {"Action": "run", "Test": "TestSkipped"},
            {"Action": "skip", "Test": "TestSkipped"},
        ]
        path = self.write("r.jsonl", "\n".join(json.dumps(x) for x in lines))
        p, f, t, fails = mtr.parse_go_jsonl(path)
        self.assertEqual((p, f, t, fails), (0, 0, 0, []))

    def test_blank_and_malformed_lines_are_ignored(self):
        path = self.write("r.jsonl", '\n{"Action": "pass", "Test": "TestX"}\nnot json\n\n')
        p, f, t, fails = mtr.parse_go_jsonl(path)
        self.assertEqual((p, f, t), (1, 0, 1))


class TestFlutterJsonl(TmpFileMixin, unittest.TestCase):
    """Real `flutter test --machine` shape (dart-lang/test's JSON
    reporter protocol under the hood) — confirmed against
    pkgs/test/doc/json_reporter.md's TestStartEvent/ErrorEvent/
    TestDoneEvent/Test schemas."""

    def test_mixed_pass_and_fail(self):
        lines = [
            {"type": "testStart", "test": {"id": 1, "name": "renders the home screen"}},
            {"type": "testDone", "testID": 1, "result": "success", "hidden": False, "skipped": False},
            {"type": "testStart", "test": {"id": 2, "name": "shows an error banner"}},
            {"type": "error", "testID": 2, "error": "Expected: exactly one matching node\n  Actual: _TextFinder:<zero widgets>", "stackTrace": "#0 ...", "isFailure": True},
            {"type": "testDone", "testID": 2, "result": "failure", "hidden": False, "skipped": False},
        ]
        path = self.write("r.jsonl", "\n".join(json.dumps(x) for x in lines))
        p, f, t, fails = mtr.parse_flutter_jsonl(path)
        self.assertEqual((p, f, t), (1, 1, 2))
        self.assertEqual(fails[0]["test_name"], "shows an error banner")
        self.assertIn("exactly one matching node", fails[0]["message"])

    def test_hidden_setup_all_is_not_counted_as_a_failure(self):
        """Regression test: hidden testDone events used to be
        unconditionally marked "failure" and counted, even though the
        real protocol (json_reporter.md) states hidden tests -- virtual
        setUpAll()/tearDownAll() -- are "not counted towards the total
        number of tests run" and "only successful tests will be hidden".
        """
        lines = [
            {"type": "testStart", "test": {"id": 1, "name": "(setUpAll)"}},
            {"type": "testDone", "testID": 1, "result": "success", "hidden": True, "skipped": False},
            {"type": "testStart", "test": {"id": 2, "name": "the real test"}},
            {"type": "testDone", "testID": 2, "result": "success", "hidden": False, "skipped": False},
        ]
        path = self.write("r.jsonl", "\n".join(json.dumps(x) for x in lines))
        p, f, t, fails = mtr.parse_flutter_jsonl(path)
        self.assertEqual((p, f, t, fails), (1, 0, 1, []))


class TestTrx(TmpFileMixin, unittest.TestCase):
    """Real .trx (dotnet test's Visual Studio Test Results XML) shape,
    confirmed against a real .trx file with a failing UnitTestResult
    (espertechinc/nesper's TestResults + AutomateThePlanet's
    Exceptions.trx) rather than guessed."""

    def test_mixed_pass_and_fail(self):
        path = self.write("r.trx", """<?xml version="1.0" encoding="utf-8"?>
<TestRun id="abc" xmlns="http://microsoft.com/schemas/VisualStudio/TeamTest/2010">
  <Results>
    <UnitTestResult testName="GetTasks_ReturnsOk" outcome="Passed" />
    <UnitTestResult testName="CreateTask_MissingTitle_Returns400" outcome="Failed">
      <Output>
        <ErrorInfo>
          <Message>Assert.Equal() Failure
Expected: 400
Actual:   500</Message>
        </ErrorInfo>
      </Output>
    </UnitTestResult>
  </Results>
  <ResultSummary outcome="Failed">
    <Counters total="2" passed="1" failed="1" />
  </ResultSummary>
</TestRun>
""")
        p, f, t, fails = mtr.parse_trx(path)
        self.assertEqual((p, f, t), (1, 1, 2))
        self.assertEqual(fails[0]["test_name"], "CreateTask_MissingTitle_Returns400")
        self.assertIn("Expected: 400", fails[0]["message"])

    def test_trx_without_default_namespace_still_parses(self):
        # The parser's own comment notes some real .trx files omit the
        # default xmlns — confirm the non-namespaced fallback path works.
        path = self.write("r.trx", """<?xml version="1.0"?>
<TestRun>
  <Results>
    <UnitTestResult testName="Foo" outcome="Passed" />
  </Results>
  <ResultSummary>
    <Counters total="1" passed="1" failed="0" />
  </ResultSummary>
</TestRun>
""")
        p, f, t, fails = mtr.parse_trx(path)
        self.assertEqual((p, f, t, fails), (1, 0, 1, []))


class TestCargoText(TmpFileMixin, unittest.TestCase):
    """Real `cargo test` human-readable summary shape (stable Rust has
    no built-in JSON test output)."""

    def test_mixed_pass_and_fail(self):
        path = self.write("r.txt", """running 2 tests
test tests::test_get_tasks ... ok
test tests::test_create_task_missing_title ... FAILED

failures:

---- tests::test_create_task_missing_title stdout ----
thread 'tests::test_create_task_missing_title' panicked at src/main.rs:42:5:
assertion `left == right` failed
  left: 500
 right: 400

failures:
    tests::test_create_task_missing_title

test result: FAILED. 1 passed; 1 failed; 0 ignored; 0 measured; 0 filtered out
""")
        p, f, t, fails = mtr.parse_cargo_text(path)
        self.assertEqual((p, f, t), (1, 1, 2))
        self.assertEqual(fails[0]["test_name"], "tests::test_create_task_missing_title")
        self.assertIn("assertion `left == right` failed", fails[0]["message"])

    def test_all_passed_has_no_failures(self):
        path = self.write("r.txt", """running 1 test
test tests::test_ok ... ok

test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out
""")
        p, f, t, fails = mtr.parse_cargo_text(path)
        self.assertEqual((p, f, t, fails), (1, 0, 1, []))


if __name__ == "__main__":
    unittest.main()
