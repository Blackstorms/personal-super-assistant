"""加载运行时 .env（开发态 server/.env，打包态用户数据目录）。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

SEARCH_ENV_NAMES = (
    "PSA_WEB_SEARCH_PROVIDER",
    "PSA_WEB_SEARCH_API_URL",
    "PSA_WEB_SEARCH_API_KEY",
    "TAVILY_API_KEY",
    "PSA_WEB_SEARCH_TRUST_ENV",
    "PSA_LLM_THINKING",
    "PSA_LLM_REASONING_EFFORT",
)


def extra_gui_path_dirs() -> list[Path]:
    """Finder/开始菜单启动时系统 PATH 很短，补上常见 Node/uv 安装位置。"""
    home = Path.home()
    dirs: list[Path] = []
    if sys.platform == "darwin":
        dirs.extend(
            [
                Path("/opt/homebrew/bin"),
                Path("/usr/local/bin"),
                home / ".local" / "bin",
                home / ".nvm" / "current" / "bin",
            ]
        )
        nvm = home / ".nvm" / "versions" / "node"
        if nvm.is_dir():
            versions = sorted((p for p in nvm.iterdir() if p.is_dir()), reverse=True)
            if versions:
                dirs.append(versions[0] / "bin")
    elif sys.platform == "win32":
        pf = Path(os.environ.get("ProgramFiles") or r"C:\Program Files")
        pf86 = Path(os.environ.get("ProgramFiles(x86)") or r"C:\Program Files (x86)")
        local = Path(os.environ.get("LOCALAPPDATA") or (home / "AppData" / "Local"))
        roaming = Path(os.environ.get("APPDATA") or (home / "AppData" / "Roaming"))
        dirs.extend(
            [
                pf / "nodejs",
                pf86 / "nodejs",
                roaming / "npm",
                local / "Programs" / "nodejs",
                home / ".local" / "bin",
            ]
        )
    else:
        dirs.extend([Path("/usr/local/bin"), home / ".local" / "bin"])
    return [p for p in dirs if p.is_dir()]


def ensure_gui_path() -> str:
    """把 Homebrew / nvm / Node 安装目录前置进 PATH，返回新 PATH。"""
    current = os.environ.get("PATH") or ""
    parts = [p for p in current.split(os.pathsep) if p]
    for extra in reversed(extra_gui_path_dirs()):
        s = str(extra)
        if s not in parts:
            parts.insert(0, s)
    merged = os.pathsep.join(parts)
    os.environ["PATH"] = merged
    return merged


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False)) or bool(getattr(sys, "_MEIPASS", None))


def default_data_dir() -> Path:
    raw = (os.environ.get("PSA_DATA_DIR") or "").strip()
    if raw:
        return Path(raw)
    return Path.home() / ".personal-super-assistant"


def env_file_candidates() -> list[Path]:
    """按优先级列出 .env 候选；已存在的环境变量不会被覆盖。"""
    out: list[Path] = []
    data = default_data_dir() / ".env"
    out.append(data)
    if not _is_frozen():
        # server/app/core/env_load.py → server/.env
        out.append(Path(__file__).resolve().parents[2] / ".env")
    return out


def _ensure_frozen_certs() -> None:
    """PyInstaller 冻结后补上 certifi CA，避免 https 握手失败。"""
    if not _is_frozen():
        return
    try:
        import certifi

        ca = certifi.where()
        if ca and Path(ca).is_file():
            os.environ.setdefault("SSL_CERT_FILE", ca)
            os.environ.setdefault("REQUESTS_CA_BUNDLE", ca)
    except Exception:  # noqa: BLE001
        return


def load_runtime_env() -> list[Path]:
    """加载候选 .env（override=False），返回实际读到的文件。"""
    _ensure_frozen_certs()
    ensure_gui_path()
    loaded: list[Path] = []
    for path in env_file_candidates():
        if path.is_file():
            load_dotenv(path, override=False)
            loaded.append(path)
    return loaded


def persist_search_env(data_dir: Path | None = None, *, overwrite: bool = False) -> Path | None:
    """把进程内搜索相关环境变量写入 data_dir/.env。

    overwrite=False：只补缺失键（开发态同步到打包目录）。
    overwrite=True：设置页保存时覆盖已有键。
    """
    updates = {k: (os.environ.get(k) or "").strip() for k in SEARCH_ENV_NAMES}
    updates = {k: v for k, v in updates.items() if v}
    if not updates:
        return None
    target = (data_dir or default_data_dir()) / ".env"
    target.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, str] = {}
    others: list[str] = []
    if target.is_file():
        for line in target.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                others.append(line)
                continue
            key, _, val = stripped.partition("=")
            key = key.strip()
            if key in SEARCH_ENV_NAMES:
                existing[key] = val.strip().strip('"').strip("'")
            else:
                others.append(line)
    merged = dict(existing)
    for key, val in updates.items():
        if overwrite or key not in merged:
            merged[key] = val
    if merged == existing and target.is_file():
        return target
    body: list[str] = []
    if others:
        body.extend(others)
        if others[-1].strip():
            body.append("")
    for key in SEARCH_ENV_NAMES:
        if key in merged:
            body.append(f"{key}={merged[key]}")
    target.write_text("\n".join(body).rstrip() + "\n", encoding="utf-8")
    return target
