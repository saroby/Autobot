## Step 4: Docker Backend 검증

`build-state.json`의 `backend_required == true`일 때만 실행. iOS 빌드 성공 후에 수행한다.

```bash
cd backend && docker compose build
docker compose up -d --wait
curl -f http://localhost:8080/health  # Expected: {"status": "ok"}
docker compose down && cd ..
```

실패 시 진단:

| 실패 지점 | 원인 | 해결 |
|----------|------|------|
| `docker compose build` | requirements.txt 누락/Dockerfile 오류 | 에러 메시지 읽고 수정 |
| `docker compose up` | 포트 충돌 | `lsof -i :8080`으로 확인 후 프로세스 종료 |
| health check | /health 라우트 없음 | `app/main.py`에 health 엔드포인트 추가 |
