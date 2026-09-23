"""Stack-aware project planning, bounded project memory and static completion gates."""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from threading import RLock
from typing import Any, Iterable

from .project import ProjectDetector, ProjectInfo
from .languages import ProgrammingLanguageRouter, ProjectTypeResolver


@dataclass(frozen=True, slots=True)
class RequirementTrace:
    requirement: str
    implementation: tuple[str, ...] = ()
    verification: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ProjectPlan:
    goal: str
    platform: str
    stack: str
    requirements: tuple[str, ...]
    files: tuple[str, ...]
    folders: tuple[str, ...]
    dependencies: tuple[str, ...]
    assets: tuple[str, ...]
    routes: tuple[str, ...]
    components: tuple[str, ...]
    tests: tuple[str, ...]
    run_command: tuple[str, ...]
    build_command: tuple[str, ...]
    deliverables: tuple[str, ...]
    constraints: tuple[str, ...]
    existing_project: bool = False
    traceability: tuple[RequirementTrace, ...] = ()
    language: tuple[str, ...] = ()
    framework: str | None = None
    runtime: str | None = None
    project_type: str = "application"
    architecture: tuple[str, ...] = ()
    data: tuple[str, ...] = ()

    def public(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ProjectContext:
    root: str
    stack: str
    requirements: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    current_task: str = ""
    files_changed: list[str] = field(default_factory=list)
    tests: list[dict[str, Any]] = field(default_factory=list)
    updated_at: float = field(default_factory=time.time)

    def remember_change(self, path: str) -> None:
        normalized = str(path)
        if normalized not in self.files_changed:
            self.files_changed.append(normalized)
        self.files_changed = self.files_changed[-200:]
        self.updated_at = time.time()

    def remember_test(self, command: Iterable[str], *, passed: bool) -> None:
        self.tests.append({"command": list(command), "passed": bool(passed), "at": time.time()})
        self.tests = self.tests[-100:]
        self.updated_at = time.time()


class ProjectContextStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve(); self._lock = RLock()

    def _path(self, project_root: str | Path) -> Path:
        normalized = str(Path(project_root).expanduser().resolve()).casefold()
        return self.root / f"{hashlib.sha256(normalized.encode()).hexdigest()[:24]}.json"

    def save(self, context: ProjectContext) -> Path:
        path = self._path(context.root); path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        with self._lock:
            temporary.write_text(json.dumps(asdict(context), ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(path)
        return path

    def load(self, project_root: str | Path) -> ProjectContext | None:
        path = self._path(project_root)
        if not path.is_file(): return None
        try:
            with self._lock: value = json.loads(path.read_text(encoding="utf-8"))
            return ProjectContext(**{key: item for key, item in value.items() if key in ProjectContext.__dataclass_fields__})
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return None


class ProjectPlanner:
    """Produce a minimal plan from natural constraints; it never creates or executes files."""

    def plan(self, request: str, *, root: str | Path | None = None) -> ProjectPlan:
        goal = " ".join(str(request).split())[:2000]
        normalized = goal.casefold()
        existing = root is not None and Path(root).expanduser().exists()
        info = ProjectDetector().detect(root) if existing else None
        constraints = self._constraints(normalized)
        languages = tuple(profile.id for profile in ProgrammingLanguageRouter().route(goal))
        project_type = ProjectTypeResolver().resolve(goal)
        if info:
            plan = self._existing(goal, info, constraints)
            return replace(
                plan, language=languages or tuple(info.kinds),
                framework=project_type.framework, runtime=info.runtime or project_type.runtime,
                project_type=project_type.project_type,
            )
        if re.search(r"\b(?:vite|react|vue|svelte)\b", normalized) and "only html css js" not in constraints:
            stack = "vite-react" if "react" in normalized else "vite"
            files = ("package.json", "index.html", "src/main.jsx", "src/styles.css", "README.md", ".gitignore", ".env.example")
            folders = ("src", "src/components", "src/assets", "public")
            dependencies = ("vite", "react", "react-dom") if stack == "vite-react" else ("vite",)
            run, build, tests = ("npm", "run", "dev"), ("npm", "run", "build"), ("npm run build", "responsive smoke")
            platform = "web"
        elif re.search(r"\b(?:api|backend)\b", normalized) and re.search(r"\b(?:node|express|javascript|typescript)\b", normalized):
            stack = "node-api"; platform = "server"
            files = ("package.json", "src/app.js", "src/server.js", "README.md", ".gitignore", ".env.example")
            folders = ("src", "src/routes", "src/controllers", "src/services", "src/middleware", "tests")
            dependencies = ("express",); run, build, tests = ("npm", "start"), (), ("route smoke", "error handling")
        elif re.search(r"\b(?:python|fastapi|flask|cli)\b", normalized):
            stack = "python"; platform = "desktop-cli" if "cli" in normalized else "server" if "api" in normalized else "general"
            files = ("pyproject.toml", "src/main.py", "tests/test_main.py", "README.md", ".gitignore", ".env.example")
            folders = ("src", "tests")
            dependencies = ("fastapi", "uvicorn") if "fastapi" in normalized else ("flask",) if "flask" in normalized else ()
            run, build, tests = ("python", "-m", "src.main"), (), ("python -m pytest",)
        else:
            stack = "html-css-js"; platform = "web"
            files = ("index.html", "css/styles.css", "js/app.js", "README.md")
            folders = ("css", "js", "assets/images", "assets/icons")
            dependencies = (); run, build, tests = ("open", "index.html"), (), ("HTML load", "JS syntax", "responsive smoke", "keyboard navigation")
        requirements = self._requirements(goal)
        traces = tuple(RequirementTrace(item, files, tests) for item in requirements)
        return ProjectPlan(
            goal, platform, stack, requirements, files, folders, dependencies,
            ("assets/images", "assets/icons"), (), (), tests, run, build,
            files, constraints, False, traces, languages, project_type.framework,
            project_type.runtime, project_type.project_type, folders, (),
        )

    @staticmethod
    def _existing(goal: str, info: ProjectInfo, constraints: tuple[str, ...]) -> ProjectPlan:
        requirements = ProjectPlanner._requirements(goal)
        files = tuple(info.markers) + tuple(info.entrypoints)
        verification = tuple(filter(None, (info.test_framework or "", "startup smoke")))
        return ProjectPlan(
            goal, "existing", "+".join(info.kinds) or "unknown", requirements,
            files, (), (), (), (), (), verification, info.suggested_command, (),
            (), constraints + ("preserve existing architecture", "minimal relevant changes"), True,
            tuple(RequirementTrace(item, (), verification) for item in requirements),
        )

    @staticmethod
    def _constraints(normalized: str) -> tuple[str, ...]:
        constraints = []
        for pattern, value in (
            (r"solo html(?:,|\s)+(?:css(?:,|\s)+)?(?:y\s+)?js|solo html css js", "only html css js"),
            (r"sin backend", "no backend"), (r"no cambies el dise[nñ]o", "preserve design"),
            (r"sin react", "no react"), (r"responsive", "responsive"),
        ):
            if re.search(pattern, normalized): constraints.append(value)
        return tuple(constraints)

    @staticmethod
    def _requirements(goal: str) -> tuple[str, ...]:
        parts = [item.strip(" .;:-") for item in re.split(r"[,;\n]|\s+y\s+", goal) if item.strip(" .;:-")]
        return tuple(dict.fromkeys(parts[:30])) or (goal,)


class ProjectCompletionGate:
    """Static checks never claim runtime success."""

    SECRET_PATTERN = re.compile(r"(?i)(?:api[_-]?key|secret|password|token)\s*[:=]\s*['\"][^'\"]{8,}['\"]")
    RESOURCE_PATTERN = re.compile(r"(?:src|href)\s*=\s*['\"](?!https?://|data:|#|mailto:)([^'\"]+)['\"]", re.I)

    def validate(self, root: str | Path, plan: ProjectPlan) -> dict[str, Any]:
        project = Path(root).expanduser().resolve()
        if not project.is_dir(): raise FileNotFoundError("project_folder_not_found")
        missing = [item for item in plan.files if not (project / item).exists()]
        broken: list[dict[str, str]] = []; secrets: list[str] = []; inspected = 0
        for path in project.rglob("*"):
            if not path.is_file() or any(part in {".git", "node_modules", ".venv", "venv", "dist", "build"} for part in path.parts):
                continue
            if path.suffix.casefold() not in {".html", ".css", ".js", ".jsx", ".ts", ".tsx", ".py", ".json", ".toml", ".md"} or path.stat().st_size > 2_000_000:
                continue
            inspected += 1
            text = path.read_text(encoding="utf-8", errors="replace")
            if self.SECRET_PATTERN.search(text) and path.name != ".env.example": secrets.append(str(path.relative_to(project)))
            if path.suffix.casefold() == ".html":
                for reference in self.RESOURCE_PATTERN.findall(text):
                    clean = reference.split("?", 1)[0].split("#", 1)[0]
                    target = (project / clean.lstrip("/\\")) if clean.startswith(("/", "\\")) else (path.parent / clean)
                    if clean and not target.resolve().is_file():
                        broken.append({"source": str(path.relative_to(project)), "reference": reference})
        passed = not missing and not broken and not secrets
        return {
            "status": "STATIC VALIDATED" if passed else "STATIC VALIDATION FAILED",
            "runtime_verified": False, "passed": passed, "files_inspected": inspected,
            "missing_planned_files": missing, "broken_resources": broken,
            "possible_secrets": secrets,
        }
