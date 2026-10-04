---
name: autobot-make
user-invocable: false
description: "Generate or update a project Makefile with runtime-specific development targets (/autobot:make)."
---

# Autobot Make

프로젝트 실행 명령·포트를 탐지해 `<project>/Makefile`을 생성하거나 비파괴 병합한다. 서버의 `run`은 `kill-port`에 의존해 이전 포트를 해제하고 시작한다.

## 탐지·타깃 선택

| 프로젝트 신호 | 실행 명령·포트 출처 |
|---|---|
| `package.json` scripts.dev/start | `npm run dev` / `npm start`, 코드·`.env`의 `PORT`(기본 3000) |
| FastAPI/uvicorn | 실제 모듈의 `uvicorn … --reload --port <P>`, `--port`(기본 8000/8080) |
| Flask | `flask run --port <P>`(기본 5000) |
| Django | `python manage.py runserver 0.0.0.0:<P>`(기본 8000) |
| `docker-compose.yml` | `docker compose up`, `ports:`의 호스트 포트 |
| `go.mod` | `go run .`, 코드의 `:PORT` |
| 기존 Makefile | 기존 타깃과 `PORT`/`PORTS` |

명령·포트는 파일에서 확인한다. 포트를 못 찾으면 하나만 물어보고, 여러 포트는 `PORTS = 8080 5173`처럼 공백으로 구분한다.

존재하는 명령에 해당하는 `install` · `run`/`dev` · `stop` · `test` · `clean`만 만든다. 포트를 안 쓰는 CLI/라이브러리는 `kill-port`/`stop`을 생략한다.

## 작성 계약

- 기존 사용자 타깃은 보존하고 없는 것만 추가한다. 같은 이름 타깃은 확인 후에만 교체한다.
- 레시피는 **TAB 들여쓰기**다(스페이스는 `missing separator`).
- [references/port-targets.mk](references/port-targets.mk)의 `kill-port` 블록을 탭 보존해 인라인한다. 이 파일이 SSOT이며 블록은 동일해야 한다(`tests/test_make_port_kill.py`가 검증).
- 서버 `run: kill-port`, `stop: kill-port`를 연결하고 `.PHONY`를 실제 타깃에 맞춘다.
- 포트 규약: `lsof -ti tcp:<port>` → PID가 있으면 `kill -9`, 없으면 `already free`. `PORTS` 루프는 빈 입력에도 안전해야 한다. lsof 없는 최소 Linux는 reference 주석대로 `fuser $$p/tcp`를 쓴다.

작성한 Makefile과 `make run`(포트 해제 후 시작) / `make stop`(포트 해제) 사용법을 보여준다. 실행 환경에는 `make`와 `lsof` 또는 위 대체 도구가 필요하다.
