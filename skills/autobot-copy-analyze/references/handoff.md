### Step 6 — 검토 + 핸드오프

1. **화면 흐름도를 만든다.** 탐험 로그가 이미 모든 전이를 갖고 있다 — 쓰지 않으면 버리는 것이다.
   ```bash
   scripts/device_flow.py map .autobot/copy-analysis/flow.jsonl .autobot/copy-analysis/flow-map.html
   scripts/device_flow.py stats .autobot/copy-analysis/flow.jsonl     # 커버리지 한 줄
   ```
   이미지 경로는 출력 파일 기준 상대경로라, **산출물 폴더 안에 직접 생성해야** `device/00-home.png` 로 붙어 폴더째 옮겨도 안 깨진다.

   맵이 보여주는 것: 화면 카드마다 스크린샷이 붙고, **어디를 눌렀는지가 그 스크린샷 위에 점으로 찍히며** 거기서 목적지 화면으로 선이 나간다. 미탐 후보도 같은 방식으로 **눌리지 않은 그 자리에** 점선 점으로 찍힌다 — 빈틈이 몇 개인지가 아니라 **어디인지**가 보인다.

2. **기기 쪽을 정리한다.** `quit` 은 WDA 세션만 닫는다 — `session` 이 자동으로 띄운 Appium 서버는 launchd 가 소유해 셸이 끝난 뒤에도 계속 돈다. 둘 다 내린다:
   ```bash
   CLONE_STATE_DIR=.autobot/copy-analysis scripts/device_wda.sh quit "$sid"
   CLONE_STATE_DIR=.autobot/copy-analysis scripts/device_wda.sh stop-server
   ```
   `stop-server` 는 **이 상태 폴더가 기록한 서버만** 내린다 — 남이 띄운 서버는 거부하므로 `/autobot:clone` 의 서버를 실수로 죽이지 않는다. `INFO: no Appium server managed by device_wda.sh` 는 정상이다: 이미 돌던 서버를 빌려 썼다는 뜻이고, 그건 우리가 내릴 것이 아니다.
3. 수집 이미지·트리·브리프·흐름도를 사용자가 보게 연다 (`open .autobot/copy-analysis/`).
4. 다음 안내:
   ```
   브리프 준비 완료 → 원본 앱을 빌드하려면:
     /autobot:plan  (기획·디자인 검토 후 진행)  또는
     /autobot:mvp   (질문 없이 바로 빌드)
   에 .autobot/copy-analysis/brief.md 내용을 아이디어로 넘기세요.
   ```
