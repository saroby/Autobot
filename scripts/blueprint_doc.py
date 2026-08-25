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

# 접두사는 스펙이 정한 다섯 개뿐이다 (`V-` 제품, `P-` 원칙, `F-` 기능,
# `E-` 엔티티, `D-` 디자인). 아무 대문자나 받으면 오타난 ID 가 멀쩡한 항목인
# 척한다.
_HEADING = re.compile(r"^##\s+([VPFED]-\d+)\s+(.*?)\s*$")
# 항목이 되지 못한 `## ` 줄. 무시되는 것이 아니라 직전 항목 본문으로 흡수되고,
# 그 항목이 `관찰` 이면 다음 회차가 본문을 통째로 갈아끼우며 함께 지운다.
_ANY_HEADING = re.compile(r"^##\s")
# 코드펜스 안의 `## F-999 …` 는 사람이 쓴 예시지 항목이 아니다. 가르면 멀쩡한
# 문서가 라벨 없는 항목을 갖게 되고 `check` 가 ERROR 를 낸다.
#
# 다만 여닫이를 단순 토글로 세면 안 된다. ``` 블록 안에 `~~~` 줄이 하나 있으면
# (마크다운 예시를 보여주는 문서에서 흔하다) 상태가 뒤집혀 그 뒤가 영영 "펜스
# 안" 이 되고, 뒤따르는 `## F-002 …` 는 항목이 되지 못한 채 직전 항목 본문으로
# 흡수된다 — 직전 항목이 `관찰` 이면 다음 병합이 사람의 글을 통째로 지운다.
# 그래서 CommonMark 대로 마커의 문자와 길이를 맞춰 닫는다.
_FENCE_LINE = re.compile(r"^\s*(?P<marker>`{3,}|~{3,})(?P<info>.*)$")
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


class _FenceState:
    """코드펜스 안/밖. 여는 마커의 문자와 길이를 기억한다 (CommonMark).

    펜스를 닫는 것은 **같은 문자**로, 여는 마커만큼 이상 길고, 뒤에 정보
    문자열이 없는 줄뿐이다. 종류를 안 보고 세면 ``` 안의 `~~~` 한 줄이 펜스를
    닫은 것으로 오인되고, 반대로 짝이 안 맞는 줄 하나가 뒤 전체를 펜스 안으로
    만든다. 둘 다 항목을 삼키는 결과는 같다.
    """

    def __init__(self) -> None:
        self._marker = ""
        self.opened_at = 0
        self.opened_line = ""

    @property
    def inside(self) -> bool:
        return bool(self._marker)

    def feed(self, number: int, line: str) -> bool:
        """줄 하나를 넘기고, 그 줄이 펜스 안인지 돌려준다.

        여는 줄과 닫는 줄 자체도 "안" 으로 본다 — 그 줄은 항목이 될 수 없다.
        """
        match = _FENCE_LINE.match(line)
        if match is None:
            return self.inside
        marker = match.group("marker")
        info = match.group("info")
        if not self.inside:
            # 백틱 펜스의 정보 문자열에는 백틱이 올 수 없다 (CommonMark).
            # 인라인 코드가 든 산문 줄을 펜스로 오인하지 않으려는 규칙이다.
            if marker[0] == "`" and "`" in info:
                return False
            self._marker = marker
            self.opened_at = number
            self.opened_line = line.strip()
            return True
        if (marker[0] == self._marker[0] and len(marker) >= len(self._marker)
                and not info.strip()):
            self._marker = ""
        return True


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
    fence = _FenceState()
    for number, line in enumerate(text.splitlines(), start=1):
        fenced = fence.feed(number, line)
        heading = None if fenced else _HEADING.match(line)
        if heading:
            if current is not None:
                items.append(_finish(current, body_lines))
            current = Item(id=heading.group(1), title=heading.group(2), evidence="")
            body_lines = []
            continue
        if current is None:
            preamble_lines.append(line)
            continue
        if not fenced and _absorb(current, line):
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


class DocumentWriteRefused(RuntimeError):
    """항목 0개로, 항목이 있던 문서를 덮어쓰려는 시도."""


def _refuse_to_blank(path: Path, document: Document) -> None:
    """항목을 하나도 못 뽑았는데 파일에는 `## ` 줄이 있으면 쓰지 않는다.

    항목 0개는 두 가지를 뜻할 수 있다 — 정말 빈 문서이거나, 파서가 문서를
    통째로 못 읽었거나. 후자에 쓰기를 허용하면 사람이 쓴 문서가 빈 파일이 된다.
    """
    if document.items or not path.is_file():
        return
    existing = path.read_text(encoding="utf-8")
    if any(_ANY_HEADING.match(line) for line in existing.splitlines()):
        raise DocumentWriteRefused(
            f"{path}: 항목 0개로 덮어쓰려 한다 — 원본에 `## ` 줄이 있다")


def read_doc(path: Path | str) -> Document:
    path = Path(path)
    if not path.is_file():
        return Document()
    return parse_document(path.read_text(encoding="utf-8"))


def write_doc(path: Path | str, document: Document) -> None:
    """제자리에서 덮어쓰지 않는다 — CONVENTIONS.md 의 원자성 규칙."""
    path = Path(path)
    _refuse_to_blank(path, document)
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


def malformed_headings(text: str) -> list[tuple[int, str]]:
    """`## ` 로 시작하지만 항목 형식이 아닌 줄의 (줄번호, 원문).

    이런 줄은 조용히 직전 항목의 본문이 된다. 사람이 ID 없이 손으로 추가한
    섹션이 바로 이 모양이고, 직전 항목이 `관찰` 이면 다음 병합이 본문을 통째로
    갈아끼우며 그 글을 지운다. 흡수는 무성(無聲)이면 안 된다.
    """
    stray: list[tuple[int, str]] = []
    fence = _FenceState()
    for number, line in enumerate(text.splitlines(), start=1):
        if fence.feed(number, line):
            continue
        if _ANY_HEADING.match(line) and not _HEADING.match(line):
            stray.append((number, line.strip()))
    return stray


def unclosed_fence(text: str) -> tuple[int, str] | None:
    """문서 끝까지 닫히지 않은 코드펜스의 (여는 줄번호, 원문). 없으면 None.

    닫히지 않은 펜스 뒤의 `## ` 줄은 전부 펜스 안으로 보여 항목이 되지 못하고
    직전 항목 본문으로 흡수된다. `malformed_headings` 도 펜스 안을 건너뛰므로
    이 검사가 없으면 그 흡수가 무성(無聲)이고, 직전 항목이 `관찰` 이면 다음
    병합이 사람의 글을 통째로 지운다. 파서가 삼키는 것을 막을 수 없다면 최소한
    소리는 내야 한다 — `malformed_headings` 가 이미 세운 기준이다.
    """
    fence = _FenceState()
    for number, line in enumerate(text.splitlines(), start=1):
        fence.feed(number, line)
    if not fence.inside:
        return None
    return (fence.opened_at, fence.opened_line)


def duplicate_ids(items: list[Item]) -> list[str]:
    """두 번 이상 나온 항목 ID.

    ID 는 병합의 키이고 다른 문서가 참조하는 주소다. 중복이 있으면 뒤의 항목은
    이번 회차에 관찰됐는데도 `없음` 표시를 받는다 — 문서가 거짓말을 한다.
    """
    seen: set[str] = set()
    duplicates: list[str] = []
    for item in items:
        if item.id in seen and item.id not in duplicates:
            duplicates.append(item.id)
        seen.add(item.id)
    return duplicates


def unlabelled(items: list[Item]) -> list[Item]:
    """근거 라벨이 없거나 알 수 없는 항목. 하나라도 있으면 문서가 계약을 어긴 것이다."""
    return [item for item in items if item.evidence not in EVIDENCE_LABELS]
