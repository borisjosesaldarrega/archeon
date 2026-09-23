from __future__ import annotations

import tempfile
from pathlib import Path

from archeon.programming import (
    ProjectCompletionGate, ProjectContext, ProjectContextStore, ProjectPlanner,
)


def test_user_constraint_prevents_unrequested_framework() -> None:
    plan = ProjectPlanner().plan("Haz una web responsive, solo HTML CSS JS, sin React y sin backend")
    assert plan.stack == "html-css-js"
    assert plan.dependencies == ()
    assert "no backend" in plan.constraints
    assert "index.html" in plan.files and "css/styles.css" in plan.files


def test_stack_specific_plans_are_not_one_structure_for_everything() -> None:
    planner = ProjectPlanner()
    vite = planner.plan("Crea un frontend React con Vite")
    api = planner.plan("Créame una API para usuarios con Node y Express")
    python = planner.plan("Haz una herramienta CLI en Python")
    assert vite.stack == "vite-react" and "src/components" in vite.folders
    assert api.stack == "node-api" and "src/routes" in api.folders
    assert python.stack == "python" and "pyproject.toml" in python.files
    assert all(plan.traceability for plan in (vite, api, python))


def test_existing_project_is_detected_and_preserved() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "package.json").write_text('{"scripts":{"test":"node --test"}}', encoding="utf-8")
        (root / "server.js").write_text("console.log('ok')", encoding="utf-8")
        plan = ProjectPlanner().plan("Arregla el login pero no cambies el diseño", root=root)
        assert plan.existing_project
        assert "preserve existing architecture" in plan.constraints
        assert "minimal relevant changes" in plan.constraints


def test_completion_gate_detects_broken_asset_and_never_claims_runtime() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "css").mkdir(); (root / "js").mkdir()
        (root / "index.html").write_text('<link href="css/styles.css"><img src="assets/images/missing.png"><script src="js/app.js"></script>', encoding="utf-8")
        (root / "css" / "styles.css").write_text("body{}", encoding="utf-8")
        (root / "js" / "app.js").write_text("'use strict';", encoding="utf-8")
        (root / "README.md").write_text("# Project", encoding="utf-8")
        plan = ProjectPlanner().plan("Haz una web responsive solo HTML CSS JS")
        result = ProjectCompletionGate().validate(root, plan)
        assert not result["passed"] and result["broken_resources"]
        assert result["runtime_verified"] is False
        (root / "assets" / "images").mkdir(parents=True)
        (root / "assets" / "images" / "missing.png").write_bytes(b"png")
        assert ProjectCompletionGate().validate(root, plan)["status"] == "STATIC VALIDATED"


def test_project_context_is_bounded_and_persistent() -> None:
    with tempfile.TemporaryDirectory() as directory:
        store = ProjectContextStore(Path(directory) / "memory")
        context = ProjectContext(str(Path(directory) / "project"), "python", ["CLI"])
        context.remember_change("src/main.py")
        context.remember_test(("python", "-m", "pytest"), passed=True)
        store.save(context)
        loaded = store.load(context.root)
        assert loaded is not None
        assert loaded.stack == "python" and loaded.files_changed == ["src/main.py"]
        assert loaded.tests[-1]["passed"] is True
