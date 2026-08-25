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
from blueprint_doc import EVIDENCE_OBSERVED, EVIDENCE_OURS, Item  # noqa: E402

NOTE_ABSENT = "관찰: 최근 회차에 없음"
NOTE_CONFLICT_PREFIX = "⚠ 관찰이 다름: "


def merge_items(existing: list[Item], incoming: list[Item]) -> list[Item]:
    """기존 순서를 유지한 채 관찰을 반영한다. `우리 결정` 항목은 건드리지 않는다."""
    fresh = {item.id: item for item in incoming}
    merged: list[Item] = []
    for item in existing:
        candidate = fresh.pop(item.id, None)
        if candidate is None:
            if item.evidence == EVIDENCE_OBSERVED and NOTE_ABSENT not in item.notes:
                # 복사본에 붙인다 — 호출자가 넘긴 문서를 바꾸지 않는다.
                item = replace(item, notes=[*item.notes, NOTE_ABSENT])
            merged.append(item)
            continue
        if item.evidence == EVIDENCE_OURS:
            # 회차마다 쌓으면 어느 것이 최신인지 알 수 없다 — 마지막 것만 남긴다.
            notes = [note for note in item.notes
                     if not note.startswith(NOTE_CONFLICT_PREFIX)]
            if candidate.body and candidate.body != item.body:
                notes.append(f"{NOTE_CONFLICT_PREFIX}{candidate.body}")
            merged.append(replace(item, notes=notes))
            continue
        merged.append(candidate)
    merged.extend(item for item in incoming if item.id in fresh)
    return merged
