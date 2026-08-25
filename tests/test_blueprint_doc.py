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
    Document,
    DocumentWriteRefused,
    Item,
    Note,
    image_line,
    parse_document,
    parse_items,
    read_doc,
    render_document,
    render_items,
    malformed_headings,
    unclosed_fence,
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
        self.assertEqual(items[0].images,
                         ['<img src="../observed/raw/03-feed.png" width="220">'])
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

    def test_a_line_that_mixes_prose_and_an_image_stays_in_the_body(self):
        """이미지 옆의 설명은 사람이 쓴 글이다 — 이미지로 흡수되면 저장 한 번에 사라진다."""
        text = """## F-012 피드
근거: 우리 결정

핵심은 필터다 <img src="../observed/raw/03-feed.png" alt="피드" width="600"> 처럼 붙인다.
"""

        items = parse_items(text)

        self.assertEqual(items[0].images, [])
        self.assertEqual(
            items[0].body,
            '핵심은 필터다 <img src="../observed/raw/03-feed.png" alt="피드" '
            'width="600"> 처럼 붙인다.')

    def test_an_image_line_keeps_the_attributes_the_person_wrote(self):
        """`src` 만 뽑아 다시 쓰면 사람이 정한 `alt`·`width` 를 되살릴 방법이 없다."""
        original = '<img src="../observed/raw/03-feed.png" alt="피드" width="600">'

        items = parse_items(f"## F-012 피드\n근거: 관찰\n{original}\n")

        self.assertEqual(items[0].images, [original])
        self.assertIn(original, render_items(items))

    def test_a_blockquote_without_the_marker_stays_in_the_body(self):
        """`>` 는 사람이 쓰는 평범한 마크다운이다 — 마커 없는 인용문은 본문이다."""
        text = """## F-012 피드
근거: 관찰

> 인용문입니다.
"""

        items = parse_items(text)

        self.assertEqual(items[0].notes, [])
        self.assertEqual(items[0].body, "> 인용문입니다.")


class TestHeadingsThatAreNotItems(unittest.TestCase):
    """항목이 되지 못한 `## ` 줄은 조용히 직전 항목 본문으로 흡수된다.

    그 직전 항목이 `관찰` 이면 다음 병합이 본문을 통째로 갈아끼우므로 사람이
    손으로 넣은 섹션이 지워진다. 파서가 막을 수는 없지만 검사가 잡을 수는 있다.
    """

    def test_a_section_without_an_id_is_reported(self):
        text = """## F-001 피드
근거: 관찰

카드 3장.

## 우리가 빠뜨린 것 — 오프라인 모드
근거: 우리 결정

네트워크가 없을 때 캐시를 보여줘야 한다.
"""

        stray = malformed_headings(text)

        self.assertEqual(stray, [(6, "## 우리가 빠뜨린 것 — 오프라인 모드")])

    def test_an_id_outside_the_five_prefixes_is_not_an_item(self):
        """접두사는 `V-`/`P-`/`F-`/`E-`/`D-` 다섯뿐이다 — 오타를 항목으로 받으면 안 된다."""
        text = "## X-001 피드\n근거: 관찰\n\n카드 3장.\n"

        self.assertEqual(parse_items(text), [])
        self.assertEqual(malformed_headings(text), [(1, "## X-001 피드")])

    def test_every_spec_prefix_is_an_item(self):
        text = "".join(f"## {prefix}-001 항목\n근거: 관찰\n\n본문.\n\n"
                       for prefix in "VPFED")

        self.assertEqual([item.id for item in parse_items(text)],
                         ["V-001", "P-001", "F-001", "E-001", "D-001"])
        self.assertEqual(malformed_headings(text), [])

    def test_a_heading_inside_a_code_fence_does_not_split_the_item(self):
        """코드펜스 안의 `## F-999` 는 사람이 쓴 예시다 — 항목이 아니다."""
        text = """## F-001 피드
근거: 관찰

이렇게 씁니다:

```markdown
## F-999 가짜
근거: 관찰
```
"""

        items = parse_items(text)

        self.assertEqual([item.id for item in items], ["F-001"])
        self.assertEqual(unlabelled(items), [])
        self.assertIn("## F-999 가짜", items[0].body)
        self.assertEqual(malformed_headings(text), [])

    def test_a_tilde_line_inside_a_backtick_fence_does_not_close_it(self):
        """마크다운 예시를 보여주는 평범한 문서다 — 펜스는 같은 마커로만 닫힌다."""
        text = """# 기능

## F-001 피드
근거: 관찰

마크다운 예시:

```markdown
~~~
```

## F-002 오프라인 모드
근거: 우리 결정

캐시가 없으면 이 서비스는 반쪽이다. 이 문장은 사람이 썼다.
"""

        items = parse_items(text)

        self.assertEqual([item.id for item in items], ["F-001", "F-002"])
        self.assertEqual(items[1].evidence, EVIDENCE_OURS)
        self.assertIn("이 문장은 사람이 썼다", items[1].body)
        self.assertEqual(malformed_headings(text), [])
        self.assertIsNone(unclosed_fence(text))

    def test_a_fence_left_open_is_named_so_the_loss_is_not_silent(self):
        """닫히지 않은 펜스는 뒤따르는 항목을 삼킨다 — 삼키더라도 소리는 내야 한다."""
        text = """# 기능

## F-001 피드
근거: 관찰

예시 코드:

```swift
let x = 1

## F-002 오프라인 모드
근거: 우리 결정

캐시가 없으면 이 서비스는 반쪽이다. 이 문장은 사람이 썼다.
"""

        # 파서는 여전히 삼킨다 — 되살릴 방법이 없다. 그러나 무성이면 안 된다.
        self.assertEqual([item.id for item in parse_items(text)], ["F-001"])
        self.assertEqual(unclosed_fence(text), (8, "```swift"))

    def test_a_balanced_fence_leaves_nothing_open(self):
        """정상 문서가 `unclosed_fence` 에 걸리면 아무도 검사기를 안 믿는다."""
        text = "## F-001 피드\n근거: 관찰\n\n```swift\nlet x = 1\n```\n"

        self.assertIsNone(unclosed_fence(text))

    def test_a_subheading_is_ordinary_body(self):
        """`### ` 는 항목 구분자가 아니다 — 사람이 본문에 쓰는 평범한 마크다운이다."""
        text = "## F-001 피드\n근거: 관찰\n\n### 세부\n\n카드 3장.\n"

        self.assertEqual(malformed_headings(text), [])
        self.assertIn("### 세부", parse_items(text)[0].body)


class TestRenderRoundTrip(unittest.TestCase):
    def test_parsing_then_rendering_preserves_every_field(self):
        """병합은 파싱→수정→렌더링이다. 라운드트립이 새면 조용히 내용을 잃는다."""
        original = [
            Item(id="F-001", title="로그인", evidence=EVIDENCE_OBSERVED,
                 evidence_ref="observed/inventory.md#login",
                 images=[image_line("../observed/raw/01-login.png")],
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


class TestPreamble(unittest.TestCase):
    """첫 항목 앞의 제목과 안내문도 사람이 쓴 글이다."""

    TEXT = """# 기능

이 문서는 관찰로 채워지고, 부족한 부분은 우리가 채운다.
읽는 순서: F-001 부터.

## F-001 피드
근거: 관찰

카드 3장.
"""

    def test_the_lines_before_the_first_item_are_kept(self):
        document = parse_document(self.TEXT)

        self.assertEqual(document.preamble,
                         "# 기능\n\n이 문서는 관찰로 채워지고, 부족한 부분은 우리가 "
                         "채운다.\n읽는 순서: F-001 부터.")
        self.assertEqual([item.id for item in document.items], ["F-001"])

    def test_rendering_puts_the_preamble_back(self):
        """`parse_document` 와 `render_document` 가 역함수가 아니면 저장이 글을 지운다."""
        document = parse_document(self.TEXT)

        self.assertEqual(render_document(document), self.TEXT)
        self.assertEqual(parse_document(render_document(document)), document)

    def test_a_document_with_no_preamble_round_trips_too(self):
        text = "## F-001 피드\n근거: 관찰\n\n카드 3장.\n"

        self.assertEqual(render_document(parse_document(text)), text)


class TestDocFiles(unittest.TestCase):
    def test_a_missing_document_reads_as_an_empty_document(self):
        """첫 회차에는 ssot/ 가 비어 있다. 없는 파일은 오류가 아니라 빈 문서다."""
        with tempfile.TemporaryDirectory() as temp:
            self.assertEqual(read_doc(Path(temp) / "features.md"), Document())

    def test_a_written_document_reads_back_unchanged(self):
        """읽은 문서를 그대로 다시 쓰는 실제 경로 — 머리말째로 같아야 한다."""
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "features.md"
            path.write_text(TestPreamble.TEXT, encoding="utf-8")

            document = read_doc(path)
            write_doc(path, document)

            self.assertEqual(path.read_text(encoding="utf-8"), TestPreamble.TEXT)
            self.assertEqual(read_doc(path), document)

    def test_writing_no_items_over_a_document_that_has_some_is_refused(self):
        """항목 0개는 '빈 문서' 일 수도 '못 읽었다' 일 수도 있다 — 후자를 쓰면 파일이 빈다."""
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "features.md"
            path.write_text("## X-001 피드\n근거: 관찰\n\n카드 3장.\n",
                            encoding="utf-8")

            with self.assertRaises(DocumentWriteRefused):
                write_doc(path, read_doc(path))

            self.assertIn("카드 3장.", path.read_text(encoding="utf-8"))

    def test_writing_an_empty_document_to_a_new_path_is_fine(self):
        """첫 회차에는 항목이 0개인 것이 정상이다."""
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "features.md"

            write_doc(path, Document())

            self.assertEqual(path.read_text(encoding="utf-8"), "")

    def test_writing_leaves_no_temporary_file_behind(self):
        """제자리 덮어쓰기 금지가 이 레포의 규칙이다 (CONVENTIONS.md 원자성)."""
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            write_doc(directory / "features.md", Document(items=[
                Item(id="F-001", title="로그인", evidence=EVIDENCE_OBSERVED)]))

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


class TestUnicodeNormalization(unittest.TestCase):
    """제목·본문·노트도 근거 라벨과 같은 이유로 NFC 여야 한다.

    macOS 는 NFD 를 만든다 — 사람이 macOS 에서 편집하거나 관찰 레이어가 NFD 로
    쓰면, 글자로는 같은 본문이 `!=` 로 갈린다. 정규화하지 않은 필드가 하나라도
    있으면 그 필드를 비교하는 쪽(드리프트 리포트, 충돌 검사)이 매 회차 가짜
    변화를 본다.
    """

    def test_a_decomposed_title_is_normalized(self):
        decomposed_title = unicodedata.normalize("NFD", "피드")
        self.assertNotEqual(decomposed_title, "피드")   # 전제 확인

        items = parse_items(f"## F-001 {decomposed_title}\n근거: 관찰\n\n카드 3장.\n")

        self.assertEqual(items[0].title, "피드")

    def test_a_decomposed_body_is_normalized(self):
        composed_body = "카드 3장."
        decomposed_body = unicodedata.normalize("NFD", composed_body)
        self.assertNotEqual(decomposed_body, composed_body)   # 전제 확인

        items = parse_items(f"## F-001 피드\n근거: 관찰\n\n{decomposed_body}\n")

        self.assertEqual(items[0].body, composed_body)

    def test_a_decomposed_note_is_normalized(self):
        composed_note = "관찰: 최근 회차에 없음"
        decomposed_note = unicodedata.normalize("NFD", composed_note)
        self.assertNotEqual(decomposed_note, composed_note)   # 전제 확인

        items = parse_items(
            f"## F-001 피드\n근거: 관찰\n\n카드 3장.\n\n"
            f"> ⟦auto:absent⟧ {decomposed_note}\n")

        self.assertEqual(items[0].notes[0].text, composed_note)


if __name__ == "__main__":
    unittest.main()
