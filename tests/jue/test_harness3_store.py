import json

from jue.harness3.store import HarnessRecord, HarnessStore


def test_harness_md_metadata_includes_name_category_and_readable_created_at(tmp_path):
    store = HarnessStore(store_dir=tmp_path / "harness3")
    record = HarnessRecord(
        harness_id="hr-test123456",
        name="意图-目标缝隙处理",
        category="对话判断",
        situation="用户目标和真实意图可能不一致。",
        judgment="先识别缝隙，再决定是否追问。",
        structure="让目标重新忠实于意图。",
        created_at="2026-04-24T08:32:45+00:00",
    )

    harness_id = store.write(record)

    assert harness_id == "hr-test123456"
    md = (tmp_path / "harness3" / "harnesses" / harness_id / "HARNESS.md").read_text(encoding="utf-8")
    assert md.startswith(
        "# Harness: hr-test123456\n"
        "名称：意图-目标缝隙处理\n"
        "分类：对话判断\n"
        "创建时间：2026-04-24 08:32\n"
        "版本：v1\n"
    )

    meta = json.loads(
        (tmp_path / "harness3" / "harnesses" / harness_id / "meta.json").read_text(encoding="utf-8")
    )
    assert meta["name"] == "意图-目标缝隙处理"
    assert meta["category"] == "对话判断"

    loaded = store.get(harness_id)
    assert loaded is not None
    assert loaded.name == "意图-目标缝隙处理"
    assert loaded.category == "对话判断"
