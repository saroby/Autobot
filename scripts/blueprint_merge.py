#!/usr/bin/env python3
"""blueprint_merge.py — 재관찰과 사람의 편집을 한 문서에서 살린다.

대상 서비스는 계속 바뀌므로 청사진은 한 번 쓰고 마는 문서가 아니다. 그런데
재관찰이 문서를 통째로 다시 쓰면 사람이 넣은 "부족한 부분"이 매번 사라진다 —
그러면 아무도 문서를 고치지 않고, 고치지 않는 청사진은 관찰 덤프일 뿐이다.

그래서 소유권을 파일이 아니라 항목에 둔다. 근거 라벨이 그 표시다.
선례는 `clone_run.sh` 의 `views.json` 병합 — 이미 있는 이름은 유지하고 새
state 만 새 이름을 받는다.

`merge_items` 는 순수 함수다. 입력 항목을 제자리에서 바꾸면 호출자가 넘긴
문서가 몰래 달라지고, 드리프트 리포트가 병합 전·후를 비교할 수 없게 된다.

주의 — 형제 모듈 import 는 이 레포의 `sys.path.insert` 관례를 따르므로
(`device_measure.py` 와 동일), 테스트가 쓰는 `scripts.blueprint_doc` 과 여기서
쓰는 `blueprint_doc` 은 런타임에 **서로 다른 모듈**이고 `Item` 클래스도 둘이다.
문자열과 필드만 비교하면 안전하다. `Item` 을 이 경계 너머로 `isinstance` 하거나
등가 비교하지 말 것 — 조용히 False 가 된다.
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from blueprint_doc import (  # noqa: E402
    EVIDENCE_OBSERVED,
    EVIDENCE_OURS,
    NOTE_KIND_ABSENT,
    NOTE_KIND_CONFLICT,
    Item,
    Note,
    duplicate_ids,
    malformed_headings,
    parse_document,
    unclosed_fence,
    unlabelled,
)

NOTE_ABSENT = Note(NOTE_KIND_ABSENT, "관찰: 최근 회차에 없음")
NOTE_CONFLICT_PREFIX = "⚠ 관찰이 다름: "
NOTE_KEEP_HINT = " (이 줄을 지키려면 ⟦…⟧ 마커를 지우세요)"


def merge_items(existing: list[Item], incoming: list[Item]) -> list[Item]:
    """기존 순서를 유지한 채 관찰을 반영한다. `우리 결정` 항목은 건드리지 않는다."""
    fresh = {item.id: item for item in incoming}
    merged: list[Item] = []
    for item in existing:
        candidate = fresh.pop(item.id, None)
        if candidate is None:
            if (item.evidence == EVIDENCE_OBSERVED
                    and not any(note.kind == NOTE_KIND_ABSENT for note in item.notes)):
                # 복사본에 붙인다 — 호출자가 넘긴 문서를 바꾸지 않는다.
                item = replace(item, notes=[*item.notes, NOTE_ABSENT])
            merged.append(item)
            continue
        if item.evidence == EVIDENCE_OURS:
            notes = list(item.notes)
            # 갈아끼우는 것은 새 관찰이 있을 때뿐이고, 갈아끼우는 대상은
            # **기계가 쓴 conflict 노트뿐**이다. 사람이 그 줄에 덧붙인 주석은
            # kind 가 다르므로 살아남는다.
            if candidate.body:
                notes = [note for note in notes if note.kind != NOTE_KIND_CONFLICT]
                if candidate.body != item.body:
                    notes.append(Note(NOTE_KIND_CONFLICT,
                                      f"{NOTE_CONFLICT_PREFIX}{candidate.body}"
                                      f"{NOTE_KEEP_HINT}"))
            merged.append(replace(item, notes=notes))
            continue
        if not candidate.body and (item.body or item.images):
            # `우리 결정` 경로와 같은 가드다 — 본문을 못 뽑은 회차는 새 관찰이
            # 아니다. 한 화면에서 텍스트 추출이 실패했다고 해서 누적된 서술과
            # 이미지·참조를 지우면, 부분 관찰이 "없어졌다"로 둔갑한다.
            merged.append(item)
            continue
        merged.append(candidate)
    merged.extend(item for item in incoming if item.id in fresh)
    return merged


def drift_report(existing: list[Item], incoming: list[Item]) -> str:
    """이번 회차가 무엇을 바꿨는지. `observed/drift.md` 의 내용이 된다."""
    before = {item.id: item for item in existing}
    after = {item.id: item for item in incoming}
    added = [after[i] for i in after if i not in before]
    absent = [before[i] for i in before
              if i not in after and before[i].evidence == EVIDENCE_OBSERVED]
    conflicts = [(before[i], after[i]) for i in before
                 if i in after and before[i].evidence == EVIDENCE_OURS
                 and after[i].body and after[i].body != before[i].body]
    changed = [(before[i], after[i]) for i in before
               if i in after and before[i].evidence != EVIDENCE_OURS
               and after[i].body != before[i].body]
    relabelled = [(before[i], after[i]) for i in before
                  if i in after and before[i].evidence != EVIDENCE_OURS
                  and after[i].evidence != before[i].evidence]
    if not (added or absent or conflicts or changed or relabelled):
        return "변화 없음.\n"
    sections: list[str] = []
    if added:
        sections.append("## 새로 관찰됨\n\n"
                        + "\n".join(f"- {i.id} {i.title}" for i in added))
    if absent:
        sections.append("## 최근 회차에 없음\n\n"
                        + "\n".join(f"- {i.id} {i.title}" for i in absent))
    if changed:
        sections.append("## 내용이 바뀜\n\n"
                        + "\n".join(f"- {b.id} {b.title}: {b.body} → {a.body}"
                                    for b, a in changed))
    if relabelled:
        sections.append("## 근거가 바뀜\n\n"
                        + "\n".join(f"- {b.id} {b.title}: {b.evidence} → {a.evidence}"
                                    for b, a in relabelled))
    if conflicts:
        sections.append("## 충돌 — 사람이 정한 항목과 관찰이 다름\n\n"
                        + "\n".join(f"- {b.id} {b.title}: 문서 \"{b.body}\" / "
                                    f"관찰 \"{a.body}\"" for b, a in conflicts))
    return "\n\n".join(sections) + "\n"


def main(argv: list[str]) -> int:
    """`blueprint_merge.py check <doc.md>` — 사람이 라벨 계약을 확인하는 유일한 진입점."""
    if len(argv) != 3 or argv[1] != "check":
        print("ERROR: usage: blueprint_merge.py check <doc.md>", file=sys.stderr)
        return 2
    path = Path(argv[2])
    # read_doc 은 없는 파일을 빈 문서로 돌려준다 — 첫 회차의 정상 상태다.
    # 하지만 검사하라고 지목받은 파일이 없는 것은 "검사할 게 없다"가 아니라
    # 오류다. 구분하지 않으면 경로 오타가 OK 로 보고된다.
    if not path.is_file():
        print(f"ERROR: no such document: {path}", file=sys.stderr)
        return 1
    text = path.read_text(encoding="utf-8")
    items = parse_document(text).items
    broken = False
    # 닫히지 않은 코드펜스. 그 뒤의 `## ` 줄은 전부 펜스 안으로 보여 항목이 되지
    # 못하고, stray 검사도 펜스 안을 건너뛰므로 아무 소리 없이 사라진다.
    # 먼저 낸다 — 뒤의 검사들이 조용한 이유가 바로 이것이기 때문이다.
    fence = unclosed_fence(text)
    if fence is not None:
        broken = True
        opened_at, opened_line = fence
        print("ERROR: a code fence is never closed — every `## ` line after it is "
              "absorbed into the previous item and deleted on the next round:",
              file=sys.stderr)
        print(f"ERROR:   line {opened_at}: {opened_line}", file=sys.stderr)
    # 항목이 되지 못한 `## ` 줄. 조용히 직전 항목 본문으로 흡수되므로, 검사가
    # 잡지 않으면 다음 회차에 그 글이 사라지고 아무도 이유를 모른다.
    stray = malformed_headings(text)
    if stray:
        broken = True
        print(f"ERROR: {len(stray)} heading(s) are not items — they are absorbed "
              "into the previous item and deleted on the next round:", file=sys.stderr)
        for number, line in stray:
            print(f"ERROR:   line {number}: {line}", file=sys.stderr)
    duplicates = duplicate_ids(items)
    if duplicates:
        broken = True
        print(f"ERROR: {len(duplicates)} duplicate item id(s) — an id is the merge "
              "key and the address other documents cite:", file=sys.stderr)
        for item_id in duplicates:
            print(f"ERROR:   {item_id}", file=sys.stderr)
    missing = unlabelled(items)
    if missing:
        broken = True
        print(f"ERROR: {len(missing)} item(s) have no valid 근거 label — "
              "every item must declare who owns it:", file=sys.stderr)
        for item in missing:
            print(f"ERROR:   {item.id} {item.title}", file=sys.stderr)
    if broken:
        return 1
    print(f"OK: {len(items)} item(s), every one labelled")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
