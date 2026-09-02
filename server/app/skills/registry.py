"""
技能注册表：扫描 skills/*/SKILL.md 并写入 SQLite。

SKILL.md 约定（YAML frontmatter + Markdown 正文）：
---
name: xxx
description: ...
triggers: [a, b]
permissions: [fs_read]   # 或 allowed-tools（deer-flow 兼容）
version: "1.0"
---
正文说明...

渐进加载（对齐 deer-flow SkillActivation / skill index）：
- system 只注入技能目录元数据
- Agent 用 describe_skill 按需加载全文
- 用户消息 `/skill-id ...` 可强制注入全文 reminder
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

import aiosqlite
import yaml

from app.core.config import resource_root, settings
from app.db.database import get_db, utc_now

_FRONT_MATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.S)
# 斜杠激活：消息以 /skill-id 开头（可选后续任务文本）
_SLASH_SKILL = re.compile(r"^/([a-zA-Z0-9_-]+)(?:\s+(.*))?$", re.S)

# describe_skill 返回正文上限（字符）
DESCRIBE_BODY_MAX = 4000

_SKILL_ID = re.compile(r"^[a-zA-Z0-9_-]+$")


@dataclass
class SkillMeta:
    id: str
    name: str
    description: str
    triggers: list[str]
    permissions: list[str]
    skill_path: str
    body: str
    enabled: bool = True
    version: str = "1.0"


@dataclass
class SlashActivation:
    """斜杠激活结果：剥离后的用户文本 + 注入的技能全文 reminder。"""

    skill_id: str
    remaining_content: str
    reminder: str
    permissions: list[str]


class SkillRegistry:
    """进程内技能缓存 + DB 同步。"""

    def __init__(self, skills_dir: Path | None = None):
        self.skills_dir = skills_dir or settings.skills_dir or (resource_root() / "skills")
        self._cache: dict[str, SkillMeta] = {}

    def _parse_permissions(self, meta: dict) -> list[str]:
        """permissions 与 deer-flow 风格 allowed-tools 合并。"""
        perms: list[str] = []
        raw_perms = meta.get("permissions")
        if isinstance(raw_perms, list):
            perms.extend(str(x).strip() for x in raw_perms if str(x).strip())
        raw_allowed = meta.get("allowed-tools") or meta.get("allowed_tools")
        if isinstance(raw_allowed, list):
            for x in raw_allowed:
                s = str(x).strip()
                if s and s not in perms:
                    perms.append(s)
        return perms

    def _slug_skill_id(self, name: str) -> str:
        slug = re.sub(r"[^\w\-]", "-", name.strip().lower())
        slug = re.sub(r"-+", "-", slug).strip("-")
        return slug[:64] if slug else ""

    def parse_skill_content(
        self,
        text: str,
        *,
        skill_id: str | None = None,
        fallback_id: str | None = None,
    ) -> SkillMeta:
        """从 SKILL.md 文本解析技能（YAML frontmatter + Markdown 正文）。"""
        m = _FRONT_MATTER.match(text.strip())
        if not m:
            raise ValueError("无效 SKILL.md：缺少 YAML frontmatter（文件需以 --- 开头）")
        meta_dict = yaml.safe_load(m.group(1)) or {}
        if not isinstance(meta_dict, dict):
            raise ValueError("frontmatter 必须是 YAML 对象")
        body = m.group(2).strip()

        fb = (fallback_id or "").strip()
        if fb.lower() in ("skill", "skill.md"):
            fb = ""
        sid = (skill_id or fb or self._slug_skill_id(str(meta_dict.get("name") or ""))).strip()
        if not sid:
            raise ValueError("无法确定技能 ID：请设置 name 或使用可识别的文件名")
        self._validate_skill_id(sid)

        return SkillMeta(
            id=sid,
            name=str(meta_dict.get("name") or sid),
            description=str(meta_dict.get("description") or ""),
            triggers=list(meta_dict.get("triggers") or []),
            permissions=self._parse_permissions(meta_dict),
            skill_path=str(self.skills_dir / sid),
            body=body,
            version=str(meta_dict.get("version") or "1.0"),
        )

    def _parse_skill(self, skill_id: str, path: Path) -> SkillMeta | None:
        text = path.read_text(encoding="utf-8")
        m = _FRONT_MATTER.match(text)
        if not m:
            return None
        meta = yaml.safe_load(m.group(1)) or {}
        body = m.group(2).strip()
        return SkillMeta(
            id=skill_id,
            name=str(meta.get("name") or skill_id),
            description=str(meta.get("description") or ""),
            triggers=list(meta.get("triggers") or []),
            permissions=self._parse_permissions(meta if isinstance(meta, dict) else {}),
            skill_path=str(path.parent),
            body=body,
            version=str(meta.get("version") or "1.0"),
        )

    def _serialize_skill(self, meta: SkillMeta) -> str:
        front = {
            "name": meta.name,
            "description": meta.description,
            "triggers": meta.triggers,
            "permissions": meta.permissions,
            "version": meta.version,
        }
        yaml_str = yaml.dump(front, allow_unicode=True, default_flow_style=False, sort_keys=False).strip()
        body = meta.body.strip()
        return f"---\n{yaml_str}\n---\n{body}\n"

    def _validate_skill_id(self, skill_id: str) -> None:
        if not _SKILL_ID.fullmatch(skill_id):
            raise ValueError("skill id 仅允许字母、数字、下划线与连字符")

    async def _upsert_db(self, db: aiosqlite.Connection, meta: SkillMeta) -> None:
        await db.execute(
            """
            INSERT INTO skills(id, name, description, triggers_json, permissions_json, skill_path, enabled, version, updated_at)
            VALUES(?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
              name=excluded.name,
              description=excluded.description,
              triggers_json=excluded.triggers_json,
              permissions_json=excluded.permissions_json,
              skill_path=excluded.skill_path,
              enabled=excluded.enabled,
              version=excluded.version,
              updated_at=excluded.updated_at
            """,
            (
                meta.id,
                meta.name,
                meta.description,
                json.dumps(meta.triggers, ensure_ascii=False),
                json.dumps(meta.permissions, ensure_ascii=False),
                meta.skill_path,
                1 if meta.enabled else 0,
                meta.version,
                utc_now(),
            ),
        )

    async def create_skill(
        self,
        db: aiosqlite.Connection,
        *,
        skill_id: str,
        name: str,
        description: str = "",
        triggers: list[str] | None = None,
        permissions: list[str] | None = None,
        body: str = "",
        version: str = "1.0",
        enabled: bool = True,
    ) -> SkillMeta:
        self._validate_skill_id(skill_id)
        if self.get(skill_id) or (self.skills_dir / skill_id).exists():
            raise ValueError(f"技能已存在: {skill_id}")
        skill_dir = self.skills_dir / skill_id
        meta = SkillMeta(
            id=skill_id,
            name=name.strip() or skill_id,
            description=description.strip(),
            triggers=list(triggers or []),
            permissions=list(permissions or []),
            skill_path=str(skill_dir),
            body=body.strip(),
            enabled=enabled,
            version=version.strip() or "1.0",
        )
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(self._serialize_skill(meta), encoding="utf-8")
        self._cache[skill_id] = meta
        await self._upsert_db(db, meta)
        await db.commit()
        return meta

    def _write_extra_files(self, skill_dir: Path, extra_files: dict[str, str | bytes] | None) -> None:
        """写入 SKILL.md 以外的附属文件；拒绝路径穿越。"""
        if not extra_files:
            return
        root = skill_dir.resolve()
        for rel, data in extra_files.items():
            rel_path = Path(str(rel))
            if rel_path.is_absolute() or ".." in rel_path.parts:
                continue
            if rel_path.name in {"SKILL.md", "skill.md"}:
                continue
            dest = (skill_dir / rel_path).resolve()
            try:
                dest.relative_to(root)
            except ValueError:
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(data, bytes):
                dest.write_bytes(data)
            else:
                dest.write_text(str(data), encoding="utf-8")

    async def import_from_markdown(
        self,
        db: aiosqlite.Connection,
        *,
        content: str,
        skill_id: str | None = None,
        fallback_id: str | None = None,
        extra_files: dict[str, str | bytes] | None = None,
        enabled: bool = True,
    ) -> SkillMeta:
        """从 SKILL.md 文本导入为本地技能，并可附带同包文件。"""
        meta = self.parse_skill_content(content, skill_id=skill_id, fallback_id=fallback_id)
        created = await self.create_skill(
            db,
            skill_id=meta.id,
            name=meta.name,
            description=meta.description,
            triggers=meta.triggers,
            permissions=meta.permissions,
            body=meta.body,
            version=meta.version,
            enabled=enabled,
        )
        self._write_extra_files(Path(created.skill_path), extra_files)
        return created

    async def update_skill(
        self,
        db: aiosqlite.Connection,
        skill_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        triggers: list[str] | None = None,
        permissions: list[str] | None = None,
        body: str | None = None,
        version: str | None = None,
        enabled: bool | None = None,
    ) -> SkillMeta:
        existing = self.get(skill_id)
        if not existing:
            skill_md = self.skills_dir / skill_id / "SKILL.md"
            if skill_md.exists():
                existing = self._parse_skill(skill_id, skill_md)
            if not existing:
                raise ValueError(f"技能不存在: {skill_id}")
        meta = SkillMeta(
            id=skill_id,
            name=name if name is not None else existing.name,
            description=description if description is not None else existing.description,
            triggers=triggers if triggers is not None else list(existing.triggers),
            permissions=permissions if permissions is not None else list(existing.permissions),
            skill_path=existing.skill_path,
            body=body if body is not None else existing.body,
            enabled=enabled if enabled is not None else existing.enabled,
            version=version if version is not None else existing.version,
        )
        (Path(meta.skill_path) / "SKILL.md").write_text(self._serialize_skill(meta), encoding="utf-8")
        self._cache[skill_id] = meta
        await self._upsert_db(db, meta)
        await db.commit()
        return meta

    async def delete_skill(self, db: aiosqlite.Connection, skill_id: str) -> bool:
        existing = self.get(skill_id)
        if not existing:
            cur = await db.execute("SELECT skill_path FROM skills WHERE id=?", (skill_id,))
            row = await cur.fetchone()
            if not row:
                return False
            skill_path = row["skill_path"]
        else:
            skill_path = existing.skill_path

        await db.execute("DELETE FROM skills WHERE id=?", (skill_id,))
        await db.commit()
        self._cache.pop(skill_id, None)

        if skill_path:
            path = Path(skill_path)
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            elif path.is_file():
                path.unlink(missing_ok=True)
        return True

    async def reload(self) -> int:
        """扫描磁盘并 upsert 到 skills 表。"""
        self._cache.clear()
        if not self.skills_dir.exists():
            return 0
        loaded = 0
        db = await get_db()
        try:
            for child in sorted(self.skills_dir.iterdir()):
                skill_md = child / "SKILL.md"
                if not child.is_dir() or not skill_md.exists():
                    continue
                meta = self._parse_skill(child.name, skill_md)
                if not meta:
                    continue
                # 保留用户对 enabled 的修改
                cur = await db.execute("SELECT enabled FROM skills WHERE id=?", (meta.id,))
                row = await cur.fetchone()
                enabled = True if row is None else bool(row["enabled"])
                meta.enabled = enabled
                self._cache[meta.id] = meta
                await self._upsert_db(db, meta)
                loaded += 1
            await db.commit()
        finally:
            await db.close()
        return loaded

    def list_enabled(self, allowed_ids: set[str] | None = None) -> list[SkillMeta]:
        enabled = [s for s in self._cache.values() if s.enabled]
        if allowed_ids is None:
            return enabled
        return [s for s in enabled if s.id in allowed_ids]

    def get(self, skill_id: str) -> SkillMeta | None:
        return self._cache.get(skill_id)

    def match(
        self,
        query: str,
        top_k: int = 5,
        allowed_ids: set[str] | None = None,
    ) -> list[tuple[SkillMeta, float]]:
        """粗匹配：触发词包含或描述关键字命中则加分。"""
        q = query.lower()
        # 去掉可能的斜杠前缀再匹配
        slash = _SLASH_SKILL.match(query.strip())
        if slash:
            q = (slash.group(2) or "").lower()
        scored: list[tuple[SkillMeta, float]] = []
        for skill in self.list_enabled(allowed_ids):
            score = 0.0
            for t in skill.triggers:
                if t.lower() in q:
                    score += 2.0
            for token in re.split(r"\W+", skill.description.lower()):
                if token and token in q:
                    score += 0.5
            if skill.name.lower() in q:
                score += 1.5
            if score > 0:
                scored.append((skill, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    def catalog_prompt(self, allowed_ids: set[str] | None = None) -> str:
        """
        技能目录（仅元数据，对齐 deer-flow progressive / deferred discovery）。
        全文须通过 describe_skill 或 /skill-id 加载。
        """
        enabled = self.list_enabled(allowed_ids)
        if not enabled:
            return "可用技能：（暂无）"
        lines = [
            "可用技能（需要时用 describe_skill 加载完整 SKILL.md；",
            "用户也可在消息里用 /skill-id 强制加载）：",
        ]
        for s in enabled:
            triggers = ", ".join(s.triggers) if s.triggers else "-"
            lines.append(f"- /{s.id} | {s.name}: {s.description}（触发词: {triggers}）")
        return "\n".join(lines)

    def progressive_prompt(self, query: str, allowed_ids: set[str] | None = None) -> str:
        """
        渐进注入：默认只给目录；命中技能仅附加一行提示（不灌全文）。
        全文由 describe_skill 或 slash 激活加载。
        """
        catalog = self.catalog_prompt(allowed_ids)
        matched = self.match(query, allowed_ids=allowed_ids)
        if not matched:
            return catalog
        hints = [
            "可能相关的技能（执行流程前请先 describe_skill 加载）：",
        ]
        for skill, score in matched:
            hints.append(f"- {skill.id}（{skill.name}，相关度={score:.1f}）")
        return catalog + "\n\n" + "\n".join(hints)

    def parse_slash(
        self,
        user_content: str,
        allowed_ids: set[str] | None = None,
    ) -> SlashActivation | None:
        """解析 `/skill-id [task]`；技能不存在或未启用则返回 None。"""
        m = _SLASH_SKILL.match(user_content.strip())
        if not m:
            return None
        skill_id = m.group(1)
        if allowed_ids is not None and skill_id not in allowed_ids:
            return None
        skill = self.get(skill_id)
        if not skill or not skill.enabled:
            return None
        remaining = (m.group(2) or "").strip() or f"(Apply skill {skill_id})"
        body = skill.body[:DESCRIBE_BODY_MAX]
        reminder = (
            f"<slash_skill_activation skill=\"{skill.id}\">\n"
            f"# {skill.name}\n{skill.description}\n\n{body}\n"
            f"</slash_skill_activation>"
        )
        return SlashActivation(
            skill_id=skill.id,
            remaining_content=remaining,
            reminder=reminder,
            permissions=list(skill.permissions),
        )

    def describe(self, skill_id: str, allowed_ids: set[str] | None = None) -> dict:
        """describe_skill 工具：返回截断后的技能正文。"""
        if allowed_ids is not None and skill_id not in allowed_ids:
            return {"error": f"skill not allowed in this session: {skill_id}"}
        skill = self.get(skill_id)
        if not skill or not skill.enabled:
            return {"error": f"skill not found or disabled: {skill_id}"}
        return {
            "skill_id": skill.id,
            "name": skill.name,
            "description": skill.description,
            "permissions": skill.permissions,
            "body": skill.body[:DESCRIBE_BODY_MAX],
            "truncated": len(skill.body) > DESCRIBE_BODY_MAX,
        }

    def filter_tools_for_permissions(
        self,
        tools: list[dict],
        permissions: list[str] | None,
    ) -> list[dict]:
        """
        斜杠激活时按 allowed-tools/permissions 收紧工具面。
        permissions 为空：不额外限制。
        非空：保留名单内工具 + describe_skill / run_skill。
        """
        if not permissions:
            return tools
        allowed = set(permissions)
        allowed.update({"describe_skill", "run_skill"})
        # 声明了任意 fs_* 时，允许同组只读工具
        if "fs_read" in allowed or "fs_list" in allowed:
            allowed.update({"fs_read", "fs_list"})
        out: list[dict] = []
        for t in tools:
            name = (t.get("function") or {}).get("name") or ""
            if name in allowed:
                out.append(t)
            elif name.startswith("mcp__") and ("mcp" in allowed or name in allowed):
                out.append(t)
        return out

    async def set_enabled(self, db: aiosqlite.Connection, skill_id: str, enabled: bool) -> None:
        await db.execute(
            "UPDATE skills SET enabled=?, updated_at=? WHERE id=?",
            (1 if enabled else 0, utc_now(), skill_id),
        )
        await db.commit()
        if skill_id in self._cache:
            self._cache[skill_id].enabled = enabled

    def to_openai_tools(self) -> list[dict]:
        """暴露 describe_skill（按需加载）+ run_skill（按 guidance 处理输入）。"""
        return [
            {
                "type": "function",
                "function": {
                    "name": "describe_skill",
                    "description": (
                        "按 skill_id 加载已注册技能的完整 SKILL.md 正文。"
                        "执行技能工作流前请先调用本工具。"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "skill_id": {"type": "string", "description": "技能 ID"},
                        },
                        "required": ["skill_id"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "run_skill",
                    "description": (
                        "在理解技能指引后，将本地已注册技能应用到输入文本"
                        "（除非用户已斜杠激活，否则请先 describe_skill）。"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "skill_id": {"type": "string", "description": "技能 ID"},
                            "input": {"type": "string", "description": "输入文本"},
                        },
                        "required": ["skill_id", "input"],
                    },
                },
            },
        ]
