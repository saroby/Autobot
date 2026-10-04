---
name: autobot-blueprint
description: "Validate or merge ssot/*.md blueprint items while preserving human edits."
---

# Autobot Blueprint

사람 편집을 보존하며 `ssot/*.md` 항목을 검증·병합한다. 입력은 사람이 쓰거나 다른 도구가 만든 문서다. **대상 서비스 관찰→`observed/` 수집→청사진 합성 계층은 아직 없다.** 설계: `docs/superpowers/specs/2026-08-25-autobot-blueprint-design.md` 분할 ②·③.

## 항목 계약

```markdown
# 기능

## F-012 피드 무한 스크롤
근거: 관찰 · observed/inventory.md#feed

스크롤 끝에서 다음 페이지를 불러온다.
<img src="../observed/raw/03-feed.png" width="220">

> ⟦auto:conflict⟧ ⚠ 관찰이 다름: 카드 5장
```

- ID는 `<접두사>-<숫자>`: `V`(제품), `P`(원칙), `F`(기능), `E`(엔티티), `D`(디자인). 병합 키이자 참조 주소다.
- 첫 항목 앞 머리말과 본문의 이미지 위치를 보존한다. 썸네일 생성 없이 원본 `<img … width="220">`을 쓴다(stdlib만 사용, Pillow 없음).
- `⟦auto:…⟧` 마커 줄만 기계 노트다. 마커 없는 인용문은 사람 본문이며, 노트 종류는 문자열 접두사가 아닌 `kind`로 판별한다.
- 라벨·제목·본문·노트는 NFC 정규화한다(macOS NFD에서도 보호 라벨이 같아야 한다).

| 필수 근거 라벨 | 소유·재실행 |
|---|---|
| `관찰` | 실제로 본 것, 기계 갱신 |
| `공개자료` | 공개 문서·리뷰, 기계 갱신 |
| `가설(미검증)` | 확인 못 한 추론, 기계 갱신 |
| `우리 결정` | 사람 소유, 교체 금지 |

사람은 라벨을 `우리 결정`으로 바꿔 항목을 보호하고, 기계 노트의 마커를 지워 사람 본문으로 전환한다. 관찰과 추론을 섞거나 근거 없는 칸을 채우지 않는다(알 수 없으면 비워두고 사람에게 넘긴다).

## 병합·드리프트

`merge_items(existing, incoming) -> list[Item]`는 입력을 변형하지 않는 순수 함수다.

1. 기존 순서 유지, 새 항목은 뒤에 추가.
2. `우리 결정`은 보존. 다른 관찰은 `⚠ 관찰이 다름: …` 노트로 알린다.
3. 새 관찰이 있을 때만 교체한다. 본문을 못 뽑은 회차는 기존 충돌 노트와 관찰 본문·이미지·참조를 비우지 않는다.
4. 최근 회차에 없는 `관찰`은 삭제 대신 `관찰: 최근 회차에 없음` 표시.

`drift_report(existing, incoming) -> str`는 **새로 관찰됨 · 최근 회차에 없음 · 내용이 바뀜 · 근거가 바뀜 · 충돌**을 보고하며, 변화가 없으면 `변화 없음.`을 반환한다.

## 검증·산출물

```bash
python3 scripts/blueprint_merge.py check ssot/features.md
```

라벨 없는 항목, 항목이 아닌 `##` 줄, 중복 ID, 닫히지 않은 코드펜스를 거부한다. 성공 출력은 `OK: N item(s), every one labelled`.

파서·렌더러 변경 시 `write_doc(path, read_doc(path))` 항등성을 검증한다. 재실행은 사람 내용을 지우면 안 된다.

- `ssot/*.md`: 사람이 편집하는 제품 청사진, `/autobot:mvp`의 입력.
- `observed/*`: 관찰 계층 구현 후 기계 증거.
- `autobot-ssot`: 같은 형식의 문서를 인터뷰로 작성.
- `autobot-clone-app`: 대상 앱 화면 재현. 아직 없는 관찰 계층을 이 스킬의 능력으로 주장하지 않는다.
