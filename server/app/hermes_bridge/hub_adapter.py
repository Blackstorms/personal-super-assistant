"""
Hermes Skills Hub 薄封装：浏览本地 Hermes 技能、搜索 Hub、导入到 PSA 技能库。

不搬运 Hub 全部 CLI；安装优先走 Python API，失败则 subprocess 调用
`hermes skills install`。导入到 PSA 时只读取 SKILL.md（及同目录附属文件），
写入项目 skills/ 目录，不修改 Hermes 源码。
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_FRONT_MATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.S)
_SKIP_PARTS = {
    ".hub",
    ".trash",
    ".git",
    "node_modules",
    "references",
    "__pycache__",
    "tests",
    "dist",
    "vendor",
}
_LOCAL_PREFIX = "local:"
_MAX_EXTRA_FILE = 2 * 1024 * 1024


def _skill_id_from_name(name: str) -> str:
    slug = re.sub(r"[^\w\-]", "-", name.strip().lower())
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug[:64] if slug else ""


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    m = _FRONT_MATTER.match(text.strip())
    if not m:
        return {}, text.strip()
    data = yaml.safe_load(m.group(1)) or {}
    if not isinstance(data, dict):
        data = {}
    return data, m.group(2).strip()


def _skip_rel(rel: Path) -> bool:
    return any(p in _SKIP_PARTS or p.startswith(".") for p in rel.parts[:-1])


def _allowed_roots() -> list[Path]:
    from app.hermes_bridge.paths import hermes_home, hermes_root

    roots: list[Path] = []
    home = hermes_home()
    root = hermes_root()
    for p in (
        home / "skills",
        root / "skills",
        root / "optional-skills",
        root / "plugins",
    ):
        if p.is_dir():
            roots.append(p.resolve())
    return roots


def _is_allowed_local(path: Path) -> bool:
    resolved = path.resolve()
    for root in _allowed_roots():
        try:
            resolved.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def _iter_skill_mds(root: Path):
    for skill_md in root.rglob("SKILL.md"):
        try:
            rel = skill_md.relative_to(root)
        except ValueError:
            continue
        if _skip_rel(rel):
            continue
        yield skill_md


def _item_from_skill_md(skill_md: Path, source: str) -> dict[str, Any] | None:
    try:
        text = skill_md.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return None
    meta, _body = _parse_frontmatter(text)
    folder = skill_md.parent.name
    sid = _skill_id_from_name(str(meta.get("name") or folder) or folder)
    if not sid:
        sid = _skill_id_from_name(folder)
    if not sid:
        return None
    resolved = skill_md.parent.resolve()
    return {
        "id": sid,
        "name": str(meta.get("name") or sid),
        "description": str(meta.get("description") or ""),
        "source": source,
        "identifier": f"{_LOCAL_PREFIX}{resolved}",
        "skill_path": str(resolved),
        "version": str(meta.get("version") or "1.0"),
    }


def list_hermes_catalog() -> list[dict[str, Any]]:
    """扫描 vendored Hermes / HERMES_HOME 中可导入的 SKILL.md。"""
    from app.hermes_bridge.paths import hermes_home, hermes_root, project_skills_dir

    psa_skills = project_skills_dir().resolve()
    home = hermes_home()
    root = hermes_root()
    scans: list[tuple[Path, str]] = [
        (home / "skills", "hermes-home"),
        (root / "skills", "bundled"),
        (root / "optional-skills", "optional"),
        (root / "plugins", "plugin"),
    ]
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for scan_root, source in scans:
        if not scan_root.is_dir():
            continue
        try:
            resolved_root = scan_root.resolve()
        except OSError:
            continue
        if resolved_root == psa_skills:
            continue
        for skill_md in _iter_skill_mds(scan_root):
            try:
                if skill_md.parent.resolve() == psa_skills or psa_skills in skill_md.resolve().parents:
                    continue
            except OSError:
                continue
            item = _item_from_skill_md(skill_md, source)
            if not item:
                continue
            key = item["identifier"]
            if key in seen:
                continue
            seen.add(key)
            items.append(item)
    items.sort(key=lambda x: (x.get("name") or x["id"]).lower())
    return items


def resolve_hermes_skill(identifier: str) -> dict[str, Any]:
    """
    解析 Hermes 技能为可导入内容。
    本地 identifier 形如 local:/abs/path；其余视为 Hub identifier。
    """
    ident = (identifier or "").strip()
    if not ident:
        raise ValueError("缺少技能 identifier")
    if ident.startswith(_LOCAL_PREFIX):
        return _resolve_local(ident[len(_LOCAL_PREFIX) :])
    return _resolve_hub(ident)


def _collect_extra_files(source_dir: Path) -> dict[str, bytes]:
    extra: dict[str, bytes] = {}
    extra_skip = {".hub", ".trash", ".git", "node_modules", "__pycache__", "tests", "dist", "vendor"}
    for f in source_dir.rglob("*"):
        if not f.is_file():
            continue
        rel = f.relative_to(source_dir)
        if rel.name in {"SKILL.md", "skill.md"}:
            continue
        if any(p in extra_skip or p.startswith(".") for p in rel.parts):
            continue
        try:
            if f.stat().st_size > _MAX_EXTRA_FILE:
                continue
            extra[rel.as_posix()] = f.read_bytes()
        except OSError:
            continue
    return extra


def _resolve_local(raw_path: str) -> dict[str, Any]:
    source_dir = Path(raw_path)
    if not source_dir.is_dir():
        raise ValueError(f"本地 Hermes 技能目录不存在: {raw_path}")
    if not _is_allowed_local(source_dir):
        raise ValueError("拒绝导入该路径：不在 Hermes 技能目录内")
    skill_md = source_dir / "SKILL.md"
    if not skill_md.is_file():
        raise ValueError("源目录缺少 SKILL.md")
    text = skill_md.read_text(encoding="utf-8-sig")
    meta, _body = _parse_frontmatter(text)
    sid = _skill_id_from_name(str(meta.get("name") or source_dir.name) or source_dir.name)
    if not sid:
        raise ValueError("无法确定技能 ID")
    from app.hermes_bridge.paths import hermes_root

    try:
        under_plugin = source_dir.resolve().is_relative_to((hermes_root() / "plugins").resolve())
    except (OSError, ValueError):
        under_plugin = False
    extra = {} if under_plugin else _collect_extra_files(source_dir)
    return {
        "id": sid,
        "name": str(meta.get("name") or sid),
        "description": str(meta.get("description") or ""),
        "version": str(meta.get("version") or "1.0"),
        "content": text,
        "extra_files": extra,
        "source": "local",
        "identifier": f"{_LOCAL_PREFIX}{source_dir.resolve()}",
    }


def _resolve_hub(identifier: str) -> dict[str, Any]:
    from app.hermes_bridge.paths import ensure_hermes_on_syspath

    if not ensure_hermes_on_syspath():
        raise ValueError("Hermes 不可用，无法从 Hub 拉取技能")

    try:
        from tools.skills_hub import create_source_router  # type: ignore
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"无法加载 Hermes Skills Hub: {e}") from e

    sources = create_source_router()
    bundle = None
    meta = None
    for src in sources:
        try:
            bundle = src.fetch(identifier)
        except Exception:  # noqa: BLE001
            bundle = None
        if not bundle or not getattr(bundle, "files", None):
            continue
        try:
            meta = src.inspect(identifier)
        except Exception:  # noqa: BLE001
            meta = None
        break
    if not bundle:
        raise ValueError(f"Hub 未找到技能: {identifier}")

    files = bundle.files or {}
    raw = files.get("SKILL.md") or files.get("skill.md")
    if raw is None:
        raise ValueError("Hub 技能缺少 SKILL.md")
    if isinstance(raw, bytes):
        text = raw.decode("utf-8", errors="replace")
    else:
        text = str(raw)
    fm, _body = _parse_frontmatter(text)
    name = str((meta.name if meta else None) or fm.get("name") or getattr(bundle, "name", "") or identifier)
    sid = _skill_id_from_name(name) or _skill_id_from_name(identifier.rsplit("/", 1)[-1])
    if not sid:
        raise ValueError("无法确定技能 ID")
    extra: dict[str, bytes] = {}
    for rel, data in files.items():
        if rel in {"SKILL.md", "skill.md"}:
            continue
        if isinstance(data, bytes):
            extra[str(rel)] = data
        else:
            extra[str(rel)] = str(data).encode("utf-8")
    return {
        "id": sid,
        "name": name,
        "description": str((meta.description if meta else None) or fm.get("description") or ""),
        "version": str(fm.get("version") or "1.0"),
        "content": text,
        "extra_files": extra,
        "source": str((meta.source if meta else None) or "hub"),
        "identifier": identifier,
    }


async def hub_search(query: str, limit: int = 20) -> list[dict[str, Any]]:
    """搜索 Hub（Hermes unified_search）。"""
    from app.hermes_bridge.paths import ensure_hermes_on_syspath

    q = (query or "").strip()
    if not q:
        return []
    if not ensure_hermes_on_syspath():
        return []

    def _run() -> list[dict[str, Any]]:
        try:
            from tools.skills_hub import GitHubAuth, create_source_router, unified_search  # type: ignore

            sources = create_source_router(GitHubAuth())
            raw = unified_search(q, sources, limit=limit)
            items = []
            for it in raw:
                ident = str(getattr(it, "identifier", None) or getattr(it, "name", "") or "")
                if not ident:
                    continue
                items.append(
                    {
                        "id": _skill_id_from_name(str(getattr(it, "name", None) or ident.rsplit("/", 1)[-1]))
                        or ident,
                        "name": str(getattr(it, "name", None) or ident),
                        "description": str(getattr(it, "description", None) or ""),
                        "source": str(getattr(it, "source", None) or "hub"),
                        "identifier": ident,
                        "trust_level": str(getattr(it, "trust_level", None) or ""),
                    }
                )
            return items
        except Exception as e:  # noqa: BLE001
            logger.warning("hub_search failed: %s", e)
            return [{"id": "error", "name": "error", "description": str(e), "source": "hub", "identifier": ""}]

    return await asyncio.to_thread(_run)


def _hermes_cli() -> str | None:
    from app.hermes_bridge.paths import hermes_root

    which = shutil.which("hermes")
    if which:
        return which
    root = hermes_root()
    if root:
        for name in ("hermes", "cli.py"):
            p = root / name
            if p.is_file():
                return str(p)
    return None


async def hub_install(identifier: str) -> dict[str, Any]:
    """尝试安装 Hub 技能：先 API，再 CLI subprocess。"""
    from app.hermes_bridge.paths import ensure_hermes_on_syspath, hermes_root

    if not ensure_hermes_on_syspath():
        return {"ok": False, "message": "hermes unavailable", "cli_hint": True}

    def _api() -> dict[str, Any] | None:
        try:
            import tools.skills_hub as hub  # type: ignore

            for fn_name in ("install_skill", "hub_install", "install"):
                fn = getattr(hub, fn_name, None)
                if callable(fn):
                    result = fn(identifier)
                    return {"ok": True, "result": result, "identifier": identifier, "via": "api"}
        except Exception as e:  # noqa: BLE001
            logger.debug("hub api install failed: %s", e)
        return None

    api_result = await asyncio.to_thread(_api)
    if api_result:
        return api_result

    def _cli() -> dict[str, Any]:
        cli = _hermes_cli()
        if not cli:
            return {
                "ok": False,
                "message": "skills_hub install API not found and hermes CLI missing; "
                f"run: hermes skills install {identifier}",
                "cli_hint": True,
                "identifier": identifier,
            }
        root = hermes_root()
        cmd = [cli, "skills", "install", identifier] if not cli.endswith("cli.py") else [
            os.environ.get("PYTHON", "python3"),
            cli,
            "skills",
            "install",
            identifier,
        ]
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(root) if root else None,
                capture_output=True,
                text=True,
                timeout=120,
                env={**os.environ, "HERMES_HOME": os.environ.get("HERMES_HOME", "")},
            )
            out = (proc.stdout or "") + (proc.stderr or "")
            if proc.returncode == 0:
                return {"ok": True, "result": out[-2000:], "identifier": identifier, "via": "cli"}
            return {
                "ok": False,
                "message": out[-2000:] or f"exit {proc.returncode}",
                "identifier": identifier,
                "via": "cli",
                "cli_hint": True,
            }
        except subprocess.TimeoutExpired:
            return {"ok": False, "message": "hermes skills install timed out (120s)", "cli_hint": True}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "message": str(e), "cli_hint": True, "identifier": identifier}

    return await asyncio.to_thread(_cli)
