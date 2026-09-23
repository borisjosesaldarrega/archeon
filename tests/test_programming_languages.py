from __future__ import annotations

from archeon.programming import (
    BUILTIN_PROFILES, ProgrammingLanguageRouter, ProjectPlanner,
    ProjectTypeResolver, ToolchainDetector,
)


def test_required_language_profiles_are_present():
    identifiers = {item.id for item in BUILTIN_PROFILES}
    assert {
        "python", "javascript", "typescript", "html", "css", "sql", "c", "cpp",
        "csharp", "java", "php", "powershell", "bash", "dart", "flutter", "json",
        "yaml", "xml", "markdown",
    } <= identifiers


def test_language_and_project_type_are_independent():
    request = "Crea un backend API en TypeScript con Express"
    routed = ProgrammingLanguageRouter().route(request)
    resolved = ProjectTypeResolver().resolve(request)
    assert "typescript" in {item.id for item in routed}
    assert resolved.project_type == "api"
    assert resolved.framework == "express"


def test_multilanguage_web_project_recognition():
    routed = ProgrammingLanguageRouter().route("HTML CSS TypeScript y SQL PostgreSQL")
    assert {"html", "css", "typescript", "sql"} <= {item.id for item in routed}


def test_cpp_does_not_accidentally_route_as_c():
    routed = ProgrammingLanguageRouter().route("haz un programa estructurado en C++")
    assert [item.id for item in routed] == ["cpp"]


def test_explicit_vanilla_stack_is_not_replaced_by_framework():
    plan = ProjectPlanner().plan("haz una página solo HTML CSS JS sin React")
    assert plan.stack == "html-css-js"
    assert "react" not in plan.dependencies
    assert {"html", "css", "javascript"} <= set(plan.language)


def test_toolchain_detector_is_lazy_until_detect_called():
    detector = ToolchainDetector()
    assert detector._cache == {}
    result = detector.detect("python", include_version=False)
    assert result["name"] == "python"
    assert result["version_checked"] is False
    assert "python" in detector._cache


def test_unknown_toolchain_is_rejected():
    try:
        ToolchainDetector().detect("imaginary-compiler")
    except ValueError as error:
        assert str(error) == "unsupported_toolchain"
    else:
        raise AssertionError("unsupported toolchain was accepted")
