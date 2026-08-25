#!/usr/bin/env python3
"""blueprint_doc.py — ssot 청사진을 항목 단위로 읽고 쓴다.

청사진은 재관찰마다 갱신되지만, 사람이 고친 항목은 절대 덮이면 안 된다.
파일 단위로는 그 구분이 불가능하므로 문서를 항목으로 쪼갠다. 항목마다 붙는
근거 라벨이 곧 소유권이다 — 어느 항목을 기계가 갱신해도 되고 어느 항목이
사람 것인지가 문서 자체에 적혀 있다.

산문 자유도를 조금 잃는 대신 얻는 것: 재관찰이 편집을 지우지 않는다는 보장.
그 보장이 없으면 "사람이 부족한 부분을 채운다"는 단계가 성립하지 않는다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

EVIDENCE_OBSERVED = "관찰"
EVIDENCE_PUBLIC = "공개자료"
EVIDENCE_HYPOTHESIS = "가설(미검증)"
EVIDENCE_OURS = "우리 결정"
EVIDENCE_LABELS = {
    EVIDENCE_OBSERVED, EVIDENCE_PUBLIC, EVIDENCE_HYPOTHESIS, EVIDENCE_OURS,
}

_HEADING = re.compile(r"^##\s+([A-Z]-\d+)\s+(.*?)\s*$")
_EVIDENCE = re.compile(r"^근거:\s*(.+?)\s*$")
_IMAGE = re.compile(r'<img\s+src="([^"]+)"')
# 기계 노트는 전용 마커를 달고 나간다. `>` 만으로 가르면 사람이 본문에 쓴
# 평범한 인용문이 기계 메모로 재분류되어 다음 렌더에서 항목 아래로 밀려난다.
NOTE_MARKER = "⟦auto⟧"
_NOTE = re.compile(r"^>\s*" + re.escape(NOTE_MARKER) + r"\s?(.*)$")


@dataclass
class Item:
    id: str
    title: str
    evidence: str
    evidence_ref: str = ""
    images: list[str] = field(default_factory=list)
    body: str = ""
    notes: list[str] = field(default_factory=list)


def _finish(item: Item, body_lines: list[str]) -> Item:
    item.body = "\n".join(body_lines).strip()
    return item


def parse_items(text: str) -> list[Item]:
    """`## <ID> <제목>` 으로 시작하는 항목들. 그 밖의 줄은 무시한다."""
    items: list[Item] = []
    current: Item | None = None
    body_lines: list[str] = []
    for line in text.splitlines():
        heading = _HEADING.match(line)
        if heading:
            if current is not None:
                items.append(_finish(current, body_lines))
            current = Item(id=heading.group(1), title=heading.group(2), evidence="")
            body_lines = []
            continue
        if current is None:
            continue
        evidence = _EVIDENCE.match(line)
        if evidence and not current.evidence:
            raw = evidence.group(1)
            label, _, reference = raw.partition("·")
            current.evidence = label.strip()
            current.evidence_ref = reference.strip()
            continue
        image = _IMAGE.search(line)
        if image:
            current.images.append(image.group(1))
            continue
        note = _NOTE.match(line)
        if note:
            current.notes.append(note.group(1).strip())
            continue
        body_lines.append(line)
    if current is not None:
        items.append(_finish(current, body_lines))
    return items


def render_item(item: Item) -> str:
    """항목 하나를 마크다운으로. `parse_items` 가 그대로 되읽을 수 있어야 한다."""
    lines = [f"## {item.id} {item.title}"]
    evidence = item.evidence
    if item.evidence_ref:
        evidence = f"{evidence} · {item.evidence_ref}"
    lines.append(f"근거: {evidence}")
    # 폭 지정은 마크다운 `![]()` 로 불가능하고, 이 레포는 stdlib 만 쓰므로
    # 썸네일을 새로 만들지 않는다. 원본을 인라인 HTML 로 폭만 제한해 싣는다.
    lines.extend(f'<img src="{src}" width="220">' for src in item.images)
    if item.body:
        lines.extend(["", item.body])
    if item.notes:
        lines.append("")
        lines.extend(f"> {NOTE_MARKER} {note}" for note in item.notes)
    return "\n".join(lines)


def render_items(items: list[Item], heading: str = "") -> str:
    blocks = [render_item(item) for item in items]
    text = "\n\n".join(blocks)
    if heading:
        text = f"# {heading}\n\n{text}"
    return text + "\n"
