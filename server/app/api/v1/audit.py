"""工具调用审计舱 API（I6）。"""

from __future__ import annotations

import json

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from app.audit.labels import enrich_audit_records
from app.core.security import require_token
from app.core.workspace_scope import workspace_scope_clause, workspace_scope_where
from app.db.deps import db_dep

router = APIRouter(dependencies=[Depends(require_token)])


class ExportBody(BaseModel):
    workspace_id: str | None = None
    standalone: bool = False
    format: str = "markdown"


def _format_export_markdown(enriched: list[dict]) -> str:
    lines = ["# 工具调用审计报告", ""]
    for item in enriched:
        labels = item.get("labels") or {}
        tool = labels.get("tool") or {}
        source = labels.get("source") or {}
        confirm = labels.get("confirm_status") or {}
        risk = labels.get("risk") or {}
        status = (labels.get("status") or {}).get("label") or ("失败" if item.get("is_error") else "成功")

        lines.append(f"## {item.get('created_at')} · {tool.get('label', item.get('name'))}")
        lines.append(f"- **摘要**：{labels.get('summary', '')}")
        lines.append(f"- **工具**：{tool.get('label', item.get('name'))}（`{item.get('name')}`）")
        if tool.get("description"):
            lines.append(f"- **说明**：{tool['description']}")
        lines.append(
            f"- **来源**：{source.get('label', item.get('source'))} · "
            f"**风险**：{risk.get('label', item.get('risk'))} · "
            f"**确认**：{confirm.get('label', item.get('confirm_status'))} · "
            f"**状态**：{status} · **耗时**：{item.get('duration_ms', 0)}ms"
        )
        hints = labels.get("arguments_hint") or []
        if hints:
            lines.append("- **入参摘要**：")
            for h in hints:
                lines.append(f"  - {h.get('label', h.get('key'))}：`{h.get('value', '')}`")
        lines.append("")
        lines.append("入参（原始 JSON）：")
        lines.append("```json")
        lines.append(json.dumps(item.get("arguments") or {}, ensure_ascii=False, indent=2))
        lines.append("```")
        lines.append("结果（原始 JSON）：")
        lines.append("```json")
        lines.append(json.dumps(item.get("result"), ensure_ascii=False, indent=2))
        lines.append("```")
        lines.append("")
    return "\n".join(lines)


@router.get("/tool-calls")
async def list_audits(
    workspace_id: str | None = None,
    standalone: bool = False,
    session_id: str | None = None,
    name: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    db: aiosqlite.Connection = Depends(db_dep),
):
    sql = "SELECT * FROM tool_call_audits WHERE 1=1"
    params: list = []
    clause, scope_params = workspace_scope_clause(workspace_id=workspace_id, standalone=standalone)
    sql += clause
    params.extend(scope_params)
    if session_id:
        sql += " AND session_id=?"
        params.append(session_id)
    if name:
        sql += " AND name=?"
        params.append(name)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    cur = await db.execute(sql, params)
    rows = await cur.fetchall()
    items = await enrich_audit_records(db, rows)
    return {"items": items}


@router.get("/tool-calls/{audit_id}")
async def get_audit(audit_id: str, db: aiosqlite.Connection = Depends(db_dep)):
    cur = await db.execute("SELECT * FROM tool_call_audits WHERE id=?", (audit_id,))
    r = await cur.fetchone()
    if not r:
        raise HTTPException(404, detail={"code": "not_found", "message": "audit not found"})
    items = await enrich_audit_records(db, [r])
    return items[0]


@router.post("/tool-calls/export")
async def export_audits(body: ExportBody, db: aiosqlite.Connection = Depends(db_dep)):
    sql = "SELECT * FROM tool_call_audits"
    params: list = []
    where, scope_params = workspace_scope_where(workspace_id=body.workspace_id, standalone=body.standalone)
    sql += where
    params.extend(scope_params)
    sql += " ORDER BY created_at DESC LIMIT 500"
    cur = await db.execute(sql, params)
    rows = await cur.fetchall()
    enriched = await enrich_audit_records(db, rows)
    if body.format == "json":
        return PlainTextResponse(
            json.dumps(enriched, ensure_ascii=False, indent=2),
            media_type="application/json",
        )
    return PlainTextResponse(_format_export_markdown(enriched), media_type="text/markdown")
