#!/usr/bin/env python3
"""인터뷰 설문 서버 — 질문 spec(JSON) 을 HTML 폼으로 띄우고 답변을 JSON 으로 회수.

한 번에 한 질문씩 멈추는 대화형 인터뷰 대신, 연관 없는 질문들을 한 페이지에
모아 받는다. 빈칸은 "불필요한 질문"으로 간주되어 `skipped` 에 기록된다.

사용:
    python3 interview_form.py <spec.json> <answers.json> [--port 8766]
    python3 interview_form.py --selftest

동작: 127.0.0.1:PORT 로 폼을 서빙 → 사용자가 "다음"/"완료" 제출 → answers.json
기록 후 서버 종료(호출자가 재개할 수 있게). 제출 응답으로 대기 페이지를 주며,
그 페이지는 `/round` 를 폴링하다 round 번호가 올라가면 자동으로 새 페이지를 연다.
=> 다음 라운드는 "spec 파일을 먼저 쓰고, 같은 포트로 서버를 다시 띄우면" 된다.

spec 스키마:
{
  "round": 1,                                  # 단조 증가. 대기 페이지 갱신 기준
  "title": "SSOT 인터뷰 — 1차",
  "intro": "답하고 싶은 것만 …",               # 선택
  "sections": [
    {"title": "왜 존재하나", "note": "…",      # note 선택
     "questions": [
       {"id": "problem", "type": "textarea", "label": "…", "hint": "…"},
       {"id": "tone", "type": "choice", "label": "…", "options": ["a", "b"], "other": true},
       {"id": "musts", "type": "multi", "label": "…", "options": ["x", "y"]},
       {"id": "name", "type": "text", "label": "…", "hint": "현재 파악: …", "confirm": true}
     ]}
  ]
}
type: text | textarea | choice | multi.  confirm: true = 확인형 질문("확인" 배지).

**중립 원칙**: 미리 채우거나 미리 선택하는 수단은 없다 (prefill·preselect·추천 표시 없음).
기본값은 답을 유도한다. 스캔으로 이미 아는 값은 `hint` 에 "현재 파악: …" 로만 보여주고,
사용자가 손대지 않으면 그 값이 유지된 것으로 본다.

answers 스키마:
{"round": 1, "action": "next"|"done", "ts": "...",
 "answers": {"problem": "…", "musts": ["x"]}, "skipped": ["tone"]}
"""

from __future__ import annotations

import html
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs

OTHER = "__other__"

CSS = """
/* 라이트 고정 — 설문지는 시스템 테마를 따라가지 않는다 (구글 설문지와 동일) */
:root{color-scheme:light;--bg:#f0f1f3;--card:#fff;--fg:#202124;--dim:#5f6368;--line:#dadce0;--mark:#3c4043;--btn-fg:#fff}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.6 -apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo",system-ui,sans-serif}
.wrap{max-width:760px;margin:0 auto;padding:28px 16px 120px}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:22px 24px;margin-bottom:12px}
h1{font-size:26px;font-weight:400;margin:0 0 8px}
.intro{color:var(--dim);margin:0;white-space:pre-wrap}
.round{color:var(--dim);font-size:12px;margin:0 0 14px}
h2{font-size:16px;font-weight:500;margin:0 0 2px}
.note{color:var(--dim);font-size:13px;margin:0}
.q{padding:20px 0 4px;border-top:1px solid var(--line)}
.q:first-of-type{border-top:0;padding-top:16px}
label.lb{display:block;font-size:16px;font-weight:400;margin-bottom:2px}
.hint{color:var(--dim);font-size:13px;margin-bottom:10px}
.badge{font-size:11px;color:var(--dim);border:1px solid var(--line);border-radius:3px;padding:0 5px;margin-left:6px;vertical-align:2px}
input[type=text],textarea{width:100%;background:transparent;color:var(--fg);font:inherit;font-size:15px;
  border:0;border-bottom:1px solid var(--line);border-radius:0;padding:7px 1px}
textarea{min-height:64px;resize:vertical;line-height:1.7}
input[type=text]:focus,textarea:focus{outline:0;border-bottom:2px solid var(--mark);padding-bottom:6px}
.opt{display:flex;gap:11px;align-items:flex-start;padding:7px 0;cursor:pointer}
.opt input{margin-top:4px;accent-color:var(--mark);flex:none;width:16px;height:16px}
.otherbox{margin:2px 0 0 27px;max-width:380px}
.bar{position:fixed;left:0;right:0;bottom:0;background:var(--card);border-top:1px solid var(--line);
  padding:12px 20px;display:flex;gap:8px;justify-content:center;align-items:center;flex-wrap:wrap}
button{font:inherit;font-size:14px;font-weight:500;border-radius:6px;padding:9px 24px;border:1px solid var(--line);background:transparent;color:var(--fg);cursor:pointer}
button.primary{background:var(--mark);color:var(--btn-fg);border-color:transparent}
.bar .tip{color:var(--dim);font-size:12px;margin-left:6px}
.mid{max-width:520px;margin:22vh auto;text-align:center}
.mid h1{font-size:22px}
.mid p{color:var(--dim)}
"""

WAIT_JS = """
let mine=%d;
async function tick(){
  try{
    const r=await fetch('/round',{cache:'no-store'});
    const j=await r.json();
    if(j.round>mine){location.href='/';return}
  }catch(e){}
  setTimeout(tick,1500);
}
tick();
"""


def esc(s) -> str:
    return html.escape(str(s if s is not None else ""))


def _question(q: dict) -> str:
    qid, typ = q["id"], q.get("type", "text")
    name = f"q_{qid}"
    badge = '<span class="badge">확인</span>' if q.get("confirm") else ""
    out = [f'<div class="q"><label class="lb" for="{esc(name)}">{esc(q["label"])}{badge}</label>']
    if q.get("hint"):
        out.append(f'<div class="hint">{esc(q["hint"])}</div>')

    # 어떤 타입도 미리 채우거나 미리 고르지 않는다. 스캔으로 파악한 값은 hint 에
    # "현재 파악: …" 로 보여주고, 빈칸은 그대로 "무응답"으로 남게 둔다.
    if typ == "textarea":
        out.append(f'<textarea id="{esc(name)}" name="{esc(name)}"></textarea>')
    elif typ == "text":
        out.append(f'<input type="text" id="{esc(name)}" name="{esc(name)}">')
    elif typ in ("choice", "multi"):
        # 미리 선택하지 않는다 — 기본 선택은 답을 유도한다 (중립 원칙).
        kind = "radio" if typ == "choice" else "checkbox"
        for i, opt in enumerate(q.get("options", [])):
            out.append(
                f'<label class="opt"><input type="{kind}" name="{esc(name)}" '
                f'value="{esc(opt)}" id="{esc(name)}_{i}"><span>{esc(opt)}</span></label>'
            )
        if q.get("other", True):
            out.append(
                f'<label class="opt"><input type="{kind}" name="{esc(name)}" value="{OTHER}">'
                f"<span>기타</span></label>"
                f'<input class="otherbox" type="text" name="{esc(name)}__other" placeholder="직접 입력">'
            )
    else:
        raise ValueError(f"unknown question type: {typ}")
    out.append("</div>")
    return "".join(out)


def render(spec: dict) -> str:
    rnd = int(spec.get("round", 1))
    body = [
        '<div class="wrap"><div class="card">',
        f'<div class="round">라운드 {rnd}</div>',
        f'<h1>{esc(spec.get("title", "인터뷰"))}</h1>',
        f'<p class="intro">{esc(spec.get("intro") or "답하고 싶은 것만 답하세요. 빈칸은 불필요한 질문으로 보고 다시 묻지 않습니다.")}</p>',
        '</div><form method="post" action="/submit" id="f">',
    ]
    for sec in spec.get("sections", []):
        body.append(f'<section class="card"><h2>{esc(sec.get("title", ""))}</h2>')
        if sec.get("note"):
            body.append(f'<p class="note">{esc(sec["note"])}</p>')
        body += [_question(q) for q in sec.get("questions", [])]
        body.append("</section>")
    body.append(
        '<div class="bar">'
        '<button type="submit" name="action" value="next" class="primary">다음 →</button>'
        '<button type="submit" name="action" value="done">완료</button>'
        '<span class="tip">다음 = 답변 기반으로 더 깊은 질문지 / 완료 = 인터뷰 종료 · ⌘⏎</span>'
        "</div></form></div>"
        "<script>addEventListener('keydown',e=>{if((e.metaKey||e.ctrlKey)&&e.key==='Enter')"
        "document.querySelector('button.primary').click()})</script>"
    )
    return (
        f'<!doctype html><meta charset="utf-8"><title>{esc(spec.get("title", "인터뷰"))}</title>'
        f'<meta name="viewport" content="width=device-width,initial-scale=1"><style>{CSS}</style>'
        + "".join(body)
    )


def wait_page(rnd: int, done: bool) -> str:
    if done:
        inner = "<h1>완료</h1><p>인터뷰를 마쳤습니다. 이 창은 닫으셔도 됩니다.</p>"
        script = ""
    else:
        inner = "<h1>다음 질문을 만드는 중…</h1><p>답변을 반영한 질문지가 준비되면 자동으로 넘어갑니다.</p>"
        script = f"<script>{WAIT_JS % rnd}</script>"
    return (
        '<!doctype html><meta charset="utf-8"><title>대기</title>'
        f"<style>{CSS}</style><div class=\"mid\">{inner}</div>{script}"
    )


def collect(spec: dict, form: dict[str, list[str]]) -> tuple[dict, list[str]]:
    """폼 데이터 → (answers, skipped). 빈 답 = skipped."""
    answers, skipped = {}, []
    for sec in spec.get("sections", []):
        for q in sec.get("questions", []):
            qid, typ = q["id"], q.get("type", "text")
            raw = form.get(f"q_{qid}", [])
            other = (form.get(f"q_{qid}__other", [""])[0] or "").strip()
            if typ in ("choice", "multi"):
                vals = [other if v == OTHER else v for v in raw]
                vals = [v for v in vals if v]
                val = (vals[0] if vals else "") if typ == "choice" else vals
            else:
                val = (raw[0] if raw else "").strip()
            if val:
                answers[qid] = val
            else:
                skipped.append(qid)
    return answers, skipped


def make_server(spec: dict, out: Path, port: int) -> HTTPServer:
    page = render(spec)
    rnd = int(spec.get("round", 1))

    class H(BaseHTTPRequestHandler):
        def _send(self, body: str, ctype="text/html; charset=utf-8"):
            data = body.encode()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path.startswith("/round"):
                self._send(json.dumps({"round": rnd}), "application/json")
            else:
                self._send(page)

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            form = parse_qs(self.rfile.read(n).decode(), keep_blank_values=True)
            action = "done" if form.get("action", ["next"])[0] == "done" else "next"
            answers, skipped = collect(spec, form)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(
                json.dumps(
                    {
                        "round": rnd,
                        "action": action,
                        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                        "answers": answers,
                        "skipped": skipped,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            self._send(wait_page(rnd, action == "done"))
            threading.Thread(target=httpd.shutdown, daemon=True).start()

        def log_message(self, *a):
            pass

    httpd = HTTPServer(("127.0.0.1", port), H)
    return httpd


def selftest() -> None:
    import http.client
    import tempfile

    spec = {
        "round": 2,
        "title": "셀프테스트",
        "sections": [
            {
                "title": "S",
                "questions": [
                    {"id": "why", "type": "textarea", "label": "왜 존재하나"},
                    {"id": "tone", "type": "choice", "label": "톤", "options": ["차분", "경쾌"]},
                    {"id": "musts", "type": "multi", "label": "필수", "options": ["x", "y"]},
                    {"id": "skipme", "type": "text", "label": "안 답할 것", "confirm": True},
                ],
            }
        ],
    }
    page = render(spec)
    for frag in ['name="q_why"', 'value="next"', "완료", "라운드 2", "확인"]:
        assert frag in page, f"render missing: {frag}"
    # 중립: 어떤 입력도 미리 채워지거나 선택되어 있지 않다.
    assert "checked" not in page and "value=\"\"" not in page, "neutral violation: prefilled/preselected"
    assert "<textarea id=\"q_why\" name=\"q_why\"></textarea>" in page, "textarea must be empty"

    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "sub" / "answers.json"
        httpd = make_server(spec, out, 0)
        port = httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, daemon=True).start()

        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        c.request("GET", "/round")
        assert json.loads(c.getresponse().read())["round"] == 2

        c.request(
            "POST",
            "/submit",
            "action=next&q_why=%EB%8B%B5&q_tone=__other__&q_tone__other=%EB%B3%84%EB%8F%84"
            "&q_musts=x&q_musts=y&q_skipme=++",
            {"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert "다음 질문을 만드는 중" in c.getresponse().read().decode()
        httpd.server_close()

        got = json.loads(out.read_text(encoding="utf-8"))
    assert got["action"] == "next" and got["round"] == 2, got
    assert got["answers"] == {"why": "답", "tone": "별도", "musts": ["x", "y"]}, got["answers"]
    assert got["skipped"] == ["skipme"], got["skipped"]
    print("selftest ok")


def main(argv: list[str]) -> int:
    if "--selftest" in argv:
        selftest()
        return 0
    args = [a for a in argv if not a.startswith("--")]
    if len(args) < 2:
        print(__doc__)
        return 2
    port = 8766
    if "--port" in argv:
        port = int(argv[argv.index("--port") + 1])
    spec = json.loads(Path(args[0]).read_text(encoding="utf-8"))
    out = Path(args[1])
    httpd = make_server(spec, out, port)
    print(f"http://127.0.0.1:{httpd.server_address[1]}/  (round {spec.get('round', 1)})", flush=True)
    httpd.serve_forever()
    httpd.server_close()
    print(f"submitted -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
