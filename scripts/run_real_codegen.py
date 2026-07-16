import asyncio
from pathlib import Path
import sys


def extract_build_codegen_prompt(path: Path):
    import ast
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


async def main():
    repo_root = Path(__file__).resolve().parents[1]
    codegen_path = repo_root / "apps" / "backend" / "app" / "api" / "v1" / "codegen.py"
    if not codegen_path.exists():
        print("codegen.py not found at", codegen_path)
        return 2

    build_codegen_prompt = extract_build_codegen_prompt(codegen_path)

    prompt = build_codegen_prompt(
        "RealRunTestApp",
        {"tech_stack": {"frontend": "React + Vite"}, "database_tables": []},
        {"screens": [{"name": "Home", "purpose": "Landing"}]},
    )

    print("Generated prompt preview (first 800 chars):\n")
    print(prompt[:800])

    try:
        import sys
        backend_app_path = repo_root / "apps" / "backend"
        sys.path.insert(0, str(backend_app_path))
        from app.ai import orchestrator
    except Exception as e:
        print("Could not import orchestrator.generate_text:", type(e).__name__, e)
        return 3

    try:
        res = await orchestrator.generate_text(prompt)
        print("\nAI response source:", res.get('source'))
        text = res.get('text', '')
        print('\nAI text (first 2000 chars):\n')
        print(text[:2000])
        return 0
    except Exception as e:
        print("AI generation failed:", type(e).__name__, e)
        return 4


if __name__ == '__main__':
    code = asyncio.run(main())
    sys.exit(code)
