"""blueprint_doc.py — ssot/*.md 를 항목 단위로 읽고 쓴다.

산문 덩어리는 병합할 수 없다. 재관찰이 사람의 편집을 덮지 않으려면 문서가
항목으로 쪼개져 있어야 하고, 항목마다 누가 소유하는지(근거 라벨)가 붙어야
한다. 이 파일이 그 계약을 고정한다.
"""

from __future__ import annotations

import unittest

from scripts.blueprint_doc import (
    EVIDENCE_OBSERVED,
    EVIDENCE_OURS,
    Item,
    parse_items,
)


class TestParseItems(unittest.TestCase):
    def test_one_item_carries_its_id_title_evidence_and_body(self):
        text = """# 기능

## F-012 피드 무한 스크롤
근거: 관찰 · observed/inventory.md#feed
<img src="../observed/raw/03-feed.png" width="220">

스크롤 끝에서 다음 페이지를 불러온다.
"""

        items = parse_items(text)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].id, "F-012")
        self.assertEqual(items[0].title, "피드 무한 스크롤")
        self.assertEqual(items[0].evidence, EVIDENCE_OBSERVED)
        self.assertEqual(items[0].evidence_ref, "observed/inventory.md#feed")
        self.assertEqual(items[0].images, ["../observed/raw/03-feed.png"])
        self.assertEqual(items[0].body, "스크롤 끝에서 다음 페이지를 불러온다.")

    def test_blockquote_lines_are_machine_notes_not_body(self):
        """노트가 본문에 섞이면 다음 병합이 같은 경고를 다시 쌓는다."""
        text = """## F-012 피드
근거: 관찰

스크롤 끝에서 다음 페이지를 불러온다.

> 관찰: 최근 회차에 없음
"""

        items = parse_items(text)

        self.assertEqual(items[0].body, "스크롤 끝에서 다음 페이지를 불러온다.")
        self.assertEqual(items[0].notes, ["관찰: 최근 회차에 없음"])


if __name__ == "__main__":
    unittest.main()
