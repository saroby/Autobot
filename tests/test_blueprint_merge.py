"""blueprint_merge.py — 재관찰이 사람의 편집을 덮지 않게 하는 규칙.

근거 라벨이 곧 소유권이다. 이 파일이 지키는 단 하나의 성질: 사람이 넣은
"부족한 부분"은 몇 번을 재관찰해도 그대로 있다. 그 보장이 없으면 청사진을
고칠 이유가 없어진다.
"""

from __future__ import annotations

import unittest

from scripts.blueprint_doc import EVIDENCE_OBSERVED, EVIDENCE_OURS, Item
from scripts.blueprint_merge import NOTE_ABSENT, NOTE_CONFLICT_PREFIX, merge_items


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


class TestDisappearedItems(unittest.TestCase):
    def test_an_item_the_observation_no_longer_sees_is_marked_not_deleted(self):
        """지우면 그 항목을 근거로 삼은 사람의 결정이 붕 뜬다."""
        existing = [Item(id="F-001", title="피드", evidence=EVIDENCE_OBSERVED)]

        merged = merge_items(existing, [])

        self.assertEqual([item.id for item in merged], ["F-001"])
        self.assertIn(NOTE_ABSENT, merged[0].notes)

    def test_the_absent_note_is_not_stacked_on_every_round(self):
        existing = [Item(id="F-001", title="피드", evidence=EVIDENCE_OBSERVED,
                         notes=[NOTE_ABSENT])]

        merged = merge_items(existing, [])

        self.assertEqual(merged[0].notes, [NOTE_ABSENT])

    def test_an_item_the_person_owns_is_not_marked_absent(self):
        """`우리 결정` 항목은 원본에 없는 것이 정상이다 — 그것이 추가한 이유다."""
        existing = [Item(id="F-002", title="다크 모드", evidence=EVIDENCE_OURS)]

        merged = merge_items(existing, [])

        self.assertEqual(merged[0].notes, [])


class TestConflictWithHumanDecision(unittest.TestCase):
    def test_a_conflicting_observation_is_appended_as_a_note(self):
        """지우지도 덮지도 않는다 — 판단은 사람이 한다."""
        existing = [Item(id="F-001", title="피드", evidence=EVIDENCE_OURS,
                         body="카드 3장 + 필터")]
        incoming = [Item(id="F-001", title="피드", evidence=EVIDENCE_OBSERVED,
                         body="카드 5장")]

        merged = merge_items(existing, incoming)

        self.assertEqual(merged[0].body, "카드 3장 + 필터")
        self.assertEqual(merged[0].notes, [f"{NOTE_CONFLICT_PREFIX}카드 5장"])

    def test_an_agreeing_observation_adds_no_note(self):
        existing = [Item(id="F-001", title="피드", evidence=EVIDENCE_OURS,
                         body="카드 5장")]
        incoming = [Item(id="F-001", title="피드", evidence=EVIDENCE_OBSERVED,
                         body="카드 5장")]

        merged = merge_items(existing, incoming)

        self.assertEqual(merged[0].notes, [])

    def test_a_new_conflict_replaces_the_previous_one(self):
        """회차마다 쌓이면 사람이 어느 것이 최신인지 알 수 없다."""
        existing = [Item(id="F-001", title="피드", evidence=EVIDENCE_OURS,
                         body="카드 3장 + 필터",
                         notes=[f"{NOTE_CONFLICT_PREFIX}카드 5장"])]
        incoming = [Item(id="F-001", title="피드", evidence=EVIDENCE_OBSERVED,
                         body="카드 7장")]

        merged = merge_items(existing, incoming)

        self.assertEqual(merged[0].notes, [f"{NOTE_CONFLICT_PREFIX}카드 7장"])

    def test_an_observation_with_no_body_leaves_the_standing_conflict_alone(self):
        """본문을 못 뽑은 회차는 새 관찰이 아니다 — 알린 불일치를 지우지 않는다."""
        existing = [Item(id="F-001", title="피드", evidence=EVIDENCE_OURS,
                         body="카드 3장 + 필터",
                         notes=[f"{NOTE_CONFLICT_PREFIX}카드 5장"])]
        incoming = [Item(id="F-001", title="피드", evidence=EVIDENCE_OBSERVED, body="")]

        merged = merge_items(existing, incoming)

        self.assertEqual(merged[0].notes, [f"{NOTE_CONFLICT_PREFIX}카드 5장"])

    def test_a_conflict_clears_once_the_observation_agrees(self):
        existing = [Item(id="F-001", title="피드", evidence=EVIDENCE_OURS,
                         body="카드 5장",
                         notes=[f"{NOTE_CONFLICT_PREFIX}카드 3장"])]
        incoming = [Item(id="F-001", title="피드", evidence=EVIDENCE_OBSERVED,
                         body="카드 5장")]

        merged = merge_items(existing, incoming)

        self.assertEqual(merged[0].notes, [])


if __name__ == "__main__":
    unittest.main()
