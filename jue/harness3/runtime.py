from __future__ import annotations

import json
import logging
import threading
from typing import Any

from .orientation import build_orientation
from .store import JudgmentTriplet, TripletMetaCheck, TripletStore

logger = logging.getLogger(__name__)

_HOOKS_INSTALLED = False
_TURN_STATE: dict[str, dict[str, Any]] = {}
_TURN_STATE_LOCK = threading.Lock()


def _tracker_key(task_id: str = "", session_id: str = "") -> str:
    return task_id or session_id or "default"


def _safe_json_loads(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        return dict(payload)
    if not isinstance(payload, str) or not payload.strip():
        return {}
    try:
        loaded = json.loads(payload)
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def write_triplet(
    *,
    situation: str,
    judgment: str,
    structure: str,
    tags: list[str] | None = None,
    track: str = "harness",
    task_id: str = "",
    session_id: str = "",
    meta_answer: str = "",
) -> str:
    """Best-effort direct triplet write for Jue runtime hooks."""
    triplet = JudgmentTriplet(
        situation=(situation or "").strip(),
        judgment=(judgment or "").strip(),
        structure=(structure or "").strip(),
        tags=list(tags or []),
        track=track or "harness",
        task_id=task_id or "",
        session_id=session_id or "",
    )
    if not triplet.situation or not triplet.judgment or not triplet.structure:
        return ""
    meta = TripletMetaCheck(
        passed=not any(
            kw in (meta_answer or "").lower()
            for kw in ("规定动作", "rule", "prescribe", "if-then", "步骤")
        ),
        answer=meta_answer or "",
    )
    try:
        return TripletStore().write(triplet, meta)
    except Exception:
        logger.debug("Jue Harness③ direct write failed", exc_info=True)
        return ""


def build_preserved_context(task_description: str = "", active_harness_id: str = "") -> str:
    """Return Jue-specific context that compression should preserve."""
    parts = [
        "## Jue 连续性\n",
        "- ROOT_PARADIGM 是判断力的根基规则。压缩、fork、恢复、委托之后，它必须保持一致。\n",
        "- 保留解释决策为什么做出的推理依据，不只是做了什么。\n",
    ]
    if active_harness_id:
        parts.append(f"- 当前激活的harness除非显式变更，否则持续生效：`{active_harness_id}`。\n")
        try:
            from .store import HarnessStore

            harness = HarnessStore().get(active_harness_id)
            if harness:
                parts.append(f"- 激活harness的情境：{harness.situation}\n")
                parts.append(f"- 激活harness的判断过程：{harness.judgment}\n")
                parts.append(f"- 激活harness的方向：{harness.structure}\n")
        except Exception:
            logger.debug("Could not summarize active harness for compression", exc_info=True)

    if task_description.strip():
        try:
            orientation = build_orientation(task_description)
            if orientation.relevant_triplets:
                parts.append("- 相关判断三元组（判断过程为主，生成的方向为辅）：\n")
                for triplet in orientation.relevant_triplets:
                    parts.append(f"  - {triplet.triplet_id}: 情境={triplet.situation} | 判断过程={triplet.judgment}")
                    if triplet.structure.strip():
                        parts.append(f" | 方向={triplet.structure}")
                    parts.append("\n")
        except Exception:
            logger.debug("Could not summarize triplets for compression", exc_info=True)

    return "".join(parts).strip()


def restore_active_harness_id(messages: list[dict[str, Any]] | None) -> str:
    """Recover the most recently activated harness from conversation history."""
    if not messages:
        return ""
    for msg in reversed(messages):
        if not isinstance(msg, dict) or msg.get("role") != "tool":
            continue
        payload = _safe_json_loads(msg.get("content"))
        harness_id = str(payload.get("harness_id") or "").strip()
        if payload.get("success") and harness_id:
            return harness_id
    return ""


def record_memory_write_triplet(
    *,
    action: str,
    target: str,
    content: str,
    task_id: str = "",
    session_id: str = "",
) -> str:
    """Bridge built-in memory writes into Harness③."""
    cleaned = (content or "").strip()
    if action not in {"add", "replace"} or not cleaned:
        return ""
    location = "USER.md" if target == "user" else "MEMORY.md"
    return write_triplet(
        situation=(
            f"Agent把一条经过判断后适合持久保存的信息写入了 {location}。"
            "这里关注的是存储边界本身，而不是那条事实内容。"
        ),
        judgment=(
            "这条信息足够稳定，可以跨会话存活。"
            "判断过程是：这是持久事实/偏好/环境信息（属于MEMORY.md/USER.md），"
            "还是判断结构（属于三元组）？它是事实——所以去了记忆，不是三元组。"
        ),
        structure=(
            "方向是先分辨信息类型：更像稳定事实/偏好/环境时，优先放入 MEMORY.md/USER.md；"
            "更像历史会话回忆时，留给 session_search；"
            "更像判断过程及其指向时，再考虑 triplet/harness。"
            "关键是守住边界，而不是记住这条具体事实本身。"
        ),
        tags=["memory-boundary", "memory-write", target or "memory"],
        track="harness",
        task_id=task_id,
        session_id=session_id,
    )


def note_post_tool_call(
    *,
    tool_name: str,
    args: dict[str, Any] | None,
    result: Any,
    task_id: str = "",
    session_id: str = "",
) -> None:
    """Capture post-tool-call signals for later turn-end triplet deposition."""
    key = _tracker_key(task_id, session_id)
    payload = _safe_json_loads(result)
    with _TURN_STATE_LOCK:
        state = _TURN_STATE.setdefault(
            key,
            {
                "mcp_servers": set(),
                "blocked_tools": [],
                "memory_writes": [],
            },
        )
        if isinstance(tool_name, str) and tool_name.startswith("mcp_"):
            try:
                from tools.registry import registry

                toolset = registry.get_toolset_for_tool(tool_name) or ""
                if isinstance(toolset, str) and toolset.startswith("mcp-"):
                    state["mcp_servers"].add(toolset[len("mcp-"):])
            except Exception:
                logger.debug("Could not resolve MCP toolset for %s", tool_name, exc_info=True)
        error_text = str(payload.get("error") or "")
        if "[Harness① BLOCKED]" in error_text:
            state["blocked_tools"].append({"tool_name": tool_name, "error": error_text})
        if (
            tool_name == "memory"
            and payload.get("success")
            and (args or {}).get("action") in {"add", "replace"}
        ):
            state["memory_writes"].append(
                {
                    "action": (args or {}).get("action", ""),
                    "target": (args or {}).get("target", "memory"),
                    "content": (args or {}).get("content", ""),
                }
            )


def drain_turn_triplets(
    *,
    session_id: str = "",
    task_id: str = "",
    user_message: str = "",
    final_response: str = "",
    messages: list[dict[str, Any]] | None = None,
) -> list[str]:
    """Write turn-end triplets from buffered tool observations."""
    key = _tracker_key(task_id, session_id)
    with _TURN_STATE_LOCK:
        state = _TURN_STATE.pop(key, None) or {}

    triplet_ids: list[str] = []
    for mem in state.get("memory_writes", []):
        triplet_id = record_memory_write_triplet(
            action=mem.get("action", ""),
            target=mem.get("target", "memory"),
            content=mem.get("content", ""),
            task_id=task_id,
            session_id=session_id,
        )
        if triplet_id:
            triplet_ids.append(triplet_id)

    mcp_servers = sorted(s for s in state.get("mcp_servers", set()) if s)
    if mcp_servers:
        triplet_id = write_triplet(
            situation=(
                f"任务依赖MCP服务器 {', '.join(mcp_servers)}"
                + (f"，处理请求：{user_message}" if user_message else "")
            ),
            judgment=(
                "MCP支撑的工作带有服务器特有的语义和权限。"
                "值得保存的判断不是具体的API调用序列，"
                "而是对'这类任务依赖特定外部系统'的识别——"
                "未来类似任务应该回溯哪个MCP服务器塑造了当时的推理。"
            ),
            structure=(
                "当任务依赖MCP工具时，服务器身份是判断上下文的一部分。"
                "未来类似任务的定向应该浮现这个依赖，"
                "让模型知道推理是由一个有自身约束的外部系统中介的。"
            ),
            tags=["mcp", *[f"mcp:{name}" for name in mcp_servers]],
            track="harness",
            task_id=task_id,
            session_id=session_id,
        )
        if triplet_id:
            triplet_ids.append(triplet_id)

    blocked_tools = state.get("blocked_tools", [])
    if blocked_tools:
        blocked_names = ", ".join(sorted({entry.get("tool_name", "") for entry in blocked_tools if entry.get("tool_name")}))
        triplet_id = write_triplet(
            situation=(
                f"代码层Harness①拦截了工具调用：{blocked_names or '未知工具'}"
                + (f"，处理请求：{user_message}" if user_message else "")
            ),
            judgment=(
                "字面请求触碰了硬安全边界。"
                "值得保存的判断是：用户底层意图很可能不需要这个破坏性操作——"
                "拦截是重新评估意图的信号，不是重试的信号。"
                "目标没有正确呈现意图——检验没过——判断力该起作用了。"
            ),
            structure=(
                "当Harness①拦截了一个操作，方向是：重新评估用户意图。"
                "不要重试同一条破坏性路径。诚实地呈现安全边界，"
                "转向更安全的解读或请求澄清。"
                "拦截本身是支持判断的信息，不是障碍。"
            ),
            tags=["harness1", "guard-block", "intent-gap"],
            track="harness",
            task_id=task_id,
            session_id=session_id,
        )
        if triplet_id:
            triplet_ids.append(triplet_id)

    return triplet_ids


def register_hooks() -> None:
    """Register Jue Harness③ observational hooks into Jue."""
    global _HOOKS_INSTALLED
    if _HOOKS_INSTALLED:
        return
    try:
        from hermes_cli.plugins import get_plugin_manager
    except Exception:
        logger.debug("Jue Harness③ hooks unavailable: plugin manager missing", exc_info=True)
        return

    def _post_tool_call(
        tool_name: str,
        args: dict[str, Any] | None = None,
        result: Any = None,
        task_id: str = "",
        session_id: str = "",
        **_: Any,
    ) -> None:
        note_post_tool_call(
            tool_name=tool_name,
            args=args or {},
            result=result,
            task_id=task_id or "",
            session_id=session_id or "",
        )

    def _on_session_end(
        session_id: str = "",
        task_id: str = "",
        user_message: str = "",
        final_response: str = "",
        messages: list[dict[str, Any]] | None = None,
        **_: Any,
    ) -> None:
        drain_turn_triplets(
            session_id=session_id or "",
            task_id=task_id or "",
            user_message=user_message or "",
            final_response=final_response or "",
            messages=messages or [],
        )

    manager = get_plugin_manager()
    manager._hooks.setdefault("post_tool_call", []).append(_post_tool_call)
    manager._hooks.setdefault("on_session_end", []).append(_on_session_end)
    _HOOKS_INSTALLED = True
    logger.info("Jue Harness③ hooks installed")
