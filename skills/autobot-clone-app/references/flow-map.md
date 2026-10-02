### Step 2a — flow 맵 (사람이 보는 지점)

```bash
scripts/device_flow.py map .autobot/clone/flow.jsonl .autobot/clone/flow-map.html
open .autobot/clone/flow-map.html
```

화면 썸네일을 진입 화면으로부터의 깊이별로 놓고, 어떤 탭이 어디로 가는지와 **미탐험 후보**를 함께 보여준다. `observe` 가 매번 다시 생성하며, **이 지점에서 멈추지 않는다** — 사람이 보는 창이지 게이트가 아니다. 더 탐험할 곳이 남았으면 `observe` 를 다시 실행하는 것이 답이고, 지도를 보고 결정할 필요가 없다.
