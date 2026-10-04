---
name: autobot-ssot
user-invocable: false
description: "Interview, resume, or update the product blueprint and its ssot submodule (/autobot:ssot)."
---

# Autobot SSOT

제품 인터뷰 결정을 재빌드 가능한 `ssot/` 청사진으로 기록하고 독립 git repository/submodule로 관리한다. 파이프라인 밖에서도 동작한다. 제품 정수는 `ssot/`, 화면 픽셀·구현 디테일은 `docs/screens/`·코드 소유다.

## 산출물·진입 상태

| 산출물 | 역할·기존 처리 |
|---|---|
| `ssot/*.md` | 인터뷰 정본, 라운드마다 갱신·재개 |
| 루트 `SOUL.md` | 제품 정체성 증류, 비파괴 병합 |
| 루트 `AGENTS.md` | 작업 규칙·SSOT 지도, 비파괴 병합 |
| `.gitmodules` + `ssot` gitlink | 청사진 별도 repo, 기존 submodule은 UPDATE |

**CLAUDE.md는 만들거나 수정·병합하지 않는다.** [references/templates.md](references/templates.md)의 파일 세트는 상한이다. 내용이 나온 파일만 만들고 빈 파일·헤딩은 만들지 않는다:

- `README.md`: 인덱스, status frontmatter, 재빌드 안내.
- `product.md`: 문제·유저와 순간·차별화·성공 지표.
- `features.md`: MVP/이후 기능·우선순위.
- `domain.md`: 엔티티·관계·용어집.
- `principles.md`: 원칙·하지 않을 것·제약.
- `design.md`: 톤·플랫폼·디자인 방침.
- `decisions.md`: 결정 로그·미결/재검토.

질문 전에 git/submodule(`git submodule status ssot`, `.gitmodules` 등록, `ssot/.git` 파일), 기존 청사진·SOUL·AGENTS·코드·`.autobot/architecture.md`를 확인한다.

| 상태 | 처리 |
|---|---|
| A: `ssot/` 없음 | 신규 인터뷰→청사진→배선 |
| B: 일반 디렉토리 | README `interviewing`: 마지막 라운드 다음; `confirmed`: 인터뷰 생략, 확정·배선부터 |
| C: 이미 submodule | UPDATE. 변경 라운드만 재오픈→submodule 안에서 편집·커밋·푸시→부모 gitlink 갱신. `gh repo create`/`submodule add` 재실행 금지 |

진입 상태·스캔을 2–4줄로 알린다. A/B 인터뷰 시작부터 README `status: interviewing`으로 기록한다. 재개 정본은 `ssot/`이며 별도 상태 파일을 만들지 않는다.

## 인터뷰 계약

- 코드·문서가 답을 주면 재질문하지 않고 확인한다. 설문 확인형은 `confirm: true`, `hint: "현재 파악: …"`를 사용한다.
- **대화로 한 줄 정의·누구의 어떤 문제인지부터** 시작한다(이미 받은 답은 확인만). 맥락 없이 첫 설문을 띄우지 않는다.
- 한 주제의 1–3질문은 대화, 4개 이상 또는 2주제 이상은 브라우저 설문. 설문 기동 실패(포트/python)는 대화로 fallback. 되돌리기 어려운 외부 동작(GitHub repo 생성)은 AskUserQuestion으로 확인하며 설문으로 대체하지 않는다.
- 대화는 한 라운드 한 주제, 설문은 R1–R5 여러 섹션을 한 장에 묶는다. **제출 즉시 해당 ssot 파일에 기록**하며 기존 섹션에 추가하고 헤딩을 중복 생성하지 않는다.
- 모호한 답만 다음 설문에서 구체 시나리오로 한 번 되묻는다. 그래도 미결이면 추천안을 `(잠정)`으로 채택하고 decisions에 재검토 기록.
- `skipped` 빈칸은 **다시 묻지 않는다**. decisions에 `미응답 — 필요해지면 재질문` 기록; 청사진 필수 항목은 `(잠정)` 추천안으로 채운다.
- 선택지는 실제로 다른 결과를 낳는 중립 대안이다. 설문 기본 선택·미리 입력·추천 표시 금지. 확인값은 hint에만 두고 입력은 비운다(손대지 않으면 기존값 유지); 추천은 응답 후 대화로 한다.

| 라운드 | 결정→파일 |
|---|---|
| R1 존재 이유 | 한 문장 정의, 문제·현재 대체재, 유저·순간, 차별화, 숫자/관찰 행동 성공 지표→product |
| R2 기능 | 차별화를 구현할 핵심 기능·P0/P1/P2·이유, 훅을 포함한 MVP/이후 경계→features |
| R3 도메인 | 엔티티·핵심 속성·관계, 혼동할 용어 정의→domain |
| R4 원칙 | 타협하지 않을 2–4원칙, 배제 기능/패턴, 플랫폼·규제·성능/프라이버시 제약→principles |
| R5 디자인 | 톤 3개와 UI 의미, 플랫폼/폼팩터, 레퍼런스, 모션·다크모드 방침→design |
| R6 확정 | 전체 청사진·재빌드 안내 스냅샷 승인→README `confirmed` |

기존 답에 따라 라운드를 축소한다. 첫 설문은 이미 답한 질문을 제외한 R1–R5 넓은 스윕, 이후는 얇게 답한 섹션만 심화한다. R1 차별화/R2 MVP가 바뀌면 기능·도메인도 갱신하거나 유지 이유를 decisions에 남긴다.

## 설문 실행·복구

spec/answers 스키마와 질문 타입(`text`/`textarea`/`choice`/`multi`, `hint`/`other`/`confirm`)은 `scripts/interview_form.py` docstring이 소유한다. 상태는 **ssot 밖** `.autobot/ssot-form/`에 두고 커밋하지 않는다. 첫 기동 전에 `.gitignore`에 `.autobot/`가 없으면 추가한다.

이번 질문 `spec-r<N>.json`을 먼저 쓴 후, 설문 전용 포트 8766으로 서버를 세션에서 분리한다:

```bash
lsof -ti :8766 | xargs kill 2>/dev/null
nohup python3 "$CLAUDE_PLUGIN_ROOT/scripts/interview_form.py"   .autobot/ssot-form/spec-r<N>.json .autobot/ssot-form/answers-r<N>.json --port 8766   > .autobot/ssot-form/server.log 2>&1 & disown
```

- 첫 장만 `open http://127.0.0.1:8766/`. 재기동마다 URL을 사용자에게 보여준다(닫힌 탭 복구용).
- 추적 백그라운드 태스크(`run_in_background: true`)는 턴 끝에 죽으므로 사용하지 않는다. 제출은 Monitor `persistent: true`로 answers 파일을 기다린다.
- 서버가 죽으면 같은 포트로 재기동한다. 이미 열린 정적 폼의 입력은 유지되므로 다시 열도록 요청하지 않는다.
- `action: "next"`: 답변·skipped 즉시 기록→다음 spec 먼저 작성→같은 포트 재기동. `round`는 단조 증가하며 대기 페이지가 자동 이동한다.
- `action: "done"`: 기록 후 새 질문 없이 R6로. **완료는 질문 종료이며 스냅샷 승인·배선 확인을 대신하지 않는다.**
- 제출이 오래 없으면 한 줄로 상태를 알린다. 재개는 마지막 answers 다음 장부터; 폼 상태는 힌트이며 지워져도 ssot로 재개한다.

## SSOT 병합·submodule

완성 ssot→SOUL→AGENTS 순서로 templates를 적용한다. 기존 문장·섹션은 보존하고 이번 결정만 추가하며 충돌은 사용자에게 확인한다. SOUL은 product/principles 요약 + ssot 정본 포인터, AGENTS 지도에는 `ssot/`(재빌드 청사진)와 `docs/screens/`(화면 spec)를 명시한다.

배선·정확한 커맨드·실패 재개는 **[references/submodule-setup.md](references/submodule-setup.md)**만 따른다:

- 부모 git이 없으면 먼저 `git init`.
- 원격은 GitHub repo / 로컬 bare / 건너뛰기 중 확인. **GitHub 생성은 실행 전 외부 동작 확인**이 필요하다. 이름은 origin/디렉토리에서 `<project>-ssot`로 유도한다.
- 완성 ssot 안에서 init·commit→원격 생성·푸시 성공 검증→기존 repo를 `git submodule add` + `absorbgitdirs`로 등록. 원본 이동·재clone·삭제 없이 각 성공 후 진행한다. 로컬 bare도 file transport 설정 변경 없이 등록한다.
- repo 이름 충돌은 `already_exists`로 기존 원격 재사용. C는 배선 대신 UPDATE.
- 부모 `.gitmodules`+gitlink 커밋을 권장하고 `git add .gitmodules ssot`처럼 **명시 스테이징**한다(`git add -A` 금지). 커밋 여부·내용을 보고한다.
- 배선 완료 후 README `status: blueprinted`.

최종 보고: A/B/C와 수행 내용, 제품 정의·차별화, ssot 파일 및 SOUL/AGENTS 생성/병합/유지, 원격 URL·부모 커밋·`git submodule status ssot`, 미결/재검토, `git submodule add <url> ssot` 재사용 안내.
