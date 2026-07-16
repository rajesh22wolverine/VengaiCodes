
import ast
from pathlib import Path
import sys


def extract_build_codegen_prompt(path: Path):
    src = path.read_text(encoding='utf-8')
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == 'build_codegen_prompt':
            mod = ast.Module(body=[node], type_ignores=[])
            code = compile(mod, filename=str(path), mode='exec')
            ns = {}
            exec(code, ns)
            return ns['build_codegen_prompt']
    raise RuntimeError('build_codegen_prompt not found')


def main():
    repo_root = Path(__file__).resolve().parents[1]
    codegen_path = repo_root / "apps" / "backend" / "app" / "api" / "v1" / "codegen.py"
    if not codegen_path.exists():
        print("codegen.py not found at", codegen_path)
        sys.exit(2)

    build_codegen_prompt = extract_build_codegen_prompt(codegen_path)

    prompt = build_codegen_prompt(
        "MyTestApp",
        {"tech_stack": {"frontend": "React + Vite"}, "database_tables": []},
        {"screens": [{"name": "Home", "purpose": "Landing screen"}]},
    )

    checks = [
        "@tailwind base;",
        "@tailwind components;",
        "@tailwind utilities;",
        "tailwind.config.js",
        "postcss.config.js",
        "tailwindcss",
        "autoprefixer",
        "import './index.css';",
        "Tailwind",
        "className",
    ]

    missing = [c for c in checks if c not in prompt]
    if missing:
        print("FAILED: prompt is missing expected Tailwind items:")
        for m in missing:
            print(" -", m)
        sys.exit(1)

    print("OK: build_codegen_prompt includes Tailwind requirements.")


if __name__ == '__main__':
    main()
