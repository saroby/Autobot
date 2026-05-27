# Design System SPM (`<Name>DS`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Autobot가 `/autobot:mvp` 로 앱을 생성할 때마다 그 앱 안에 in-tree 로컬 Swift Package `<Name>DS` (예: `InstagramDS`) 를 함께 만들어 디자인 토큰과 SwiftUI 공용 컴포넌트를 그 패키지에 넣고, 앱 타깃은 그것을 `import` 해서 쓰도록 파이프라인을 바꾼다.

**Architecture:** Phase 3 (Project Scaffold) 를 2-step 으로 확장한다. (1) 기존 scaffold (self) 가 `Packages/<Name>DS/` 골격 + `Package.swift` + `project.yml` 의 로컬 패키지 wiring 까지 생성하고, (2) 새 `design-system` 서브 에이전트가 architecture.md 의 Design Direction + design-spec.md 의 토큰을 참고해 `Sources/<Name>DS/Tokens/*.swift` 와 `Sources/<Name>DS/Components/*.swift` 를 채운다. 패키지 이름은 architect 가 Phase 1 에서 `architecture.json.designSystemModule` 로 결정한다. ui-builder 는 Theme.swift 를 더 이상 만들지 않고 `import <Name>DS` 로 토큰을 사용한다.

**Tech Stack:** Swift 6.0 / iOS 26+ / SPM local package / XcodeGen `packages:` + `dependencies:` + fallback Python pbxproj generator / `spec/pipeline.json` SSOT + `scripts/gate_runner.py` 게이트 / Python `unittest` 회귀 스위트.

---

## File Structure (생성/수정 대상)

| 책임 | 파일 | 신규/수정 |
|------|------|----------|
| Pipeline SSOT (file ownership, Phase 3, Gate 3→4) | `spec/pipeline.json` | 수정 |
| Gate 체크 함수 + 레지스트리 | `scripts/gate_runner.py` | 수정 |
| Gate 체크 회귀 테스트 | `tests/test_design_system_gates.py` | 신규 |
| Architect 산출물 contract (designSystemModule 필드) | `agents/architect.md` | 수정 |
| Scaffold 셸 (Package 골격 + project.yml wiring) | `skills/autobot-ios-scaffold/scripts/create-xcode-project.sh` | 수정 |
| 폴백 pbxproj 생성기 (package 참조) | `skills/autobot-ios-scaffold/scripts/generate-pbxproj.py` | 수정 |
| Template 문서 (Package.swift, project.yml packages) | `skills/autobot-ios-scaffold/references/project-templates.md` | 수정 |
| Scaffold 스킬 본문 (새 step 문서화) | `skills/autobot-ios-scaffold/SKILL.md` | 수정 |
| 새 서브 에이전트 정의 | `agents/design-system.md` | 신규 |
| ui-builder agent (Theme.swift 제거 + import) | `agents/ui-builder.md` | 수정 |
| Orchestrator skill (Phase 3 two-step + 새 에이전트) | `skills/autobot-orchestrator/SKILL.md` | 수정 |
| Context pack (REFERENCE_FILES["design-system"]) | `scripts/context_pack.py` | 수정 |
| Smoke E2E (Package + tokens 존재 검증) | `scripts/smoke-e2e.sh` | 수정 |
| 변경 로그 | `CHANGELOG.md` | 수정 |

설계 원칙:
- **단일 책임**: scaffold (self) = 프로젝트 구조/`Package.swift`/`project.yml` wiring, design-system agent = `Sources/<Name>DS/` 의 토큰·컴포넌트 콘텐츠. 두 책임은 절대 섞지 않는다.
- **이름 결정은 한 곳**: architect 의 `architecture.json.designSystemModule` 이 SSOT. scaffold/design-system/ui-builder 모두 이 값을 읽기만 한다.
- **Theme.swift 제거**: 토큰의 단일 출처가 두 곳이 되면 drift 가 생긴다. ui-builder 는 `import <Name>DS` 만 한다.

---

## Naming Contract (전체 작업에 공통)

- `appName` 은 PascalCase ASCII (architect 가 이미 sanitize 함, 예: `Instagram`).
- `designSystemModule = appName + "DS"` (예: `InstagramDS`).
- 패키지 디렉토리: `Packages/<designSystemModule>/`
- Swift module 이름: `<designSystemModule>` (Package.swift `name:` 과 `targets[0].name` 모두 같은 값).
- import 구문: `import <designSystemModule>`

architect 가 한 번 결정해 `architecture.json.designSystemModule` 로 emit. 다른 모든 컴포넌트는 그 값을 읽는다.

---

### Task 1: spec/pipeline.json — fileOwnership / Phase 3 / Gate 3→4 갱신

**Files:**
- Modify: `spec/pipeline.json`

이 task 는 SSOT 변경이며, 이후 모든 task 가 이 spec 값을 읽는다. **이 task 가 가장 먼저 끝나야 한다.**

- [ ] **Step 1: 현재 spec 의 fileOwnership.agents 와 Phase 3, gates."3->4" 의 정확한 위치 확인**

Run:
```bash
python3 -c "
import json
d = json.load(open('spec/pipeline.json'))
print('--- agents ---')
print(list(d['fileOwnership']['agents'].keys()))
print('--- ui-builder.writes ---')
print(d['fileOwnership']['agents']['ui-builder']['writes'])
print('--- phase 3 ---')
print(d['phases']['3'])
print('--- gate 3->4 checks ---')
print([c.get('label') or c.get('name') for c in d['gates']['3->4']['checks']])
"
```
Expected: ui-builder writes 안에 `{appName}/Utilities/Theme.swift` 가 있고, Phase 3 에는 `agents` 키가 없다. Gate 3→4 checks 는 5개 (`xcodeproj_exists`, `privacy_manifest_exists`, `entitlements_exists`, `gitignore_exists`, `scaffold_build_succeeded`).

- [ ] **Step 2: fileOwnership.agents 에 `design-system` 추가**

`spec/pipeline.json` 의 `fileOwnership.agents` 객체에 새 키를 추가:

```json
"design-system": {
  "writes": [
    "Packages/"
  ]
}
```

(주의: 이 agent 는 `project.yml` 을 건드리지 않는다 — scaffold 가 한다.)

- [ ] **Step 3: ui-builder.writes 에서 Theme.swift 제거**

`fileOwnership.agents.ui-builder.writes` 에서 다음 한 줄을 제거:

```
"{appName}/Utilities/Theme.swift"
```

- [ ] **Step 4: forbiddenPerAgent 갱신**

`fileOwnership.forbiddenPerAgent` 에서 `data-engineer` 의 기존 항목 (`{appName}/Utilities/Theme.swift`) 을 제거하고 (Theme.swift 가 더 이상 존재하지 않으므로), `ui-builder` 에 다음을 추가:

```json
"ui-builder": [
  "{appName}/Services/",
  "Packages/"
]
```

`design-system` 에는 다음을 추가:

```json
"design-system": [
  "{appName}/"
]
```

(design-system 은 앱 타깃 디렉토리에 절대 쓰면 안 된다.)

- [ ] **Step 5: Phase 3 에 agents 키 + docs.outputs 갱신**

`phases."3"` 에 다음 키를 추가/갱신:

```json
"agents": ["design-system"],
"docs": {
  "displayName": "Xcode 프로젝트 + Design System",
  "readmeAgent": "(self) + design-system",
  "skillAgent": "(self) + design-system",
  "outputs": [
    "`.xcodeproj`",
    "`Packages/<Name>DS/`",
    "`PrivacyInfo.xcprivacy`",
    "`.entitlements`"
  ],
  "parallel": false,
  "gateLabel": "→ .xcodeproj + Package 존재 + tokens 채워짐"
}
```

- [ ] **Step 6: Gate 3→4 에 두 개 신규 체크 추가**

`gates."3->4".checks` 배열의 기존 5개 뒤에 다음 2개를 추가 (다른 check 들과 동일한 객체 형태로):

```json
{
  "label": "design_system_package_exists",
  "docs": "Packages/<designSystemModule>/Package.swift 존재 + name 필드가 designSystemModule 과 일치"
},
{
  "label": "design_system_tokens_exist",
  "docs": "Sources/<designSystemModule>/Tokens/ 아래 Color.swift, Typography.swift, Spacing.swift, Radius.swift 모두 존재 + 비어있지 않음"
}
```

(기존 check 들이 `label` 만 쓰는지 `name` 쓰는지 step 1 의 출력 형태에 맞춘다 — 이 spec 은 둘을 모두 허용한다.)

- [ ] **Step 7: schema 검증**

Run:
```bash
bash scripts/pipeline.sh schema
```
Expected: `OK` (또는 silent exit 0).

- [ ] **Step 8: Commit**

```bash
git add spec/pipeline.json
git commit -m "spec(pipeline): add design-system agent, Packages/ ownership, gate 3→4 SPM checks"
```

---

### Task 2: scripts/gate_runner.py — `check_design_system_package_exists` + `check_design_system_tokens_exist` (TDD)

**Files:**
- Test: `tests/test_design_system_gates.py`
- Modify: `scripts/gate_runner.py:548-600` (gate-3→4 함수 그룹 부근) + `:1140-1170` (CHECK_REGISTRY)

체크 함수 시그니처는 기존 패턴을 따른다: `def check_X(proj: Path, app: str, state: dict) -> list[dict]`. `state` 에서 `architecture.json.designSystemModule` 을 읽어 어디를 볼지 결정한다.

- [ ] **Step 1: 테스트 파일 신규 작성 (failing tests)**

Create `tests/test_design_system_gates.py`:

```python
"""Gate 3→4 design-system 체크 회귀 테스트."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from conftest import SCRIPTS_DIR, import_runtime_modules

import_runtime_modules()

from gate_runner import (  # noqa: E402  (after sys.path injection)
    check_design_system_package_exists,
    check_design_system_tokens_exist,
)


def _make_state(module: str = "InstagramDS") -> dict:
    return {"architecture": {"designSystemModule": module}}


def _write_arch_json(proj: Path, module: str = "InstagramDS") -> None:
    (proj / ".autobot").mkdir(parents=True, exist_ok=True)
    (proj / ".autobot" / "architecture.json").write_text(
        json.dumps({"appName": "Instagram", "designSystemModule": module}),
        encoding="utf-8",
    )


class TestDesignSystemPackageExists(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_missing_package_swift_fails(self) -> None:
        _write_arch_json(self.tmp)
        result = check_design_system_package_exists(self.tmp, "Instagram", _make_state())
        self.assertEqual(result[0]["ok"], False)
        self.assertIn("Package.swift", result[0]["detail"])

    def test_present_package_swift_with_matching_name_passes(self) -> None:
        _write_arch_json(self.tmp)
        pkg = self.tmp / "Packages" / "InstagramDS"
        pkg.mkdir(parents=True)
        (pkg / "Package.swift").write_text(
            'let package = Package(name: "InstagramDS", targets: [])',
            encoding="utf-8",
        )
        result = check_design_system_package_exists(self.tmp, "Instagram", _make_state())
        self.assertEqual(result[0]["ok"], True)

    def test_present_but_name_mismatch_fails(self) -> None:
        _write_arch_json(self.tmp)
        pkg = self.tmp / "Packages" / "InstagramDS"
        pkg.mkdir(parents=True)
        (pkg / "Package.swift").write_text(
            'let package = Package(name: "WrongName", targets: [])',
            encoding="utf-8",
        )
        result = check_design_system_package_exists(self.tmp, "Instagram", _make_state())
        self.assertEqual(result[0]["ok"], False)
        self.assertIn("name", result[0]["detail"].lower())

    def test_missing_arch_json_fails_with_clear_message(self) -> None:
        # architecture.json 이 없으면 designSystemModule 을 알 수 없음 — fail
        result = check_design_system_package_exists(self.tmp, "Instagram", {})
        self.assertEqual(result[0]["ok"], False)
        self.assertIn("designSystemModule", result[0]["detail"])


class TestDesignSystemTokensExist(unittest.TestCase):
    REQUIRED = ["Color.swift", "Typography.swift", "Spacing.swift", "Radius.swift"]

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        _write_arch_json(self.tmp)
        self.tokens = self.tmp / "Packages" / "InstagramDS" / "Sources" / "InstagramDS" / "Tokens"
        self.tokens.mkdir(parents=True)

    def test_all_tokens_present_and_non_empty_passes(self) -> None:
        for name in self.REQUIRED:
            (self.tokens / name).write_text("import SwiftUI\nenum X {}\n", encoding="utf-8")
        result = check_design_system_tokens_exist(self.tmp, "Instagram", _make_state())
        self.assertEqual(result[0]["ok"], True)

    def test_missing_one_token_fails(self) -> None:
        for name in self.REQUIRED[:-1]:
            (self.tokens / name).write_text("import SwiftUI\n", encoding="utf-8")
        result = check_design_system_tokens_exist(self.tmp, "Instagram", _make_state())
        self.assertEqual(result[0]["ok"], False)
        self.assertIn("Radius.swift", result[0]["detail"])

    def test_empty_token_file_fails(self) -> None:
        for name in self.REQUIRED:
            (self.tokens / name).write_text("", encoding="utf-8")
        result = check_design_system_tokens_exist(self.tmp, "Instagram", _make_state())
        self.assertEqual(result[0]["ok"], False)
        self.assertIn("empty", result[0]["detail"].lower())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 테스트 실행으로 실패 확인 (ImportError)**

Run:
```bash
cd /Users/louis/Code/Autobot && python3 -m unittest tests.test_design_system_gates -v
```
Expected: `ImportError: cannot import name 'check_design_system_package_exists' from 'gate_runner'`

- [ ] **Step 3: gate_runner.py 에 `_load_arch_json` 헬퍼 + 두 체크 함수 추가**

`scripts/gate_runner.py` 의 Gate 3→4 함수 그룹 (line 548 근처, `check_xcodeproj_exists` 정의 위 또는 같은 그룹 끝) 에 다음을 추가:

```python
def _load_design_system_module(proj: Path, state: dict) -> str | None:
    """state 우선, 그 다음 architecture.json 에서 designSystemModule 을 읽는다."""
    arch_state = (state or {}).get("architecture") or {}
    mod = arch_state.get("designSystemModule")
    if mod:
        return mod
    arch_path = proj / ".autobot" / "architecture.json"
    if not arch_path.is_file():
        return None
    try:
        return json.loads(arch_path.read_text(encoding="utf-8")).get("designSystemModule")
    except (OSError, ValueError):
        return None


def check_design_system_package_exists(proj: Path, app: str, state: dict) -> list[dict]:
    module = _load_design_system_module(proj, state)
    if not module:
        return [_ok(
            "design_system_package_exists", False,
            "architecture.json.designSystemModule 누락 (architect 가 emit 해야 함)",
        )]
    pkg_root = proj / "Packages" / module
    pkg_swift = pkg_root / "Package.swift"
    if not pkg_swift.is_file():
        return [_ok(
            "design_system_package_exists", False,
            f"Package.swift 없음: {pkg_swift.relative_to(proj)}",
        )]
    content = pkg_swift.read_text(encoding="utf-8", errors="replace")
    if f'name: "{module}"' not in content:
        return [_ok(
            "design_system_package_exists", False,
            f"Package.swift 의 name 이 '{module}' 가 아님",
        )]
    return [_ok("design_system_package_exists", True, str(pkg_swift.relative_to(proj)))]


def check_design_system_tokens_exist(proj: Path, app: str, state: dict) -> list[dict]:
    module = _load_design_system_module(proj, state)
    if not module:
        return [_ok(
            "design_system_tokens_exist", False,
            "architecture.json.designSystemModule 누락",
        )]
    tokens_dir = proj / "Packages" / module / "Sources" / module / "Tokens"
    required = ["Color.swift", "Typography.swift", "Spacing.swift", "Radius.swift"]
    missing: list[str] = []
    empty: list[str] = []
    for name in required:
        p = tokens_dir / name
        if not p.is_file():
            missing.append(name)
            continue
        if p.stat().st_size == 0:
            empty.append(name)
    if missing:
        return [_ok(
            "design_system_tokens_exist", False,
            f"missing token files: {', '.join(missing)}",
        )]
    if empty:
        return [_ok(
            "design_system_tokens_exist", False,
            f"empty token files: {', '.join(empty)}",
        )]
    return [_ok(
        "design_system_tokens_exist", True,
        f"{len(required)} tokens present under {tokens_dir.relative_to(proj)}",
    )]
```

(`_ok` 는 기존 헬퍼이며 같은 파일 안에서 다른 check 들이 쓰는 형태를 그대로 따른다. import 가 더 필요하면 파일 상단 `import json` 이 이미 있는지 확인.)

- [ ] **Step 4: CHECK_REGISTRY 에 두 항목 등록**

`scripts/gate_runner.py` 의 `# Gate 3→4` 블록 (line 1144 근처) 끝에 다음을 추가:

```python
    "design_system_package_exists": check_design_system_package_exists,
    "design_system_tokens_exist": check_design_system_tokens_exist,
```

- [ ] **Step 5: 테스트 재실행 — 전부 PASS**

Run:
```bash
cd /Users/louis/Code/Autobot && python3 -m unittest tests.test_design_system_gates -v
```
Expected: `OK` (7 tests pass).

- [ ] **Step 6: 기존 회귀 스위트 전부 통과 확인**

Run:
```bash
cd /Users/louis/Code/Autobot && python3 -m unittest discover -s tests -v 2>&1 | tail -20
```
Expected: `OK` (n tests, 모두 통과).

- [ ] **Step 7: Commit**

```bash
git add scripts/gate_runner.py tests/test_design_system_gates.py
git commit -m "feat(gates): add design_system_package_exists + design_system_tokens_exist (gate 3→4)"
```

---

### Task 3: architect 에이전트 — `designSystemModule` 필드 emit

**Files:**
- Modify: `agents/architect.md` (Output Contract (d) 섹션 — `architecture.json` 부분)

- [ ] **Step 1: Output Contract (d) 의 JSON 예시에 필드 추가**

`agents/architect.md` 의 `### (d) architecture.json — composition seam manifest` 섹션의 JSON 블록을 다음과 같이 갱신 (기존 줄들 유지, `bundleId` 다음 줄에 한 줄 추가):

```json
{
  "appName": "...",
  "displayName": "...",
  "bundleId": "...",
  "designSystemModule": "...",
  "models": ["Item", "Tag"],
  ...
}
```

- [ ] **Step 2: 같은 섹션 끝 (`스키마는 ...` 줄 위) 에 필드 정의를 한 단락 추가**

다음 텍스트를 삽입:

```markdown
`designSystemModule` 규칙 (필수):
- 값 = `appName + "DS"` (예: `appName: "Instagram"` → `"InstagramDS"`).
- PascalCase ASCII 만. 길이 ≤ 30.
- Phase 3 scaffold 가 이 값을 읽어 `Packages/<designSystemModule>/` 를 만들고 `Package.swift` 의 `name:` 으로 사용한다. design-system 에이전트 / ui-builder 도 같은 값을 읽는다. **architect 가 단일 결정자**.
```

- [ ] **Step 3: Naming Contract 섹션에 한 줄 추가**

`## Naming Contract` 섹션 끝에 다음을 추가:

```markdown
- **designSystemModule**: `appName + "DS"`. 예외 없음. architect 가 architecture.json 에 적는다.
```

- [ ] **Step 4: Commit**

```bash
git add agents/architect.md
git commit -m "agent(architect): emit designSystemModule in architecture.json"
```

---

### Task 4: create-xcode-project.sh — `--design-system-module` 플래그 + Package 골격 + project.yml wiring

**Files:**
- Modify: `skills/autobot-ios-scaffold/scripts/create-xcode-project.sh`

이 task 는 (a) 새 CLI 플래그 수신, (b) `Packages/<Module>/` 디렉토리 + `Package.swift` + 빈 `Sources/<Module>/Tokens/` `Components/` 생성, (c) `project.yml` 의 `packages:` 와 target `dependencies:` 추가, (d) fallback python 경로에도 동일 효과 — 4 가지를 한 번에 다룬다.

- [ ] **Step 1: 인자 파서에 `--design-system-module` 추가**

`# Parse arguments` 블록의 case 문에 다음 한 줄을 다른 플래그들과 같은 형식으로 추가:

```bash
    --design-system-module) DESIGN_SYSTEM_MODULE="$2"; shift 2;;
```

그리고 기본값을 파일 상단 변수 초기화 영역에:

```bash
DESIGN_SYSTEM_MODULE="${DESIGN_SYSTEM_MODULE:-}"
```

- [ ] **Step 2: 모듈 이름 검증**

인자 파싱 끝난 뒤, 다음 검증 블록을 추가:

```bash
if [ -z "$DESIGN_SYSTEM_MODULE" ]; then
  DESIGN_SYSTEM_MODULE="${APP_NAME}DS"
fi
if ! [[ "$DESIGN_SYSTEM_MODULE" =~ ^[A-Z][A-Za-z0-9]+$ ]]; then
  echo "ERROR: --design-system-module must be PascalCase ASCII (got: $DESIGN_SYSTEM_MODULE)" >&2
  exit 2
fi
```

- [ ] **Step 3: Package 골격 생성 (xcodegen / 폴백 양쪽 공통, project 생성 직전에 한 번)**

`# Create directory structure` 블록 뒤, `# Check if xcodegen is available for project generation` 직전에 다음 블록 추가:

```bash
# ── Local Swift Package (Design System) ─────────────────────────────────────
PKG_DIR="${PROJECT_DIR}/Packages/${DESIGN_SYSTEM_MODULE}"
PKG_SRC="${PKG_DIR}/Sources/${DESIGN_SYSTEM_MODULE}"
mkdir -p "${PKG_SRC}/Tokens" "${PKG_SRC}/Components"

cat > "${PKG_DIR}/Package.swift" << PKG_EOF
// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "${DESIGN_SYSTEM_MODULE}",
    platforms: [.iOS(.v26)],
    products: [
        .library(name: "${DESIGN_SYSTEM_MODULE}", targets: ["${DESIGN_SYSTEM_MODULE}"]),
    ],
    targets: [
        .target(name: "${DESIGN_SYSTEM_MODULE}", path: "Sources/${DESIGN_SYSTEM_MODULE}"),
    ]
)
PKG_EOF

# design-system 에이전트가 채울 때까지 컴파일 가능한 빈 스텁을 둔다.
# (이 파일은 design-system 에이전트가 덮어쓰며, gate 는 비어있지 않음을 검증한다.)
cat > "${PKG_SRC}/Tokens/Color.swift" << STUB_EOF
// Placeholder — design-system agent overwrites this.
import SwiftUI
public enum DSColors { public static let placeholder = Color.accentColor }
STUB_EOF
cat > "${PKG_SRC}/Tokens/Typography.swift" << STUB_EOF
// Placeholder — design-system agent overwrites this.
import SwiftUI
public enum DSTypography { public static let body = Font.body }
STUB_EOF
cat > "${PKG_SRC}/Tokens/Spacing.swift" << STUB_EOF
// Placeholder — design-system agent overwrites this.
import Foundation
public enum DSSpacing { public static let m: CGFloat = 16 }
STUB_EOF
cat > "${PKG_SRC}/Tokens/Radius.swift" << STUB_EOF
// Placeholder — design-system agent overwrites this.
import Foundation
public enum DSRadius { public static let m: CGFloat = 12 }
STUB_EOF
```

(이 stub 들은 placeholder 이므로 gate `design_system_tokens_exist` 의 "비어있지 않음" 조건을 통과한다. design-system 에이전트가 step 4 에서 덮어쓴다.)

- [ ] **Step 4: project.yml 에 packages + target dependency 추가 (xcodegen 분기)**

기존 `cat > "${PROJECT_DIR}/project.yml" << YAML_EOF` 블록의 `targets:` 위에 새 키 `packages:` 를 추가, 그리고 메인 타깃 settings 블록 뒤에 `dependencies:` 를 추가. 다음 형태가 되도록 셸 heredoc 을 갱신:

```yaml
settings:
  base:
    SWIFT_VERSION: "6.0"
    ...

packages:
  ${DESIGN_SYSTEM_MODULE}:
    path: Packages/${DESIGN_SYSTEM_MODULE}

targets:
  ${APP_NAME}:
    type: application
    platform: iOS
    sources:
      - path: ${APP_NAME}
        type: folder
    dependencies:
      - package: ${DESIGN_SYSTEM_MODULE}
    settings:
      base:
        ...
```

(주의: 기존 heredoc 안의 `${DESIGN_SYSTEM_MODULE}` 도 환경변수로 정상 치환된다 — 셸 변수 보간이 활성화된 형태 `<< YAML_EOF` 이며 `'YAML_EOF'` 가 아니다. 확인 필수.)

- [ ] **Step 5: fallback Python generator 에도 동일 효과 전달**

같은 셸 파일의 `python3 "$GENERATOR" \` 호출에 인자를 추가:

```bash
python3 "$GENERATOR" \
  --name "$APP_NAME" \
  --bundle-id "$BUNDLE_ID" \
  --deployment-target "$DEPLOYMENT_TARGET" \
  --sources-dir "$SOURCES_DIR" \
  --design-system-module "$DESIGN_SYSTEM_MODULE" \
  ${TEAM_ID:+--team-id "$TEAM_ID"}
```

(generate-pbxproj.py 의 실제 인자 처리는 Task 5.)

- [ ] **Step 6: 수동 빠른 검증 (xcodegen 경로)**

Run:
```bash
TMP=$(mktemp -d) && cd "$TMP" && mkdir Instagram && \
  bash /Users/louis/Code/Autobot/skills/autobot-ios-scaffold/scripts/create-xcode-project.sh \
    --name Instagram --bundle-id com.axi.instagram --project-dir Instagram \
    --deployment-target 26.0 --design-system-module InstagramDS && \
  ls Instagram/Packages/InstagramDS && \
  cat Instagram/Packages/InstagramDS/Package.swift | head -5 && \
  grep -E 'packages:|InstagramDS' Instagram/project.yml
```
Expected:
- `Package.swift  Sources` 디렉토리가 보인다
- Package.swift 첫 줄: `// swift-tools-version: 6.0`, 그리고 `name: "InstagramDS"`
- project.yml 에 `packages:`, `InstagramDS:`, `path: Packages/InstagramDS`, `dependencies:` 와 `package: InstagramDS` 가 모두 보인다

- [ ] **Step 7: Commit**

```bash
git add skills/autobot-ios-scaffold/scripts/create-xcode-project.sh
git commit -m "feat(scaffold): scaffold Packages/<Name>DS local package + project.yml wiring"
```

---

### Task 5: generate-pbxproj.py — local package 참조 지원 (폴백 경로)

**Files:**
- Modify: `skills/autobot-ios-scaffold/scripts/generate-pbxproj.py`

xcodegen 이 없는 환경에서도 같은 결과가 나와야 한다. pbxproj 의 `XCLocalSwiftPackageReference` + `XCSwiftPackageProductDependency` 를 직접 emit 한다.

- [ ] **Step 1: CLI 에 `--design-system-module` 추가**

스크립트 상단 argparse 영역에:

```python
parser.add_argument("--design-system-module", default=None,
                    help="Local SPM module name to add as a package dependency (e.g. InstagramDS)")
```

- [ ] **Step 2: pbxproj 작성 함수에 분기 추가**

PBXProject / 메인 application target 을 생성하는 부분에서, `args.design_system_module` 이 truthy 면 다음 4 가지를 emit:

1. `XCLocalSwiftPackageReference` 섹션 entry — `relativePath = "Packages/<Module>"`
2. `packageReferences` 배열에 위 ID 추가 (PBXProject 의 `packageReferences = (…)`)
3. `XCSwiftPackageProductDependency` — `productName = "<Module>"`, `package = <위 ref ID>`
4. 메인 타깃의 `packageProductDependencies = (…)` 에 위 ID 추가, 그리고 PBXFrameworksBuildPhase 의 files 에 `productRef = <위 ID>` 인 PBXBuildFile 추가

(generate-pbxproj.py 의 기존 pbxproj 객체 모델 — dict / OrderedDict — 을 그대로 따른다. UUID 는 기존 `_new_uuid()` 또는 동등 헬퍼 사용.)

- [ ] **Step 3: 폴백 경로 수동 검증**

Run:
```bash
TMP=$(mktemp -d) && cd "$TMP" && mkdir Acme && \
  PATH_NO_XCODEGEN=$(echo "$PATH" | tr ':' '\n' | grep -v xcodegen | paste -sd: -) && \
  PATH="$PATH_NO_XCODEGEN" bash /Users/louis/Code/Autobot/skills/autobot-ios-scaffold/scripts/create-xcode-project.sh \
    --name Acme --bundle-id com.axi.acme --project-dir Acme \
    --deployment-target 26.0 --design-system-module AcmeDS 2>&1 | tail -10 && \
  grep -E 'XCLocalSwiftPackageReference|AcmeDS' Acme/Acme.xcodeproj/project.pbxproj | head -10
```
Expected: pbxproj 안에 `XCLocalSwiftPackageReference` 와 `AcmeDS` 가 나타난다.

(`xcodegen` 이 시스템에 항상 깔려있으면 위 `PATH` 트릭으로 폴백 경로 강제. 환경에 xcodegen 이 없다면 PATH 트릭 생략.)

- [ ] **Step 4: Commit**

```bash
git add skills/autobot-ios-scaffold/scripts/generate-pbxproj.py
git commit -m "feat(scaffold): pbxproj fallback emits XCLocalSwiftPackageReference for design system"
```

---

### Task 6: project-templates.md 갱신 — Package.swift + project.yml packages 섹션

**Files:**
- Modify: `skills/autobot-ios-scaffold/references/project-templates.md`

- [ ] **Step 1: XcodeGen template 의 yaml 블록에 packages + dependencies 반영**

`## XcodeGen project.yml Template (Folder Reference)` 의 yaml 블록을 다음으로 교체 (변경점: `packages:` 섹션 신설, 메인 타깃 `dependencies:` 추가):

```yaml
name: ${APP_NAME}
options:
  bundleIdPrefix: com.axi
  deploymentTarget:
    iOS: "26.0"
  xcodeVersion: "26.3"
  useBaseInternationalization: true

settings:
  base:
    SWIFT_VERSION: "6.0"
    SWIFT_STRICT_CONCURRENCY: complete
    MARKETING_VERSION: "1.0.0"
    CURRENT_PROJECT_VERSION: 1
    DEVELOPMENT_TEAM: ""
    CODE_SIGN_STYLE: Automatic

packages:
  ${DESIGN_SYSTEM_MODULE}:
    path: Packages/${DESIGN_SYSTEM_MODULE}

targets:
  ${APP_NAME}:
    type: application
    platform: iOS
    sources:
      - path: ${APP_NAME}
        type: folder
    dependencies:
      - package: ${DESIGN_SYSTEM_MODULE}
    settings:
      base:
        PRODUCT_BUNDLE_IDENTIFIER: com.axi.${APP_NAME_LOWER}
        ASSETCATALOG_COMPILER_APPICON_NAME: AppIcon
        GENERATE_INFOPLIST_FILE: YES
        INFOPLIST_KEY_UIApplicationSceneManifest_Generation: YES
        INFOPLIST_KEY_UIApplicationSupportsIndirectInputEvents: YES
        INFOPLIST_KEY_UILaunchScreen_Generation: YES
        INFOPLIST_KEY_UISupportedInterfaceOrientations_iPad: "UIInterfaceOrientationPortrait UIInterfaceOrientationPortraitUpsideDown UIInterfaceOrientationLandscapeLeft UIInterfaceOrientationLandscapeRight"
        INFOPLIST_KEY_UISupportedInterfaceOrientations_iPhone: "UIInterfaceOrientationPortrait UIInterfaceOrientationLandscapeLeft UIInterfaceOrientationLandscapeRight"
        CODE_SIGN_ENTITLEMENTS: ${APP_NAME}/${APP_NAME}.entitlements

  ${APP_NAME}Tests:
    type: bundle.unit-test
    platform: iOS
    sources:
      - path: ${APP_NAME}Tests
        type: folder
    dependencies:
      - target: ${APP_NAME}
    settings:
      base:
        PRODUCT_BUNDLE_IDENTIFIER: com.axi.${APP_NAME_LOWER}.tests
        TEST_HOST: "$(BUILT_PRODUCTS_DIR)/${APP_NAME}.app/$(BUNDLE_EXECUTABLE_FOLDER_PATH)/${APP_NAME}"
        BUNDLE_LOADER: "$(TEST_HOST)"
```

- [ ] **Step 2: 새 섹션 `## Design System Local Package` 추가 (`## Asset Catalog Structure` 위)**

다음 markdown 을 삽입:

````markdown
## Design System Local Package

Phase 3 scaffold 가 자동으로 생성하는 in-tree 로컬 패키지. 모듈 이름은 architect 가 `architecture.json.designSystemModule` 로 결정한다 (관례: `<AppName>DS`).

```
Packages/
└── ${DESIGN_SYSTEM_MODULE}/
    ├── Package.swift
    └── Sources/
        └── ${DESIGN_SYSTEM_MODULE}/
            ├── Tokens/
            │   ├── Color.swift          # design-system agent 가 채움
            │   ├── Typography.swift     # design-system agent 가 채움
            │   ├── Spacing.swift        # design-system agent 가 채움
            │   └── Radius.swift         # design-system agent 가 채움
            └── Components/
                # design-system agent 가 채움 (PrimaryButton, Card, SectionHeader, EmptyStateView 등)
```

### Package.swift template

```swift
// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "${DESIGN_SYSTEM_MODULE}",
    platforms: [.iOS(.v26)],
    products: [
        .library(name: "${DESIGN_SYSTEM_MODULE}", targets: ["${DESIGN_SYSTEM_MODULE}"]),
    ],
    targets: [
        .target(name: "${DESIGN_SYSTEM_MODULE}", path: "Sources/${DESIGN_SYSTEM_MODULE}"),
    ]
)
```

소비측에서는 `import ${DESIGN_SYSTEM_MODULE}` 만 하면 토큰과 컴포넌트를 모두 쓸 수 있다.
````

- [ ] **Step 3: Commit**

```bash
git add skills/autobot-ios-scaffold/references/project-templates.md
git commit -m "docs(scaffold): document Packages/<Name>DS template + project.yml packages section"
```

---

### Task 7: autobot-ios-scaffold SKILL.md — 새 step 문서화

**Files:**
- Modify: `skills/autobot-ios-scaffold/SKILL.md`

- [ ] **Step 1: `## Project Configuration Essentials > Required Files (자동 생성)` 에 한 줄 추가**

기존 목록 끝에:

```markdown
- `Packages/<DesignSystemModule>/Package.swift` — in-tree 로컬 SPM 골격 (Tokens/ stub 4개 포함). Phase 3 step 2 design-system 에이전트가 토큰·컴포넌트로 덮어쓴다. 모듈 이름은 `architecture.json.designSystemModule`.
```

- [ ] **Step 2: `## Project Creation` 의 bash 예시에 `--design-system-module` 옵션 추가**

3 개의 예시 명령 각각에 다음 한 줄을 끝에 붙인 형태로 갱신:

```bash
  --design-system-module "AppNameDS"
```

- [ ] **Step 3: 같은 `## Project Creation` 끝에 새 단락 추가**

```markdown
### Two-step Phase 3

Phase 3 는 (1) 이 스크립트가 `(self)` 로 프로젝트 + Packages 골격을 생성하고, (2) `design-system` 에이전트가 Tokens/Components 를 채우는 2 단계로 구성된다. (1) 직후 (2) 가 실행되도록 orchestrator 가 dispatch 한다. Gate 3→4 의 `design_system_package_exists` / `design_system_tokens_exist` 가 두 단계 산출물 모두 검증한다.
```

- [ ] **Step 4: Commit**

```bash
git add skills/autobot-ios-scaffold/SKILL.md
git commit -m "docs(scaffold): document --design-system-module flag and two-step Phase 3"
```

---

### Task 8: `agents/design-system.md` 신규 — 서브 에이전트 정의

**Files:**
- Create: `agents/design-system.md`

기존 `agents/ux-designer.md` 와 `agents/ui-builder.md` 의 frontmatter 형식과 본문 구조를 그대로 따른다 (description / model / tools / 본문).

- [ ] **Step 1: 파일 생성**

다음 전체 내용으로 `agents/design-system.md` 작성:

```markdown
---
name: design-system
description: Use this agent when populating the in-tree local Swift Package `<Name>DS` for an Autobot-generated iOS app. Reads `.autobot/architecture.json`, `.autobot/architecture.md`, and `.autobot/design-spec.md`, then writes design tokens (Color/Typography/Spacing/Radius) and shared SwiftUI components into `Packages/<Name>DS/Sources/<Name>DS/`.
model: sonnet
tools: Read, Write, Edit, Glob, Grep
---

# design-system agent

iOS 26+ 앱의 in-tree 로컬 SPM `<DesignSystemModule>` 의 콘텐츠를 채운다. Package 골격과 `project.yml` wiring 은 이미 Phase 3 scaffold step 이 완료했다. 이 에이전트는 **오직 `Packages/<DesignSystemModule>/Sources/<DesignSystemModule>/` 디렉토리 내부만** 수정한다.

## Pre-read (필수, 순서대로)

1. `.autobot/architecture.json` — `designSystemModule`, `appName` 값 확보
2. `.autobot/architecture.md` — `## Design Direction` 섹션 (Primary/Secondary 컬러, Typography 톤, Spacing scale)
3. `.autobot/design-spec.md` — `## Color Tokens`, `## Typography`, `## Spacing & Radius`, `## Interaction Feel`
4. `Packages/<DesignSystemModule>/Package.swift` — 모듈 이름 재확인용 read-only

## Output Contract

다음 파일들을 **모두** `Packages/<DesignSystemModule>/Sources/<DesignSystemModule>/` 아래에 작성한다 (기존 stub 을 덮어쓰는 형태):

### Tokens/ (필수 4 파일, 비어있으면 gate fail)

- `Tokens/Color.swift` — `public enum <Module>Color` 안에 `primary`, `secondary`, `accent`, `surface`, `onSurface` 등 design-spec 색상을 `Color(.sRGB, red:green:blue:opacity:)` 로 정의. Light/Dark 분기가 design-spec 에 있으면 `Color(uiColor: UIColor { trait in ... })` 패턴 사용.
- `Tokens/Typography.swift` — `public enum <Module>Font` 안에 `display(_:)`, `headline(_:)`, `body(_:)`, `caption(_:)` 정적 함수. Design Direction 의 font design (`.rounded` / `.default` / `.serif`) 를 반영.
- `Tokens/Spacing.swift` — `public enum <Module>Spacing` 의 `xs/s/m/l/xl/xxl: CGFloat`.
- `Tokens/Radius.swift` — `public enum <Module>Radius` 의 `s/m/l: CGFloat`.

### Components/ (디자인 방향에 맞춰 최소 4 개)

- `Components/PrimaryButton.swift` — `public struct <Module>PrimaryButton: View`. 토큰만 참조.
- `Components/Card.swift` — `public struct <Module>Card<Content: View>: View`. Padding/Radius 토큰 사용.
- `Components/SectionHeader.swift` — `public struct <Module>SectionHeader: View`.
- `Components/EmptyStateView.swift` — `public struct <Module>EmptyStateView: View`. 빈 상태 표준화.

모든 컴포넌트는 `public` 으로 선언하고 외부 의존성 없이 SwiftUI + 토큰만 사용한다. iOS 26 Liquid Glass 호환 (`.glassEffect()`, `Material` 등) 을 적극 사용해도 좋다.

## Constraints (위반 시 Gate 3→4 fail 또는 sandbox 차단)

- `Packages/<DesignSystemModule>/Sources/<DesignSystemModule>/` 외부 절대 수정 금지 (Hooks 사전 차단).
- `{appName}/` 아래 어떤 파일도 만지지 않는다. 특히 `{appName}/Utilities/Theme.swift` 는 더 이상 존재하지 않는다 — 만들지 마라.
- 모든 토큰/컴포넌트 타입은 `public`. 그렇지 않으면 앱 타깃에서 import 가 되지 않는다.
- Token 파일은 **반드시 4 개 모두** 비어있지 않은 콘텐츠로 생성한다 (placeholder stub 을 덮어써야 함).
- 외부 SPM 의존성 추가 금지 — Package.swift 는 수정하지 않는다 (scaffold 가 SSOT).

## 산출물 요약

```
Packages/<Module>/
└── Sources/<Module>/
    ├── Tokens/
    │   ├── Color.swift
    │   ├── Typography.swift
    │   ├── Spacing.swift
    │   └── Radius.swift
    └── Components/
        ├── PrimaryButton.swift
        ├── Card.swift
        ├── SectionHeader.swift
        └── EmptyStateView.swift
```

작업 종료 시 콘솔에 작성한 파일 경로 목록을 출력해 orchestrator 가 sandbox after-diff 와 대조할 수 있게 한다.
```

- [ ] **Step 2: Commit**

```bash
git add agents/design-system.md
git commit -m "agent(design-system): new sub-agent for in-tree <Name>DS package contents"
```

---

### Task 9: ui-builder agent — Theme.swift 생성 제거 + `import <Module>` 로 대체

**Files:**
- Modify: `agents/ui-builder.md` (line 73-200 부근, "Generate Theme" 단계 + Quality Standards 의 Theme 언급)

- [ ] **Step 1: "Generate Theme (Design Direction이 있을 때)" 단계 통째로 교체**

`agents/ui-builder.md` 의 `5. **Generate Theme (Design Direction이 있을 때)**:` 로 시작하는 step (line ~73 부터, 그 안의 a/b 하위 항목 포함) 을 다음으로 교체:

```markdown
5. **Read Design System Module name**:
   `.autobot/architecture.json` 의 `designSystemModule` 값 (예: `InstagramDS`) 을 읽는다. Phase 3 scaffold 가 `Packages/<Module>/` 를 만들었고 design-system 에이전트가 Tokens/Components 를 채웠다. ui-builder 는 그 패키지를 **import 만 한다 — Theme.swift 를 만들지 않는다**.

   생성하는 모든 SwiftUI 파일 (Views, ViewModels) 상단:
   ```swift
   import SwiftUI
   import <DesignSystemModule>
   ```

   사용 예:
   ```swift
   Text("Hello")
       .font(<Module>Font.headline(.title2))
       .foregroundStyle(<Module>Color.primary)
       .padding(<Module>Spacing.m)
       .background(<Module>Color.surface, in: RoundedRectangle(cornerRadius: <Module>Radius.m))
   ```

   - Asset Catalog 의 ThemePrimary/ThemeSecondary 등 colorset 은 생성하지 않는다 (design-system 패키지가 이를 코드 토큰으로 대체했다). AccentColor.colorset 은 scaffold 가 만든 그대로 둔다.
   - `Color.accentColor`, `Color.primary` 같은 시스템 기본값 직접 사용 금지 — 항상 `<Module>Color.*` 사용.
```

- [ ] **Step 2: Quality Standards 의 Theme 줄 갱신**

같은 파일의 `**Quality Standards:**` 블록 첫 줄 (`- **Theme.swift가 존재하면 ...`) 을 다음으로 교체:

```markdown
- **반드시 `import <DesignSystemModule>` 후 토큰을 사용한다** — `Color.accentColor`, `Color.primary`, 하드코딩 RGB, magic CGFloat 금지. 토큰이 부족하면 design-system 에이전트의 산출물을 읽고 사용 가능한 가장 가까운 토큰을 선택한다 (새 토큰 정의 금지).
```

- [ ] **Step 3: 파일 안에 "Theme.swift" / "Utilities/Theme" 잔존 언급 grep 후 제거**

Run:
```bash
grep -n 'Theme\.swift\|Utilities/Theme\|ThemePrimary\|ThemeSecondary\|ThemeAccent\|ThemeSurface' agents/ui-builder.md
```
Expected after edits: 0 매치 (모두 정리됨). 매치가 남으면 같은 방식으로 토큰 import 안내로 교체.

- [ ] **Step 4: Output 섹션의 "All files go inside `<AppName>/`" 줄 보존 확인**

ui-builder 가 여전히 `Packages/` 에 절대 쓰지 않음을 명시. `**IMPORTANT:**` 블록 끝에 한 줄 추가:

```markdown
- **`Packages/` 절대 수정 금지.** Design system 패키지는 design-system 에이전트의 영역. 토큰이 부족하다고 느껴도 직접 수정하지 말고 가장 가까운 토큰을 선택한다.
```

- [ ] **Step 5: Commit**

```bash
git add agents/ui-builder.md
git commit -m "agent(ui-builder): replace Theme.swift generation with import <Name>DS"
```

---

### Task 10: Orchestrator skill — Phase 3 two-step dispatch 문서화

**Files:**
- Modify: `skills/autobot-orchestrator/SKILL.md` (Composition Seam 섹션 부근 + Dispatcher 결정 로직)

- [ ] **Step 1: `## Composition Seam (Phase 3 출력)` 섹션 끝에 한 단락 추가**

```markdown
### Phase 3 two-step dispatch

Phase 3 는 두 단계로 실행된다 (모두 같은 phase 번호 내에서):

1. **scaffold (self)** — `create-xcode-project.sh` 호출. 인자에 `--design-system-module $(jq -r .designSystemModule .autobot/architecture.json)` 를 반드시 전달. Composition seam + `Packages/<Module>/Package.swift` + project.yml wiring + Tokens stub 4개 생성.
2. **design-system 에이전트 dispatch** — context-pack 으로 phase 슬라이스 + fileOwnership.agents.design-system.writes + design-spec.md / architecture.md 슬라이스를 전달. sandbox marker 의 `agent` 는 `design-system`.

두 단계 사이에는 `advance-phase` 를 호출하지 않는다 (같은 phase). step 1 실패 시 step 2 는 생략. step 2 실패 시 retryCount 가 phase 3 의 maxRetry (1) 안이면 step 2 만 재실행.
```

- [ ] **Step 2: `## Dispatcher 결정 로직` 의 phase 3 처리 한 줄 추가**

기존 6 번 항목 (Phase 4 병렬 디스패치) 위에 새 항목 (6 번) 을 끼워넣고 기존 6/7/8/9 를 7/8/9/10 으로 번호 변경:

```markdown
6. Phase 3 은 **두 단계 dispatch**: (a) `create-xcode-project.sh` 를 self 로 실행, 직후 (b) `design-system` 에이전트를 단일 dispatch. 둘 다 끝난 뒤 `advance-phase --phase 3` 으로 gate 실행.
```

- [ ] **Step 3: Commit**

```bash
git add skills/autobot-orchestrator/SKILL.md
git commit -m "docs(orchestrator): document Phase 3 two-step dispatch (scaffold → design-system)"
```

---

### Task 11: context_pack.py — `design-system` REFERENCE_FILES 등록

**Files:**
- Modify: `scripts/context_pack.py` (REFERENCE_FILES 딕셔너리, line 38-58 부근)

- [ ] **Step 1: REFERENCE_FILES 에 새 키 추가**

`REFERENCE_FILES` 딕셔너리에 다음 항목 추가 (ux-designer 항목 다음 위치 권장):

```python
    "design-system": [
        "references/axiom-distilled/design.md",
        "references/axiom-distilled/swiftui.md",
    ],
```

- [ ] **Step 2: 빠른 검증 — context-pack 명령으로 design-system 슬라이스 생성**

Run:
```bash
cd /tmp && mkdir -p ctx_test/.autobot && \
  echo '{"appName":"Acme","designSystemModule":"AcmeDS"}' > ctx_test/.autobot/architecture.json && \
  bash /Users/louis/Code/Autobot/scripts/pipeline.sh context-pack \
    --phase 3 --agent design-system --format text 2>&1 | head -40
```
Expected: 출력에 `PHASE`, `OUTPUT CONTRACT` (writes: Packages/), `REFERENCE INDEX` (design.md, swiftui.md) 가 보인다.

- [ ] **Step 3: Commit**

```bash
git add scripts/context_pack.py
git commit -m "feat(context-pack): register reference files for design-system agent"
```

---

### Task 12: smoke-e2e.sh — Package + 토큰 존재 검증 추가

**Files:**
- Modify: `scripts/smoke-e2e.sh` (`---- 2. 프로젝트 scaffold ----` 블록 뒤)

smoke 는 design-system 에이전트를 실제로 dispatch 하지 않는다 (LLM 호출 없는 회귀). 하지만 scaffold step 1 (Package 골격 + stub) 이 정상 생성되는지는 확인할 수 있다.

- [ ] **Step 1: scaffold 호출에 `--design-system-module` 인자 추가**

기존 `create-xcode-project.sh` 호출에 다음 인자를 추가:

```bash
  --design-system-module "SmokeDS"
```

- [ ] **Step 2: scaffold 직후 검증 블록 추가**

scaffold 호출 뒤 (`---- 3. env_snapshot ----` 직전) 에 다음을 삽입:

```bash
log "design system package 골격 검증"
PKG="$WORKDIR/Smoke/Packages/SmokeDS"
[[ -f "$PKG/Package.swift" ]] || { err "Package.swift 없음: $PKG"; exit 2; }
grep -q 'name: "SmokeDS"' "$PKG/Package.swift" || { err "Package.swift name 불일치"; exit 2; }
for f in Color.swift Typography.swift Spacing.swift Radius.swift; do
  [[ -s "$PKG/Sources/SmokeDS/Tokens/$f" ]] || { err "Token stub 누락 또는 빈 파일: $f"; exit 2; }
done
grep -q 'package: SmokeDS' "$WORKDIR/Smoke/project.yml" || { err "project.yml 에 package dependency 누락"; exit 2; }
log "design system package 골격 OK"
```

- [ ] **Step 3: smoke 실행 — 로컬 환경에서만**

Run (Xcode 26+ + simulator 환경에서):
```bash
bash /Users/louis/Code/Autobot/scripts/smoke-e2e.sh --no-launch
```
Expected: exit 0, 로그에 `design system package 골격 OK` 출력 + scaffold build 성공.

(주의: 이 step 은 macOS / Xcode 26+ 가 있어야 의미가 있다. CI 외 환경이면 skip 하고 다음 task 진행.)

- [ ] **Step 4: Commit**

```bash
git add scripts/smoke-e2e.sh
git commit -m "test(smoke): verify Packages/<Name>DS skeleton after scaffold"
```

---

### Task 13: CHANGELOG.md — 변경 요약

**Files:**
- Modify: `CHANGELOG.md` (Unreleased 또는 최상단 새 버전 섹션)

- [ ] **Step 1: 다음 항목 추가**

```markdown
## [Unreleased]

### Added
- **Design System SPM**: 매 MVP 빌드마다 in-tree 로컬 패키지 `Packages/<Name>DS/` 를 자동 생성. architect 가 `architecture.json.designSystemModule` 로 이름 결정 (관례: `<AppName>DS`), Phase 3 scaffold 가 골격 + project.yml wiring, 새 `design-system` 서브 에이전트가 Tokens/Components 채움.
- 새 게이트: `design_system_package_exists`, `design_system_tokens_exist` (Gate 3→4).
- `create-xcode-project.sh --design-system-module` 플래그.

### Changed
- ui-builder 는 더 이상 `Utilities/Theme.swift` 를 생성하지 않는다. 대신 `import <Name>DS` 후 패키지 토큰을 사용한다.
- Phase 3 가 (self scaffold → design-system 에이전트) 2 단계 dispatch 로 변경.
- `fileOwnership.agents` 에 `design-system` 추가, `ui-builder.writes` 에서 `Theme.swift` 제거.
```

- [ ] **Step 2: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs(changelog): design-system SPM + ui-builder Theme.swift removal"
```

---

## Self-Review Checklist (작성자 자가 점검)

다음 항목을 모두 만족하는지 확인하고 부족하면 inline 수정:

1. **Spec coverage** — 합의된 요구사항 6 항목이 모두 task 로 매핑되는가?
   - 위치 (in-tree Packages/) → Task 4
   - 트리거 (mvp 파이프라인 자동) → Task 1 (Phase 3 agents), Task 10 (orchestrator)
   - 범위 (토큰 + 컴포넌트, 아이콘·테마 variant 제외) → Task 8 (design-system Output Contract)
   - 작명 (`<Name>DS`, architect 가 결정) → Task 3 (architect emit) + Task 4 (scaffold consume)
   - 주체 (새 design-system 에이전트) → Task 8, Task 1 (fileOwnership)
   - iOS 26+ 단일 / 테스트 없음 → Task 4 (Package.swift `.iOS(.v26)`), 테스트 타깃 미생성
   - 모두 ✅

2. **Placeholder scan** — "TBD/TODO/구현 나중에/적절한" 패턴 없음. 모든 코드 블록과 명령은 실행 가능한 형태로 작성됨. ✅

3. **Type consistency** —
   - `designSystemModule` 이름이 spec / gate / architect / scaffold / agent / ui-builder 전체에서 일관 (`InstagramDS` 형태) ✅
   - 패키지 경로 `Packages/<Module>/Sources/<Module>/Tokens/` 가 scaffold / gate check / design-system agent 모두 동일 ✅
   - Token 파일 4 개 이름 (`Color.swift`, `Typography.swift`, `Spacing.swift`, `Radius.swift`) 이 scaffold stub / gate check / agent contract 전체에서 동일 ✅
   - 컴포넌트 4 개 이름 (`PrimaryButton`, `Card`, `SectionHeader`, `EmptyStateView`) 은 agent 와 references 에 일관 ✅

---

## Execution Order Notes

- **Task 1 → Task 2 → Task 3** 순서 엄수 (spec 이 바뀌어야 gate runner test 가 의미, architect contract 가 바뀌어야 scaffold 가 값을 읽음).
- **Task 4, 5, 6, 7** 은 scaffold 클러스터 — 4 가 가장 위험 (셸 heredoc 변수 보간). 4 끝나면 5/6/7 은 순차.
- **Task 8** (design-system agent) 은 Task 4 와 무관하게 진행 가능 — 독립.
- **Task 9** (ui-builder) 는 Task 8 이 끝나야 import 대상 모듈이 정의됨.
- **Task 10, 11** 은 위 모두에 대한 메타 문서 — 마지막.
- **Task 12** (smoke) 은 Task 4 이후라면 언제든 OK. Xcode 환경 의존이므로 CI/로컬에서만.
- **Task 13** (changelog) 가장 마지막.
