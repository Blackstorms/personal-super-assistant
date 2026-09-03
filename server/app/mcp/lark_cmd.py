"""解析飞书 lark-mcp 启动命令：本地/全局优先，回退 npx。"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

_LARK_PKG = "@larksuiteoapi/lark-mcp"
_LARK_ARGS_CORE = [
    "mcp",
    "-t",
    "preset.im.default,preset.task.default,contact.v3.user.batchGetId",
    "-l",
    "zh",
    "--oauth",
    "--token-mode",
    "user_access_token",
]


def project_root() -> Path:
    # server/app/mcp/lark_cmd.py → parents[3] = repo root
    return Path(__file__).resolve().parents[3]


def local_lark_mcp_bin() -> Path | None:
    root = project_root()
    candidates = [
        root / "tools" / "mcp" / "node_modules" / ".bin" / "lark-mcp",
        root / "tools" / "mcp" / "node_modules" / ".bin" / "lark-mcp.cmd",
    ]
    if sys.platform == "win32":
        candidates.insert(0, root / "tools" / "mcp" / "node_modules" / ".bin" / "lark-mcp.cmd")
    for p in candidates:
        if p.is_file():
            return p
    return None


def which_lark_mcp() -> str | None:
    local = local_lark_mcp_bin()
    if local is not None:
        return str(local)
    found = shutil.which("lark-mcp")
    return found


def feishu_preset_command_args() -> tuple[str, list[str]]:
    """预置默认：能找到二进制用 lark-mcp，否则仍写 npx（兼容未预装环境）。"""
    if which_lark_mcp():
        return "lark-mcp", list(_LARK_ARGS_CORE)
    return "npx", ["-y", _LARK_PKG, *_LARK_ARGS_CORE]


def strip_npx_lark_wrapper(args: list) -> list[str]:
    """去掉 npx -y @larksuiteoapi/lark-mcp 包装，保留 mcp 子命令参数。"""
    out: list[str] = []
    skip_next_pkg = False
    for a in args:
        s = str(a)
        if skip_next_pkg:
            skip_next_pkg = False
            continue
        if s in ("-y", "--yes"):
            continue
        if s == _LARK_PKG or s.startswith(f"{_LARK_PKG}@"):
            continue
        out.append(s)
    if not out or out[0] != "mcp":
        # 旧包可能没有 mcp 子命令
        if "mcp" not in out:
            out = ["mcp", *out]
    return out


def resolve_stdio_launch(command: str, args: list) -> tuple[str, list[str]]:
    """
    启动时解析：
    - npx + lark-mcp 包 → 优先本地/全局 lark-mcp
    - command=lark-mcp 但 PATH 无 → 回退 npx -y
    """
    cmd = (command or "").strip()
    raw_args = [str(a) for a in (args or [])]
    joined = " ".join(raw_args)
    is_lark = cmd == "lark-mcp" or _LARK_PKG in joined or "lark-mcp" in joined

    if not is_lark:
        return cmd, raw_args

    bin_path = which_lark_mcp()
    core = strip_npx_lark_wrapper(raw_args) if cmd == "npx" else (
        raw_args if raw_args and raw_args[0] == "mcp" else list(_LARK_ARGS_CORE)
    )
    # 若已是 lark-mcp 但 args 仍带 -y/包名，同样剥掉
    if cmd == "lark-mcp" and (_LARK_PKG in joined or "-y" in raw_args):
        core = strip_npx_lark_wrapper(raw_args)

    if bin_path:
        # Windows .cmd 可直接作 command；Unix 用绝对路径更稳
        return bin_path if os.path.sep in bin_path or bin_path.endswith(".cmd") else bin_path, core

    # 无预装：回退 npx（仍可能慢，但可用）
    if cmd == "npx" and _LARK_PKG in joined:
        return "npx", raw_args
    return "npx", ["-y", _LARK_PKG, *core]
