from app.api.v1.export import build_export_filename


def test_build_export_filename_uses_app_name_when_provided() -> None:
    assert build_export_filename("My Project", "Pixel Forge") == "Pixel_Forge.zip"


def test_build_export_filename_falls_back_to_project_name() -> None:
    assert build_export_filename("My Project") == "My_Project.zip"


def test_zip_paths_can_never_leave_the_folder() -> None:
    from app.api.v1.export import _safe_zip_path

    # The old lstrip("/").replace("..", "") turned this back into "/etc/passwd".
    assert _safe_zip_path("/../etc/passwd") == "etc/passwd"
    assert _safe_zip_path("a/../../b\..\c/./d") == "a/b/c/d"
    assert _safe_zip_path("backend/models/order.py") == "backend/models/order.py"


def test_bundle_holds_readme_documents_and_code_even_before_codegen() -> None:
    from types import SimpleNamespace

    from app.api.v1.export import export_bundle_files

    base = dict(
        name="Demo",
        description=None,
        raw_idea=None,
        requirements_data=None,
        uiux_data=None,
        architecture_data=None,
        testing_data=None,
    )
    docs_only = export_bundle_files(SimpleNamespace(**base, codegen_data=None))
    assert docs_only[0][0] == "README.md" and "documents only" in docs_only[0][1]
    with_code = export_bundle_files(
        SimpleNamespace(
            **base,
            codegen_data={
                "codegen": {
                    "summary": "s",
                    "files": [{"path": "/../x.py", "content": "1"}],
                }
            },
        )
    )
    assert with_code[-1] == ("x.py", "1") and "Files included: 1" in with_code[0][1]
