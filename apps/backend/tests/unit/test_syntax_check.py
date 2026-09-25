"""
Grammar-based syntax checking (ai/syntax_check.py) and how
validate_generated_content uses it. The broader evidence — 0 false alarms
on ~900 valid files (this repo, both No-AI stacks, every adapter's
templates, real AI output) against 28 for the bracket heuristic — was
measured when this was written; these tests pin the behaviour.
"""

import pytest

from app.ai import syntax_check
from app.ai.codegen_shared import validate_generated_content

GRAMMARS = [
    "python", "javascript", "typescript", "tsx", "java", "kotlin", "csharp", "go", "rust", "php", "ruby",
    "dart", "swift", "gdscript", "lua", "cpp", "html", "css", "json", "yaml", "toml", "xml", "bash",
]  # fmt: skip


@pytest.mark.parametrize("key", GRAMMARS)
def test_every_grammar_is_installed(key):
    assert syntax_check.available(key)


VALID = {
    "backend/main.go": 'package main\n\nimport "fmt"\n\nfunc main() {\n\tfmt.Println("hi")\n}\n',
    "src/main.rs": 'fn main() {\n    let x = 1;\n    println!("{}", x);\n}\n',
    "App.java": "public class App {\n  public static void main(String[] args) {}\n}\n",
    "Program.cs": "public class Program {\n    public static void Main() { }\n}\n",
    "app/models/post.rb": "class Post < ApplicationRecord\n  validates :title, presence: true\nend\n",
    "app/Models/Post.php": "<?php\nnamespace App\\Models;\nclass Post { public $fillable = ['title']; }\n",
    "src/App.tsx": "export const App = () => <button onClick={() => 1}>Approve & Continue</button>;\n",
    "Cargo.toml": '[package]\nname = "demo"\nversion = "0.1.0"\n',
    "config.yml": "on:\n  push:\n    branches: [main]\n",
    "pom.xml": "<project><modelVersion>4.0.0</modelVersion></project>\n",
    "index.html": "<!doctype html><html><body><p>Hi</p></body></html>\n",
}


@pytest.mark.parametrize("path", sorted(VALID))
def test_valid_code_passes(path):
    assert syntax_check.check(VALID[path], path=path) is None


@pytest.mark.parametrize(
    "path,broken,fragment",
    [
        (
            "backend/main.go",
            "package main\nfunc main() {\n\tx := \n}\n",
            "invalid Go syntax",
        ),
        ("src/main.rs", "fn main() {\n    let x = 1;\n", "invalid Rust syntax"),
        ("App.java", "class A {\n  void f( {\n}\n", "invalid Java syntax"),
        (
            "app/models/post.rb",
            "class Post\n  def title\n    1\n",
            "invalid Ruby syntax",
        ),  # a missing `end`
        ("pom.xml", "<project><a></project>", "invalid XML syntax"),
        ("package.json", '{"name": "x",}', "invalid JSON syntax — line 1"),
    ],
)
def test_broken_code_is_caught_with_its_line(path, broken, fragment):
    problem = syntax_check.check(broken, path=path)
    assert problem is not None and fragment in problem, problem


def test_the_path_decides_the_grammar_not_the_label():
    # A Rust adapter's Cargo.toml is labelled "rust" but must parse as TOML.
    assert syntax_check.check(VALID["Cargo.toml"], "rust", "backend/Cargo.toml") is None
    assert (
        syntax_check.check(VALID["Cargo.toml"], "rust") is not None
    )  # label only: parsed as Rust
    assert not syntax_check.checkable("go", "backend/go.mod")  # no grammar for go.mod


def test_vue_components_check_their_script_only():
    good = '<template><p v-if="a && b">{{ x }}</p></template>\n<script setup>\nconst x = 1;\n</script>\n'
    assert syntax_check.check(good, "javascript", "src/screens/A.vue") is None
    bad = "<template><p>x</p></template>\n<script setup>\nconst x = ;\n</script>\n"
    problem = syntax_check.check(bad, "javascript", "src/screens/A.vue")
    assert problem is not None and "line 3" in problem


def test_jsx_ampersand_is_tolerated_but_real_jsx_errors_are_not():
    assert syntax_check.check("const a = <p>Tom & Jerry</p>;\n", path="a.jsx") is None
    # tree-sitter grammars never compare tag names, so <p>…</div> isn't
    # caught (the build would catch it) — an unclosed element is.
    assert syntax_check.check("const a = <p>Tom;\n", path="a.jsx") is not None


def test_validate_generated_content_uses_the_right_checker():
    assert validate_generated_content("python", "def f(:\n", "m.py").startswith(
        "invalid Python syntax"
    )
    assert (
        validate_generated_content("ruby", "class A\n") is not None
    )  # the bracket heuristic couldn't see this
    assert validate_generated_content("javascript", "const x = 1; // TODO later\n") == (
        "contains leftover TODO markers or markdown code fences"
    )
    assert (
        validate_generated_content("yaml", "a: '(unbalanced'\n", "x.yml") is None
    )  # heuristic false alarm, gone
    assert (
        validate_generated_content("markdown", "# Title\n") is None
    )  # no grammar: heuristic, as before
    assert validate_generated_content("javascript", "   ") == "empty response"
