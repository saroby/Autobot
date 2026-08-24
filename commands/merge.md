---
name: merge
description: 현재 수정을 모두 커밋하고 default branch 로 머지해 push
---

현재 체크아웃의 수정을 전부 default branch 에 반영한다. 브랜치 전환 없이
진행한다 (워크트리에서는 default branch 를 checkout 할 수 없는 경우가 있다).

1. `git status` 로 변경을 확인한다. 변경이 없고 로컬 커밋도 이미 push 됐다면 "반영할 것 없음"으로 끝낸다.
2. default branch 를 알아낸다: `git symbolic-ref refs/remotes/origin/HEAD --short` (실패 시 `git remote show origin` 의 HEAD branch).
3. 변경이 있으면 전부 스테이징(`git add -A`)하고, 이번 세션에서 한 작업을 요약한 한국어 커밋 메시지로 커밋한다.
4. `git fetch origin` 후 `origin/<default>` 가 현재 브랜치의 조상이 아니면 `git merge origin/<default>` 로 먼저 머지한다. 충돌이 나면 멈추고 충돌 파일을 보고한다 — 임의로 한쪽을 버리지 않는다.
5. `git push origin HEAD:<default>` 로 default branch 에 push 한다.
6. 현재 브랜치도 `git push origin HEAD` 로 올려 둔다 (원격 세션 브랜치가 있으면 동기화).
7. push 된 커밋 해시와 반영된 내용을 한 줄로 보고한다.
