from __future__ import annotations

import ast
from pathlib import Path


MAX_ALEMBIC_VERSION_NUM_LENGTH = 32
MIGRATION_DIRS = (
    Path(__file__).resolve().parents[1] / "alembic" / "versions",
    Path(__file__).resolve().parents[1] / "app" / "alembic" / "versions",
)


def _string_revision_ids(value: ast.AST) -> list[str]:
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return [value.value]
    if isinstance(value, (ast.Tuple, ast.List)):
        return [
            item.value
            for item in value.elts
            if isinstance(item, ast.Constant) and isinstance(item.value, str)
        ]
    return []


def _revision_ids(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    revision_ids: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            names = [target.id for target in node.targets if isinstance(target, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names = [node.target.id]
        else:
            continue

        if any(name in {"revision", "down_revision", "depends_on"} for name in names):
            revision_ids.extend(_string_revision_ids(node.value))
    return revision_ids


def test_alembic_revision_ids_fit_version_table_limit() -> None:
    too_long: list[str] = []
    for migration_dir in MIGRATION_DIRS:
        for migration in migration_dir.glob("*.py"):
            relative_path = migration.relative_to(Path(__file__).resolve().parents[1])
            too_long.extend(
                f"{relative_path}: {revision_id} ({len(revision_id)})"
                for revision_id in _revision_ids(migration)
                if len(revision_id) > MAX_ALEMBIC_VERSION_NUM_LENGTH
            )

    assert too_long == []
