"""Print the Dart package name from the generated frontend/pubspec.yaml's
`name:` field, for `flutter create --project-name` in CI.

Run from the repo root, right after project_files.json is fetched and
BEFORE `flutter create` scaffolds build/ — `flutter create` needs an
already-valid project name up front, and the generated pubspec.yaml's name
is the slug the backend already computed and validated (see flutter.py's
_package_slug: lowercase, underscore-separated, digit/reserved-word safe),
not something this script re-derives.

pubspec.yaml's `name:` line is written deterministically by
flutter.py's _pubspec_yaml() (no AI call), so a plain regex on that one
line is safe — no YAML parser dependency needed for this single field.
"""
import json
import re

with open("project_files.json", "r", encoding="utf-8") as f:
    data = json.load(f)

pubspec = next(
    (f["content"] for f in data.get("files", []) if f.get("path") == "frontend/pubspec.yaml"),
    "",
)
match = re.search(r"^name:\s*(\S+)", pubspec, re.MULTILINE)
print(match.group(1) if match else "vengaicode_app")
