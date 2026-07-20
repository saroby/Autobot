---
name: autobot-make
user-invocable: false
description: Use when generating or updating a project Makefile with conventional dev-workflow targets (install/run/dev/stop/test/clean). For any program that binds a TCP port, the run target first kills the previous port holder so restarts never hit "address already in use". Detects the project's runtime, start command, and port(s) before writing. Triggers on "Makefile 만들어줘", "make 명령어 추가", "make run 만들어줘", "포트 죽이고 재시작", "/autobot:make".
---

# Autobot Make — 프로젝트 Makefile 생성 (포트 재사용 안전)

현재 프로젝트에 맞는 `Makefile` 을 생성/갱신한다. 핵심: **포트를 바인딩하는 프로그램은 `run` 이 이전 포트 점유 프로세스를 먼저 kill** 해서 재시작이 "address already in use" 로 실패하지 않게 한다.

## CRITICAL RULES

1. **Makefile 은 레시피 줄이 반드시 TAB 들여쓰기** — 스페이스면 `missing separator` 로 깨진다. `references/port-targets.mk` 의 레시피를 그대로 복사하면 탭이 보존된다.
2. **비파괴 병합** — 기존 `Makefile` 이 있으면 사용자가 쓴 타깃을 지우지 않는다. 없는 타깃만 추가하고, 같은 이름 타깃은 사용자에게 확인 후에만 교체한다.
3. **해당하는 타깃만** — 포트를 안 쓰는 프로그램(CLI, 라이브러리)엔 `kill-port` 를 넣지 않는다. 있는 명령만 만든다("있어 보이는" 타깃 지어내지 않기).
4. **탐지 우선** — 실행 명령·포트를 추측하지 말고 프로젝트 파일에서 읽는다(아래 표).

## Workflow

### Step 1 — 프로젝트 탐지 (실행 명령 + 포트)

| 신호 | 실행 명령 | 포트 출처 |
|------|----------|----------|
| `package.json` scripts.dev/start | `npm run dev` / `npm start` | 코드/`.env`(`PORT`), 기본 3000 |
| `pyproject.toml`/`requirements.txt` + FastAPI/uvicorn | `uvicorn app.main:app --reload --port <P>` | `--port`, 기본 8000/8080 |
| Flask | `flask run --port <P>` | 기본 5000 |
| Django | `python manage.py runserver 0.0.0.0:<P>` | 기본 8000 |
| `docker-compose.yml` | `docker compose up` | `ports:` 매핑의 호스트 포트 |
| `go.mod` | `go run .` | 코드의 `:PORT` 리터럴 |
| Makefile 이미 존재 | 기존 타깃 파싱 | 기존 `PORT`/`PORTS` 변수 |

포트를 못 찾으면 하나만 물어본다(추측 금지). 여러 포트면 `PORTS = 8080 5173` 처럼 공백 구분.

### Step 2 — 타깃 선택

해당하는 것만: `install`(의존성) · `run`/`dev`(실행) · `stop`(= kill-port) · `test` · `clean`. 서버가 아니면 `kill-port`/`stop` 생략.

### Step 3 — Makefile 작성

`references/port-targets.mk` 의 `kill-port` 레시피를 **탭 보존한 채** 프로젝트 `Makefile` 에 인라인하고(별도 include 파일보다 자기완결 Makefile 이 친절), 서버 `run` 을 `kill-port` 에 의존시킨다:

```makefile
PORTS ?= 8080

.PHONY: install run stop test clean kill-port

install:
	npm install

# run 은 kill-port 에 의존 → 이전 포트 점유 프로세스를 먼저 정리하고 시작
run: kill-port
	npm run dev

stop: kill-port

kill-port:
	@for p in $(PORTS); do \
		pids=$$(lsof -ti tcp:$$p 2>/dev/null || true); \
		if [ -n "$$pids" ]; then \
			echo ">> freeing port $$p (killing: $$pids)"; \
			kill -9 $$pids 2>/dev/null || true; \
		else \
			echo ">> port $$p already free"; \
		fi; \
	done

test:
	npm test

clean:
	rm -rf node_modules
```

`run:` 앞의 예시 명령/타깃은 Step 1 탐지 결과로 치환한다. `kill-port` 블록은 `references/port-targets.mk` 와 동일해야 한다(그 파일이 SSOT 이고 `tests/test_make_port_kill.py` 가 검증).

### Step 4 — 결과 표시

작성한 `Makefile` 을 보여주고 사용 예를 한 줄로 안내: `make run` → 포트 정리 후 시작, `make stop` → 포트 해제.

## 포트-kill 규약 (SSOT)

재사용 규약은 `references/port-targets.mk` 가 소유한다:
- `lsof -ti tcp:<port>` 로 PID 조회 → 있으면 `kill -9`, 없으면 "already free" (빈 입력에도 안전).
- 여러 포트는 `PORTS` 공백 구분 루프.
- ponytail: `lsof` 가 이식성 기본. lsof 없는 최소 Linux 이미지는 `fuser $$p/tcp` 로 교체(파일 주석 참조).

## Output Artifacts

| 산출물 | 경로 | 비고 |
|-------|------|------|
| 프로젝트 Makefile | `<project>/Makefile` | 생성 또는 비파괴 병합 |

## Preconditions

- `make`, `lsof` 사용 가능 (macOS·대부분 Linux 기본)
- 서버 실행 명령·포트를 파일에서 읽을 수 있거나 사용자가 1개 확인
