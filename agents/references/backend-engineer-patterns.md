# Optional backend-engineer patterns

Use only when a pattern needs clarification. Adapt examples to the actual contracts; these are not additional requirements.

## Example 1

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ ./app/
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

## Example 2

```yaml
services:
  api:
    build: .
    ports:
      - "8080:8080"
    env_file:
      - .env
    volumes:
      - ./app:/app/app
    command: uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 10s
      timeout: 5s
      retries: 3
      start_period: 5s
```

## Example 3

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .config import settings

app = FastAPI(title="{AppName} Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Import and mount routers based on architecture
# from .auth.router import router as auth_router
# from .llm.router import router as llm_router
# app.include_router(auth_router, prefix="/auth", tags=["auth"])
# app.include_router(llm_router, prefix="/api", tags=["llm"])

@app.get("/health")
async def health():
    return {"status": "ok"}
```

## Example 4

```python
from collections.abc import AsyncGenerator
from fastapi.responses import StreamingResponse
import httpx
import json

async def stream_chat(messages: list[dict], settings: "Settings") -> AsyncGenerator[str, None]:
    """LLM 업스트림에 요청을 전달하고 SSE 청크를 변환하여 yield한다."""
    payload = {"model": settings.llm_model, "messages": messages, "stream": True}
    headers = {"Authorization": f"Bearer {settings.llm_api_key}", "Content-Type": "application/json"}
    async with httpx.AsyncClient() as client:
        try:
            async with client.stream("POST", settings.llm_upstream_url, json=payload, headers=headers) as response:
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        chunk = json.loads(line[6:])
                        content = chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")
                        yield f"data: {json.dumps({'content': content, 'done': False})}\n\n"
            yield f"data: {json.dumps({'content': '', 'done': True})}\n\n"
        except Exception:
            yield f"data: {json.dumps({'content': '', 'done': True, 'error': 'upstream_error'})}\n\n"
```
