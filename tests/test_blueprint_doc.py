"""blueprint_doc.py — ssot/*.md 를 항목 단위로 읽고 쓴다.

산문 덩어리는 병합할 수 없다. 재관찰이 사람의 편집을 덮지 않으려면 문서가
항목으로 쪼개져 있어야 하고, 항목마다 누가 소유하는지(근거 라벨)가 붙어야
한다. 이 파일이 그 계약을 고정한다.
"""

from __future__ import annotations

import tempfile
import unicodedata
import unittest
from pathlib import Path

from scripts.blueprint_doc import (
    EVIDENCE_LABELS,
    EVIDENCE_OBSERVED,
    EVIDENCE_OURS,
    NOTE_KIND_ABSENT,
    NOTE_KIND_PLAIN,
    Item,
    Note,
    parse_items,
    read_doc,
    render_items,
    unlabelled,
    write_doc,
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
        self.assertEqual([(note.kind, note.text) for note in items[0].notes],
                          [(NOTE_KIND_PLAIN, "관찰: 최근 회차에 없음")])

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
                 notes=[Note(NOTE_KIND_ABSENT, "관찰: 최근 회차에 없음")]),
            Item(id="F-002", title="다크 모드", evidence=EVIDENCE_OURS,
                 body="원본에 없다. 우리는 넣는다."),
            # 사람이 본문에 쓴 인용문. 마커가 없으므로 노트로 새지 않는다.
            Item(id="F-003", title="톤", evidence=EVIDENCE_OURS,
                 body="> 인용문입니다.\n일반 문장."),
        ]

        reparsed = parse_items(render_items(original))

        self.assertEqual(reparsed, original)


class TestDocFiles(unittest.TestCase):
    def test_a_missing_document_reads_as_no_items(self):
        """첫 회차에는 ssot/ 가 비어 있다. 없는 파일은 오류가 아니라 빈 문서다."""
        with tempfile.TemporaryDirectory() as temp:
            self.assertEqual(read_doc(Path(temp) / "features.md"), [])

    def test_a_written_document_reads_back_unchanged(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "features.md"
            items = [Item(id="F-001", title="로그인", evidence=EVIDENCE_OBSERVED,
                          body="이메일과 비밀번호를 받는다.")]

            write_doc(path, items, heading="기능")

            self.assertIn("# 기능", path.read_text(encoding="utf-8"))
            self.assertEqual(read_doc(path), items)

    def test_writing_leaves_no_temporary_file_behind(self):
        """제자리 덮어쓰기 금지가 이 레포의 규칙이다 (CONVENTIONS.md 원자성)."""
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            write_doc(directory / "features.md",
                      [Item(id="F-001", title="로그인", evidence=EVIDENCE_OBSERVED)])

            self.assertEqual([p.name for p in directory.iterdir()], ["features.md"])


class TestLabelValidation(unittest.TestCase):
    def test_an_item_without_a_label_is_reported(self):
        """검사되지 않는 규칙은 규칙이 아니다."""
        items = parse_items("## F-001 피드\n\n카드 3장.\n")

        self.assertEqual([item.id for item in unlabelled(items)], ["F-001"])

    def test_an_unknown_label_is_reported_too(self):
        """오타난 라벨이 통과하면 병합이 그 항목을 사람 것으로 오인한다."""
        items = parse_items("## F-001 피드\n근거: 추측\n\n카드 3장.\n")

        self.assertEqual([item.id for item in unlabelled(items)], ["F-001"])

    def test_every_valid_label_passes(self):
        text = "".join(
            f"## F-00{index} 항목\n근거: {label}\n\n본문.\n\n"
            for index, label in enumerate(sorted(EVIDENCE_LABELS)))

        self.assertEqual(unlabelled(parse_items(text)), [])

    def test_a_decomposed_label_is_recognised(self):
        """macOS 가 만드는 NFD 라벨도 같은 라벨이다.

        어긋나면 사람이 `우리 결정` 으로 바꾼 항목이 보호되지 않고 덮인다.
        """
        decomposed = unicodedata.normalize("NFD", EVIDENCE_OURS)
        self.assertNotEqual(decomposed, EVIDENCE_OURS)   # 전제 확인

        items = parse_items(f"## F-001 피드\n근거: {decomposed}\n\n카드 3장.\n")

        self.assertEqual(unlabelled(items), [])
        self.assertEqual(items[0].evidence, EVIDENCE_OURS)


if __name__ == "__main__":
    unittest.main()
