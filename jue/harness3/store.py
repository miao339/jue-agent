"""Harness③ — 判断三元组存储与检索

③是判断力的积累体。每次处理真实需求后，存入三元组：
  情境(situation) + 判断过程(judgment) + 生成的结构(structure)

缺了判断过程就退化成做法仓库——只有做法，没有为什么。

③的双轨进化：
- Skills进化：积累可调用的能力结构
- Harness进化：积累判断三元组，判断越来越准

库从空开始积累，库的形状就是判断力的外化。
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from jue_constants import get_jue_home

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _human_readable_time(value: str) -> str:
    """Render stored ISO timestamps for HARNESS.md headers."""
    if not value:
        return ""
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        return datetime.fromisoformat(normalized).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return value[:16].replace("T", " ")


@dataclass
class JudgmentTriplet:
    """判断三元组

    situation:  情境描述——遇到了什么
    judgment:   判断过程——为什么这么做，不是做了什么
    structure:  生成的结构——可复用的能力或方向模板

    防退化标准：
    - situation必须是具体的，不能是抽象的"一般情况"
    - judgment必须包含"为什么"，不能只有"做了什么"
    - structure必须指出注意力的方向，不能规定注意力的结果
    """
    triplet_id: str = field(default_factory=lambda: f"h3-{uuid4().hex[:12]}")
    situation: str = ""
    judgment: str = ""
    structure: str = ""
    tags: list[str] = field(default_factory=list)
    track: str = "harness"  # "harness" 或 "skill"
    status: str = "active"  # "active" | "flagged" | "revoked"
    created_at: str = field(default_factory=_utc_now_iso)
    task_id: str = ""
    session_id: str = ""


@dataclass
class TripletMetaCheck:
    """三元组的防退化自检

    生成后模型自问：这是在指出方向，还是在规定动作？
    如果是后者，需要重写。
    """
    passed: bool = True
    question: str = "这是在指出方向，还是在规定动作？"
    answer: str = ""
    notes: str = ""


class TripletStore:
    """三元组存储

    存储路径：~/.jue/harness3/triplets/
    每个三元组一个JSON文件，文件名=triplet_id.json

    索引文件：~/.jue/harness3/index.json
    存储所有三元组的摘要，用于快速检索
    """

    def __init__(self, store_dir: Path | str | None = None):
        if store_dir is None:
            store_dir = get_jue_home() / "harness3"
        self.store_dir = Path(store_dir)
        self.triplets_dir = self.store_dir / "triplets"
        self.index_path = self.store_dir / "index.json"
        self.triplets_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_index()

    def _ensure_index(self) -> None:
        if not self.index_path.exists():
            self.index_path.write_text(
                json.dumps({"triplets": [], "updated_at": _utc_now_iso()}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    # ── 写入方法（第二段）──

    def write(self, triplet: JudgmentTriplet, meta_check: TripletMetaCheck | None = None) -> str:
        """写入一个三元组，返回triplet_id

        写入前做防退化检查：如果meta_check未通过，记录但不阻止写入
        （判断力包括允许不完美的判断存在，后续可以修正）
        """
        # 防退化基本检查：三个字段不能为空
        if not triplet.situation.strip():
            logger.warning("Triplet missing situation — skipping write")
            return ""
        if not triplet.judgment.strip():
            logger.warning("Triplet missing judgment — skipping write (degrades to skill-only)")
            return ""
        if not triplet.structure.strip():
            logger.warning("Triplet missing structure — skipping write")
            return ""

        # 写入文件
        triplet_path = self.triplets_dir / f"{triplet.triplet_id}.json"
        payload = asdict(triplet)
        if meta_check:
            payload["meta_check"] = asdict(meta_check)
        triplet_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # 更新索引
        self._update_index(triplet)

        logger.info("Harness③ triplet written: %s (track=%s)", triplet.triplet_id, triplet.track)
        return triplet.triplet_id

    def _update_index(self, triplet: JudgmentTriplet) -> None:
        """更新索引文件"""
        index = self._load_index()
        # 摘要条目：不存完整内容，只存检索所需字段
        entry = {
            "triplet_id": triplet.triplet_id,
            "situation": triplet.situation[:200],  # 截断，索引不需要全文
            "tags": triplet.tags,
            "track": triplet.track,
            "status": triplet.status,
            "created_at": triplet.created_at,
            "task_id": triplet.task_id,
        }
        index.setdefault("triplets", []).append(entry)
        index["updated_at"] = _utc_now_iso()
        self.index_path.write_text(
            json.dumps(index, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ── 检索方法（第三段）──

    def search(self, query: str, limit: int = 5, track: str | None = None) -> list[JudgmentTriplet]:
        """用情境描述检索相关的过往三元组

        当前实现：基于关键词的简单匹配。
        对中文使用字符级重叠匹配（因为中文没有空格分词）。
        对英文使用单词级匹配。
        未来可替换为语义检索（embedding）。
        """
        index = self._load_index()
        entries = index.get("triplets", [])

        # 混合分词策略：英文按空格，中文按字符
        query_chars = set(query.lower())
        query_words = set(re.findall(r'[a-zA-Z0-9]+', query.lower()))
        if not query_chars and not query_words:
            return []

        scored: list[tuple[float, dict]] = []
        for entry in entries:
            if track and entry.get("track") != track:
                continue
            text = (entry.get("situation", "") + " " + " ".join(entry.get("tags", []))).lower()
            # 英文单词匹配
            entry_words = set(re.findall(r'[a-zA-Z0-9]+', text))
            word_overlap = len(query_words & entry_words)
            # 中文字符匹配
            entry_chars = set(text)
            char_overlap = len(query_chars & entry_chars)
            # 综合得分：英文单词权重高，中文字符权重低（避免短查询误匹配）
            score = word_overlap * 3 + char_overlap * 0.1
            if score > 0.5:  # 最低阈值
                scored.append((score, entry))

        scored.sort(key=lambda x: x[0], reverse=True)
        results: list[JudgmentTriplet] = []
        for _, entry in scored[:limit]:
            triplet = self.get(entry["triplet_id"])
            if triplet:
                results.append(triplet)
        return results

    def get(self, triplet_id: str) -> JudgmentTriplet | None:
        """按ID获取单个三元组"""
        triplet_path = self.triplets_dir / f"{triplet_id}.json"
        if not triplet_path.exists():
            return None
        try:
            payload = json.loads(triplet_path.read_text(encoding="utf-8"))
            # 去掉meta_check，它不属于JudgmentTriplet的字段
            payload.pop("meta_check", None)
            return JudgmentTriplet(**payload)
        except Exception as e:
            logger.warning("Could not load triplet %s: %s", triplet_id, e)
            return None

    def list_recent(self, limit: int = 20, track: str | None = None) -> list[JudgmentTriplet]:
        """列出最近的三元组"""
        index = self._load_index()
        entries = index.get("triplets", [])

        if track:
            entries = [e for e in entries if e.get("track") == track]

        # 按创建时间倒序
        entries.sort(key=lambda e: e.get("created_at", ""), reverse=True)

        results: list[JudgmentTriplet] = []
        for entry in entries[:limit]:
            triplet = self.get(entry["triplet_id"])
            if triplet:
                results.append(triplet)
        return results

    def update_status(self, triplet_id: str, new_status: str) -> bool:
        """更新三元组状态 (active/flagged/revoked)

        返回True表示成功，False表示三元组不存在或状态非法。
        同时更新JSON文件和索引。
        """
        valid = {"active", "flagged", "revoked"}
        if new_status not in valid:
            logger.warning("Invalid triplet status: %s (must be one of %s)", new_status, valid)
            return False

        triplet = self.get(triplet_id)
        if not triplet:
            logger.warning("Triplet not found: %s", triplet_id)
            return False

        old_status = triplet.status
        triplet.status = new_status

        # 更新JSON文件
        triplet_path = self.triplets_dir / f"{triplet_id}.json"
        try:
            payload = json.loads(triplet_path.read_text(encoding="utf-8"))
            payload["status"] = new_status
            triplet_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.error("Failed to update triplet %s status: %s", triplet_id, e)
            return False

        # 更新索引中的status
        index = self._load_index()
        for entry in index.get("triplets", []):
            if entry.get("triplet_id") == triplet_id:
                entry["status"] = new_status
                break
        index["updated_at"] = _utc_now_iso()
        self.index_path.write_text(
            json.dumps(index, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        logger.info("Triplet %s status: %s -> %s", triplet_id, old_status, new_status)
        return True

    # ── 索引维护 ──

    def _load_index(self) -> dict[str, Any]:
        """加载索引文件"""
        try:
            return json.loads(self.index_path.read_text(encoding="utf-8"))
        except Exception:
            return {"triplets": [], "updated_at": _utc_now_iso()}


# =============================================================================
# Harness Record — 可执行的判断结构体
# =============================================================================

@dataclass
class HarnessRecord:
    """Harness记录——可执行的判断结构体

    和JudgmentTriplet的区别：
    - Triplet是判断的痕迹：情境+判断过程+方向
    - Harness是判断的结晶：情境+判断过程+可执行结构

    Harness比Triplet多了三样东西：
    1. structure是可执行的（代码骨架或方向描述），不只是方向
    2. 可选的ROOT_PARADIGM片段（只能收窄主范式，不能更宽松）
    3. 可选的专属SOUL（可以和主SOUL完全不同）
    4. 可选的API配置引用（api_config_name指向config.json里的配置，模型不能直接写key）

    版本化：每次evolve产生新版本，旧版本保留不覆盖。
    """
    harness_id: str = field(default_factory=lambda: f"hr-{uuid4().hex[:12]}")
    name: str = ""
    category: str = ""
    situation: str = ""
    judgment: str = ""
    structure: str = ""
    root_paradigm_fragment: str = ""
    soul: str = ""
    api_config_name: str = ""      # 引用config.json里的配置名，空=用主配置兜底
    tags: list[str] = field(default_factory=list)
    track: str = "harness"
    created_at: str = field(default_factory=_utc_now_iso)
    version: int = 1
    parent_version_id: str = ""   # evolve时指向父版本的harness_id
    evolution_reason: str = ""    # evolve时记录为什么进化
    evolution_direction: str = "" # 上一个模型认为这个harness在什么情况下可能需要进化


class HarnessStore:
    """Harness记录存储

    存储路径：~/.jue/harness3/harnesses/{harness_id}/
    每个harness一个目录，包含：
    - HARNESS.md：主文档（情境、判断过程、方向、进化日志、进化方向）
    - meta.json：机器字段（version, parent_version_id, tags, status, created_at等）

    版本化：evolve时旧版本目录移到 archive/{harness_id}_v{version}/
    当前版本始终在 harnesses/{harness_id}/
    """

    def __init__(self, store_dir: Path | str | None = None):
        if store_dir is None:
            store_dir = get_jue_home() / "harness3"
        self.store_dir = Path(store_dir)
        self.harnesses_dir = self.store_dir / "harnesses"
        self.archive_dir = self.harnesses_dir / "archive"
        self.harnesses_dir.mkdir(parents=True, exist_ok=True)
        self.archive_dir.mkdir(parents=True, exist_ok=True)

    # ── HARNESS.md模板 ──

    @staticmethod
    def _build_harness_md(record: HarnessRecord) -> str:
        """从HarnessRecord生成HARNESS.md内容"""
        parts = [
            f"# Harness: {record.harness_id}\n",
            f"名称：{record.name}\n",
            f"分类：{record.category}\n",
            f"创建时间：{_human_readable_time(record.created_at)}\n",
            f"版本：v{record.version}\n\n",
        ]
        if record.tags:
            parts.append(f"**领域**: {', '.join(record.tags)}\n")

        parts.append("## 情境\n\n")
        parts.append(f"{record.situation}\n\n")

        parts.append("## 判断过程\n\n")
        parts.append(f"{record.judgment}\n\n")

        parts.append("## 可执行方向\n\n")
        parts.append(f"{record.structure}\n\n")

        if record.root_paradigm_fragment.strip():
            parts.append("## ROOT_PARADIGM收窄\n\n")
            parts.append(f"{record.root_paradigm_fragment}\n\n")
            parts.append("注意：此片段只能收窄主ROOT_PARADIGM，不能更宽松。\n\n")

        if record.soul.strip():
            parts.append("## 专属SOUL\n\n")
            parts.append(f"{record.soul}\n\n")

        if record.evolution_direction.strip():
            parts.append("## 进化方向\n\n")
            parts.append(f"{record.evolution_direction}\n\n")
            parts.append("（上一个模型认为这个harness在上述情况下可能需要进化。是方向，不是规定。）\n\n")

        # 进化日志
        parts.append("## 进化日志\n\n")
        if record.version > 1 and record.evolution_reason:
            parts.append(f"### v{record.version}\n\n")
            parts.append(f"**进化原因**: {record.evolution_reason}\n\n")
        else:
            parts.append("（首次创建，暂无进化记录。）\n\n")

        return "".join(parts)

    @staticmethod
    def _build_meta_json(record: HarnessRecord) -> dict:
        """从HarnessRecord生成meta.json内容（机器字段）"""
        return {
            "harness_id": record.harness_id,
            "name": record.name,
            "category": record.category,
            "version": record.version,
            "parent_version_id": record.parent_version_id,
            "evolution_reason": record.evolution_reason,
            "evolution_direction": record.evolution_direction,
            "tags": record.tags,
            "track": record.track,
            "created_at": record.created_at,
            "api_config_name": record.api_config_name,
        }

    @staticmethod
    def _parse_harness_md(md_text: str) -> dict[str, str]:
        """从HARNESS.md解析出各字段

        只认已知的section标题，避免用户内容里的##行误触发分割。
        已知section：情境、判断过程、可执行方向、ROOT_PARADIGM收窄、专属SOUL、进化方向、进化日志
        """
        KNOWN_SECTIONS = {
            "情境", "判断过程", "可执行方向",
            "ROOT_PARADIGM收窄", "专属SOUL", "进化方向", "进化日志",
        }
        sections: dict[str, str] = {}
        current_header = ""
        current_lines: list[str] = []

        for line in md_text.split("\n"):
            if line.startswith("## ") and line[3:].strip() in KNOWN_SECTIONS:
                if current_header:
                    sections[current_header] = "\n".join(current_lines).strip()
                current_header = line[3:].strip()
                current_lines = []
            else:
                current_lines.append(line)
        if current_header:
            sections[current_header] = "\n".join(current_lines).strip()

        return sections

    # ── 写入 ──

    def write(self, record: HarnessRecord) -> str:
        """写入一个harness记录，返回harness_id

        创建目录结构：harnesses/{harness_id}/HARNESS.md + meta.json
        """
        if not record.situation.strip():
            logger.warning("Harness missing situation — skipping write")
            return ""
        if not record.judgment.strip():
            logger.warning("Harness missing judgment — skipping write (degrades to structure-only)")
            return ""
        if not record.structure.strip():
            logger.warning("Harness missing structure — skipping write")
            return ""

        harness_dir = self.harnesses_dir / record.harness_id
        md_content = self._build_harness_md(record)
        meta = self._build_meta_json(record)

        temp_dir = Path(
            tempfile.mkdtemp(
                prefix=f".{record.harness_id}.tmp-",
                dir=str(self.harnesses_dir),
            )
        )
        backup_dir: Path | None = None

        try:
            (temp_dir / "HARNESS.md").write_text(md_content, encoding="utf-8")
            (temp_dir / "meta.json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            if harness_dir.exists():
                backup_dir = self.harnesses_dir / f".{record.harness_id}.bak-{uuid4().hex[:8]}"
                os.replace(harness_dir, backup_dir)

            os.replace(temp_dir, harness_dir)

            if backup_dir is not None and backup_dir.exists():
                shutil.rmtree(backup_dir, ignore_errors=True)
        except Exception as e:
            shutil.rmtree(temp_dir, ignore_errors=True)
            if backup_dir is not None and backup_dir.exists() and not harness_dir.exists():
                try:
                    os.replace(backup_dir, harness_dir)
                except Exception:
                    logger.warning("Could not restore harness backup for %s", record.harness_id, exc_info=True)
            logger.error("Failed to write harness %s atomically: %s", record.harness_id, e)
            return ""

        logger.info("Harness③ harness written: %s (v%d)", record.harness_id, record.version)
        return record.harness_id

    # ── 读取 ──

    def get(self, harness_id: str) -> HarnessRecord | None:
        """按ID获取当前版本的harness

        从 {harness_id}/HARNESS.md + meta.json 读取，合并成HarnessRecord
        """
        harness_dir = self.harnesses_dir / harness_id
        md_path = harness_dir / "HARNESS.md"
        meta_path = harness_dir / "meta.json"

        # 兼容旧格式：如果目录不存在但旧JSON文件存在，从JSON读取
        old_json_path = self.harnesses_dir / f"{harness_id}.json"
        if not md_path.exists() and old_json_path.exists():
            try:
                payload = json.loads(old_json_path.read_text(encoding="utf-8"))
                return HarnessRecord(**payload)
            except Exception as e:
                logger.warning("Could not load harness %s (old format): %s", harness_id, e)
                return None

        if not md_path.exists():
            return None

        try:
            # 读meta.json
            meta = {}
            if meta_path.exists():
                meta = json.loads(meta_path.read_text(encoding="utf-8"))

            # 读HARNESS.md，解析各section
            md_text = md_path.read_text(encoding="utf-8")
            sections = self._parse_harness_md(md_text)

            # 合并成HarnessRecord
            record = HarnessRecord(
                harness_id=meta.get("harness_id", harness_id),
                name=meta.get("name", ""),
                category=meta.get("category", ""),
                situation=sections.get("情境", ""),
                judgment=sections.get("判断过程", ""),
                structure=sections.get("可执行方向", ""),
                root_paradigm_fragment=sections.get("ROOT_PARADIGM收窄", ""),
                soul=sections.get("专属SOUL", ""),
                api_config_name=meta.get("api_config_name", ""),
                tags=meta.get("tags", []),
                track=meta.get("track", "harness"),
                created_at=meta.get("created_at", ""),
                version=meta.get("version", 1),
                parent_version_id=meta.get("parent_version_id", ""),
                evolution_reason=meta.get("evolution_reason", ""),
                evolution_direction=meta.get("evolution_direction", sections.get("进化方向", "")),
            )
            return record
        except Exception as e:
            logger.warning("Could not load harness %s: %s", harness_id, e)
            return None

    def get_version(self, harness_id: str, version: int) -> HarnessRecord | None:
        """获取指定版本的harness（从archive目录）"""
        archive_dir = self.archive_dir / f"{harness_id}_v{version}"
        md_path = archive_dir / "HARNESS.md"
        meta_path = archive_dir / "meta.json"

        # 兼容旧格式
        old_json_path = self.archive_dir / f"{harness_id}_v{version}.json"
        if not md_path.exists() and old_json_path.exists():
            try:
                payload = json.loads(old_json_path.read_text(encoding="utf-8"))
                return HarnessRecord(**payload)
            except Exception as e:
                logger.warning("Could not load harness %s v%d (old format): %s", harness_id, version, e)
                return None

        if not md_path.exists():
            return None
        try:
            meta = {}
            if meta_path.exists():
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            md_text = md_path.read_text(encoding="utf-8")
            sections = self._parse_harness_md(md_text)
            record = HarnessRecord(
                harness_id=meta.get("harness_id", harness_id),
                name=meta.get("name", ""),
                category=meta.get("category", ""),
                situation=sections.get("情境", ""),
                judgment=sections.get("判断过程", ""),
                structure=sections.get("可执行方向", ""),
                root_paradigm_fragment=sections.get("ROOT_PARADIGM收窄", ""),
                soul=sections.get("专属SOUL", ""),
                api_config_name=meta.get("api_config_name", ""),
                tags=meta.get("tags", []),
                track=meta.get("track", "harness"),
                created_at=meta.get("created_at", ""),
                version=meta.get("version", version),
                parent_version_id=meta.get("parent_version_id", ""),
                evolution_reason=meta.get("evolution_reason", ""),
                evolution_direction=meta.get("evolution_direction", sections.get("进化方向", "")),
            )
            return record
        except Exception as e:
            logger.warning("Could not load harness %s v%d: %s", harness_id, version, e)
            return None

    # ── 列表 ──

    def list_harnesses(
        self,
        tags: list[str] | None = None,
        track: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """列出harness摘要，不返回全文

        返回摘要列表：harness_id, situation(截断), tags, track, version, created_at
        可按tags和track过滤。
        """
        results: list[dict] = []
        # 新格式：目录结构
        for entry in sorted(self.harnesses_dir.iterdir()):
            if not entry.is_dir():
                continue
            if entry.name == "archive":
                continue
            meta_path = entry / "meta.json"
            if not meta_path.exists():
                continue
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            # 过滤
            if track and meta.get("track") != track:
                continue
            if tags:
                record_tags = set(meta.get("tags", []))
                if not record_tags.issuperset(tags):
                    continue
            # 从HARNESS.md读situation摘要
            md_path = entry / "HARNESS.md"
            situation = ""
            if md_path.exists():
                sections = self._parse_harness_md(md_path.read_text(encoding="utf-8"))
                situation = sections.get("情境", "")[:100]
            results.append({
                "harness_id": meta.get("harness_id", entry.name),
                "name": meta.get("name", ""),
                "category": meta.get("category", ""),
                "situation": situation,
                "tags": meta.get("tags", []),
                "track": meta.get("track", ""),
                "version": meta.get("version", 1),
                "created_at": meta.get("created_at", ""),
            })
            if len(results) >= limit:
                break
        return results

    # ── 检索 ──

    def search(self, query: str, limit: int = 5) -> list[HarnessRecord]:
        """用情境描述检索相关的harness

        复用TripletStore的混合分词策略。
        """
        query_chars = set(query.lower())
        query_words = set(re.findall(r'[a-zA-Z0-9]+', query.lower()))
        if not query_chars and not query_words:
            return []

        scored: list[tuple[float, str]] = []  # (score, harness_id)
        for entry in self.harnesses_dir.iterdir():
            if not entry.is_dir():
                continue
            if entry.name == "archive":
                continue
            md_path = entry / "HARNESS.md"
            meta_path = entry / "meta.json"
            if not md_path.exists():
                continue

            # 从HARNESS.md和机器元数据构建检索文本
            md_text = md_path.read_text(encoding="utf-8").lower()
            meta_text = ""
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    meta_text = " ".join([
                        str(meta.get("name", "")),
                        str(meta.get("category", "")),
                        " ".join(meta.get("tags", [])),
                    ])
                except Exception:
                    pass
            text = md_text + " " + meta_text

            entry_words = set(re.findall(r'[a-zA-Z0-9]+', text))
            word_overlap = len(query_words & entry_words)
            entry_chars = set(text)
            char_overlap = len(query_chars & entry_chars)
            score = word_overlap * 3 + char_overlap * 0.1
            if score > 0.3:
                scored.append((score, entry.name))

        scored.sort(key=lambda x: x[0], reverse=True)
        results: list[HarnessRecord] = []
        for _, harness_id in scored[:limit]:
            record = self.get(harness_id)
            if record:
                results.append(record)
        return results

    # ── 进化（版本化） ──

    def evolve(self, harness_id: str, updated: HarnessRecord, reason: str = "") -> str:
        """进化一个harness：旧版本目录归档，写入新版本目录

        返回新版本的harness_id（和原来相同，version+1）。
        """
        old = self.get(harness_id)
        if not old:
            logger.warning("Cannot evolve non-existent harness: %s", harness_id)
            return ""

        old_version = old.version

        # 归档旧版本目录
        old_dir = self.harnesses_dir / harness_id
        archive_dest = self.archive_dir / f"{harness_id}_v{old_version}"
        if old_dir.exists():
            # 如果archive目标已存在，先删除
            if archive_dest.exists():
                import shutil
                shutil.rmtree(archive_dest, ignore_errors=True)
            old_dir.rename(archive_dest)

        # 写入新版本
        updated.harness_id = harness_id
        updated.version = old_version + 1
        updated.parent_version_id = harness_id
        updated.evolution_reason = reason

        # 用write()创建新目录
        new_id = self.write(updated)
        if not new_id:
            # 写入失败，尝试恢复旧版本
            if archive_dest.exists():
                archive_dest.rename(old_dir)
            return ""

        logger.info("Harness③ harness evolved: %s v%d → v%d", harness_id, old_version, updated.version)
        return harness_id
