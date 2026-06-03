from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.flow_v2.dependency_firewall import DependencyViolation, scan_flow_v2_dependencies
from app.flow_v2.graph_validator import FlowV2GraphValidator
from app.flow_v2.node_executors import NodeExecutorRegistry
from app.flow_v2.transition_resolver import TransitionResolver


@dataclass(frozen=True)
class ArchitectureTestResult:
    name: str
    passed: bool
    details: tuple[str, ...] = ()


@dataclass(frozen=True)
class ArchitectureTestReport:
    status: str
    results: tuple[ArchitectureTestResult, ...]

    @property
    def passed(self) -> bool:
        return self.status == "PASSED"


class FlowV2ArchitectureTestSuite:
    """Executable architecture assertions for Runtime V2 isolation."""

    def __init__(self, *, root: str | Path | None = None) -> None:
        self.root = Path(root) if root is not None else Path(__file__).resolve().parent

    def run(self) -> ArchitectureTestReport:
        results = (
            self._dependency_firewall(),
            self._supported_node_surface(),
            self._snapshot_validator_surface(),
        )
        return ArchitectureTestReport(status="PASSED" if all(result.passed for result in results) else "FAILED", results=results)

    def _dependency_firewall(self) -> ArchitectureTestResult:
        violations = scan_flow_v2_dependencies(self.root)
        return ArchitectureTestResult(
            name="dependency_firewall",
            passed=not violations,
            details=tuple(_format_violation(violation) for violation in violations),
        )

    def _supported_node_surface(self) -> ArchitectureTestResult:
        registry = NodeExecutorRegistry(event_store=_NoopEventStore(), transition_resolver=TransitionResolver(_NoopEventStore()))
        supported = tuple(sorted(registry._executors))
        expected = ("choice", "condition", "delay", "message")
        return ArchitectureTestResult(
            name="supported_node_surface",
            passed=supported == expected,
            details=(f"supported={supported}", f"expected={expected}"),
        )

    def _snapshot_validator_surface(self) -> ArchitectureTestResult:
        validator = FlowV2GraphValidator()
        valid = validator.validate(
            nodes=[{"id": "start", "type": "message", "content": "hello"}],
            edges=[],
        )
        return ArchitectureTestResult(
            name="snapshot_validator_surface",
            passed=valid.is_valid,
            details=valid.errors,
        )


class _NoopEventStore:
    def append(self, *args, **kwargs):
        return None


def run_architecture_tests(root: str | Path | None = None) -> ArchitectureTestReport:
    return FlowV2ArchitectureTestSuite(root=root).run()


def assert_architecture(root: str | Path | None = None) -> None:
    report = run_architecture_tests(root)
    if not report.passed:
        details = "; ".join(f"{result.name}: {result.details}" for result in report.results if not result.passed)
        raise AssertionError(f"Flow V2 architecture tests failed: {details}")


def _format_violation(violation: DependencyViolation) -> str:
    return f"{violation.path}:{violation.line} imports {violation.imported} ({violation.reason})"
