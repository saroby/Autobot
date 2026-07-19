# git submodule 배선 — 정확한 절차와 실패 처리

`ssot/` 를 **별도 repository** 로 승격해 부모 프로젝트에 submodule 로 연결한다. 목적은 재사용: 다른 프로젝트에서 `git submodule add <url> ssot` 로 같은 청사진을 다시 끌어온다. 이 파일이 배선의 SSOT — 실패 지점이 몰려 있으니 순서와 가드를 그대로 지킨다.

이 스킬은 **사용자의 임의 프로젝트**에서 돈다. Autobot 전용 값을 가정하지 않는다.

## 0. 진입 상태 재확인 (Step 0 에서 이미 판정했으면 스킵)

```bash
git rev-parse --is-inside-work-tree 2>/dev/null       # git 여부
git submodule status ssot 2>/dev/null                  # 이미 submodule 이면 non-empty
grep -q 'path = ssot' .gitmodules 2>/dev/null && echo ALREADY_SUBMODULE
test -f ssot/.git && echo ALREADY_SUBMODULE            # .git 이 파일 = submodule
```

- `ALREADY_SUBMODULE` → **UPDATE 절차**(맨 아래)로. `gh repo create`·`submodule add` 재실행 금지.
- git work tree 아님 → **1단계**로 (git init 먼저).
- git 있고 submodule 아님 → **2단계**로.

## 1. git 없으면 부모 초기화

사용자가 명시 요청한 동작. 부모에 git 이 없을 때만:

```bash
git init
# 첫 커밋이 없어도 submodule add 는 동작한다. .gitignore 등 기존 파일은 건드리지 않는다.
```

## 2. 원격 위치 결정 (AskUserQuestion — 실행 전 확인)

**GitHub repo 생성은 외부로 나가는 동작이다. 만들기 전에 반드시 확인받는다.** 선택지:

1. **GitHub repo 생성** (추천) — 프로젝트 간 재사용 가능. `gh` 인증 필요.
2. **로컬 bare repo** — 오프라인·비공개. 이 머신 밖에선 재사용 불가.
3. **지금은 건너뛰기** — `ssot/` 를 일반 폴더로 두고 배선은 나중에. status 는 `confirmed` 로 남긴다.

repo 이름은 프로젝트에서 유도:
```bash
# 기존 origin 이 있으면 그 이름 기반, 없으면 디렉토리명
basename "$(git config --get remote.origin.url 2>/dev/null || pwd)" .git   # → <project>
# 제안 이름: <project>-ssot
```

`gh` 가능 여부:
```bash
gh auth status 2>&1 | grep -q 'Logged in' && echo GH_OK || echo GH_MISSING
```
`GH_MISSING` 이면 GitHub 선택지를 빼고 로컬 bare / 건너뛰기만 제시한다.

## 3. ssot/ 를 독립 repo 로 만들고 원격에 올린다

`ssot/` 내용이 완성된 뒤(R6 승인) 실행. **아직 부모 인덱스에 `ssot/` 를 add 하지 않은 상태여야 한다.**

```bash
git -C ssot init
git -C ssot add -A
git -C ssot commit -m "chore(ssot): initial product blueprint"
```

### 3a. GitHub repo (선택 1)

```bash
# already_exists 를 성공으로 취급 (register-app 멱등 패턴)
gh repo create "<owner>/<project>-ssot" --private --source ssot --remote origin --push 2>&1 | tee /tmp/ssot_create.log
```
- 성공 → 원격 URL 확보.
- **이미 존재**(`Name already exists` / `already exists`) → 에러 아님. 기존 원격을 재사용:
  ```bash
  gh repo view "<owner>/<project>-ssot" --json url -q .url   # URL 확인
  git -C ssot remote get-url origin 2>/dev/null || git -C ssot remote add origin <url>
  git -C ssot push -u origin HEAD
  ```

### 3b. 로컬 bare repo (선택 2)

```bash
BARE="$(cd .. && pwd)/<project>-ssot.git"      # 부모 밖 sibling 위치
git init --bare "$BARE"
git -C ssot remote add origin "$BARE"
git -C ssot push -u origin HEAD
```
URL 은 이 bare 경로.

## 4. 푸시 성공을 검증한다 (가드 — mv/rm 전 필수)

**부분 푸시면 재-clone 이 불완전해지고, 이미 원본을 옮긴 뒤라 유실된다. 검증 통과 전에는 5단계로 넘어가지 않는다.**

```bash
# 로컬 HEAD 와 원격 HEAD 가 같은 커밋을 가리키는지 확인
LOCAL=$(git -C ssot rev-parse HEAD)
REMOTE=$(git -C ssot ls-remote origin HEAD | cut -f1)
[ "$LOCAL" = "$REMOTE" ] && echo PUSH_OK || echo PUSH_FAILED
```
`PUSH_FAILED` → 원인 보고하고 **중단**. `ssot/` 는 일반 폴더 그대로 두고 status `confirmed` 유지 (다음 호출이 이 지점부터 재개).

## 5. 부모에 submodule 로 연결

푸시 검증(`PUSH_OK`) 후에만.

```bash
URL=$(git -C ssot remote get-url origin)
mv ssot ssot.tmp                    # 원본을 옆으로 (원격에 동일 내용이 이미 있음)
git submodule add "$URL" ssot       # 원격에서 fresh clone → ssot/ 재생성
rm -rf ssot.tmp                     # 확인 후 원본 제거
git submodule status ssot           # 정상 배선 확인 (커밋 해시 + ssot 출력)
```
`submodule add` 가 "already exists in the index" 로 실패하면 상태 C 를 놓친 것 → UPDATE 절차로 전환.

## 6. 부모 커밋 (권장 — 보고에 명시)

`submodule add` 는 `.gitmodules` + gitlink 를 stage 만 한다. staged-uncommitted 는 취약하니 배선의 일부로 커밋을 권장한다. 커밋 여부·메시지는 최종 보고에 남긴다.

```bash
git add .gitmodules ssot
git commit -m "chore(ssot): add product blueprint as submodule"
```

배선 완료 후 **submodule 안의** `ssot/README.md` status 를 `blueprinted` 로 갱신하고, 그 변경도 submodule 에서 커밋·푸시한 뒤 부모 gitlink 를 갱신한다 (UPDATE 절차 재사용).

---

## UPDATE 절차 (상태 C — 이미 submodule)

이미 배선된 청사진을 갱신할 때. **부모가 아니라 submodule 안에서 편집한다.** 순서가 중요하다 — submodule 은 흔히 detached HEAD 라, **브랜치로 먼저 옮긴 뒤** 커밋해야 커밋이 유실되지 않는다.

```bash
# 1) 브랜치 먼저 (detached HEAD 대비 — commit/push 전에). main 있으면 붙고, 없으면 만든다.
git -C ssot switch main 2>/dev/null || git -C ssot switch -c main
# 2) 인터뷰 결과를 ssot/ 안 파일에 반영 (일반 편집) 후 커밋·푸시
git -C ssot add -A
git -C ssot commit -m "docs(ssot): <이번 라운드 요약>"
git -C ssot push -u origin main
# 3) 푸시 성공 검증 (부모 gitlink 를 올리기 전 필수 — 4단계와 동일 가드)
LOCAL=$(git -C ssot rev-parse HEAD); REMOTE=$(git -C ssot ls-remote origin main | cut -f1)
[ "$LOCAL" = "$REMOTE" ] && echo PUSH_OK || echo PUSH_FAILED
# 4) PUSH_OK 일 때만 부모의 gitlink(하위 커밋 포인터) 갱신
git add ssot
git commit -m "chore(ssot): bump blueprint"
```

- **순서 불변식**: `switch 브랜치 → add → commit → push → PUSH_OK 검증 → 부모 gitlink 커밋`. 브랜치 전환을 커밋 뒤로 미루면 detached HEAD 에 남긴 커밋이 `main` 밖으로 새어 유실된다.
- `PUSH_FAILED`(non-ff·네트워크) → 원인 보고하고 **중단**. 부모 gitlink 를 올리지 않는다 (아무도 fetch 못 하는 커밋을 가리키게 됨).
- 부모 커밋은 6단계와 같이 권장하되 보고에 명시.
