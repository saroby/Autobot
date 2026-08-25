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
    render_items,
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

> ⟦auto⟧ 관찰: 최근 회차에 없음
"""

        items = parse_items(text)

        self.assertEqual(items[0].body, "스크롤 끝에서 다음 페이지를 불러온다.")
        self.assertEqual(items[0].notes, ["관찰: 최근 회차에 없음"])

    def test_a_blockquote_without_the_marker_stays_in_the_body(self):
        """`>` 는 사람이 쓰는 평범한 마크다운이다 — 마커 없는 인용문은 본문이다."""
        text = """## F-012 피드
근거: 관찰

> 인용문입니다.
"""

        items = parse_items(text)

        self.assertEqual(items[0].notes, [])
        self.assertEqual(items[0].body, "> 인용문입니다.")


class TestRenderRoundTrip(unittest.TestCase):
    def test_parsing_then_rendering_preserves_every_field(self):
        """병합은 파싱→수정→렌더링이다. 라운드트립이 새면 조용히 내용을 잃는다."""
        original = [
            Item(id="F-001", title="로그인", evidence=EVIDENCE_OBSERVED,
                 evidence_ref="observed/inventory.md#login",
                 images=["../observed/raw/01-login.png"],
                 body="이메일과 비밀번호를 받는다.",
                 notes=["관찰: 최근 회차에 없음"]),
            Item(id="F-002", title="다크 모드", evidence=EVIDENCE_OURS,
                 body="원본에 없다. 우리는 넣는다."),
            # 사람이 본문에 쓴 인용문. 마커가 없으므로 노트로 새지 않는다.
            Item(id="F-003", title="톤", evidence=EVIDENCE_OURS,
                 body="> 인용문입니다.\n일반 문장."),
        ]

        reparsed = parse_items(render_items(original))

        self.assertEqual(reparsed, original)


if __name__ == "__main__":
    unittest.main()
