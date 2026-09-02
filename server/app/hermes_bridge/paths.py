"""
Hermes 路径：仅使用仓库内 vendored 源码。

源码位于 personal-super-assistant/third_party/hermes-agent（从 Hermes Agent
拷贝的 MIT 代码），打包时随 sidecar / 安装包分发，不依赖本机外部路径。
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from app.core.config import resource_root, settings

logger = logging.getLogger(__name__)

_path_ready = False


def project_root() -> Path:
    """personal-super-assistant 根目录；打包态为 PyInstaller _MEIPASS。"""
    return resource_root()


def hermes_root() -> Path:
    """仓库内 / 打包内 vendored Hermes 根（含 model_tools.py / tools/）。"""
    return (project_root() / "third_party" / "hermes-agent").resolve()


# 兼容旧测试名
DEFAULT_HERMES_ROOT = hermes_root


def hermes_home() -> Path:
    """运行时数据目录（配置/缓存），不是源码路径。"""
    home = settings.data_dir / "hermes_home"
    home.mkdir(parents=True, exist_ok=True)
    (home / "skills").mkdir(parents=True, exist_ok=True)
    (home / "cache").mkdir(parents=True, exist_ok=True)
    return home


def project_skills_dir() -> Path:
    """赛题内置技能目录（挂到 Hermes external_dirs）。"""
    if settings.skills_dir:
        return Path(settings.skills_dir).resolve()
    # 开发态：项目根/skills；打包态：_MEIPASS/skills 或数据目录旁
    root = project_root()
    cand = root / "skills"
    if cand.is_dir():
        return cand.resolve()
    # sidecar 旁可能未带 skills；回退到源码布局（开发）
    return (project_root() / "skills").resolve()


def hermes_exists() -> bool:
    root = hermes_root()
    return root.is_dir() and (root / "model_tools.py").is_file() and (root / "tools").is_dir()


def diagnose_missing_deps() -> list[str]:
    """探测常用模块；返回缺失包名。"""
    if not hermes_exists():
        return ["vendored_hermes"]
    missing: list[str] = []
    root = str(hermes_root())
    if root not in sys.path:
        sys.path.insert(0, root)
    for mod, pkg in (
        ("model_tools", "vendored hermes-agent"),
        ("yaml", "pyyaml"),
        ("tenacity", "tenacity"),
        ("rich", "rich"),
    ):
        try:
            __import__(mod)
        except Exception:  # noqa: BLE001
            missing.append(pkg)
    return missing


def ensure_hermes_on_syspath() -> bool:
    """
    将仓库内 third_party/hermes-agent 插入 sys.path，并设置 HERMES_HOME。
    """
    global _path_ready
    if _path_ready and hermes_exists():
        return True
    if not hermes_exists():
        logger.warning("Vendored Hermes missing: %s", hermes_root())
        return False

    root = str(hermes_root())
    if root not in sys.path:
        sys.path.insert(0, root)

    home = hermes_home()
    os.environ["HERMES_HOME"] = str(home)
    _ensure_minimal_config(home)

    _path_ready = True
    logger.info("Vendored Hermes on sys.path: root=%s home=%s", root, home)
    return True


def _ensure_minimal_config(home: Path) -> None:
    import yaml

    cfg_path = home / "config.yaml"
    skills_ext = str(project_skills_dir())
    data: dict = {}
    if cfg_path.exists():
        try:
            loaded = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
            if isinstance(loaded, dict):
                data = loaded
        except Exception:  # noqa: BLE001
            data = {}

    skills = data.setdefault("skills", {})
    if not isinstance(skills, dict):
        skills = {}
        data["skills"] = skills
    dirs = list(skills.get("external_dirs") or [])
    if skills_ext not in dirs:
        dirs.append(skills_ext)
    skills["external_dirs"] = dirs
    data.setdefault("mcp_servers", data.get("mcp_servers") or {})

    cfg_path.write_text(
        yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
