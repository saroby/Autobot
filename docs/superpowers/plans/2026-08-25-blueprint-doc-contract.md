# Blueprint 문서 계약 · 병합 엔진 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `ssot/*.md` 를 항목 단위로 읽고 쓰고 병합해서, 재관찰이 사람의 편집을 절대 덮지 않게 만든다.

**Architecture:** 마크다운 문서를 `Item` 목록으로 파싱하는 모듈(`blueprint_doc.py`)과, 두 `Item` 목록을 근거 라벨 기준으로 병합하며 변화를 리포트하는 모듈(`blueprint_merge.py`) 둘. 관찰 계층은 이 계획에 없다 — 전부 픽스처로 테스트된다. 이것이 `docs/superpowers/specs/2026-08-25-autobot-blueprint-design.md` 의 분할 ① 이다.

**Tech Stack:** Python 3, stdlib 전용. 테스트는 `unittest` (`python3 -m unittest`).

## Global Constraints

- **stdlib 전용.** 새 의존성 금지 (Pillow·PyYAML·pytest 모두 불가). 테스트도 `unittest` 로 쓴다.
- **원자적 파일 쓰기.** 출력 파일을 제자리에서 덮어쓰지 않는다. `tempfile.mkstemp` → `os.fsync` → `os.replace`. `scripts/clone_structure.py:_write_atomic` 이 이 레포의 최신 사례이므로 그대로 따른다.
- **출력 prefix 정책.** stdout/stderr 의 모든 줄은 `OK:` `WARN:` `INFO:` `ERROR:` 중 하나로 시작한다.
- **근거 라벨 4종은 정확히 이 문자열이다**: `관찰`, `공개자료`, `가설(미검증)`, `우리 결정`. 다른 표기 금지.
- **항목 ID 접두사**: `V-` 제품, `P-` 원칙, `F-` 기능, `E-` 엔티티, `D-` 디자인. 형식은 `<접두사><숫자>` (예: `F-012`).
- **한국어 산문.** 스킬·문서·주석의 설명문은 한국어로 쓴다 (코드 식별자는 영문).
- **`merge_items` 는 순수 함수다.** 입력으로 받은 `Item` 을 제자리에서 바꾸지 않는다. 노트를 붙이거나 지울 때는 `dataclasses.replace` 로 복사본을 만든다. 호출자가 넘긴 문서가 몰래 바뀌면 드리프트 리포트가 병합 전·후를 비교할 수 없다.
- **형제 모듈 import 는 `sys.path.insert` 관례를 따른다** (`scripts/device_measure.py` 와 동일). 그 결과 테스트의 `scripts.blueprint_doc` 와 스크립트 내부의 `blueprint_doc` 은 **런타임에 서로 다른 모듈이 되고 `Item` 클래스도 둘이 된다.** 문자열·필드 비교만 하면 안전하지만, `Item` 을 이 경계 너머로 `isinstance` 하거나 등가 비교하면 조용히 실패한다. `blueprint_merge.py` 의 docstring 에 이 경고를 명시한다.
- **테스트 실행**: `XDG_CONFIG_HOME="$(mktemp -d)" AUTOBOT_TEST_XDG_ISOLATED=1 AUTOBOT_NO_GLOBAL_PUBLISH=1 python3 -m unittest tests.test_X`

## File Structure

| 파일 | 책임 |
|---|---|
| `scripts/blueprint_doc.py` | `Item` 데이터 모델. 마크다운 ⇄ `Item` 목록 파싱·렌더링. 파일 읽기·원자적 쓰기. |
| `scripts/blueprint_merge.py` | 두 `Item` 목록 병합. 근거 라벨이 소유권을 결정. 변화 리포트(드리프트) 생성. |
| `tests/test_blueprint_doc.py` | 파싱·렌더링·라운드트립 |
| `tests/test_blueprint_merge.py` | 병합 규칙·보호·충돌·드리프트 |

`blueprint_merge` 는 `blueprint_doc` 에 의존한다. 역방향 import 는 금지 — 파싱이 병합을 알 필요가 없다.

---

### Task 1: 항목 파싱 — 마크다운을 Item 목록으로

**Files:**
- Create: `scripts/blueprint_doc.py`
- Test: `tests/test_blueprint_doc.py`

**Interfaces:**
- Consumes: 없음 (첫 태스크)
- Produces:
  - `EVIDENCE_OBSERVED = "관찰"`, `EVIDENCE_PUBLIC = "공개자료"`, `EVIDENCE_HYPOTHESIS = "가설(미검증)"`, `EVIDENCE_OURS = "우리 결정"`
  - `EVIDENCE_LABELS: set[str]` — 위 넷
  - `@dataclass Item` — 필드: `id: str`, `title: str`, `evidence: str`, `evidence_ref: str`, `images: list[str]`, `body: str`, `notes: list[str]`
  - `parse_items(text: str) -> list[Item]`

- [ ] **Step 1: Write the failing test**

`tests/test_blueprint_doc.py` 를 새로 만든다:

```python
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


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `XDG_CONFIG_HOME="$(mktemp -d)" AUTOBOT_TEST_XDG_ISOLATED=1 AUTOBOT_NO_GLOBAL_PUBLISH=1 python3 -m unittest tests.test_blueprint_doc -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.blueprint_doc'`

- [ ] **Step 3: Write minimal implementation**

`scripts/blueprint_doc.py` 를 새로 만든다:

```python
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
        body_lines.append(line)
    if current is not None:
        items.append(_finish(current, body_lines))
    return items
```

- [ ] **Step 4: Run test to verify it passes**

Run: `XDG_CONFIG_HOME="$(mktemp -d)" AUTOBOT_TEST_XDG_ISOLATED=1 AUTOBOT_NO_GLOBAL_PUBLISH=1 python3 -m unittest tests.test_blueprint_doc -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/blueprint_doc.py tests/test_blueprint_doc.py
git commit -m "feat(blueprint): ssot 항목 파서 — ID·근거 라벨·이미지·본문"
```

---

### Task 2: 노트 파싱 — 기계가 덧붙인 줄을 본문과 가른다

**Files:**
- Modify: `scripts/blueprint_doc.py`
- Test: `tests/test_blueprint_doc.py`

**Interfaces:**
- Consumes: Task 1 의 `Item`, `parse_items`
- Produces: `Item.notes` 가 `> ` 로 시작하는 줄들로 채워진다 (접두사 `> ` 는 제거된 상태로 저장)

노트는 병합이 항목에 덧붙이는 기계 메모다 (`관찰: 최근 회차에 없음`, `⚠ 관찰이 다름: …`). 본문과 섞이면 사람이 고친 문장인지 기계가 붙인 경고인지 구분할 수 없고, 다음 병합이 노트를 중복해서 쌓는다.

- [ ] **Step 1: Write the failing test**

`tests/test_blueprint_doc.py` 의 `TestParseItems` 클래스 안에 추가한다:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `XDG_CONFIG_HOME="$(mktemp -d)" AUTOBOT_TEST_XDG_ISOLATED=1 AUTOBOT_NO_GLOBAL_PUBLISH=1 python3 -m unittest tests.test_blueprint_doc.TestParseItems.test_blockquote_lines_are_machine_notes_not_body -v`

Expected: FAIL — `notes` 가 `[]` 이고 `body` 에 `> 관찰: 최근 회차에 없음` 이 남아 있다

- [ ] **Step 3: Write minimal implementation**

`scripts/blueprint_doc.py` 에서 `_IMAGE` 정규식 아래에 추가:

```python
_NOTE = re.compile(r"^>\s?(.*)$")
```

`parse_items` 의 이미지 처리 블록 바로 뒤, `body_lines.append(line)` 앞에 추가:

```python
        note = _NOTE.match(line)
        if note:
            current.notes.append(note.group(1).strip())
            continue
```

- [ ] **Step 4: Run test to verify it passes**

Run: `XDG_CONFIG_HOME="$(mktemp -d)" AUTOBOT_TEST_XDG_ISOLATED=1 AUTOBOT_NO_GLOBAL_PUBLISH=1 python3 -m unittest tests.test_blueprint_doc -v`

Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/blueprint_doc.py tests/test_blueprint_doc.py
git commit -m "feat(blueprint): 기계 노트를 본문과 분리 — 중복 누적 방지"
```

---

### Task 3: 렌더링과 라운드트립

**Files:**
- Modify: `scripts/blueprint_doc.py`
- Test: `tests/test_blueprint_doc.py`

**Interfaces:**
- Consumes: Task 1–2 의 `Item`, `parse_items`
- Produces: `render_items(items: list[Item], heading: str = "") -> str`

라운드트립이 깨지면 병합이 조용히 내용을 잃는다. 병합을 쓰기 전에 이 성질을 고정한다.

- [ ] **Step 1: Write the failing test**

`tests/test_blueprint_doc.py` 에 새 클래스를 추가한다 (`if __name__` 블록 위):

```python
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
        ]

        reparsed = parse_items(render_items(original))

        self.assertEqual(reparsed, original)
```

같은 파일 상단의 import 를 다음으로 바꾼다:

```python
from scripts.blueprint_doc import (
    EVIDENCE_OBSERVED,
    EVIDENCE_OURS,
    Item,
    parse_items,
    render_items,
)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `XDG_CONFIG_HOME="$(mktemp -d)" AUTOBOT_TEST_XDG_ISOLATED=1 AUTOBOT_NO_GLOBAL_PUBLISH=1 python3 -m unittest tests.test_blueprint_doc -v`

Expected: FAIL — `ImportError: cannot import name 'render_items'`

- [ ] **Step 3: Write minimal implementation**

`scripts/blueprint_doc.py` 끝에 추가:

```python
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
        lines.extend(f"> {note}" for note in item.notes)
    return "\n".join(lines)


def render_items(items: list[Item], heading: str = "") -> str:
    blocks = [render_item(item) for item in items]
    text = "\n\n".join(blocks)
    if heading:
        text = f"# {heading}\n\n{text}"
    return text + "\n"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `XDG_CONFIG_HOME="$(mktemp -d)" AUTOBOT_TEST_XDG_ISOLATED=1 AUTOBOT_NO_GLOBAL_PUBLISH=1 python3 -m unittest tests.test_blueprint_doc -v`

Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/blueprint_doc.py tests/test_blueprint_doc.py
git commit -m "feat(blueprint): 항목 렌더링 + 라운드트립 고정"
```

---

### Task 4: 원자적 문서 읽기·쓰기

**Files:**
- Modify: `scripts/blueprint_doc.py`
- Test: `tests/test_blueprint_doc.py`

**Interfaces:**
- Consumes: Task 1–3
- Produces:
  - `read_doc(path: Path | str) -> list[Item]` — 파일이 없으면 `[]`
  - `write_doc(path: Path | str, items: list[Item], heading: str = "") -> None` — 원자적

- [ ] **Step 1: Write the failing test**

`tests/test_blueprint_doc.py` 에 새 클래스를 추가한다:

```python
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
```

같은 파일 상단의 import 블록을 다음으로 바꾼다:

```python
import tempfile
import unittest
from pathlib import Path

from scripts.blueprint_doc import (
    EVIDENCE_OBSERVED,
    EVIDENCE_OURS,
    Item,
    parse_items,
    read_doc,
    render_items,
    write_doc,
)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `XDG_CONFIG_HOME="$(mktemp -d)" AUTOBOT_TEST_XDG_ISOLATED=1 AUTOBOT_NO_GLOBAL_PUBLISH=1 python3 -m unittest tests.test_blueprint_doc -v`

Expected: FAIL — `ImportError: cannot import name 'read_doc'`

- [ ] **Step 3: Write minimal implementation**

`scripts/blueprint_doc.py` 상단 import 에 추가:

```python
import os
import tempfile
from pathlib import Path
```

파일 끝에 추가:

```python
def read_doc(path: Path | str) -> list[Item]:
    path = Path(path)
    if not path.is_file():
        return []
    return parse_items(path.read_text(encoding="utf-8"))


def write_doc(path: Path | str, items: list[Item], heading: str = "") -> None:
    """제자리에서 덮어쓰지 않는다 — CONVENTIONS.md 의 원자성 규칙."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            out.write(render_items(items, heading))
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `XDG_CONFIG_HOME="$(mktemp -d)" AUTOBOT_TEST_XDG_ISOLATED=1 AUTOBOT_NO_GLOBAL_PUBLISH=1 python3 -m unittest tests.test_blueprint_doc -v`

Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/blueprint_doc.py tests/test_blueprint_doc.py
git commit -m "feat(blueprint): 원자적 문서 읽기·쓰기"
```

---

### Task 5: 병합 — 관찰 항목은 갱신, 사람 항목은 보호

**Files:**
- Create: `scripts/blueprint_merge.py`
- Test: `tests/test_blueprint_merge.py`

**Interfaces:**
- Consumes: `scripts.blueprint_doc` 의 `Item`, `EVIDENCE_OBSERVED`, `EVIDENCE_OURS`
- Produces: `merge_items(existing: list[Item], incoming: list[Item]) -> list[Item]`

`incoming` 은 이번 회차 관찰이 만든 항목, `existing` 은 디스크의 문서. 순서는 `existing` 순서를 유지하고 새 항목은 뒤에 붙인다 — 사람이 정리해 둔 순서를 재관찰이 흩뜨리면 안 된다.

- [ ] **Step 1: Write the failing test**

`tests/test_blueprint_merge.py` 를 새로 만든다:

```python
"""blueprint_merge.py — 재관찰이 사람의 편집을 덮지 않게 하는 규칙.

근거 라벨이 곧 소유권이다. 이 파일이 지키는 단 하나의 성질: 사람이 넣은
"부족한 부분"은 몇 번을 재관찰해도 그대로 있다. 그 보장이 없으면 청사진을
고칠 이유가 없어진다.
"""

from __future__ import annotations

import unittest

from scripts.blueprint_doc import EVIDENCE_OBSERVED, EVIDENCE_OURS, Item
from scripts.blueprint_merge import merge_items


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

    def test_a_newly_observed_item_is_appended_after_the_existing_order(self):
        """사람이 정리해 둔 순서를 재관찰이 흩뜨리지 않는다."""
        existing = [Item(id="F-002", title="검색", evidence=EVIDENCE_OBSERVED),
                    Item(id="F-001", title="피드", evidence=EVIDENCE_OBSERVED)]
        incoming = [Item(id="F-003", title="설정", evidence=EVIDENCE_OBSERVED)]

        merged = merge_items(existing, incoming)

        self.assertEqual([item.id for item in merged], ["F-002", "F-001", "F-003"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `XDG_CONFIG_HOME="$(mktemp -d)" AUTOBOT_TEST_XDG_ISOLATED=1 AUTOBOT_NO_GLOBAL_PUBLISH=1 python3 -m unittest tests.test_blueprint_merge -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.blueprint_merge'`

- [ ] **Step 3: Write minimal implementation**

`scripts/blueprint_merge.py` 를 새로 만든다:

```python
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
from blueprint_doc import EVIDENCE_OURS, Item  # noqa: E402


def merge_items(existing: list[Item], incoming: list[Item]) -> list[Item]:
    """기존 순서를 유지한 채 관찰을 반영한다. `우리 결정` 항목은 건드리지 않는다."""
    fresh = {item.id: item for item in incoming}
    merged: list[Item] = []
    for item in existing:
        candidate = fresh.pop(item.id, None)
        if candidate is None or item.evidence == EVIDENCE_OURS:
            merged.append(item)
            continue
        merged.append(candidate)
    merged.extend(item for item in incoming if item.id in fresh)
    return merged
```

- [ ] **Step 4: Run test to verify it passes**

Run: `XDG_CONFIG_HOME="$(mktemp -d)" AUTOBOT_TEST_XDG_ISOLATED=1 AUTOBOT_NO_GLOBAL_PUBLISH=1 python3 -m unittest tests.test_blueprint_merge -v`

Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/blueprint_merge.py tests/test_blueprint_merge.py
git commit -m "feat(blueprint): 항목 단위 병합 — 근거 라벨이 소유권"
```

---

### Task 6: 사라진 항목은 표시만, 삭제하지 않는다

**Files:**
- Modify: `scripts/blueprint_merge.py`
- Test: `tests/test_blueprint_merge.py`

**Interfaces:**
- Consumes: Task 5 의 `merge_items`
- Produces: `NOTE_ABSENT = "관찰: 최근 회차에 없음"` — 사라진 `관찰` 항목의 `notes` 에 붙는다. 이미 있으면 중복해서 붙이지 않는다.

지우면 그 항목을 근거로 삼은 사람의 결정이 붕 뜬다. 대상 앱의 피드가 그날 비어 있었을 뿐일 수도 있다.

- [ ] **Step 1: Write the failing test**

`tests/test_blueprint_merge.py` 에 새 클래스를 추가한다 (`if __name__` 블록 위):

```python
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
```

같은 파일 상단의 import 를 다음으로 바꾼다:

```python
from scripts.blueprint_merge import NOTE_ABSENT, merge_items
```

- [ ] **Step 2: Run test to verify it fails**

Run: `XDG_CONFIG_HOME="$(mktemp -d)" AUTOBOT_TEST_XDG_ISOLATED=1 AUTOBOT_NO_GLOBAL_PUBLISH=1 python3 -m unittest tests.test_blueprint_merge -v`

Expected: FAIL — `ImportError: cannot import name 'NOTE_ABSENT'`

- [ ] **Step 3: Write minimal implementation**

`scripts/blueprint_merge.py` 의 import 블록을 다음으로 바꾼다:

```python
from blueprint_doc import EVIDENCE_OBSERVED, EVIDENCE_OURS, Item  # noqa: E402
```

그 아래에 추가:

```python
NOTE_ABSENT = "관찰: 최근 회차에 없음"
```

`merge_items` 안의 `if candidate is None or item.evidence == EVIDENCE_OURS:` 블록을 다음으로 바꾼다:

```python
        if candidate is None:
            if item.evidence == EVIDENCE_OBSERVED and NOTE_ABSENT not in item.notes:
                # 복사본에 붙인다 — 호출자가 넘긴 문서를 바꾸지 않는다.
                item = replace(item, notes=[*item.notes, NOTE_ABSENT])
            merged.append(item)
            continue
        if item.evidence == EVIDENCE_OURS:
            merged.append(item)
            continue
```

- [ ] **Step 4: Run test to verify it passes**

Run: `XDG_CONFIG_HOME="$(mktemp -d)" AUTOBOT_TEST_XDG_ISOLATED=1 AUTOBOT_NO_GLOBAL_PUBLISH=1 python3 -m unittest tests.test_blueprint_merge -v`

Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/blueprint_merge.py tests/test_blueprint_merge.py
git commit -m "feat(blueprint): 사라진 관찰 항목은 표시만 — 삭제 금지"
```

---

### Task 7: 사람 항목과 관찰이 충돌하면 덧붙여 알린다

**Files:**
- Modify: `scripts/blueprint_merge.py`
- Test: `tests/test_blueprint_merge.py`

**Interfaces:**
- Consumes: Task 5–6
- Produces: `NOTE_CONFLICT_PREFIX = "⚠ 관찰이 다름: "` — `우리 결정` 항목의 본문과 관찰 본문이 다를 때 `notes` 에 `f"{NOTE_CONFLICT_PREFIX}{관찰 본문}"` 이 붙는다. 같은 내용은 중복해서 붙이지 않고, 새 관찰이 오면 이전 충돌 노트를 대체한다.

지우지도 덮지도 않는다. 판단은 사람이 한다.

- [ ] **Step 1: Write the failing test**

`tests/test_blueprint_merge.py` 에 새 클래스를 추가한다:

```python
class TestConflictWithHumanDecision(unittest.TestCase):
    def test_a_conflicting_observation_is_appended_as_a_note(self):
        """지우지도 덮지도 않는다 — 판단은 사람이 한다."""
        existing = [Item(id="F-001", title="피드", evidence=EVIDENCE_OURS,
                         body="카드 3장 + 필터")]
        incoming = [Item(id="F-001", title="피드", evidence=EVIDENCE_OBSERVED,
                         body="카드 5장")]

        merged = merge_items(existing, incoming)

        self.assertEqual(merged[0].body, "카드 3장 + 필터")
        self.assertEqual(merged[0].notes, [f"{NOTE_CONFLICT_PREFIX}카드 5장"])

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
                         notes=[f"{NOTE_CONFLICT_PREFIX}카드 5장"])]
        incoming = [Item(id="F-001", title="피드", evidence=EVIDENCE_OBSERVED,
                         body="카드 7장")]

        merged = merge_items(existing, incoming)

        self.assertEqual(merged[0].notes, [f"{NOTE_CONFLICT_PREFIX}카드 7장"])
```

같은 파일 상단의 import 를 다음으로 바꾼다:

```python
from scripts.blueprint_merge import NOTE_ABSENT, NOTE_CONFLICT_PREFIX, merge_items
```

- [ ] **Step 2: Run test to verify it fails**

Run: `XDG_CONFIG_HOME="$(mktemp -d)" AUTOBOT_TEST_XDG_ISOLATED=1 AUTOBOT_NO_GLOBAL_PUBLISH=1 python3 -m unittest tests.test_blueprint_merge -v`

Expected: FAIL — `ImportError: cannot import name 'NOTE_CONFLICT_PREFIX'`

- [ ] **Step 3: Write minimal implementation**

`scripts/blueprint_merge.py` 의 `NOTE_ABSENT` 아래에 추가:

```python
NOTE_CONFLICT_PREFIX = "⚠ 관찰이 다름: "
```

`merge_items` 의 `if item.evidence == EVIDENCE_OURS:` 블록을 다음으로 바꾼다:

```python
        if item.evidence == EVIDENCE_OURS:
            # 회차마다 쌓으면 어느 것이 최신인지 알 수 없다 — 마지막 것만 남긴다.
            notes = [note for note in item.notes
                     if not note.startswith(NOTE_CONFLICT_PREFIX)]
            if candidate.body and candidate.body != item.body:
                notes.append(f"{NOTE_CONFLICT_PREFIX}{candidate.body}")
            merged.append(replace(item, notes=notes))
            continue
```

- [ ] **Step 4: Run test to verify it passes**

Run: `XDG_CONFIG_HOME="$(mktemp -d)" AUTOBOT_TEST_XDG_ISOLATED=1 AUTOBOT_NO_GLOBAL_PUBLISH=1 python3 -m unittest tests.test_blueprint_merge -v`

Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/blueprint_merge.py tests/test_blueprint_merge.py
git commit -m "feat(blueprint): 사람 항목과 관찰이 충돌하면 노트로 알린다"
```

---

### Task 8: 드리프트 리포트

**Files:**
- Modify: `scripts/blueprint_merge.py`
- Test: `tests/test_blueprint_merge.py`

**Interfaces:**
- Consumes: Task 5–7
- Produces: `drift_report(existing: list[Item], incoming: list[Item]) -> str` — 마크다운 한 덩이. `observed/drift.md` 에 그대로 쓰인다. 변화가 없으면 `"변화 없음.\n"` 을 돌려준다.

병합은 문서를 조용히 바꾼다. 사람이 무엇이 달라졌는지 알아야 청사진을 고칠지 판단할 수 있다.

- [ ] **Step 1: Write the failing test**

`tests/test_blueprint_merge.py` 에 새 클래스를 추가한다:

```python
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
```

같은 파일 상단의 import 를 다음으로 바꾼다:

```python
from scripts.blueprint_merge import (
    NOTE_ABSENT,
    NOTE_CONFLICT_PREFIX,
    drift_report,
    merge_items,
)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `XDG_CONFIG_HOME="$(mktemp -d)" AUTOBOT_TEST_XDG_ISOLATED=1 AUTOBOT_NO_GLOBAL_PUBLISH=1 python3 -m unittest tests.test_blueprint_merge -v`

Expected: FAIL — `ImportError: cannot import name 'drift_report'`

- [ ] **Step 3: Write minimal implementation**

`scripts/blueprint_merge.py` 끝에 추가:

```python
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
    if not (added or absent or conflicts or changed):
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
    if conflicts:
        sections.append("## 충돌 — 사람이 정한 항목과 관찰이 다름\n\n"
                        + "\n".join(f"- {b.id} {b.title}: 문서 \"{b.body}\" / "
                                    f"관찰 \"{a.body}\"" for b, a in conflicts))
    return "\n\n".join(sections) + "\n"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `XDG_CONFIG_HOME="$(mktemp -d)" AUTOBOT_TEST_XDG_ISOLATED=1 AUTOBOT_NO_GLOBAL_PUBLISH=1 python3 -m unittest tests.test_blueprint_merge -v`

Expected: PASS (11 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/blueprint_merge.py tests/test_blueprint_merge.py
git commit -m "feat(blueprint): 드리프트 리포트 — 회차 간 변화를 사람에게"
```

---

### Task 9: 라벨 검증 — 라벨 없는 항목은 통과시키지 않는다

**Files:**
- Modify: `scripts/blueprint_doc.py`
- Test: `tests/test_blueprint_doc.py`

**Interfaces:**
- Consumes: Task 1–4
- Produces: `unlabelled(items: list[Item]) -> list[Item]` — 근거 라벨이 없거나 `EVIDENCE_LABELS` 에 없는 항목들

스펙 규칙 1: *"모든 항목은 근거 라벨을 갖는다. 라벨 없는 문장은 금지."* 규칙이 검사되지 않으면 규칙이 아니다 — 오늘 clone 의 시각 점수가 그랬다.

- [ ] **Step 1: Write the failing test**

`tests/test_blueprint_doc.py` 에 새 클래스를 추가한다:

```python
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
```

같은 파일 상단의 import 블록에 `EVIDENCE_LABELS` 와 `unlabelled` 를 추가한다:

```python
from scripts.blueprint_doc import (
    EVIDENCE_LABELS,
    EVIDENCE_OBSERVED,
    EVIDENCE_OURS,
    Item,
    parse_items,
    read_doc,
    render_items,
    unlabelled,
    write_doc,
)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `XDG_CONFIG_HOME="$(mktemp -d)" AUTOBOT_TEST_XDG_ISOLATED=1 AUTOBOT_NO_GLOBAL_PUBLISH=1 python3 -m unittest tests.test_blueprint_doc -v`

Expected: FAIL — `ImportError: cannot import name 'unlabelled'`

- [ ] **Step 3: Write minimal implementation**

`scripts/blueprint_doc.py` 끝에 추가:

```python
def unlabelled(items: list[Item]) -> list[Item]:
    """근거 라벨이 없거나 알 수 없는 항목. 하나라도 있으면 문서가 계약을 어긴 것이다."""
    return [item for item in items if item.evidence not in EVIDENCE_LABELS]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `XDG_CONFIG_HOME="$(mktemp -d)" AUTOBOT_TEST_XDG_ISOLATED=1 AUTOBOT_NO_GLOBAL_PUBLISH=1 python3 -m unittest tests.test_blueprint_doc -v`

Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/blueprint_doc.py tests/test_blueprint_doc.py
git commit -m "feat(blueprint): 근거 라벨 검증 — 라벨 없는 항목을 보고한다"
```

---

### Task 10: CLI — 문서 하나를 검사하고 병합한다

**Files:**
- Modify: `scripts/blueprint_merge.py`
- Test: `tests/test_blueprint_merge.py`

**Interfaces:**
- Consumes: Task 5–9 전부
- Produces: `main(argv: list[str]) -> int` — `blueprint_merge.py check <doc.md>` 는 라벨 없는 항목이 있으면 `1`, 없으면 `0`.

이 계획의 산출물을 사람이 손으로 확인할 수 있는 표면. 관찰 계층(분할 ②)이 붙기 전까지 이것이 유일한 진입점이다.

- [ ] **Step 1: Write the failing test**

`tests/test_blueprint_merge.py` 에 새 클래스를 추가한다:

```python
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
```

같은 파일 상단 import 블록을 다음으로 바꾼다:

```python
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.blueprint_doc import EVIDENCE_OBSERVED, EVIDENCE_OURS, Item
from scripts.blueprint_merge import (
    NOTE_ABSENT,
    NOTE_CONFLICT_PREFIX,
    drift_report,
    merge_items,
)

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "blueprint_merge.py"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `XDG_CONFIG_HOME="$(mktemp -d)" AUTOBOT_TEST_XDG_ISOLATED=1 AUTOBOT_NO_GLOBAL_PUBLISH=1 python3 -m unittest tests.test_blueprint_merge -v`

Expected: FAIL — returncode 가 `2` (usage) 이거나 스크립트가 아무것도 하지 않는다

- [ ] **Step 3: Write minimal implementation**

`scripts/blueprint_merge.py` 의 import 블록을 다음으로 바꾼다:

```python
from blueprint_doc import (  # noqa: E402
    EVIDENCE_OBSERVED,
    EVIDENCE_OURS,
    Item,
    read_doc,
    unlabelled,
)
```

파일 끝에 추가:

```python
def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[1] != "check":
        print("ERROR: usage: blueprint_merge.py check <doc.md>", file=sys.stderr)
        return 2
    items = read_doc(argv[2])
    missing = unlabelled(items)
    if missing:
        print(f"ERROR: {len(missing)} item(s) have no valid 근거 label — "
              "every item must declare who owns it:", file=sys.stderr)
        for item in missing:
            print(f"ERROR:   {item.id} {item.title}", file=sys.stderr)
        return 1
    print(f"OK: {len(items)} item(s), every one labelled")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `XDG_CONFIG_HOME="$(mktemp -d)" AUTOBOT_TEST_XDG_ISOLATED=1 AUTOBOT_NO_GLOBAL_PUBLISH=1 python3 -m unittest tests.test_blueprint_merge -v`

Expected: PASS (13 tests)

- [ ] **Step 5: Run the whole suite**

Run: `bash tests/run_tests.sh 2>&1 | tail -5`
Expected: `OK` — 기존 테스트에 회귀 없음. (약 4~5분 걸린다.)

- [ ] **Step 6: Commit**

```bash
git add scripts/blueprint_merge.py tests/test_blueprint_merge.py
git commit -m "feat(blueprint): check 커맨드 — 라벨 계약을 사람이 확인할 표면"
```

---

## 이 계획이 끝나면

`ssot/*.md` 를 항목으로 읽고, 쓰고, 사람의 편집을 지키며 병합하고, 무엇이 달라졌는지 보고할 수 있다. **관찰 계층은 아직 없다** — 분할 ②(iOS 관찰 → `observed/` 생성 → `ssot/` 초안 합성)와 ③(웹)이 이 계약 위에 데이터를 붓는다.

`scripts/blueprint_merge.py check` 가 유일한 사용자 표면이고, 스킬 파일(`skills/autobot-blueprint/SKILL.md`)과 커맨드(`commands/blueprint.md`)는 분할 ②에서 쓴다 — 관찰 없이 스킬 문서를 쓰면 아직 못 하는 일을 약속하게 된다.
