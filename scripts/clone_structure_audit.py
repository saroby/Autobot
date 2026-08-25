#!/usr/bin/env python3
"""clone_structure_audit.py — 구조가 실제로 뽑혔는지 확인하는 세 번째 축.

    clone_structure_audit.py <clone-root> <stem> <view>

`clone_structural_diff.py` 는 측정한 요소가 렌더에 다 있는지(요소 축)를 보고,
`device_compare.py` 는 원본과 닮았는지(픽셀 축)를 본다. 둘 다 충실도를 재지,
생성된 코드에 구조가 있는지는 아무도 재지 않는다 — 그 구멍 때문에 카드 30장을
독립된 30개 블록으로 찍어낸 결과물도 두 축을 만점으로 통과할 수 있었다.

`clone_structure.py` 가 반복 그룹을 감지해 `structure/<stem>.json` 에 초안을
쓰고, `clone_view_codegen.py` 의 `repeat_units()` 가 확정된 그룹을 컴포넌트 +
`ForEach` 로 뽑는다. 문제는 `repeat_units()` 가 그룹을 조용히 건너뛰는 경로가
있다는 것이다 — id 를 다른 그룹이 먼저 채간 경우, crop 이 id 하나를 지워
부분집합이 깨진 경우, 스크롤 경계를 넘는 경우. 어느 쪽이든 결과는 같다: 화면이
평평한 replay 로 조용히 되돌아가고, `polish` 는 여전히 성공을 보고한다.

규칙은 비율이 아니라 원칙이다: **선언된 그룹은 전부 추출된 컴포넌트로
나타나야 한다.** 아무도 측정한 적 없는 퍼센트 문턱을 새로 만드는 대신, 하나라도
빠지면 그 화면은 실패다. 감지된 그룹이 없는 화면은 애초에 뽑을 게 없으므로
실패가 아니다.

이 게이트가 주장하지 *않는* 것: 추출된 컴포넌트의 내용이 옳다거나, 그
컴포넌트가 좋은 이름인지, 반복 감지 자체가 맞았는지는 보지 않는다. 오직
"선언되었다면 뽑혔는가"만 본다 — 요소 충실도·시각 유사도와 같은 층위에서,
같은 이유로: 사람이 편집할 수 있는 코드인지 아닌지가 숫자 뒤에 숨지 않게.

사람이 화면을 손으로 가져간 경우(`clone_view_codegen.MARKER` 를 지운 경우)는
그 사람 소유다 — 파이프라인의 나머지가 쓰는 것과 같은 소유권 경계를 따라, 이
게이트도 그 화면에서는 손을 뗀다.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

# clone_view_codegen.py 가 이미 아는 것(구조 파일을 읽는 법, 생성 마커의 정확한
# 문자열)을 다시 쓰지 않는다 — 두 벌의 "구조 파일 읽기"가 갈라지면 이 게이트가
# 확정 그룹이라 믿는 것과 생성기가 실제로 시도한 것이 서로 달라질 수 있다.
_codegen_spec = importlib.util.spec_from_file_location(
    "clone_view_codegen", Path(__file__).resolve().parent / "clone_view_codegen.py")
codegen = importlib.util.module_from_spec(_codegen_spec)
assert _codegen_spec.loader is not None
_codegen_spec.loader.exec_module(codegen)


def audit_screen(root: Path, stem: str, view: str) -> tuple[list[str], int]:
    """한 화면의 선언된 반복 그룹 중 추출되지 않은 것을 찾는다.

    반환값은 (보고 줄들, 추출 실패 그룹 수) — 두 번째 값이 0보다 크면 실패다.
    """
    groups = codegen.confirmed_groups(root, stem)
    if not groups:
        return [f"OK: {stem} declares no repeat group — nothing to extract"], 0

    source = root / "Sources" / f"{view}.swift"
    if not source.is_file():
        return ([f"ERROR: {stem} ({view}) declares {len(groups)} repeat group(s) "
                  f"but {source} does not exist"], len(groups))

    text = source.read_text(encoding="utf-8", errors="replace")
    if codegen.MARKER not in text:
        # 생성 마커가 없다는 것은 사람이 이 화면을 가져갔다는 뜻이다 — 이제부터
        # 그 사람 것이고, `clone_view_codegen.py` 도 이 파일을 다시 쓰지 않는다.
        # 추출을 요구하는 것은 이 화면을 소유한 사람에게 파이프라인의 규칙을
        # 강요하는 것이라 이 게이트도 같은 경계에서 손을 뗀다.
        return ([f"OK: {stem} ({view}) is hand-owned — the generated marker is "
                  f"gone, exempt from the structure gate"], 0)

    # `repeat_units()` 가 뽑은 그룹은 파일 끝에 정확히 이 모양으로 나타난다
    # (`_unit_struct()` 참고). 이름이 같으면 뽑힌 것이고, 없으면 조용히
    # 건너뛴 것이다 — id 충돌·crop 결손·스크롤 경계 넘김 중 하나.
    missing = []
    for group in groups:
        component = group.get("component")
        needle = f"struct {component}: View" if component else None
        if not needle or needle not in text:
            missing.append(component or "<component 이름 없음>")
    if missing:
        return ([f"ERROR: {stem} ({view}) declares {len(groups)} repeat group(s) "
                  f"but did not extract {len(missing)}: {', '.join(missing)} — "
                  f"the screen reverted to flat replay for these"], len(missing))
    return ([f"OK: {stem} ({view}) extracted all {len(groups)} declared "
              f"repeat group(s)"], 0)


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print("ERROR: usage: clone_structure_audit.py <clone-root> <stem> <view>",
              file=sys.stderr)
        return 2
    root, stem, view = Path(argv[1]), argv[2], argv[3]
    lines, missing = audit_screen(root, stem, view)
    for line in lines:
        print(line)
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
