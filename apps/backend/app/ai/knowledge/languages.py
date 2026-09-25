# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Programming language knowledge
#  ai/knowledge/languages.py — The rules of every language VengaiCode
#  generates or reads, as data: reserved words (from each language's own
#  specification), identifier syntax, naming conventions, comment syntax,
#  toolchain (package manager, formatter, linter, test runners) and the
#  tree-sitter grammar that parses it.
#
#  Three consumers, so the rules live in ONE place:
#    - db_schema / knowledge.identifier_problem — a table or field name
#      that would become a keyword in the generated code is refused
#      while the user is still in the Architecture editor
#    - codegen_shared.generate_text_validated — every AI code prompt
#      gets the language's rules (language_rules_for_prompt)
#    - the syntax checker (tree-sitter grammar per language)
#  `keywords` are words that can NEVER be an identifier in that
#  language; `avoid` are legal but harmful to shadow (builtins, standard
#  types) — generators refuse the first and prompts warn about the second.
# ═══════════════════════════════════════════════════════════════

from dataclasses import dataclass, field


@dataclass(frozen=True)
class LanguageSpec:
    key: str
    label: str
    extensions: tuple[str, ...]
    typing: str  # "static" | "dynamic" | "gradual"
    keywords: frozenset[str]
    identifier_pattern: str  # regex for a valid identifier
    naming: dict[str, str]  # element -> convention, e.g. {"type": "PascalCase"}
    line_comment: str | None
    block_comment: tuple[str, str] | None
    package_manager: str
    manifest: str
    formatter: str
    linter: str
    test_frameworks: tuple[str, ...]
    grammar: str | None  # tree-sitter grammar package module (tree_sitter_<x>)
    rules: tuple[str, ...]  # short, prompt-ready rules
    avoid: frozenset[str] = field(default_factory=frozenset)
    keywords_case_insensitive: bool = False


def _words(text: str) -> frozenset[str]:
    return frozenset(text.split())


_IDENT = r"^[A-Za-z_][A-Za-z0-9_]*$"

LANGUAGES: dict[str, LanguageSpec] = {}


def _add(spec: LanguageSpec) -> None:
    LANGUAGES[spec.key] = spec


# ── Python (3.11 — keyword.kwlist; soft keywords match/case/type/_ are legal names) ──
_add(
    LanguageSpec(
        key="python",
        label="Python",
        extensions=(".py",),
        typing="gradual",
        keywords=_words(
            "False None True and as assert async await break class continue def del elif else except "
            "finally for from global if import in is lambda nonlocal not or pass raise return try while with yield"
        ),
        identifier_pattern=_IDENT,
        naming={
            "type": "PascalCase",
            "function": "snake_case",
            "variable": "snake_case",
            "constant": "UPPER_SNAKE_CASE",
            "module": "snake_case",
            "file": "snake_case.py",
        },
        line_comment="#",
        block_comment=None,
        package_manager="pip",
        manifest="requirements.txt / pyproject.toml",
        formatter="ruff format / black",
        linter="ruff",
        test_frameworks=("pytest", "unittest"),
        grammar="tree_sitter_python",
        rules=(
            "Indent with 4 spaces; never mix tabs and spaces.",
            "Follow PEP 8 naming: PascalCase classes, snake_case functions/variables, UPPER_SNAKE_CASE constants.",
            "Import only what the file uses; no wildcard imports.",
            "Type-annotate public functions (PEP 484); use `X | None` rather than a bare None default for typed values.",
            "Never use a mutable default argument (list/dict/set); default to None and create inside.",
            "Raise specific exceptions; never a bare `except:`.",
            "Use f-strings for formatting and pathlib/os.path for paths.",
        ),
        avoid=_words(
            "list dict str int float bool set tuple type id object len range input print open format hash "
            "filter map min max sum any all next iter sorted reversed zip vars dir help bytes super property"
        ),
    )
)

# ── JavaScript (ECMAScript 2023 reserved words, strict mode) ──
_JS_RESERVED = _words(
    "break case catch class const continue debugger default delete do else enum export extends false finally for "
    "function if import in instanceof new null return super switch this throw true try typeof var void while with "
    "yield let static implements interface package private protected public await"
)
_add(
    LanguageSpec(
        key="javascript",
        label="JavaScript",
        extensions=(".js", ".mjs", ".cjs", ".jsx"),
        typing="dynamic",
        keywords=_JS_RESERVED,
        identifier_pattern=r"^[A-Za-z_$][A-Za-z0-9_$]*$",
        naming={
            "type": "PascalCase",
            "function": "camelCase",
            "variable": "camelCase",
            "constant": "UPPER_SNAKE_CASE",
            "component": "PascalCase",
            "file": "camelCase.js / PascalCase.jsx for components",
        },
        line_comment="//",
        block_comment=("/*", "*/"),
        package_manager="npm / pnpm / yarn",
        manifest="package.json",
        formatter="prettier",
        linter="eslint",
        test_frameworks=("vitest", "jest", "mocha"),
        grammar="tree_sitter_javascript",
        rules=(
            "Use const by default, let when reassigned; never var.",
            "Use === and !== (strict equality).",
            "Always handle rejected promises: await inside try/catch, or .catch().",
            "Use ES modules (import/export) in browser/Vite code; CommonJS (require) only where the project already does.",
            "Semicolons and 2-space indentation, consistently.",
            "Don't shadow globals such as Date, Map, Set, Error, Number, String or JSON.",
        ),
        avoid=_words(
            "Object Array Date Map Set WeakMap Promise Error Number String Boolean Symbol JSON Math Function RegExp "
            "undefined NaN Infinity arguments eval globalThis window document"
        ),
    )
)

# ── TypeScript (JS reserved words plus TS-only reserved names) ──
_add(
    LanguageSpec(
        key="typescript",
        label="TypeScript",
        extensions=(".ts", ".tsx", ".mts", ".cts"),
        typing="static",
        keywords=_JS_RESERVED
        | _words("any boolean never number string symbol unknown void object bigint"),
        identifier_pattern=r"^[A-Za-z_$][A-Za-z0-9_$]*$",
        naming={
            "type": "PascalCase",
            "interface": "PascalCase (no I- prefix)",
            "function": "camelCase",
            "variable": "camelCase",
            "constant": "UPPER_SNAKE_CASE",
            "file": "camelCase.ts / PascalCase.tsx for components",
        },
        line_comment="//",
        block_comment=("/*", "*/"),
        package_manager="npm / pnpm / yarn",
        manifest="package.json + tsconfig.json",
        formatter="prettier",
        linter="eslint (typescript-eslint)",
        test_frameworks=("vitest", "jest"),
        grammar="tree_sitter_typescript",
        rules=(
            "Code must compile under `strict: true`: no implicit any, handle null/undefined explicitly.",
            "Prefer `unknown` over `any`; narrow with type guards.",
            "Use `interface` for object shapes and `type` for unions/intersections.",
            "Mark fields readonly when they never change; prefer `as const` for literal tables.",
            "Import types with `import type` when only types are used.",
            "All JavaScript rules apply (const/let, ===, handled promises).",
        ),
        avoid=_words(
            "Object Array Date Map Set Promise Error Number String Boolean Symbol JSON Math Function RegExp Record Partial"
        ),
    )
)

# ── Java (JLS 21 keywords + literals; contextual words noted in rules) ──
_add(
    LanguageSpec(
        key="java",
        label="Java",
        extensions=(".java",),
        typing="static",
        keywords=_words(
            "abstract assert boolean break byte case catch char class const continue default do double else enum "
            "extends final finally float for goto if implements import instanceof int interface long native new "
            "package private protected public return short static strictfp super switch synchronized this throw "
            "throws transient try void volatile while true false null _"
        ),
        identifier_pattern=r"^[A-Za-z_$][A-Za-z0-9_$]*$",
        naming={
            "type": "PascalCase",
            "method": "camelCase",
            "field": "camelCase",
            "constant": "UPPER_SNAKE_CASE",
            "package": "lowercase.dotted",
            "file": "PascalCase.java (must match the public class)",
        },
        line_comment="//",
        block_comment=("/*", "*/"),
        package_manager="Maven / Gradle",
        manifest="pom.xml / build.gradle(.kts)",
        formatter="google-java-format / spotless",
        linter="checkstyle / SpotBugs",
        test_frameworks=("JUnit 5", "Mockito", "AssertJ"),
        grammar="tree_sitter_java",
        rules=(
            "One public top-level type per file, and the file name must equal it.",
            "Package names are lowercase; every file starts with its package declaration.",
            "Don't name your own classes after java.lang types (String, Object, Integer, Record, …).",
            "Use Optional for maybe-absent return values, never return null collections.",
            "Close resources with try-with-resources.",
            "`var`, `record`, `yield`, `sealed` and `permits` are contextual — avoid them as names.",
        ),
        avoid=_words(
            "String Object Integer Long Short Byte Double Float Boolean Character Number Class System Thread Exception "
            "RuntimeException Error Record Override Deprecated List Map Set Optional var record yield sealed permits"
        ),
    )
)

# ── Kotlin (hard keywords) ──
_add(
    LanguageSpec(
        key="kotlin",
        label="Kotlin",
        extensions=(".kt", ".kts"),
        typing="static",
        keywords=_words(
            "as break class continue do else false for fun if in interface is null object package return super "
            "this throw true try typealias typeof val var when while"
        ),
        identifier_pattern=_IDENT,
        naming={
            "type": "PascalCase",
            "function": "camelCase",
            "property": "camelCase",
            "constant": "UPPER_SNAKE_CASE",
            "package": "lowercase.dotted",
            "file": "PascalCase.kt",
        },
        line_comment="//",
        block_comment=("/*", "*/"),
        package_manager="Gradle",
        manifest="build.gradle.kts",
        formatter="ktlint / ktfmt",
        linter="ktlint / detekt",
        test_frameworks=("JUnit 5", "kotlin.test", "MockK"),
        grammar="tree_sitter_kotlin",
        rules=(
            "Prefer val over var; make classes immutable where possible (data classes for records).",
            "Use nullable types (T?) with ?. and ?: instead of !!.",
            "Use trailing lambdas and named arguments for readability.",
            "Soft keywords (by, get, set, field, value, init, constructor) are legal names but confusing — avoid them.",
        ),
        avoid=_words(
            "Any Unit Nothing String Int Long Double Float Boolean List Map Set Result by get set field value init constructor"
        ),
    )
)

# ── C# (the 77 reserved keywords) ──
_add(
    LanguageSpec(
        key="csharp",
        label="C#",
        extensions=(".cs",),
        typing="static",
        keywords=_words(
            "abstract as base bool break byte case catch char checked class const continue decimal default delegate "
            "do double else enum event explicit extern false finally fixed float for foreach goto if implicit in int "
            "interface internal is lock long namespace new null object operator out override params private "
            "protected public readonly ref return sbyte sealed short sizeof stackalloc static string struct switch "
            "this throw true try typeof uint ulong unchecked unsafe ushort using virtual void volatile while"
        ),
        identifier_pattern=_IDENT,
        naming={
            "type": "PascalCase",
            "method": "PascalCase",
            "property": "PascalCase",
            "field": "_camelCase (private)",
            "local": "camelCase",
            "interface": "IPascalCase",
            "file": "PascalCase.cs",
        },
        line_comment="//",
        block_comment=("/*", "*/"),
        package_manager="NuGet (dotnet add package)",
        manifest="<Project>.csproj",
        formatter="dotnet format",
        linter="Roslyn analyzers",
        test_frameworks=("xUnit", "NUnit", "MSTest"),
        grammar="tree_sitter_c_sharp",
        rules=(
            "Enable nullable reference types; mark maybe-null references with `?`.",
            "Public members are PascalCase; interfaces start with I.",
            "Use async/await end to end with Task-returning methods; never .Result or .Wait().",
            "Dispose IDisposable resources with `using`.",
            "One type per file, file named after the type; file-scoped namespaces.",
        ),
        avoid=_words(
            "String Object Task Action Func Exception Console Math DateTime Guid List Dictionary var dynamic async await"
        ),
    )
)

# ── Go (the 25 keywords; predeclared identifiers in `avoid`) ──
_add(
    LanguageSpec(
        key="go",
        label="Go",
        extensions=(".go",),
        typing="static",
        keywords=_words(
            "break case chan const continue default defer else fallthrough for func go goto if import interface map "
            "package range return select struct switch type var"
        ),
        identifier_pattern=_IDENT,
        naming={
            "exported": "PascalCase (capitalized = exported)",
            "unexported": "camelCase",
            "package": "short lowercase, no underscores",
            "acronyms": "all caps (ID, URL, HTTP)",
            "file": "snake_case.go",
        },
        line_comment="//",
        block_comment=("/*", "*/"),
        package_manager="go modules",
        manifest="go.mod",
        formatter="gofmt",
        linter="go vet / staticcheck",
        test_frameworks=("testing", "testify"),
        grammar="tree_sitter_go",
        rules=(
            "Code must be gofmt-formatted (tabs for indentation).",
            "Every error is checked: `if err != nil { return … }`; never discard with _ silently.",
            "Unused imports and unused local variables are compile errors.",
            'Capitalized names are exported; JSON field names go in struct tags (`json:"name"`).',
            "Pass context.Context as the first parameter of request-scoped functions.",
        ),
        avoid=_words(
            "bool byte complex64 complex128 error float32 float64 int int8 int16 int32 int64 rune string uint uint8 "
            "uint16 uint32 uint64 uintptr true false iota nil append cap clear close complex copy delete imag len "
            "make max min new panic print println real recover any comparable"
        ),
    )
)

# ── Rust (strict + reserved keywords, 2021 edition) ──
_add(
    LanguageSpec(
        key="rust",
        label="Rust",
        extensions=(".rs",),
        typing="static",
        keywords=_words(
            "as break const continue crate else enum extern false fn for if impl in let loop match mod move mut pub "
            "ref return self Self static struct super trait true type unsafe use where while async await dyn "
            "abstract become box do final macro override priv typeof unsized virtual yield try"
        ),
        identifier_pattern=_IDENT,
        naming={
            "type": "PascalCase",
            "function": "snake_case",
            "variable": "snake_case",
            "constant": "UPPER_SNAKE_CASE",
            "module": "snake_case",
            "file": "snake_case.rs",
        },
        line_comment="//",
        block_comment=("/*", "*/"),
        package_manager="cargo",
        manifest="Cargo.toml",
        formatter="rustfmt",
        linter="clippy",
        test_frameworks=("cargo test",),
        grammar="tree_sitter_rust",
        rules=(
            "Code must pass the borrow checker: no use after move, one mutable borrow at a time.",
            "Handle Result/Option with ? or match; never .unwrap() in request handlers.",
            "Derive Serialize/Deserialize (serde) for JSON types; #[serde(rename)] for non-snake names.",
            "Keywords can only be used as names with the r# prefix (r#type) — prefer another name.",
            "Unused imports warn and `#![deny(warnings)]` projects fail — import only what's used.",
        ),
        avoid=_words(
            "String Vec Option Result Box Some None Ok Err str i32 i64 u32 u64 f64 bool union"
        ),
    )
)

# ── PHP (reserved keywords + reserved class names) ──
_add(
    LanguageSpec(
        key="php",
        label="PHP",
        extensions=(".php",),
        typing="gradual",
        keywords=_words(
            "__halt_compiler abstract and array as break callable case catch class clone const continue declare "
            "default die do echo else elseif empty enddeclare endfor endforeach endif endswitch endwhile eval exit "
            "extends final finally fn for foreach function global goto if implements include include_once instanceof "
            "insteadof interface isset list match namespace new or print private protected public readonly require "
            "require_once return static switch throw trait try unset use var while xor yield",
        ),
        identifier_pattern=r"^[A-Za-z_\x80-\xff][A-Za-z0-9_\x80-\xff]*$",
        naming={
            "class": "PascalCase (PSR-1)",
            "method": "camelCase",
            "property": "camelCase (Eloquent attributes: snake_case)",
            "constant": "UPPER_SNAKE_CASE",
            "namespace": "PascalCase\\Segments (PSR-4)",
            "file": "PascalCase.php matching the class",
        },
        line_comment="//",
        block_comment=("/*", "*/"),
        package_manager="composer",
        manifest="composer.json",
        formatter="php-cs-fixer / Laravel Pint",
        linter="PHPStan / Psalm",
        test_frameworks=("PHPUnit", "Pest"),
        grammar="tree_sitter_php",
        rules=(
            "Start every file with <?php and declare(strict_types=1) where the project does.",
            "Follow PSR-12 formatting and PSR-4 autoloading (namespace matches folder).",
            "Type-declare parameters, return values and properties.",
            "Keywords are case-insensitive — `Class` is as reserved as `class`.",
            "Never interpolate request input into SQL; use the query builder or bound parameters.",
        ),
        avoid=_words(
            "int float bool string true false null void iterable object mixed never enum resource numeric self parent"
        ),
        keywords_case_insensitive=True,
    )
)

# ── Ruby (the language's keywords) ──
_add(
    LanguageSpec(
        key="ruby",
        label="Ruby",
        extensions=(".rb", ".rake", ".erb"),
        typing="dynamic",
        keywords=_words(
            "__ENCODING__ __LINE__ __FILE__ BEGIN END alias and begin break case class def defined? do else elsif end "
            "ensure false for if in module next nil not or redo rescue retry return self super then true undef "
            "unless until when while yield"
        ),
        identifier_pattern=r"^[A-Za-z_][A-Za-z0-9_]*[?!]?$",
        naming={
            "class": "PascalCase",
            "method": "snake_case (predicates end in ?)",
            "variable": "snake_case",
            "constant": "UPPER_SNAKE_CASE",
            "file": "snake_case.rb",
        },
        line_comment="#",
        block_comment=("=begin", "=end"),
        package_manager="bundler (gem)",
        manifest="Gemfile",
        formatter="rubocop -a",
        linter="rubocop",
        test_frameworks=("RSpec", "Minitest"),
        grammar="tree_sitter_ruby",
        rules=(
            "Two-space indentation; `# frozen_string_literal: true` at the top of files.",
            "Predicate methods end in ?, dangerous (mutating) methods in !.",
            "Prefer guard clauses and early returns over nested conditionals.",
            "Don't reopen core classes (String, Array, Hash) in application code.",
        ),
        avoid=_words(
            "Object String Array Hash Integer Float Symbol Kernel Class Module Comparable Enumerable Time Date"
        ),
    )
)

# ── Dart (reserved words; built-in identifiers can't be type names) ──
_add(
    LanguageSpec(
        key="dart",
        label="Dart",
        extensions=(".dart",),
        typing="static",
        keywords=_words(
            "assert break case catch class const continue default do else enum extends false final finally for if in "
            "is new null rethrow return super switch this throw true try var void while with await yield"
        ),
        identifier_pattern=r"^[A-Za-z_$][A-Za-z0-9_$]*$",
        naming={
            "type": "UpperCamelCase",
            "member": "lowerCamelCase",
            "constant": "lowerCamelCase",
            "library/file": "lowercase_with_underscores.dart",
        },
        line_comment="//",
        block_comment=("/*", "*/"),
        package_manager="pub (flutter pub)",
        manifest="pubspec.yaml",
        formatter="dart format",
        linter="dart analyze (flutter_lints)",
        test_frameworks=("flutter_test", "test"),
        grammar="tree_sitter_dart",
        rules=(
            "Sound null safety: non-nullable by default, `?` for nullable, `late` only when truly initialized later.",
            "Prefer const constructors for widgets that never change.",
            "Constants are lowerCamelCase in Dart, not UPPER_CASE.",
            "Built-in identifiers (abstract, dynamic, factory, get, set, late, required, typedef…) can't name types.",
        ),
        avoid=_words(
            "abstract as covariant deferred dynamic export extension external factory Function get implements import "
            "interface late library mixin operator part required set static typedef Object String int double bool List Map"
        ),
    )
)

# ── Swift ──
_add(
    LanguageSpec(
        key="swift",
        label="Swift",
        extensions=(".swift",),
        typing="static",
        keywords=_words(
            "associatedtype class deinit enum extension fileprivate func import init inout internal let open operator "
            "private precedencegroup protocol public rethrows static struct subscript typealias var break case catch "
            "continue default defer do else fallthrough for guard if in repeat return throw switch where while Any as "
            "await false is nil self Self super throws true try"
        ),
        identifier_pattern=_IDENT,
        naming={
            "type": "UpperCamelCase",
            "function": "lowerCamelCase",
            "property": "lowerCamelCase",
            "file": "UpperCamelCase.swift",
        },
        line_comment="//",
        block_comment=("/*", "*/"),
        package_manager="Swift Package Manager",
        manifest="Package.swift / .xcodeproj",
        formatter="swift-format",
        linter="SwiftLint",
        test_frameworks=("XCTest", "Swift Testing"),
        grammar="tree_sitter_swift",
        rules=(
            "Prefer let over var and value types (struct) over classes.",
            "Unwrap optionals safely (if let / guard let); avoid force-unwrapping with !.",
            "Keywords can only be names inside backticks (`default`) — choose another name instead.",
            "Mark UI updates @MainActor; use async/await for concurrency.",
        ),
        avoid=_words(
            "String Int Double Bool Array Dictionary Set Optional Result Error View Type Protocol"
        ),
    )
)

# ── GDScript (Godot 4) ──
_add(
    LanguageSpec(
        key="gdscript",
        label="GDScript",
        extensions=(".gd",),
        typing="gradual",
        keywords=_words(
            "if elif else for while match when break continue pass return class class_name extends is in as self "
            "super signal func static const enum var breakpoint preload await yield assert void and or not true "
            "false null PI TAU INF NAN"
        ),
        identifier_pattern=_IDENT,
        naming={
            "class": "PascalCase",
            "function": "snake_case",
            "variable": "snake_case",
            "signal": "snake_case, past tense",
            "constant": "CONSTANT_CASE",
            "file": "snake_case.gd",
        },
        line_comment="#",
        block_comment=None,
        package_manager="Godot Asset Library",
        manifest="project.godot",
        formatter="gdformat (gdtoolkit)",
        linter="gdlint (gdtoolkit)",
        test_frameworks=("GUT", "gdUnit4"),
        grammar="tree_sitter_gdscript",
        rules=(
            "Indent with tabs (Godot's default); one class per file, named with class_name.",
            "Use static typing (var speed: float = 10.0) for performance and errors at parse time.",
            "Connect signals in code with signal.connect(callable).",
            "Engine callbacks start with an underscore (_ready, _process, _physics_process).",
        ),
        avoid=_words(
            "Node Object Vector2 Vector3 Color String Array Dictionary Resource int float bool"
        ),
    )
)

# ── Lua (O3DE and Godot tooling scripts) ──
_add(
    LanguageSpec(
        key="lua",
        label="Lua",
        extensions=(".lua",),
        typing="dynamic",
        keywords=_words(
            "and break do else elseif end false for function goto if in local nil not or repeat return then true until while"
        ),
        identifier_pattern=_IDENT,
        naming={
            "function": "camelCase or snake_case (match the codebase)",
            "variable": "local, camelCase",
            "file": "snake_case.lua",
        },
        line_comment="--",
        block_comment=("--[[", "]]"),
        package_manager="LuaRocks",
        manifest="*.rockspec",
        formatter="StyLua",
        linter="luacheck",
        test_frameworks=("busted",),
        grammar="tree_sitter_lua",
        rules=(
            "Declare every variable `local`; globals leak across scripts.",
            "Tables are 1-indexed.",
            "O3DE component scripts return a table with OnActivate/OnDeactivate.",
        ),
        avoid=_words(
            "table string math os io print type pairs ipairs next select error assert require"
        ),
    )
)

# ── C++ (O3DE engine code) ──
_add(
    LanguageSpec(
        key="cpp",
        label="C++",
        extensions=(".cpp", ".cc", ".h", ".hpp"),
        typing="static",
        keywords=_words(
            "alignas alignof and and_eq asm auto bitand bitor bool break case catch char char8_t char16_t char32_t "
            "class compl concept const consteval constexpr constinit const_cast continue co_await co_return co_yield "
            "decltype default delete do double dynamic_cast else enum explicit export extern false float for friend "
            "goto if inline int long mutable namespace new noexcept not not_eq nullptr operator or or_eq private "
            "protected public register reinterpret_cast requires return short signed sizeof static static_assert "
            "static_cast struct switch template this thread_local throw true try typedef typeid typename union "
            "unsigned using virtual void volatile wchar_t while xor xor_eq"
        ),
        identifier_pattern=_IDENT,
        naming={
            "type": "PascalCase",
            "function": "PascalCase (O3DE) / camelCase",
            "member": "m_camelCase (O3DE)",
            "file": "PascalCase.cpp/.h",
        },
        line_comment="//",
        block_comment=("/*", "*/"),
        package_manager="CMake + vcpkg/conan",
        manifest="CMakeLists.txt",
        formatter="clang-format",
        linter="clang-tidy",
        test_frameworks=("GoogleTest", "AzTest (O3DE)"),
        grammar="tree_sitter_cpp",
        rules=(
            "Prefer RAII and smart pointers (AZStd::unique_ptr in O3DE); no naked new/delete.",
            "Headers use #pragma once and include only what they need.",
            "Const-correctness: mark methods const when they don't mutate.",
        ),
        avoid=_words(
            "std string vector map size_t int8_t int16_t int32_t int64_t uint8_t uint32_t uint64_t"
        ),
    )
)

# ── Supporting languages every stack touches ──
_add(
    LanguageSpec(
        key="sql",
        label="SQL",
        extensions=(".sql",),
        typing="static",
        # Reserved in SQLite and/or PostgreSQL — a column with one of these
        # names must be double-quoted everywhere (check_expr quotes them).
        keywords=_words(
            "all alter and any as asc between by case check column constraint create cross current_date "
            "current_time current_timestamp default delete desc distinct drop else end except exists false foreign "
            "from full group having in index inner insert intersect into is join left like limit natural not null "
            "offset on or order outer primary references right select set table then to true union unique update "
            "user using values when where with"
        ),
        identifier_pattern=r"^[A-Za-z_][A-Za-z0-9_]*$",
        naming={
            "table": "snake_case, plural",
            "column": "snake_case",
            "constraint": "prefix_table_column (pk_, fk_, uq_, ck_, ix_)",
        },
        line_comment="--",
        block_comment=("/*", "*/"),
        package_manager="—",
        manifest="migrations",
        formatter="sqlfluff",
        linter="sqlfluff",
        test_frameworks=("pgTAP",),
        grammar="tree_sitter_sql",
        rules=(
            "Never build SQL by concatenating user input; always bind parameters.",
            "Name every constraint explicitly so migrations can alter or drop it.",
            "Use snake_case identifiers; quote any identifier that is a reserved word.",
        ),
        keywords_case_insensitive=True,
    )
)

_add(
    LanguageSpec(
        key="html",
        label="HTML",
        extensions=(".html", ".htm"),
        typing="dynamic",
        keywords=frozenset(),
        identifier_pattern=r"^[A-Za-z][A-Za-z0-9_-]*$",
        naming={"id/class": "kebab-case", "file": "kebab-case.html"},
        line_comment=None,
        block_comment=("<!--", "-->"),
        package_manager="—",
        manifest="index.html",
        formatter="prettier",
        linter="html-validate",
        test_frameworks=("Playwright",),
        grammar="tree_sitter_html",
        rules=(
            "Start with <!doctype html> and <html lang>; include a viewport meta tag.",
            "Use semantic elements (header, nav, main, section, button) — not clickable divs.",
            "Every form input has a <label>; every image has alt text (WCAG 2.2 AA).",
        ),
    )
)

_add(
    LanguageSpec(
        key="css",
        label="CSS",
        extensions=(".css",),
        typing="dynamic",
        keywords=frozenset(),
        identifier_pattern=r"^-?[A-Za-z_][A-Za-z0-9_-]*$",
        naming={
            "class": "kebab-case (or BEM block__element--modifier)",
            "custom property": "--kebab-case",
        },
        line_comment=None,
        block_comment=("/*", "*/"),
        package_manager="—",
        manifest="—",
        formatter="prettier",
        linter="stylelint",
        test_frameworks=(),
        grammar="tree_sitter_css",
        rules=(
            "Use CSS custom properties for colors and spacing; support prefers-color-scheme.",
            "Mobile-first media queries; relative units (rem) for type.",
            "Keep text contrast at least 4.5:1 (WCAG AA).",
        ),
    )
)

for _key, _label, _ext, _grammar, _rules in (
    (
        "json",
        "JSON",
        (".json",),
        "tree_sitter_json",
        ("No comments and no trailing commas.", "Keys are double-quoted strings."),
    ),
    (
        "yaml",
        "YAML",
        (".yml", ".yaml"),
        "tree_sitter_yaml",
        (
            "Indent with spaces, never tabs.",
            "Quote strings that look like numbers, booleans or dates (yes/no/on/off).",
        ),
    ),
    (
        "toml",
        "TOML",
        (".toml",),
        "tree_sitter_toml",
        ("Keys are unique within a table.", "Strings are double-quoted."),
    ),
    (
        "xml",
        "XML",
        (".xml", ".csproj", ".pom"),
        "tree_sitter_xml",
        ("Exactly one root element; every tag closed.", "Escape & < > in text."),
    ),
    (
        "bash",
        "Shell (bash)",
        (".sh",),
        "tree_sitter_bash",
        ("Start with set -euo pipefail.", 'Quote every variable expansion ("$var").'),
    ),
):
    _add(
        LanguageSpec(
            key=_key,
            label=_label,
            extensions=_ext,
            typing="dynamic",
            keywords=frozenset(),
            identifier_pattern=r"^.+$",
            naming={},
            line_comment="#" if _key in ("yaml", "toml", "bash") else None,
            block_comment=("<!--", "-->") if _key == "xml" else None,
            package_manager="—",
            manifest="—",
            formatter="prettier" if _key in ("json", "yaml") else "—",
            linter="—",
            test_frameworks=(),
            grammar=_grammar,
            rules=_rules,
        )
    )

# Aliases the codebase already uses for GeneratedFile.language / stack keys.
LANGUAGE_ALIASES: dict[str, str] = {
    "js": "javascript",
    "jsx": "javascript",
    "ts": "typescript",
    "tsx": "typescript",
    "c#": "csharp",
    "cs": "csharp",
    "c_sharp": "csharp",
    "golang": "go",
    "rs": "rust",
    "rb": "ruby",
    "py": "python",
    "kt": "kotlin",
    "c++": "cpp",
    "o3de_script": "lua",
    "shell": "bash",
    "sh": "bash",
    "yml": "yaml",
}


def language(key: str | None) -> LanguageSpec | None:
    if not key:
        return None
    k = key.strip().lower()
    return LANGUAGES.get(LANGUAGE_ALIASES.get(k, k))


def is_keyword(word: str, lang: LanguageSpec) -> bool:
    if lang.keywords_case_insensitive:
        return word.lower() in {k.lower() for k in lang.keywords}
    return word in lang.keywords
