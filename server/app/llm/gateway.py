"""
OpenAI 兼容 LLM 网关 + Mock 模式。

只由后端调用模型；统一 chat.completions（stream + tools）。
provider=mock 或无 api_key 且显式 mock 时可离线跑通 Tool-Loop。
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
import uuid
from typing import Any, AsyncIterator, Protocol

from openai import AsyncOpenAI

# 单轮流式：无 chunk 过久 / 整轮过久则中断，避免 SSE 一直占着前端转圈
STREAM_IDLE_TIMEOUT_SEC = 90.0
STREAM_TOTAL_TIMEOUT_SEC = 300.0


def normalize_base_url(base_url: str) -> str:
    """OpenAI SDK 会自动追加 /chat/completions，base_url 应止于 /v1。"""
    url = (base_url or "https://api.openai.com/v1").strip().rstrip("/")
    for suffix in ("/chat/completions", "/completions"):
        if url.endswith(suffix):
            url = url[: -len(suffix)]
            url = url.rstrip("/")
    return url or "https://api.openai.com/v1"


_THINK_OPEN = re.compile(
    r"(?:<(?:think|thinking|reasoning)\s*>)|(?:<\|begin_of_thought\|>)|(?:◁think▷)",
    re.IGNORECASE,
)
_THINK_CLOSE = re.compile(
    r"(?:</(?:think|thinking|reasoning)\s*>)|(?:<\|end_of_thought\|>)|(?:◁/think▷)",
    re.IGNORECASE,
)
_THINK_TAG_CANDIDATES = (
    "<think>",
    "<thinking>",
    "<reasoning>",
    "</think>",
    "</thinking>",
    "</reasoning>",
    "<|begin_of_thought|>",
    "<|end_of_thought|>",
    "◁think▷",
    "◁/think▷",
)
_REASONING_KEYS = ("reasoning_content", "reasoning", "thinking", "reasoning_text")


def _delta_field_str(obj: Any, keys: tuple[str, ...]) -> str:
    if obj is None:
        return ""
    for key in keys:
        val = getattr(obj, key, None) if not isinstance(obj, dict) else obj.get(key)
        if isinstance(val, str) and val:
            return val
        if val is not None and not isinstance(val, (str, list, dict, bool, int, float)):
            inner = getattr(val, "content", None) or getattr(val, "text", None)
            if isinstance(inner, str) and inner:
                return inner
    extra = getattr(obj, "model_extra", None)
    if isinstance(extra, dict):
        for key in keys:
            val = extra.get(key)
            if isinstance(val, str) and val:
                return val
    if isinstance(obj, dict):
        for key in keys:
            val = obj.get(key)
            if isinstance(val, str) and val:
                return val
    return ""


def _parts_text(parts: list[Any], *, thinking: bool) -> str:
    bits: list[str] = []
    for p in parts:
        if isinstance(p, str):
            if not thinking:
                bits.append(p)
            continue
        typ = ""
        if isinstance(p, dict):
            typ = str(p.get("type") or "").lower()
            text = p.get("text") or p.get("content") or p.get("thinking") or ""
        else:
            typ = str(getattr(p, "type", "") or "").lower()
            text = getattr(p, "text", None) or getattr(p, "content", None) or getattr(p, "thinking", None) or ""
        is_think = typ in {"thinking", "reasoning", "thought"}
        if thinking == is_think and isinstance(text, str) and text:
            bits.append(text)
    return "".join(bits)


def _delta_reasoning(delta: Any) -> str:
    """从流式 delta 提取推理文本（DeepSeek / 通义 / 部分 OpenAI 兼容）。"""
    got = _delta_field_str(delta, _REASONING_KEYS)
    if got:
        return got
    raw = getattr(delta, "content", None) if not isinstance(delta, dict) else (delta or {}).get("content")
    if isinstance(raw, list):
        return _parts_text(raw, thinking=True)
    return ""


def _delta_content(delta: Any) -> str:
    """提取正文增量；忽略 thinking 类型的 content parts。"""
    if delta is None:
        return ""
    raw = getattr(delta, "content", None) if not isinstance(delta, dict) else delta.get("content")
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list):
        return _parts_text(raw, thinking=False)
    return ""


def _content_duplicates_reasoning(content: str, reasoning_delta: str, acc_reasoning: str) -> bool:
    """兼容网关把思考同时塞进 content / reasoning_content 的重复增量。"""
    if not content:
        return True
    if not content.strip():
        # 思考 chunk 里夹带的空白不应提前打开正文
        return bool((reasoning_delta or "").strip())
    c = content.strip()
    r = (reasoning_delta or "").strip()
    if r and (c == r or r.endswith(c) or c in r):
        return True
    ar = (acc_reasoning or "").strip()
    if ar and (c == ar or ar.endswith(c)):
        return True
    if ar and len(c) <= 24 and c in ar:
        return True
    return False


def _hold_partial_tag(buf: str) -> int:
    """可能是半截 think 标签时，返回应暂扣的尾部长度。"""
    last = max(buf.rfind("<"), buf.rfind("◁"))
    if last < 0:
        return 0
    frag = buf[last:]
    if ">" in frag or "▷" in frag:
        return 0
    lower = frag.lower()
    if any(c.lower().startswith(lower) for c in _THINK_TAG_CANDIDATES):
        return len(buf) - last
    return 0


def should_enable_thinking(model: str) -> bool:
    """是否向模型请求思考链（DeepSeek V4 等需显式/默认开启）。"""
    flag = (os.getenv("PSA_LLM_THINKING") or "auto").strip().lower()
    if flag in {"0", "false", "off", "disabled", "no"}:
        return False
    if flag in {"1", "true", "on", "enabled", "yes"}:
        return True
    m = (model or "").strip().lower()
    needles = ("deepseek", "reasoner", "r1", "qwq", "thinking")
    return any(n in m for n in needles)


def thinking_request_kwargs(model: str) -> dict[str, Any]:
    """构造 chat.completions 的思考模式参数。"""
    if not should_enable_thinking(model):
        return {}
    effort = (os.getenv("PSA_LLM_REASONING_EFFORT") or "medium").strip().lower()
    if effort not in {"low", "medium", "high", "max"}:
        effort = "medium"
    return {
        "reasoning_effort": effort,
        "extra_body": {"thinking": {"type": "enabled"}},
    }


def effective_max_tokens(model: str, max_tokens: int) -> int:
    """思考模型需要更大输出预算，避免 reasoning 占满后正文/工具调用被截断。"""
    base = max(1, int(max_tokens or 2048))
    if not should_enable_thinking(model):
        # 长文攻略等也容易顶穿 2048
        floor = int(os.getenv("PSA_LLM_MAX_TOKENS_FLOOR") or 8192)
        return max(base, floor)
    # 至少给思考+正文留足空间；可用 PSA_LLM_THINKING_MAX_TOKENS 覆盖
    floor = int(os.getenv("PSA_LLM_THINKING_MAX_TOKENS") or 32768)
    return max(base, floor)


class ThinkTagSplitter:
    """把正文里的 <think>…</think> 拆成 reasoning / token 流（兼容部分网关）。"""

    def __init__(self) -> None:
        self._buf = ""
        self._in_think = False

    def feed(self, text: str) -> list[tuple[str, str]]:
        if not text:
            return []
        self._buf += text
        out: list[tuple[str, str]] = []
        while self._buf:
            if self._in_think:
                m = _THINK_CLOSE.search(self._buf)
                if not m:
                    hold = _hold_partial_tag(self._buf)
                    if hold and len(self._buf) > hold:
                        emit, self._buf = self._buf[:-hold], self._buf[-hold:]
                        if emit:
                            out.append(("reasoning", emit))
                    elif not hold:
                        out.append(("reasoning", self._buf))
                        self._buf = ""
                    break
                before = self._buf[: m.start()]
                if before:
                    out.append(("reasoning", before))
                self._buf = self._buf[m.end() :]
                self._in_think = False
                continue

            m_open = _THINK_OPEN.search(self._buf)
            m_close = _THINK_CLOSE.search(self._buf)
            # 只有闭合标签：模型省略 <think> 时，闭合前全部视为思考
            if m_close and (not m_open or m_close.start() < m_open.start()):
                before = self._buf[: m_close.start()]
                if before:
                    out.append(("reasoning", before))
                self._buf = self._buf[m_close.end() :]
                self._in_think = False
                continue

            if m_open:
                before = self._buf[: m_open.start()]
                if before:
                    out.append(("token", before))
                self._buf = self._buf[m_open.end() :]
                self._in_think = True
                continue

            hold = _hold_partial_tag(self._buf)
            if hold:
                emit, self._buf = self._buf[:-hold], self._buf[-hold:]
                if emit:
                    out.append(("token", emit))
                break

            out.append(("token", self._buf))
            self._buf = ""
            break
        return out

    def flush(self) -> list[tuple[str, str]]:
        if not self._buf:
            return []
        kind = "reasoning" if self._in_think else "token"
        piece = self._buf
        self._buf = ""
        return [(kind, piece)] if piece else []


class StreamThinkMux:
    """把 native reasoning + 正文 think 标签 + 重复 content 收成统一事件。"""

    def __init__(self) -> None:
        self.splitter = ThinkTagSplitter()
        self.acc_reasoning = ""

    def feed_delta(self, reasoning: str, content: str) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        if reasoning:
            self.acc_reasoning += reasoning
            out.append(("reasoning", reasoning))
        if content:
            for kind, piece in self.splitter.feed(content):
                out.extend(self._emit_piece(kind, piece, reasoning))
        return out

    def flush(self) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        for kind, piece in self.splitter.flush():
            out.extend(self._emit_piece(kind, piece, ""))
        return out

    def _emit_piece(self, kind: str, piece: str, reasoning_delta: str) -> list[tuple[str, str]]:
        if not piece:
            return []
        if kind == "reasoning":
            if self.acc_reasoning and _content_duplicates_reasoning(piece, "", self.acc_reasoning):
                return []
            self.acc_reasoning += piece
            return [("reasoning", piece)]
        if _content_duplicates_reasoning(piece, reasoning_delta, self.acc_reasoning):
            return []
        return [("token", piece)]


class LLMGatewayProtocol(Protocol):
    async def test_connection(self) -> dict: ...

    def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[dict[str, Any]]: ...

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]: ...


class LLMGateway:
    """封装 openai SDK，便于单测 mock。"""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ):
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.client = AsyncOpenAI(base_url=normalize_base_url(base_url), api_key=api_key or "EMPTY")

    async def _create_chat_stream(self, kwargs: dict[str, Any]):
        """创建流式请求；思考参数不被上游接受时自动降级重试。"""
        try:
            return await self.client.chat.completions.create(**kwargs)
        except TypeError:
            # 旧版 SDK：reasoning_effort 可能不在签名中
            retry = dict(kwargs)
            effort = retry.pop("reasoning_effort", None)
            eb = dict(retry.get("extra_body") or {})
            if effort:
                eb.setdefault("reasoning_effort", effort)
            if eb:
                retry["extra_body"] = eb
            return await self.client.chat.completions.create(**retry)
        except Exception as e:  # noqa: BLE001
            msg = str(e).lower()
            if "thinking" in msg or "reasoning_effort" in msg or "unexpected" in msg:
                retry = {k: v for k, v in kwargs.items() if k not in {"reasoning_effort", "extra_body"}}
                return await self.client.chat.completions.create(**retry)
            raise

    async def test_connection(self) -> dict:
        t0 = time.perf_counter()
        try:
            resp = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=5,
            )
            choices = resp.choices or []
            if not choices or not choices[0].message:
                return {
                    "ok": False,
                    "latency_ms": int((time.perf_counter() - t0) * 1000),
                    "message": "模型返回空响应，请检查 Base URL 与 Model 名称",
                }
            msg = choices[0].message
            text = msg.content or getattr(msg, "reasoning_content", None) or ""
            if not str(text).strip():
                return {
                    "ok": True,
                    "latency_ms": int((time.perf_counter() - t0) * 1000),
                    "message": "ok（模型已连通，返回内容为空）",
                }
            return {"ok": True, "latency_ms": int((time.perf_counter() - t0) * 1000), "message": "ok"}
        except Exception as e:  # noqa: BLE001
            return {
                "ok": False,
                "latency_ms": int((time.perf_counter() - t0) * 1000),
                "message": str(e),
            }

    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        should_stop: Any | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": effective_max_tokens(self.model, self.max_tokens),
            "stream": True,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        kwargs.update(thinking_request_kwargs(self.model))

        stream = await self._create_chat_stream(kwargs)
        tool_acc: dict[int, dict[str, Any]] = {}
        think_mux = StreamThinkMux()
        stopped = False
        timed_out = False
        timeout_message = ""
        finish_reason: str | None = None
        deadline = time.monotonic() + STREAM_TOTAL_TIMEOUT_SEC
        aiter = stream.__aiter__()

        async def _next_chunk() -> Any:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"llm_stream_total_timeout（单轮超过 {int(STREAM_TOTAL_TIMEOUT_SEC)} 秒）"
                )
            wait = min(STREAM_IDLE_TIMEOUT_SEC, remaining)
            try:
                return await asyncio.wait_for(aiter.__anext__(), timeout=wait)
            except StopAsyncIteration:
                raise
            except asyncio.TimeoutError as e:
                idle = STREAM_IDLE_TIMEOUT_SEC
                if deadline - time.monotonic() <= 0:
                    raise TimeoutError(
                        f"llm_stream_total_timeout（单轮超过 {int(STREAM_TOTAL_TIMEOUT_SEC)} 秒）"
                    ) from e
                raise TimeoutError(
                    f"llm_stream_idle_timeout（超过 {int(idle)} 秒无新输出）"
                ) from e

        try:
            while True:
                if should_stop and should_stop():
                    stopped = True
                    break
                try:
                    chunk = await _next_chunk()
                except StopAsyncIteration:
                    break
                except TimeoutError as e:
                    timed_out = True
                    timeout_message = str(e)
                    break
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                fr = getattr(choice, "finish_reason", None)
                if isinstance(fr, str) and fr:
                    finish_reason = fr
                delta = choice.delta
                reasoning = _delta_reasoning(delta)
                content = _delta_content(delta)
                for kind, piece in think_mux.feed_delta(reasoning, content):
                    yield {"type": kind, "delta": piece}
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        slot = tool_acc.setdefault(
                            idx,
                            {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
                        )
                        if tc.id:
                            slot["id"] = tc.id
                        if tc.function:
                            if tc.function.name:
                                slot["function"]["name"] = tc.function.name
                            if tc.function.arguments:
                                slot["function"]["arguments"] += tc.function.arguments
        finally:
            close = getattr(stream, "close", None) or getattr(stream, "aclose", None)
            if close:
                try:
                    result = close()
                    if asyncio.iscoroutine(result):
                        await result
                except Exception:  # noqa: BLE001
                    pass

        if stopped:
            yield {"type": "done", "stopped": True, "finish_reason": finish_reason}
            return
        if timed_out:
            for kind, piece in think_mux.flush():
                yield {"type": kind, "delta": piece}
            yield {
                "type": "error",
                "code": "llm_timeout",
                "message": timeout_message or "llm stream timeout",
            }
            yield {"type": "done", "finish_reason": "timeout"}
            return
        for kind, piece in think_mux.flush():
            yield {"type": kind, "delta": piece}
        if tool_acc:
            yield {"type": "tool_calls", "tool_calls": [tool_acc[i] for i in sorted(tool_acc)]}
        yield {"type": "done", "finish_reason": finish_reason}

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": effective_max_tokens(self.model, self.max_tokens),
        }
        if tools:
            kwargs["tools"] = tools
        kwargs.update(thinking_request_kwargs(self.model))
        resp = await self.client.chat.completions.create(**kwargs)
        msg = resp.choices[0].message
        reasoning = _delta_reasoning(msg)
        content = _delta_content(msg)
        mux = StreamThinkMux()
        parts = mux.feed_delta(reasoning, content) + mux.flush()
        reasoning = "".join(p for k, p in parts if k == "reasoning")
        content = "".join(p for k, p in parts if k == "token")
        return {
            "content": content,
            "reasoning_content": reasoning if isinstance(reasoning, str) else "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in (msg.tool_calls or [])
            ],
        }


class MockLLMGateway:
    """
    无 Key 离线演示：按用户消息关键词触发 fs_write / 普通回复。
    输出契约与 LLMGateway.stream_chat 一致。
    """

    def __init__(self, model: str = "mock"):
        self.model = model
        self.temperature = 0.0
        self.max_tokens = 512

    async def test_connection(self) -> dict:
        return {"ok": True, "latency_ms": 1, "message": "ok (mock)"}

    def _last_user(self, messages: list[dict[str, Any]]) -> str:
        for m in reversed(messages):
            if m.get("role") == "user":
                return str(m.get("content") or "")
        return ""

    def _decide(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None):
        tool_names = {
            ((t.get("function") or {}).get("name") or "") for t in (tools or [])
        }
        tool_msgs = [m for m in messages if m.get("role") == "tool"]
        user = self._last_user(messages)

        # 已有 tool 结果：多步脚本可再调一次工具，否则总结
        if tool_msgs:
            # 确认后继续：若上一轮是 fs_write 且用户要求「再列出/再读」，发第二次工具调用
            last_assistant = None
            for m in reversed(messages):
                if m.get("role") == "assistant" and m.get("tool_calls"):
                    last_assistant = m
                    break
            last_tool_name = ""
            if last_assistant:
                tcs = last_assistant.get("tool_calls") or []
                if tcs:
                    last_tool_name = ((tcs[0].get("function") or {}).get("name") or "")
            if (
                last_tool_name == "fs_write"
                and "fs_list" in tool_names
                and len(tool_msgs) == 1
                and re.search(r"(列出|list|目录|然后再|继续)", user, re.I)
            ):
                path_m = re.search(r"([/\\][\w./\\-]+)", user)
                path = path_m.group(0) if path_m else "/tmp"
                return "tool", [
                    {
                        "id": f"call_{uuid.uuid4().hex[:8]}",
                        "type": "function",
                        "function": {
                            "name": "fs_list",
                            "arguments": json.dumps({"path": path}, ensure_ascii=False),
                        },
                    }
                ]
            # 同批：read + write 场景下，若仅完成了其中一个且用户同时要求读写
            if (
                last_tool_name == "fs_read"
                and "fs_write" in tool_names
                and len(tool_msgs) == 1
                and re.search(r"(写入|写到|写文件|保存)", user, re.I)
            ):
                path_m = re.search(r"([/\\][\w./\\-]+\.\w+)|([A-Za-z]:\\[\w.\\-]+)", user)
                path = path_m.group(0) if path_m else "/tmp/mock-write.txt"
                return "tool", [
                    {
                        "id": f"call_{uuid.uuid4().hex[:8]}",
                        "type": "function",
                        "function": {
                            "name": "fs_write",
                            "arguments": json.dumps(
                                {"path": path, "content": "mock content from PSA"},
                                ensure_ascii=False,
                            ),
                        },
                    }
                ]
            if last_tool_name == "current_time":
                try:
                    data = json.loads(str(tool_msgs[-1].get("content") or "{}"))
                    display = data.get("display") or data.get("datetime")
                    if display:
                        return "text", f"现在是 {display}"
                except Exception:  # noqa: BLE001
                    pass
                return "text", "（mock）已获取当前时间。"
            return "text", "（mock）已根据工具结果完成操作。"

        if "current_time" in tool_names and re.search(
            r"(几点了|现在几点|当前时间|现在的时间|现在是什么时候|今天几号|今天是几号|"
            r"星期几|今天星期|今天周几|什么日期|现在日期|当前日期|查询时间|"
            r"what time|current time|what(?:'s| is) (?:the )?date)",
            user,
            re.I,
        ):
            tz = ""
            if re.search(r"纽约|美东", user):
                tz = "America/New_York"
            elif re.search(r"洛杉矶|美西", user):
                tz = "America/Los_Angeles"
            elif re.search(r"东京|日本", user):
                tz = "Asia/Tokyo"
            elif re.search(r"伦敦", user):
                tz = "Europe/London"
            elif re.search(r"UTC|格林[尼威]治", user, re.I):
                tz = "UTC"
            args: dict[str, str] = {}
            if tz:
                args["timezone"] = tz
            return "tool", [
                {
                    "id": f"call_{uuid.uuid4().hex[:8]}",
                    "type": "function",
                    "function": {
                        "name": "current_time",
                        "arguments": json.dumps(args, ensure_ascii=False),
                    },
                }
            ]

        # 写文件意图
        if "fs_write" in tool_names and re.search(
            r"(写入|写到|写文件|保存到|write\s+to|create\s+file)", user, re.I
        ):
            path_m = re.search(r"([/\\][\w./\\-]+\.\w+)|([A-Za-z]:\\[\w.\\-]+)", user)
            path = path_m.group(0) if path_m else "/tmp/mock-write.txt"
            # 同批：若同时要求 list，一次返回两个 tool_calls（测试 dangling/sibling）
            calls = [
                {
                    "id": f"call_{uuid.uuid4().hex[:8]}",
                    "type": "function",
                    "function": {
                        "name": "fs_write",
                        "arguments": json.dumps(
                            {"path": path, "content": "mock content from PSA"},
                            ensure_ascii=False,
                        ),
                    },
                }
            ]
            if "fs_list" in tool_names and re.search(r"(同时列出|并列出|同批)", user, re.I):
                parent = "/tmp"
                if path and "/" in path:
                    parent = path.rsplit("/", 1)[0] or "/tmp"
                elif path and "\\" in path:
                    parent = path.rsplit("\\", 1)[0] or "C:\\"
                calls.append(
                    {
                        "id": f"call_{uuid.uuid4().hex[:8]}",
                        "type": "function",
                        "function": {
                            "name": "fs_list",
                            "arguments": json.dumps({"path": parent}, ensure_ascii=False),
                        },
                    }
                )
            return "tool", calls
        if "fs_list" in tool_names and re.search(r"(列出|list|目录)", user, re.I):
            path_m = re.search(r"([/\\][\w./\\-]+)", user)
            path = path_m.group(0) if path_m else "."
            return "tool", [
                {
                    "id": f"call_{uuid.uuid4().hex[:8]}",
                    "type": "function",
                    "function": {
                        "name": "fs_list",
                        "arguments": json.dumps({"path": path}, ensure_ascii=False),
                    },
                }
            ]
        return "text", f"（mock）收到：{user[:200] or '你好'}。当前为离线 Mock 模式，配置真实 API Key 后可调用大模型。"

    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        should_stop: Any | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        kind, payload = self._decide(messages, tools)
        if should_stop and should_stop():
            yield {"type": "done", "stopped": True}
            return
        if kind == "tool":
            # 演示：工具前先推一段简短推理，便于前端验证 reasoning SSE
            for piece in ("先确认用户意图，", "再调用合适的工具。"):
                if should_stop and should_stop():
                    yield {"type": "done", "stopped": True}
                    return
                yield {"type": "reasoning", "delta": piece}
                await asyncio.sleep(0.01)
            yield {"type": "tool_calls", "tool_calls": payload}
            yield {"type": "done"}
            return
        text = str(payload)
        for piece in ("梳理问题要点，", "组织简洁回答。"):
            if should_stop and should_stop():
                yield {"type": "done", "stopped": True}
                return
            yield {"type": "reasoning", "delta": piece}
            await asyncio.sleep(0.01)
        for i in range(0, len(text), 8):
            if should_stop and should_stop():
                yield {"type": "done", "stopped": True}
                return
            await asyncio.sleep(0.01)
            yield {"type": "token", "delta": text[i : i + 8]}
        yield {"type": "done"}

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        kind, payload = self._decide(messages, tools)
        if kind == "tool":
            return {"content": "", "tool_calls": payload}
        return {"content": str(payload), "tool_calls": []}


def create_gateway(
    *,
    base_url: str,
    api_key: str,
    model: str,
    temperature: float = 0.7,
    max_tokens: int = 2048,
    provider: str | None = None,
) -> LLMGateway | MockLLMGateway:
    """按 provider 选择真实或 Mock 网关（显式 provider=mock）。"""
    prov = (provider or "").strip().lower()
    if prov == "mock" or (model or "").strip().lower() == "mock":
        return MockLLMGateway(model=model or "mock")
    return LLMGateway(
        base_url=base_url,
        api_key=api_key,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )


# 兼容类型别名
LLMGatewayType = LLMGateway | MockLLMGateway
