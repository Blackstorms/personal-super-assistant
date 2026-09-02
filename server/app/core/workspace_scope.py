"""工作空间范围筛选：全部 / 独立任务 / 指定工作空间。"""

from __future__ import annotations


def workspace_scope_clause(
    *,
    workspace_id: str | None = None,
    standalone: bool = False,
    column: str = "workspace_id",
) -> tuple[str, list]:
    if standalone:
        return f" AND {column} IS NULL", []
    if workspace_id:
        return f" AND {column}=?", [workspace_id]
    return "", []


def workspace_scope_where(
    *,
    workspace_id: str | None = None,
    standalone: bool = False,
    column: str = "workspace_id",
) -> tuple[str, list]:
    clause, params = workspace_scope_clause(
        workspace_id=workspace_id, standalone=standalone, column=column
    )
    if not clause:
        return "", []
    return f" WHERE {clause.strip().removeprefix('AND').strip()}", params
