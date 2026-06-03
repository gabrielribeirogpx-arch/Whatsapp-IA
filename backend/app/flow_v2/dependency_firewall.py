from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


FORBIDDEN_IMPORTS: tuple[str, ...] = (
    "app.services.flow_engine_service",
    "app.services.flow_runtime_service",
    "app.services.bot_service",
    "app.services.whatsapp_service",
    "app.workers",
)
FORBIDDEN_MODULE_BASENAMES: tuple[str, ...] = (
    "flow_engine_service",
    "flow_runtime_service",
    "bot_service",
    "whatsapp_service",
)


class DependencyFirewallError(RuntimeError):
    def __init__(self, violations: tuple["DependencyViolation", ...]) -> None:
        self.violations = violations
        details = "; ".join(f"{v.path}:{v.line} imports {v.imported}" for v in violations)
        super().__init__(f"Flow V2 dependency firewall failed: {details}")


@dataclass(frozen=True)
class DependencyViolation:
    path: str
    line: int
    imported: str
    reason: str


def scan_flow_v2_dependencies(root: str | Path | None = None) -> tuple[DependencyViolation, ...]:
    """Scan Flow V2 Python files for forbidden Runtime V1 dependencies."""

    flow_v2_root = Path(root) if root is not None else Path(__file__).resolve().parent
    violations: list[DependencyViolation] = []
    for path in sorted(flow_v2_root.rglob("*.py")):
        if path.name == "dependency_firewall.py":
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            violations.append(
                DependencyViolation(
                    path=_display_path(path),
                    line=exc.lineno or 0,
                    imported="<syntax-error>",
                    reason=str(exc),
                )
            )
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    _append_if_forbidden(violations, path=path, line=node.lineno, imported=alias.name)
            elif isinstance(node, ast.ImportFrom):
                module = _absolute_module(node)
                if module:
                    module_reason = _forbidden_reason(module)
                    _append_if_forbidden(violations, path=path, line=node.lineno, imported=module)
                    if module_reason is None:
                        for alias in node.names:
                            if alias.name == "*":
                                continue
                            _append_if_forbidden(violations, path=path, line=node.lineno, imported=f"{module}.{alias.name}")
    return tuple(violations)


def assert_flow_v2_dependency_firewall(root: str | Path | None = None) -> None:
    violations = scan_flow_v2_dependencies(root)
    if violations:
        raise DependencyFirewallError(violations)


def _absolute_module(node: ast.ImportFrom) -> str | None:
    if not node.module:
        return None
    if node.level == 0:
        return node.module
    return "." * node.level + node.module


def _append_if_forbidden(violations: list[DependencyViolation], *, path: Path, line: int, imported: str) -> None:
    reason = _forbidden_reason(imported)
    if reason:
        candidate = DependencyViolation(path=_display_path(path), line=line, imported=imported, reason=reason)
        if candidate not in violations:
            violations.append(candidate)


def _forbidden_reason(imported: str) -> str | None:
    normalized = imported.strip()
    for forbidden in FORBIDDEN_IMPORTS:
        if normalized == forbidden or normalized.startswith(f"{forbidden}."):
            if forbidden == "app.workers":
                return "Runtime V2 must not import V1 workers"
            return "Runtime V2 must not import Runtime V1 service dependencies"
    basename = normalized.rsplit(".", 1)[-1]
    if basename in FORBIDDEN_MODULE_BASENAMES:
        return "Runtime V2 must not import Runtime V1 service dependencies"
    return None


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(Path.cwd()))
    except ValueError:
        return str(path)
