# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Testing Recipes
#  ai/testing_recipes.py — One real, CI-runnable test toolchain per
#  codegen framework (see app.ai.codegen.frontend/backend), replacing
#  testing.py's old hardcoded assumption that every backend is
#  Python/pytest and every frontend is Jest/Vitest.
#
#  HONEST SCOPE: SwiftUI gets a recipe for generation purposes (so the
#  Testing screen can still show something and the file lands with the
#  right name/style) but `ci_runnable=False` — it is NEVER dispatched to
#  run-tests.yml. Same reasoning as the E2E (Playwright/Cypress)
#  exclusion this file's docstring in testing.py already documented:
#  `xcodebuild test` needs a real .xcodeproj (which SwiftUI's own
#  codegen adapter deliberately never produces — see
#  app/ai/codegen/frontend/swiftui.py) and a macOS runner, neither of
#  which fits this pipeline.
# ═══════════════════════════════════════════════════════════════

from dataclasses import dataclass


@dataclass(frozen=True)
class TestRecipe:
    key: str  # matches run-tests.yml's step `if:` conditions and merge_test_results.py's dispatch
    label: str  # shown in the picker UI, round-trips through GenerateTestsRequest as a plain string
    language: str
    test_path_template: str  # "{name}" is replaced with a slug derived from what's being tested
    style_notes: str  # syntax guidance folded into the AI prompt
    result_format: str  # which merge_test_results.py parser reads this recipe's raw output
    ci_runnable: bool = True


# ─── Backend recipes, keyed by app.ai.codegen.backend's adapter keys ───
BACKEND_TEST_RECIPES: dict[str, list[TestRecipe]] = {
    "fastapi": [
        TestRecipe("pytest", "pytest", "python", "backend/tests/test_{name}.py",
                   "bare `assert` statements and pytest fixtures, no test classes", "pytest-json"),
        TestRecipe("unittest", "unittest", "python", "backend/tests/test_{name}.py",
                   "a `unittest.TestCase` subclass using `self.assertEqual`/`self.assertTrue` (pytest's runner discovers and executes these natively)", "pytest-json"),
    ],
    "flask": [
        TestRecipe("pytest", "pytest", "python", "backend/tests/test_{name}.py",
                   "bare `assert` statements and pytest fixtures (use Flask's test client via `app.test_client()`)", "pytest-json"),
    ],
    "django": [
        TestRecipe("pytest_django", "pytest (pytest-django)", "python", "backend/tests/test_{name}.py",
                   "bare `assert` statements using pytest-django's `client` fixture for request tests and `@pytest.mark.django_db` on any test touching the database", "pytest-json"),
    ],
    "express": [
        TestRecipe("jest_supertest", "Jest + Supertest", "javascript", "backend/tests/{name}.test.js",
                   "Jest's `describe`/`it`/`expect`, using `supertest` against the exported Express app/router to make real HTTP requests", "jest-json"),
    ],
    "nestjs": [
        TestRecipe("jest_nestjs", "Jest (ts-jest)", "typescript", "backend/test/{name}.spec.ts",
                   "Jest's `describe`/`it`/`expect` in TypeScript, using `@nestjs/testing`'s `Test.createTestingModule(...)` to build a testable module", "jest-json"),
    ],
    "spring_boot": [
        TestRecipe("junit_spring", "JUnit 5 (Spring Boot Test)", "java", "backend/src/test/java/{package_path}/{Name}Test.java",
                   "JUnit 5 (`@Test`, `org.junit.jupiter.api.Assertions`), annotate the class `@SpringBootTest` and autowire real repositories/MockMvc as needed", "junit-xml"),
    ],
    "aspnet_core": [
        TestRecipe("xunit_aspnet", "xUnit", "csharp", "backend/Tests/{Name}Tests.cs",
                   "xUnit (`[Fact]`/`[Theory]`, `Assert.Equal`/`Assert.True`), using `Microsoft.AspNetCore.Mvc.Testing`'s `WebApplicationFactory<Program>` for real HTTP request tests", "trx"),
    ],
    "rails": [
        TestRecipe("rspec", "RSpec", "ruby", "backend/spec/{name}_spec.rb",
                   "RSpec's `describe`/`it`/`expect(...).to eq(...)` blocks, using Rails' request-spec style (`get '/tasks'`, `expect(response).to have_http_status(200)`)", "rspec-json"),
    ],
    "laravel": [
        TestRecipe("phpunit", "PHPUnit", "php", "backend/tests/Feature/{Name}Test.php",
                   "PHPUnit (`extends TestCase`, `public function test_...()`, `$this->assertEquals(...)`), using Laravel's `$this->get(...)`/`$this->postJson(...)` HTTP test helpers", "junit-xml"),
    ],
    "actix": [
        TestRecipe("cargo_test", "cargo test", "rust", "backend/tests/{name}.rs",
                   "a `#[actix_web::test]` async test function using `actix_web::test::TestRequest`/`call_service` against the real service, with plain `assert_eq!`/`assert!` — no external test framework needed", "cargo-text"),
    ],
    "axum": [
        TestRecipe("cargo_test", "cargo test", "rust", "backend/tests/{name}.rs",
                   "a `#[tokio::test]` async test function using `tower::ServiceExt::oneshot` against the real router, with plain `assert_eq!`/`assert!` — no external test framework needed", "cargo-text"),
    ],
    "gin": [
        TestRecipe("go_test", "go test", "go", "backend/handlers/{name}_test.go",
                   "Go's built-in `testing` package (`func Test{Name}(t *testing.T)`, `t.Errorf(...)`), using `net/http/httptest` (`httptest.NewRecorder()`/`httptest.NewRequest()`) against the real Gin router", "go-jsonl"),
    ],
}

# ─── Frontend recipes, keyed by app.ai.codegen.frontend's adapter keys ───
FRONTEND_TEST_RECIPES: dict[str, list[TestRecipe]] = {
    "react": [
        TestRecipe("jest_rtl", "Jest + React Testing Library", "javascript", "frontend/src/screens/{Name}.test.jsx",
                   "Jest's `describe`/`it`/`expect`, `@testing-library/react`'s `render`/`screen`/`fireEvent`, `jest.mock` for mocking `fetch`", "jest-json"),
        TestRecipe("vitest_rtl", "Vitest + React Testing Library", "javascript", "frontend/src/screens/{Name}.test.jsx",
                   "Vitest's `describe`/`it`/`expect` (`import { describe, it, expect, vi } from 'vitest'`), `@testing-library/react`'s `render`/`screen`, `vi.mock` for mocking `fetch`", "jest-json"),
    ],
    "vue": [
        TestRecipe("vitest_vtu", "Vitest + Vue Test Utils", "javascript", "frontend/src/screens/{Name}.test.js",
                   "Vitest's `describe`/`it`/`expect`, `@vue/test-utils`'s `mount`, `vi.mock` for mocking `fetch`", "jest-json"),
    ],
    "svelte": [
        TestRecipe("vitest_svelte", "Vitest + Testing Library Svelte", "javascript", "frontend/src/screens/{Name}.test.js",
                   "Vitest's `describe`/`it`/`expect`, `@testing-library/svelte`'s `render`/`screen`, `vi.mock` for mocking `fetch`", "jest-json"),
    ],
    "html_css_js": [
        TestRecipe("vitest_jsdom", "Vitest", "javascript", "frontend/src/screens/{name}.test.js",
                   "Vitest's `describe`/`it`/`expect` calling the screen module's exported `render(container)` directly against a real `document.createElement('div')`, asserting on `container.innerHTML`/`container.querySelector(...)`", "jest-json"),
    ],
    "angular": [
        TestRecipe("karma_jasmine", "Karma + Jasmine", "typescript", "frontend/src/app/screens/{name}.component.spec.ts",
                   "Angular's standard `TestBed.configureTestingModule({{ imports: [{Name}Component] }})` + Jasmine's `describe`/`it`/`expect`, since the component is standalone", "junit-xml"),
    ],
    "flutter": [
        TestRecipe("flutter_test", "flutter_test", "dart", "frontend/test/{name}_test.dart",
                   "Flutter's `flutter_test` package (`testWidgets('...', (tester) async {{ ... }})`, `find.text(...)`, `tester.pumpWidget(...)`, `expect(find..., findsOneWidget)`)", "flutter-jsonl"),
    ],
    "jetpack_compose": [
        TestRecipe("gradle_unit_test", "Gradle unit test (JUnit, JVM-only)", "kotlin", "frontend/app/src/test/java/{package_path}/{Name}Test.kt",
                   "plain JUnit 4 (`@Test`, `org.junit.Assert.assertEquals`) testing any non-Compose helper/parsing function only — this is a headless JVM unit test, NOT a Compose UI test (no ComposeTestRule, no emulator available in CI)", "junit-xml"),
    ],
    "swiftui": [
        TestRecipe("xctest_stub", "XCTest (generated only, not run in CI)", "swift", "frontend/{Name}Tests.swift",
                   "XCTest (`import XCTest`, `class {Name}Tests: XCTestCase`, `func test...()`, `XCTAssertEqual`)", "none", ci_runnable=False),
    ],
}


# ─── Label-based lookup, scoped to a specific framework ───
#
# A recipe label (e.g. "pytest", "cargo test") is only guaranteed unique
# WITHIN one framework's own recipe list — fastapi and flask both have a
# "pytest" entry, actix and axum both have a "cargo test" entry (same
# label, genuinely different style_notes underneath). A single flat
# {label: recipe} dict across every framework would let one silently
# shadow the other, so lookups always take the framework key too, exactly
# like BACKEND_TEST_RECIPES/FRONTEND_TEST_RECIPES themselves are already
# scoped — there is no global, framework-less label lookup.
def find_backend_recipe(backend_framework: str | None, label: str | None) -> TestRecipe:
    recipes = BACKEND_TEST_RECIPES.get(backend_framework or "", BACKEND_TEST_RECIPES["fastapi"])
    if label:
        match = next((r for r in recipes if r.label == label), None)
        if match:
            return match
    return recipes[0]


def find_frontend_recipe(frontend_framework: str | None, label: str | None) -> TestRecipe:
    recipes = FRONTEND_TEST_RECIPES.get(frontend_framework or "", FRONTEND_TEST_RECIPES["react"])
    if label:
        match = next((r for r in recipes if r.label == label), None)
        if match:
            return match
    return recipes[0]
