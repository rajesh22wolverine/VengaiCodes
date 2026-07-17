from app.api.v1.export import build_export_filename


def test_build_export_filename_uses_app_name_when_provided() -> None:
    assert build_export_filename("My Project", "Pixel Forge") == "Pixel_Forge.zip"


def test_build_export_filename_falls_back_to_project_name() -> None:
    assert build_export_filename("My Project") == "My_Project.zip"
