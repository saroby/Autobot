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

import os
import re
import tempfile
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

EVIDENCE_OBSERVED = "관찰"
EVIDENCE_PUBLIC = "공개자료"
EVIDENCE_HYPOTHESIS = "가설(미검증)"
EVIDENCE_OURS = "우리 결정"
EVIDENCE_LABELS = {
    EVIDENCE_OBSERVED, EVIDENCE_PUBLIC, EVIDENCE_HYPOTHESIS, EVIDENCE_OURS,
}

# 폭 지정은 마크다운 `![]()` 로 불가능하고, 이 레포는 stdlib 만 쓰므로 썸네일을
# 새로 만들지 않는다. 원본을 인라인 HTML 로 폭만 제한해 싣는다.
IMAGE_WIDTH = 220

_HEADING = re.compile(r"^##\s+([A-Z]-\d+)\s+(.*?)\s*$")
_EVIDENCE = re.compile(r"^근거:\s*(.+?)\s*$")
# 줄 **전체**가 이미지 태그일 때만 이미지 줄이다. 아무 데나 찾으면 같은 줄에
# 사람이 쓴 문장까지 통째로 흡수해 렌더에서 잃는다 — 스펙 규칙 6 이 이미지를
# 문서 어디에나 흔하게 만들므로, 이미지 옆에 설명을 붙이는 것은 예외가 아니라
# 기본 사용법이다. 저장하는 것도 `src` 가 아니라 줄 원문이다: 사람이 정한
# `alt`·`width` 는 되살릴 방법이 없으므로 애초에 버리지 않는다.
_IMAGE_LINE = re.compile(r"^\s*(?:<img\s[^>]*>\s*)+$")
# 기계 노트는 전용 마커를 달고 나간다. `>` 만으로 가르면 사람이 본문에 쓴
# 평범한 인용문이 기계 메모로 재분류되어 다음 렌더에서 항목 아래로 밀려난다.
_NOTE = re.compile(r"^>\s*⟦auto(?::([a-z]+))?⟧\s?(.*)$")


@dataclass(frozen=True)
class Note:
    """기계가 항목에 덧붙인 메모. `kind` 가 소유권과 교체 대상을 결정한다.

    문자열만으로는 기계 노트와 사람이 손댄 줄을 가를 수 없다 — 접두사가 같으면
    사람이 덧붙인 주석까지 다음 병합이 갈아끼운다. 종류를 실어 보내면 병합이
    문자열이 아니라 `kind` 로 판별하므로 사람의 주석이 안전해진다.
    """
    kind: str
    text: str


NOTE_KIND_PLAIN = "note"          # 종류 없는 메모 (사람이 손댄 것 포함)
NOTE_KIND_ABSENT = "absent"       # 관찰에서 사라짐
NOTE_KIND_CONFLICT = "conflict"   # 사람 항목과 관찰이 불일치


@dataclass
class Document:
    """문서 하나 — 첫 항목 앞의 머리말과 항목들.

    머리말은 문서 제목과 사람이 쓴 안내문이다. 항목만 들고 다니면
    `read_doc → merge_items → write_doc` 이 역함수가 아니게 되고, 저장 한 번에
    그 글이 조용히 사라진다. 소유권 라벨은 항목에만 붙으므로 항목 밖의 글은
    보호받을 자리조차 없다 — 그러니 잃지 않는 것이 유일한 보호다.
    """
    preamble: str = ""
    items: list[Item] = field(default_factory=list)


@dataclass
class Item:
    id: str
    title: str
    evidence: str
    evidence_ref: str = ""
    images: list[str] = field(default_factory=list)
    body: str = ""
    notes: list[Note] = field(default_factory=list)


def image_line(src: str) -> str:
    """관찰이 새로 싣는 이미지 줄. 파서가 그대로 되읽는 형태다."""
    return f'<img src="{src}" width="{IMAGE_WIDTH}">'


def _finish(item: Item, body_lines: list[str]) -> Item:
    item.body = "\n".join(body_lines).strip()
    return item


def _absorb(item: Item, line: str) -> bool:
    """항목의 구조 줄(근거·이미지·기계 노트)이면 흡수하고 True 를 돌려준다."""
    evidence = _EVIDENCE.match(line)
    if evidence and not item.evidence:
        raw = evidence.group(1)
        label, _, reference = raw.partition("·")
        # 한글은 NFC/NFD 로 다르게 저장될 수 있고 macOS 는 NFD 를 만든다.
        # 정규화하지 않으면 눈에 같은 `우리 결정` 이 상수와 어긋나 소유권
        # 보호가 조용히 풀린다 — 이 계약이 지키려는 단 하나의 성질이다.
        item.evidence = unicodedata.normalize("NFC", label.strip())
        item.evidence_ref = reference.strip()
        return True
    if _IMAGE_LINE.match(line):
        item.images.append(line.strip())
        return True
    note = _NOTE.match(line)
    if note:
        item.notes.append(Note(note.group(1) or NOTE_KIND_PLAIN,
                               note.group(2).strip()))
        return True
    return False


def parse_document(text: str) -> Document:
    """머리말과 `## <ID> <제목>` 항목들.

    첫 항목 앞의 줄은 머리말로 보관한다. 항목 형식이 아닌 `## ` 줄은 직전 항목의
    본문으로 들어간다 — 무시되는 것이 아니므로 `malformed_headings` 가 따로
    집어내고 CLI 가 거부한다.
    """
    items: list[Item] = []
    preamble_lines: list[str] = []
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
            preamble_lines.append(line)
            continue
        if _absorb(current, line):
            continue
        body_lines.append(line)
    if current is not None:
        items.append(_finish(current, body_lines))
    return Document(preamble="\n".join(preamble_lines).strip("\n"), items=items)


def parse_items(text: str) -> list[Item]:
    """`## <ID> <제목>` 으로 시작하는 항목들. 머리말이 필요하면 `parse_document`."""
    return parse_document(text).items


def render_item(item: Item) -> str:
    """항목 하나를 마크다운으로. `parse_items` 가 그대로 되읽을 수 있어야 한다."""
    lines = [f"## {item.id} {item.title}"]
    evidence = item.evidence
    if item.evidence_ref:
        evidence = f"{evidence} · {item.evidence_ref}"
    lines.append(f"근거: {evidence}")
    lines.extend(item.images)
    if item.body:
        lines.extend(["", item.body])
    if item.notes:
        lines.append("")
        lines.extend(f"> ⟦auto:{note.kind}⟧ {note.text}" for note in item.notes)
    return "\n".join(lines)


def render_items(items: list[Item]) -> str:
    if not items:
        return ""
    return "\n\n".join(render_item(item) for item in items) + "\n"


def render_document(document: Document) -> str:
    """`parse_document` 가 그대로 되읽을 수 있어야 한다 — 이 둘은 역함수다."""
    parts = [part for part in (document.preamble.strip("\n"),
                               render_items(document.items).rstrip("\n")) if part]
    if not parts:
        return ""
    return "\n\n".join(parts) + "\n"


def read_doc(path: Path | str) -> Document:
    path = Path(path)
    if not path.is_file():
        return Document()
    return parse_document(path.read_text(encoding="utf-8"))


def write_doc(path: Path | str, document: Document) -> None:
    """제자리에서 덮어쓰지 않는다 — CONVENTIONS.md 의 원자성 규칙."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            out.write(render_document(document))
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def unlabelled(items: list[Item]) -> list[Item]:
    """근거 라벨이 없거나 알 수 없는 항목. 하나라도 있으면 문서가 계약을 어긴 것이다."""
    return [item for item in items if item.evidence not in EVIDENCE_LABELS]
