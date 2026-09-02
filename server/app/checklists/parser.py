"""对话 → 任务清单解析；仅保留待办 / 提醒等可执行项。"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid

import aiosqlite

from app.db.database import utc_now

logger = logging.getLogger(__name__)

_CHECKBOX = re.compile(r"^\s*[-*]\s+\[([ xX])\]\s+(.+)$")
_BULLET = re.compile(r"^\s*[-*]\s+(.+)$")
_NUMBERED = re.compile(r"^\s*\d+[\.\)、]\s*(.+)$")

_HEADING = re.compile(r"^\s{0,3}#{1,3}\s+(.+)$")
_TITLE_PREFIX = re.compile(
    r"^\s*(?:清单|待办|任务|Todo|TODO|Checklist|计划|步骤|提醒|下一步)[:：\s]*(.+)$",
    re.I,
)

# 段落标题：命中则该段下列表更偏向纳入
_SECTION_TODO = re.compile(
    r"(待办|任务|清单|todo|checklist|提醒|下一步|action\s*items?|to-?do|跟进|计划)",
    re.I,
)
# 明显非待办段落
_SECTION_SKIP = re.compile(
    r"(总结|结论|背景|分析|原因|优缺点|对比|说明|注意|参考|摘要|概述|答疑|问答)",
    re.I,
)

_ACTION_VERBS = re.compile(
    r"^(?:"
    r"完成|实现|编写|撰写|写|发|发送|回复|更新|修改|修复|检查|确认|核实|联系|通知|"
    r"准备|提交|合并|部署|发布|测试|验证|同步|整理|归档|备份|删除|添加|新增|创建|"
    r"开会|约|安排|处理|跟进|催|购买|下单|安装|配置|接入|接入|对接|迁移|重构|"
    r"review|fix|add|update|send|check|call|schedule|deploy|test|merge|create|"
    r"write|reply|remind|follow\s*up|investigate|implement"
    r")",
    re.I,
)

_REMINDER_HINT = re.compile(
    r"(记得|别忘|提醒|截止|ddl|deadline|明天|后天|下周|本周|今日|今晚|"
    r"asap|urgent|优先级|p[0-2]\b|todo|待办|需要|必须|务必)",
    re.I,
)

_NOISE = re.compile(
    r"^(?:"
    r"例如|比如|如下|如上|总之|综上|因此|所以|因为|如果|当|在于|包括|以及|"
    r"首先|其次|再次|最后|另外|此外|注[：:]|说明[：:]|注意[：:]|提示[：:]|"
    r"优点|缺点|背景|结论|摘要|总结"
    r")",
    re.I,
)

TITLE_PROMPT = """根据用户意图与待办条目，生成一个简短的中文清单标题。
要求：6-20字，概括这份清单要完成的主题，不要「清单」「待办」等套话，不要标点与引号，只输出标题本身。"""


def _strip_markdown_noise(content: str) -> str:
    c = content.strip()
    c = re.sub(r"^\*\*(.+)\*\*$", r"\1", c)
    c = re.sub(r"^`(.+)`$", r"\1", c)
    return c.strip()


def is_actionable_item(content: str, *, in_todo_section: bool = False) -> bool:
    """
    判断是否应列入任务清单：
    - 明确 checkbox 待办优先（调用方已处理）
    - 动词开头 / 含提醒·截止语义 / 位于「待办」类章节下的短动作句
    - 排除说明、分析、总结等非执行项
    """
    c = _strip_markdown_noise(content)
    if not c or len(c) < 2 or len(c) > 200:
        return False
    if _NOISE.match(c):
        return False
    # 纯名词解释 / 过长论述
    if "：" in c[:8] and not _ACTION_VERBS.match(c) and not _REMINDER_HINT.search(c):
        # 「负责人：张三」可保留；「原因：……」跳过
        head = c.split("：", 1)[0]
        if head in {"原因", "背景", "说明", "注意", "结论", "摘要", "优点", "缺点"}:
            return False
    if _ACTION_VERBS.match(c) or _REMINDER_HINT.search(c):
        return True
    if in_todo_section and len(c) <= 80 and not c.endswith(("。", "！", "？", ".", "!", "?")):
        # 待办章节下的短句（无句号收尾的动作短语）
        return True
    if in_todo_section and len(c) <= 60:
        return True
    return False


def parse_checklist_items(text: str) -> list[str]:
    """从助手回复中提取可执行待办 / 提醒项，过滤无关列表。"""
    items: list[str] = []
    in_todo_section = False
    in_skip_section = False

    for line in (text or "").splitlines():
        hm = _HEADING.match(line)
        if hm:
            title = hm.group(1).strip()
            in_todo_section = bool(_SECTION_TODO.search(title))
            in_skip_section = bool(_SECTION_SKIP.search(title)) and not in_todo_section
            continue

        pm = _TITLE_PREFIX.match(line.strip())
        if pm and not any(p.match(line) for p in (_CHECKBOX, _BULLET, _NUMBERED)):
            # 「待办：xxx」整行作章节提示
            in_todo_section = True
            in_skip_section = False
            rest = pm.group(1).strip()
            if rest and is_actionable_item(rest, in_todo_section=True):
                items.append(_strip_markdown_noise(rest))
            continue

        if in_skip_section:
            continue

        m = _CHECKBOX.match(line)
        if m:
            content = _strip_markdown_noise(m.group(2))
            # checkbox 默认视为待办；空内容跳过
            if content and len(content) < 500:
                items.append(content)
            continue

        m = _BULLET.match(line) or _NUMBERED.match(line)
        if m:
            content = _strip_markdown_noise(m.group(1))
            # 误把 checkbox 残行当 bullet 时已在上面处理
            if content.startswith("[") and "]" in content[:4]:
                continue
            if is_actionable_item(content, in_todo_section=in_todo_section):
                items.append(content)
            continue

    seen: set[str] = set()
    out: list[str] = []
    for i in items:
        key = i.casefold()
        if key not in seen:
            seen.add(key)
            out.append(i)
    return out


def sanitize_title(raw: str) -> str:
    t = (raw or "").strip().strip("\"'""''「」《》")
    t = re.sub(r"\s+", " ", t.replace("\n", " ")).strip()
    t = re.sub(r"[。.!！?？:：;；]+$", "", t)
    if len(t) > 40:
        t = t[:40]
    return t


def fallback_title_from_text(
    assistant_content: str,
    items: list[str],
    *,
    user_content: str | None = None,
) -> str:
    """
    规则标题（无 LLM 时）：
    1) 助手正文里清单前的标题行 / Markdown 标题
    2) 用户问题首行提炼
    3) 前几条清单项语义压缩
    """
    lines = (assistant_content or "").splitlines()
    list_pats = (_CHECKBOX, _BULLET, _NUMBERED)
    first_item_idx = None
    for i, line in enumerate(lines):
        if any(p.match(line) for p in list_pats):
            first_item_idx = i
            break

    if first_item_idx is not None:
        for j in range(first_item_idx - 1, max(-1, first_item_idx - 6), -1):
            raw = lines[j].strip()
            if not raw:
                continue
            hm = _HEADING.match(raw)
            if hm:
                t = sanitize_title(hm.group(1))
                if len(t) >= 2:
                    return t
            pm = _TITLE_PREFIX.match(raw)
            if pm:
                t = sanitize_title(pm.group(1))
                if len(t) >= 2:
                    return t
            if len(raw) <= 30 and not any(p.match(raw) for p in list_pats):
                t = sanitize_title(raw)
                if len(t) >= 2:
                    return t
            break

    if user_content:
        u = user_content.strip().split("\n")[0].strip()
        u = re.sub(r"^[/\\]\S+\s*", "", u)
        u = sanitize_title(u)
        for noise in ("帮我", "请帮我", "请", "生成", "列出", "整理"):
            if u.startswith(noise):
                u = u[len(noise) :].lstrip("，,：: ")
        if 2 <= len(u) <= 24:
            return u
        if len(u) > 24:
            return u[:24] + "…"

    if items:
        joined = "、".join(items[:3])
        joined = sanitize_title(joined)
        if len(joined) > 24:
            return joined[:24] + "…"
        if len(items) == 1:
            return joined or "待办事项"
        return f"{joined}等{len(items)}项" if len(joined) <= 18 else joined

    return "对话待办"


async def generate_title_llm(
    llm,
    *,
    user_content: str | None,
    items: list[str],
    assistant_snippet: str,
) -> str:
    blob_parts = []
    if user_content:
        blob_parts.append(f"用户请求：{user_content.strip()[:300]}")
    blob_parts.append("待办条目：\n" + "\n".join(f"- {x}" for x in items[:12]))
    if assistant_snippet:
        blob_parts.append("助手上下文摘要：\n" + assistant_snippet.strip()[:400])
    resp = await llm.complete(
        [
            {"role": "system", "content": TITLE_PROMPT},
            {"role": "user", "content": "\n\n".join(blob_parts)},
        ]
    )
    title = sanitize_title(resp.get("content") or "")
    if len(title) < 2:
        return ""
    for bad in ("清单：", "标题：", "待办：", "Checklist:"):
        if title.startswith(bad):
            title = sanitize_title(title[len(bad) :])
    return title if len(title) >= 2 else ""


async def _prev_user_message(db: aiosqlite.Connection, session_id: str, before_created_at: str) -> str | None:
    cur = await db.execute(
        """
        SELECT content FROM messages
        WHERE session_id=? AND role='user' AND created_at<=?
        ORDER BY created_at DESC LIMIT 1
        """,
        (session_id, before_created_at),
    )
    row = await cur.fetchone()
    return (row["content"] if row else None) or None


async def resolve_checklist_title(
    db: aiosqlite.Connection,
    *,
    assistant_content: str,
    items: list[str],
    user_content: str | None = None,
    use_llm: bool = True,
) -> str:
    """优先 LLM 语义标题，失败则规则回退。"""
    base = fallback_title_from_text(assistant_content, items, user_content=user_content)
    if not use_llm:
        return base
    try:
        from app.agent.runtime import _load_llm

        llm = await _load_llm(db, None)
        llm_title = await asyncio.wait_for(
            generate_title_llm(
                llm,
                user_content=user_content,
                items=items,
                assistant_snippet=assistant_content[:600],
            ),
            timeout=4.0,
        )
        if llm_title and llm_title not in {"从对话生成的清单", "对话待办", "待办事项"}:
            return llm_title
    except Exception as e:  # noqa: BLE001
        logger.debug("checklist title llm fallback: %s", e)
    return base


async def create_from_message(
    db: aiosqlite.Connection,
    message_id: str,
    *,
    title: str | None = None,
) -> dict:
    cur = await db.execute("SELECT * FROM messages WHERE id=?", (message_id,))
    msg = await cur.fetchone()
    if not msg:
        raise ValueError("message not found")
    content = msg["content"] or ""
    items = parse_checklist_items(content)
    if not items:
        raise ValueError("未找到可执行的待办/提醒项（说明、分析类内容不会列入清单）")
    cur = await db.execute("SELECT workspace_id FROM sessions WHERE id=?", (msg["session_id"],))
    sess = await cur.fetchone()
    workspace_id = sess["workspace_id"] if sess else None

    if title and title.strip() and title.strip() not in {"从对话生成的清单", "手动清单"}:
        final_title = sanitize_title(title)
    else:
        user_content = await _prev_user_message(db, msg["session_id"], msg["created_at"] or utc_now())
        final_title = await resolve_checklist_title(
            db,
            assistant_content=content,
            items=items,
            user_content=user_content,
            use_llm=True,
        )

    cid = str(uuid.uuid4())
    now = utc_now()
    await db.execute(
        """
        INSERT INTO checklists(id, workspace_id, session_id, source_message_id, title, created_at, updated_at)
        VALUES(?,?,?,?,?,?,?)
        """,
        (cid, workspace_id, msg["session_id"], message_id, final_title, now, now),
    )
    for idx, item in enumerate(items):
        await db.execute(
            """
            INSERT INTO checklist_items(id, checklist_id, content, done, sort_order, updated_at)
            VALUES(?,?,?,?,?,?)
            """,
            (str(uuid.uuid4()), cid, item, 0, idx, now),
        )
    await db.commit()
    return {"id": cid, "items": items, "title": final_title}


async def create_from_session(db: aiosqlite.Connection, session_id: str) -> dict:
    """从会话中最近一条含可执行待办的助手回复生成清单。"""
    cur = await db.execute("SELECT id FROM sessions WHERE id=?", (session_id,))
    if not await cur.fetchone():
        raise ValueError("session not found")
    cur = await db.execute(
        """
        SELECT id, content, tool_calls_json FROM messages
        WHERE session_id=? AND role='assistant'
        ORDER BY created_at DESC
        """,
        (session_id,),
    )
    for row in await cur.fetchall():
        if row["tool_calls_json"]:
            continue
        content = row["content"] or ""
        if not content.strip():
            continue
        if parse_checklist_items(content):
            return await create_from_message(db, row["id"])
    raise ValueError("会话中未找到可执行的待办/提醒项")
