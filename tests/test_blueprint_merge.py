"""blueprint_merge.py — 재관찰이 사람의 편집을 덮지 않게 하는 규칙.

근거 라벨이 곧 소유권이다. 이 파일이 지키는 단 하나의 성질: 사람이 넣은
"부족한 부분"은 몇 번을 재관찰해도 그대로 있다. 그 보장이 없으면 청사진을
고칠 이유가 없어진다.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from scripts.blueprint_doc import (
    EVIDENCE_OBSERVED,
    EVIDENCE_OURS,
    EVIDENCE_PUBLIC,
    NOTE_KIND_ABSENT,
    NOTE_KIND_CONFLICT,
    Item,
    Note,
    parse_document,
    render_document,
)
from scripts.blueprint_merge import (
    NOTE_ABSENT,
    NOTE_CONFLICT_PREFIX,
    NOTE_KEEP_HINT,
    drift_report,
    merge_items,
)

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "blueprint_merge.py"


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

    def test_a_round_that_extracted_no_body_does_not_empty_an_observed_item(self):
        """본문을 못 뽑은 회차는 새 관찰이 아니다 — `우리 결정` 경로와 같은 가드다."""
        existing = [Item(id="F-001", title="피드", evidence=EVIDENCE_OBSERVED,
                         body="카드 3장", evidence_ref="observed/inventory.md#feed",
                         images=['<img src="../observed/raw/03-feed.png" width="220">'])]
        incoming = [Item(id="F-001", title="피드", evidence=EVIDENCE_OBSERVED, body="")]

        merged = merge_items(existing, incoming)

        self.assertEqual(merged[0].body, "카드 3장")
        self.assertEqual(merged[0].images,
                         ['<img src="../observed/raw/03-feed.png" width="220">'])
        self.assertEqual(merged[0].evidence_ref, "observed/inventory.md#feed")

    def test_a_round_with_no_body_still_fills_an_item_that_had_none(self):
        """지킬 것이 없으면 가드가 걸리지 않는다 — 새 관찰이 그대로 들어온다."""
        existing = [Item(id="F-001", title="피드", evidence=EVIDENCE_OBSERVED)]
        incoming = [Item(id="F-001", title="피드 목록", evidence=EVIDENCE_OBSERVED,
                         images=['<img src="a.png" width="220">'])]

        merged = merge_items(existing, incoming)

        self.assertEqual(merged[0].title, "피드 목록")
        self.assertEqual(merged[0].images, ['<img src="a.png" width="220">'])

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
        self.assertEqual([(note.kind, note.text) for note in merged[0].notes],
                          [(NOTE_KIND_CONFLICT, f"{NOTE_CONFLICT_PREFIX}카드 5장{NOTE_KEEP_HINT}")])

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
                         notes=[Note(NOTE_KIND_CONFLICT,
                                    f"{NOTE_CONFLICT_PREFIX}카드 5장{NOTE_KEEP_HINT}")])]
        incoming = [Item(id="F-001", title="피드", evidence=EVIDENCE_OBSERVED,
                         body="카드 7장")]

        merged = merge_items(existing, incoming)

        self.assertEqual([(note.kind, note.text) for note in merged[0].notes],
                          [(NOTE_KIND_CONFLICT, f"{NOTE_CONFLICT_PREFIX}카드 7장{NOTE_KEEP_HINT}")])

    def test_an_observation_with_no_body_leaves_the_standing_conflict_alone(self):
        """본문을 못 뽑은 회차는 새 관찰이 아니다 — 알린 불일치를 지우지 않는다."""
        existing = [Item(id="F-001", title="피드", evidence=EVIDENCE_OURS,
                         body="카드 3장 + 필터",
                         notes=[Note(NOTE_KIND_CONFLICT,
                                    f"{NOTE_CONFLICT_PREFIX}카드 5장{NOTE_KEEP_HINT}")])]
        incoming = [Item(id="F-001", title="피드", evidence=EVIDENCE_OBSERVED, body="")]

        merged = merge_items(existing, incoming)

        self.assertEqual([(note.kind, note.text) for note in merged[0].notes],
                          [(NOTE_KIND_CONFLICT, f"{NOTE_CONFLICT_PREFIX}카드 5장{NOTE_KEEP_HINT}")])

    def test_a_conflict_clears_once_the_observation_agrees(self):
        existing = [Item(id="F-001", title="피드", evidence=EVIDENCE_OURS,
                         body="카드 5장",
                         notes=[Note(NOTE_KIND_CONFLICT,
                                    f"{NOTE_CONFLICT_PREFIX}카드 3장{NOTE_KEEP_HINT}")])]
        incoming = [Item(id="F-001", title="피드", evidence=EVIDENCE_OBSERVED,
                         body="카드 5장")]

        merged = merge_items(existing, incoming)

        self.assertEqual(merged[0].notes, [])

    def test_a_note_the_person_edited_is_not_replaced_by_the_next_conflict(self):
        """마커를 지운 줄은 본문이 되어 병합이 건드리지 않는다.

        이것이 노트의 소유권 제스처다 — 근거 라벨을 바꾸는 것, 생성 마커를
        지우는 것과 같은 동작이다.
        """
        existing = [Item(id="F-001", title="피드", evidence=EVIDENCE_OURS,
                         body="카드 3장 + 필터\n> ⚠ 관찰이 다름: 카드 5장 ← 확인함, 3장 유지")]
        incoming = [Item(id="F-001", title="피드", evidence=EVIDENCE_OBSERVED,
                         body="카드 7장")]

        merged = merge_items(existing, incoming)

        self.assertIn("← 확인함, 3장 유지", merged[0].body)
        self.assertEqual([(note.kind, note.text) for note in merged[0].notes],
                         [(NOTE_KIND_CONFLICT,
                           f"{NOTE_CONFLICT_PREFIX}카드 7장{NOTE_KEEP_HINT}")])


class TestTheWholePath(unittest.TestCase):
    """마크다운 → `parse_document` → `merge_items` → `render_document` → 재파싱.

    두 모듈이 실제로 만나는 유일한 경로다. 각 모듈만 따로 보면 병합 규칙도
    라운드트립도 옳은데, 이음매에서 사람이 쓴 글이 샌다 — 소유권 판정은
    항목 단위로 내려지므로, 사람이 쓴 것이 먼저 항목 안에 온전히 들어와
    있지 않으면 라벨이 아무것도 지키지 못한다.
    """

    DOCUMENT = """# 기능

이 문서는 관찰로 채워지고, 부족한 부분은 우리가 채운다.
읽는 순서: F-001 부터.

## F-001 피드
근거: 관찰

카드 3장.

## F-002 오프라인 모드
근거: 우리 결정

핵심은 필터다 <img src="../observed/raw/03-feed.png" alt="피드 화면" width="600"> 처럼 붙인다.
캐시가 없으면 이 서비스는 반쪽이다.
"""

    HUMAN_BODY = ('핵심은 필터다 <img src="../observed/raw/03-feed.png" alt="피드 화면" '
                  'width="600"> 처럼 붙인다.\n캐시가 없으면 이 서비스는 반쪽이다.')

    def _round(self, text: str, incoming: list[Item]) -> str:
        document = parse_document(text)
        merged = merge_items(document.items, incoming)
        return render_document(replace(document, items=merged))

    def test_a_human_item_survives_a_full_round_verbatim(self):
        """`우리 결정` 항목의 본문은 인라인 이미지째로 글자 그대로 남는다."""
        incoming = [Item(id="F-001", title="피드", evidence=EVIDENCE_OBSERVED,
                         body="카드 5장.")]

        after = parse_document(self._round(self.DOCUMENT, incoming))

        human = {item.id: item for item in after.items}["F-002"]
        self.assertEqual(human.body, self.HUMAN_BODY)
        self.assertEqual(human.evidence, EVIDENCE_OURS)

    def test_the_preamble_the_person_wrote_survives_the_round(self):
        """첫 항목 앞의 제목과 머리말도 사람이 쓴 글이다."""
        after = parse_document(self._round(self.DOCUMENT, []))

        self.assertIn("읽는 순서: F-001 부터.", after.preamble)
        self.assertIn("# 기능", after.preamble)

    def test_a_second_round_with_the_same_observation_changes_nothing(self):
        """회차가 반복돼도 문서는 자라거나 줄지 않는다."""
        incoming = [Item(id="F-001", title="피드", evidence=EVIDENCE_OBSERVED,
                         body="카드 5장.")]

        once = self._round(self.DOCUMENT, incoming)
        twice = self._round(once, incoming)

        self.assertEqual(twice, once)

    def test_an_item_that_reappears_drops_its_absent_note(self):
        """사라졌다 돌아온 항목에 낡은 `없음` 표시가 남으면 문서가 거짓말을 한다."""
        incoming = [Item(id="F-001", title="피드", evidence=EVIDENCE_OBSERVED,
                         body="카드 5장.")]

        gone = self._round(self.DOCUMENT, [])
        self.assertIn(NOTE_KIND_ABSENT, gone)

        back = parse_document(self._round(gone, incoming))

        feed = {item.id: item for item in back.items}["F-001"]
        self.assertEqual([note.kind for note in feed.notes], [])
        self.assertEqual(feed.body, "카드 5장.")


class TestDriftReport(unittest.TestCase):
    def test_it_names_added_absent_and_conflicting_items(self):
        existing = [
            Item(id="F-001", title="피드", evidence=EVIDENCE_OBSERVED, body="카드 3장"),
            Item(id="F-002", title="검색", evidence=EVIDENCE_OBSERVED),
            Item(id="F-003", title="다크 모드", evidence=EVIDENCE_OURS, body="우리 것"),
        ]
        incoming = [
            Item(id="F-001", title="피드", evidence=EVIDENCE_OBSERVED, body="카드 5장"),
            Item(id="F-003", title="다크 모드", evidence=EVIDENCE_OBSERVED, body="원본에도 있다"),
            Item(id="F-004", title="설정", evidence=EVIDENCE_OBSERVED),
        ]

        report = drift_report(existing, incoming)

        self.assertIn("F-004", report)   # 새로 관찰됨
        self.assertIn("F-002", report)   # 사라짐
        self.assertIn("F-003", report)   # 사람 항목과 충돌
        self.assertNotIn("F-001", report.split("## 충돌")[-1])

    def test_no_change_says_so_instead_of_an_empty_file(self):
        """빈 파일은 '안 돌았다'와 '변화 없다'를 구분하지 못한다."""
        items = [Item(id="F-001", title="피드", evidence=EVIDENCE_OBSERVED)]

        self.assertEqual(drift_report(items, items), "변화 없음.\n")

    def test_a_relabelled_item_is_reported(self):
        """라벨은 소유권을 정한다 — 그 변화가 리포트에서 사라지면 안 된다."""
        existing = [Item(id="F-001", title="피드", evidence=EVIDENCE_PUBLIC, body="카드")]
        incoming = [Item(id="F-001", title="피드", evidence=EVIDENCE_OBSERVED, body="카드")]

        report = drift_report(existing, incoming)

        self.assertIn("근거가 바뀜", report)
        self.assertIn("F-001", report)


class TestCheckCommand(unittest.TestCase):
    def _run(self, text: str) -> subprocess.CompletedProcess:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "features.md"
            path.write_text(text, encoding="utf-8")
            return subprocess.run(
                [sys.executable, str(SCRIPT), "check", str(path)],
                capture_output=True, text=True)

    def test_a_document_whose_items_are_all_labelled_passes(self):
        result = self._run("## F-001 피드\n근거: 관찰\n\n카드 3장.\n")

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("OK:", result.stdout)

    def test_an_unlabelled_item_fails_and_is_named(self):
        result = self._run("## F-001 피드\n\n카드 3장.\n")

        self.assertEqual(result.returncode, 1)
        self.assertIn("ERROR:", result.stderr)
        self.assertIn("F-001", result.stderr)

    def test_a_missing_document_is_an_error_not_a_pass(self):
        """경로 오타가 OK 로 보고되면 검사기가 검사기가 아니다."""
        with tempfile.TemporaryDirectory() as temp:
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "check", str(Path(temp) / "nope.md")],
                capture_output=True, text=True)

        self.assertEqual(result.returncode, 1)
        self.assertIn("no such document", result.stderr)

    def test_a_heading_that_is_not_an_item_is_rejected(self):
        """사람이 ID 없이 손으로 넣은 섹션은 다음 회차에 지워진다 — 조용히 통과시키면 안 된다."""
        result = self._run("## F-001 피드\n근거: 관찰\n\n카드 3장.\n\n"
                           "## 우리가 빠뜨린 것\n근거: 우리 결정\n\n캐시를 보여준다.\n")

        self.assertEqual(result.returncode, 1)
        self.assertIn("not items", result.stderr)
        self.assertIn("우리가 빠뜨린 것", result.stderr)

    def test_a_heading_inside_a_code_fence_is_not_reported(self):
        """멀쩡한 문서가 코드펜스 하나로 ERROR 를 받으면 검사기를 아무도 안 믿는다."""
        result = self._run("## F-001 피드\n근거: 관찰\n\n```\n## F-999 가짜\n```\n")

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("OK:", result.stdout)

    def test_a_fence_left_open_is_rejected(self):
        """닫히지 않은 펜스는 뒤따르는 `우리 결정` 항목을 삼킨다 — `OK` 를 내면 안 된다."""
        result = self._run("""## F-001 피드
근거: 관찰

예시 코드:

```swift
let x = 1

## F-002 오프라인 모드
근거: 우리 결정

캐시가 없으면 이 서비스는 반쪽이다. 이 문장은 사람이 썼다.
""")

        self.assertEqual(result.returncode, 1)
        self.assertIn("never closed", result.stderr)
        self.assertIn("line 6", result.stderr)

    def test_a_tilde_line_inside_a_backtick_fence_keeps_the_next_item(self):
        """마크다운 예시가 든 평범한 문서다 — 항목 두 개가 그대로 남아야 한다."""
        result = self._run("""## F-001 피드
근거: 관찰

마크다운 예시:

```markdown
~~~
```

## F-002 오프라인 모드
근거: 우리 결정

캐시가 없으면 이 서비스는 반쪽이다. 이 문장은 사람이 썼다.
""")

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("OK: 2 item(s)", result.stdout)

    def test_a_duplicate_id_is_rejected(self):
        """ID 는 병합의 키다. 중복이면 뒤의 항목이 관찰됐는데도 `없음` 표시를 받는다."""
        result = self._run("## F-002 X\n근거: 관찰\n\n가.\n\n"
                           "## F-002 Y\n근거: 관찰\n\n나.\n")

        self.assertEqual(result.returncode, 1)
        self.assertIn("duplicate", result.stderr)
        self.assertIn("F-002", result.stderr)

    def test_an_empty_document_passes(self):
        """빈 파일은 항목이 없는 것이지 오류가 아니다 — 첫 회차의 정상 상태다."""
        result = self._run("")

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("OK:", result.stdout)


if __name__ == "__main__":
    unittest.main()
