"""Structural validation for templates/o3de/ — CI-friendly, no engine required.

Checks that the O3DE scaffold hasn't silently broken: required files exist,
project/workspace XML parses, and the placeholder Python script compiles.
Does NOT attempt to actually build or run an O3DE project — that requires a
real O3DE engine install (tens of GB, no GPU on hosted runners) and is
intentionally out of scope for hosted CI. See templates/o3de/README.md.
"""
import py_compile
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

TEMPLATE_ROOT = Path("templates/o3de")

REQUIRED_FILES = [
    "ProjectName.project",
    "ProjectName.workspace",
    "README.md",
    "build_o3de_project.sh",
    "build_o3de_project.ps1",
    "Project/README.md",
    "Project/Assets/placeholder.txt",
    "Project/Scripts/placeholder.py",
]

errors = []


def check_required_files():
    for rel_path in REQUIRED_FILES:
        path = TEMPLATE_ROOT / rel_path
        if not path.is_file():
            errors.append(f"missing required file: {path}")
        else:
            print(f"found: {path}")


def check_xml(rel_path):
    path = TEMPLATE_ROOT / rel_path
    if not path.is_file():
        return
    try:
        ET.parse(path)
        print(f"valid XML: {path}")
    except ET.ParseError as e:
        errors.append(f"invalid XML in {path}: {e}")


def check_python_compiles(rel_path):
    path = TEMPLATE_ROOT / rel_path
    if not path.is_file():
        return
    try:
        py_compile.compile(str(path), doraise=True)
        print(f"compiles: {path}")
    except py_compile.PyCompileError as e:
        errors.append(f"Python syntax error in {path}: {e}")


check_required_files()
check_xml("ProjectName.project")
check_xml("ProjectName.workspace")
check_python_compiles("Project/Scripts/placeholder.py")

if errors:
    print("\nO3DE template validation FAILED:")
    for err in errors:
        print(f"  - {err}")
    sys.exit(1)

print("\nO3DE template validation passed.")
