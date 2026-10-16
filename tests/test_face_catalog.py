from __future__ import annotations

from collections import Counter

import pytest

from astrbot_plugin_qq_enhance.face_names import (
    QQ_FACE_NAMES,
    QQ_FACES,
    lookup_qq_faces,
)


def test_pinned_catalog_preserves_upstream_categories_and_hidden_chain_stages():
    assert len(QQ_FACES) == len(QQ_FACE_NAMES) == 329
    assert Counter(face.category for face in QQ_FACES) == {
        "normal": 227,
        "super": 87,
        "random": 3,
        "chain": 12,
    }
    assert len(lookup_qq_faces(category="super")) == 102
    assert {face["id"] for face in lookup_qq_faces(category="random")} == {
        "114",
        "358",
        "359",
    }
    # An older low ID can be a super face; category cannot be inferred from IDs.
    assert lookup_qq_faces("5")[0]["is_super"] is True
    assert lookup_qq_faces("428")[0]["is_super"] is False
    assert lookup_qq_faces("393")[0] == {
        "id": "393",
        "name": "新年中龙",
        "category": "chain",
        "is_super": True,
        "hidden": True,
    }


@pytest.mark.parametrize(
    "query,expected_ids",
    [
        ("0", ["0"]),
        ("311", ["311"]),
        ("[打 call]", ["311"]),
        ("超级ＯＫ", ["398"]),
        ("/微笑", ["14", "452"]),
        ("超级", ["364", "375", "398", "401"]),
        ("不存在的表情", []),
    ],
)
def test_face_lookup_normalizes_names_and_keeps_duplicate_ids(query, expected_ids):
    assert [face["id"] for face in lookup_qq_faces(query)] == expected_ids


def test_face_lookup_prefers_exact_names_and_applies_category_filter():
    # Other faces contain this name, but an exact name wins over substrings.
    assert [face["id"] for face in lookup_qq_faces("赞")] == ["76"]
    assert lookup_qq_faces("篮球", category="normal") == []
    assert [face["id"] for face in lookup_qq_faces("篮球", category="super")] == ["114"]
    assert len(lookup_qq_faces()) == 329
