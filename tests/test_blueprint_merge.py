"""blueprint_merge.py — 재관찰이 사람의 편집을 덮지 않게 하는 규칙.

근거 라벨이 곧 소유권이다. 이 파일이 지키는 단 하나의 성질: 사람이 넣은
"부족한 부분"은 몇 번을 재관찰해도 그대로 있다. 그 보장이 없으면 청사진을
고칠 이유가 없어진다.
"""

from __future__ import annotations

import unittest

from scripts.blueprint_doc import EVIDENCE_OBSERVED, EVIDENCE_OURS, Item
from scripts.blueprint_merge import merge_items


class TestMergeOwnership(unittest.TestCase):
    def test_an_observed_item_is_refreshed_by_the_new_observation(self):
        existing = [Item(id="F-001", title="피드", evidence=EVIDENCE_OBSERVED,
                         body="카드 3장")]
        incoming = [Item(id="F-001", title="피드", evidence=EVIDENCE_OBSERVED,
                         body="카드 5장")]

        merged = merge_items(existing, incoming)

        self.assertEqual([item.body for item in merged], ["카드 5장"])

    def test_an_item_the_person_owns_is_never_rewritten(self):
        """사람이 라벨을 `우리 결정` 으로 바꾸면 그 항목은 보호 영역으로 들어간다."""
        existing = [Item(id="F-001", title="피드", evidence=EVIDENCE_OURS,
                         body="카드 3장 + 우리가 추가한 필터")]
        incoming = [Item(id="F-001", title="피드", evidence=EVIDENCE_OBSERVED,
                         body="카드 5장")]

        merged = merge_items(existing, incoming)

        self.assertEqual(merged[0].body, "카드 3장 + 우리가 추가한 필터")
        self.assertEqual(merged[0].evidence, EVIDENCE_OURS)

    def test_a_newly_observed_item_is_appended_after_the_existing_order(self):
        """사람이 정리해 둔 순서를 재관찰이 흩뜨리지 않는다."""
        existing = [Item(id="F-002", title="검색", evidence=EVIDENCE_OBSERVED),
                    Item(id="F-001", title="피드", evidence=EVIDENCE_OBSERVED)]
        incoming = [Item(id="F-003", title="설정", evidence=EVIDENCE_OBSERVED)]

        merged = merge_items(existing, incoming)

        self.assertEqual([item.id for item in merged], ["F-002", "F-001", "F-003"])


if __name__ == "__main__":
    unittest.main()
