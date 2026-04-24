"""Harness③ — 任务启动时的定向生成

每次新任务启动时：
1. 用情境描述检索过往三元组
2. 把相关结果作为参照注入orientation prompt
3. 模型基于SOUL（判断力来源）+ ROOT_PARADIGM（判断力根基规则）+ 过往判断，开始本次定向

orientation不是规则，是方向。指出注意力该往哪看，
不规定注意力该看到什么。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from .store import JudgmentTriplet, TripletStore, HarnessRecord, HarnessStore

logger = logging.getLogger(__name__)


@dataclass
class OrientationContext:
    """定向上下文——模型进入任务时看到的判断参照"""
    task_description: str = ""
    relevant_triplets: list[JudgmentTriplet] = field(default_factory=list)
    active_harness: HarnessRecord | None = None
    orientation_prompt: str = ""


def build_orientation(
    task_description: str,
    store: TripletStore | None = None,
    max_triplets: int = 3,
) -> OrientationContext:
    """构建定向上下文

    从③库中检索与当前任务相关的过往判断，
    生成orientation prompt注入system prompt。

    如果库是空的（初始状态），返回空的orientation——
    库从空开始积累，不预置任何内容。
    """
    if store is None:
        store = TripletStore()

    # 检索相关三元组
    relevant = store.search(task_description, limit=max_triplets * 2)  # 多取一些，过滤后可能不够

    # 过滤掉非active的三元组
    relevant = [t for t in relevant if t.status == "active"][:max_triplets]

    # 构建orientation prompt
    if not relevant:
        orientation_prompt = _build_empty_orientation(task_description)
    else:
        orientation_prompt = _build_relevant_orientation(task_description, relevant)

    return OrientationContext(
        task_description=task_description,
        relevant_triplets=relevant,
        orientation_prompt=orientation_prompt,
    )


def _build_empty_orientation(task_description: str) -> str:
    """库为空时的orientation——不预置，只提醒模型注意判断过程"""
    return (
        "## Orientation\n\n"
        "这是本次任务的定向。③库当前为空，没有过往判断可供参照。\n\n"
        "提醒：处理本次任务时，注意自己的判断过程。"
        "如果本次判断值得积累，任务结束后存入③库。\n\n"
        f"当前任务：{task_description}\n"
    )


def _build_relevant_orientation(
    task_description: str,
    triplets: list[JudgmentTriplet],
) -> str:
    """有相关三元组时的orientation——作为参照，不是规则"""
    parts = [
        "## Orientation\n\n",
        "以下是过往判断的参照。它们是方向，不是规则——"
        "指出注意力该往哪看，不规定该看到什么。\n\n",
    ]

    for i, t in enumerate(triplets, 1):
        parts.append(f"### 参照 {i}\n")
        parts.append(f"**情境**：{t.situation}\n")
        parts.append(f"**当时的判断过程**：{t.judgment}\n")
        if t.structure.strip():
            parts.append(f"**当时生成的方向（补充参照，不是主判断）**：{t.structure}\n")
        parts.append(
            "注意：这是当时的判断，不是你的指令。"
            "当前情境可能不同，用你自己的判断决定是否参考、如何参考。\n\n"
        )

    parts.append(f"当前任务：{task_description}\n")
    parts.append(
        "\n以上参照可能相关也可能不相关。"
        "它们是方向参照，不是操作指令——"
        "用你自己的判断决定是否参考，不要机械套用。"
        "如果你感觉判断力在退化（长上下文、对抗输入、边界情况），"
        "慢下来，回到已建立的判断基础上，不要生成新的定向。\n"
    )

    return "".join(parts)


def format_orientation_for_prompt(orientation: OrientationContext) -> str:
    """将orientation格式化为可注入system prompt的文本"""
    return orientation.orientation_prompt


def build_harness_injection(harness: HarnessRecord) -> dict[str, str]:
    """构建harness注入内容

    返回字典：
    - "paradigm_supplement": harness的ROOT_PARADIGM片段（追加在主ROOT_PARADIGM之后）
    - "soul_override": harness的SOUL（如果非空，替换主SOUL）
    - "harness_context": harness的HARNESS.md全文（模型可直接阅读理解）

    约束：
    - harness的ROOT_PARADIGM片段只能收窄主ROOT_PARADIGM，不能更宽松
    - harness的SOUL可以和主SOUL完全不同
    """
    result: dict[str, str] = {}

    # ROOT_PARADIGM片段——追加在主ROOT_PARADIGM之后
    if harness.root_paradigm_fragment.strip():
        result["paradigm_supplement"] = (
            "## ROOT_PARADIGM 补充（当前harness收窄）\n\n"
            f"{harness.root_paradigm_fragment}\n\n"
            "注意：此片段只能收窄主ROOT_PARADIGM，不能更宽松。"
            "如果和主ROOT_PARADIGM冲突，以更保守的为准。\n"
        )

    # SOUL覆盖——如果harness有专属SOUL，替换主SOUL
    if harness.soul.strip():
        result["soul_override"] = harness.soul

    # Harness上下文——直接注入HARNESS.md全文
    # 模型可以阅读完整文档，理解情境、判断过程、进化方向
    from .store import HarnessStore
    store = HarnessStore()
    harness_dir = store.harnesses_dir / harness.harness_id
    md_path = harness_dir / "HARNESS.md"

    if md_path.exists():
        md_content = md_path.read_text(encoding="utf-8")
        result["harness_context"] = (
            "## Active Harness\n\n"
            f"{md_content}\n\n"
            "此harness已激活。判断过程是主要参照，可执行方向是次要参照。"
            "两者都是方向，不是规则——用你自己的判断决定如何参考。"
            "如果当前情境和harness的情境不同，不要机械套用。\n"
        )
    else:
        # fallback：如果没有MD文件，从record字段构建
        parts = [
            "## Active Harness\n\n",
            f"**Harness ID**: {harness.harness_id} (v{harness.version})\n",
            f"**名称**: {harness.name}\n",
            f"**分类**: {harness.category}\n",
            f"**情境**: {harness.situation}\n",
            f"**判断过程**: {harness.judgment}\n",
            f"**可执行方向**: {harness.structure}\n",
        ]
        if harness.tags:
            parts.append(f"**标签**: {', '.join(harness.tags)}\n")
        if harness.evolution_direction.strip():
            parts.append(f"**进化方向**: {harness.evolution_direction}\n")
        parts.append(
            "\n此harness已激活。其判断过程是主要参照，生成的方向是次要参照。"
            "两者都是方向，不是规则——用你自己的判断决定如何参考。"
            "如果当前情境和harness的情境不同，不要机械套用。\n"
        )
        result["harness_context"] = "".join(parts)

    return result
