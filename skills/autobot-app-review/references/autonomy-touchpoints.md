# App Review 자율성 계약 — 인간 개입 지점 완전 인벤토리

`/autobot:app-review`(= `autobot-app-review` 스킬)가 "빌드 완료된 앱 → App Store 첫 심사 제출"을 **인간 도움 없이 끝까지** 수행하는지에 대한 정직한 답. 파이프라인이 멈출 수 있는 모든 지점을 `CLOSED`(완전 자동) / `IRREDUCIBLE`(불가피한 인간 단계, API 우회 없음) / `CONDITIONAL`(앱 성격에 따라 조건부)로 분류한다.

**한 줄 결론:** per-app 자율성은 완전하다. 앱마다 반복되는 작업(메타·스크린샷·연령등급·빌드·제출)에 인간 손이 필요한 곳은 없다. 인간이 필요한 건 **계정 레벨 1회 부트스트랩**과 **Apple이 주기적으로 강제하는 약관 수락** 두 부류뿐이며, 이는 어떤 자동화도 우회할 수 없다.

---

## CLOSED — 완전 자동 (인간 개입 0)

| 단계 | 무엇 | 자동화 방식 |
|------|------|-------------|
| B | ASO 메타데이터 생성 (제목/부제/키워드/설명/릴리스노트) | LLM이 `architecture.md`에서 도출, ASC 글자수 계약 강제 |
| B | 메타데이터 ASC 업로드 | `fastlane deliver --skip_binary_upload` |
| **B** | **연령 등급 설문 (age rating questionnaire)** | **`fastlane/metadata/app_store_rating_config.json` → `deliver --app_rating_config_path`. 이전엔 유일한 수동 ASC-웹 단계였다 (닫음, 아래 참조)** |
| C | 스크린샷 narrative 계획 (5-slot) | `aso-skills:screenshot-optimization` 원칙 inline 적용 |
| D-1 | 원본 화면 캡쳐 | `ios-marketing-capture` in-app SwiftUI 캡쳐 |
| D-2 | 4개 iPhone 사이즈(6.9"/6.5"/6.3"/6.1") 광고 슬라이드 합성 | `app-store-screenshots` 제너레이터 |
| B | 마케팅/지원/개인정보 URL 주입 | 마케팅=지원=`https://axi-homepage.vercel.app/ko/products/<slug>`, 개인정보=`https://axi-homepage.vercel.app/en/privacy`(고정 공유 페이지). 메타데이터 per-locale url 필드로 자동 기록 |
| H | 마케팅 URL(홈페이지) 등록 — Apple 심사가 검증하는 공개 URL | `register-on-homepage.sh` → AXI-Homepage push (`/ko/products/<slug>` 생성). `/en/privacy`는 앱별이 아닌 고정 페이지라 Phase H 불필요 |
| E | 스크린샷 ASC 업로드 | `upload-screenshots.sh` |
| 0b | ASC 앱 레코드 등록 (메타/연령등급 업로드 전 보장) | `autobot-register-app` (멱등 — `already_exists` 조용히 통과). Phase F의 register는 이후 no-op |
| F | Archive + 코드 서명 | `xcodebuild -allowProvisioningUpdates` (프로비저닝 자동 생성) |
| F | 바이너리 업로드 | `autobot-upload-build` |
| G | 빌드 PROCESSING 대기 | 최대 30분 폴링 |
| G | 수출 규정 (export compliance) | `ITSAppUsesNonExemptEncryption=false` 기본 계약 |
| G | 콘텐츠 권리 / IDFA 선언 | 스캐폴드 기본값 (3rd-party 콘텐츠 없음, IDFA 없음) |
| G | 심사 제출 + 승인 시 자동 출시 | `deliver --submit_for_review --automatic_release true` |

### 닫은 갭: 연령 등급 설문

이전에는 `submit-for-review.sh`가 `age_rating_missing`에서 **"ASC 웹에서 수동으로 답하라"**고 인간에게 떠넘겼다 — 자율 완주를 깨는 유일한 프로그래밍 가능 지점이었다.

- **메커니즘:** fastlane 2.235.0의 `deliver`는 `--app_rating_config_path <json>`을 지원하고, 이를 **메타데이터 업로드 호출 안에서** ASC Connect API `ageRatingDeclaration` 리소스로 전송한다 (submit 호출이 아님 — 연령 등급은 앱 레벨 속성이라 1회 설정).
- **키 스키마:** modern camelCase 키(`violenceCartoonOrFantasy`, `messagingAndChat`, `gamblingSimulated` …). fastlane이 그대로 통과시키며 2025년 Apple 연령등급 개편 신규 필드(`ageAssurance`, `lootBox`, `parentalControls`, `kidsAgeBand`, `koreaAgeRatingOverride` 등)를 포함한다. 구식 iTunesConnect 키도 자동 매핑(deprecation 경고).
- **배선:** Phase B가 `app_store_rating_config.json`(전 필드 `NONE`/`false` = 깨끗한 4+)을 쓰고, `upload-metadata.sh`가 파일 존재 시 자동으로 플래그를 붙인다. 파일 없으면 legacy 무변경(backward-compatible).
- **1회차 순서 보장:** fastlane은 앱이 ASC에 존재해야 rating을 적용한다(메타데이터와 동일 전제). 그래서 파이프라인은 **Phase 0b**(`autobot-register-app`, 멱등)를 Phase B(메타/연령등급 업로드) **앞에** 배치해, 첫 실행에서도 단일 패스로 rating이 적용되도록 보장한다. name/bundle 충돌은 Phase 0b에서 fail-fast(값비싼 메타/스크린샷 작업 전).

---

## IRREDUCIBLE — 불가피한 인간 단계 (API 우회 없음)

이 셋은 자동화가 **원천적으로 불가능**하다. Apple이 신뢰의 뿌리(root of trust)와 법적 동의를 인간에게 묶어놨기 때문. "자율 실행이 갑자기 멈췄다"의 대부분은 여기서 온다.

1. **ASC API 키 발급 + Apple Developer Program 가입** — 계정당 1회. 인간이 ASC 웹에서 App Manager 이상 role의 `.p8` 키를 만들어 `ASC_API_KEY_ID` / `ASC_API_ISSUER_ID` / `ASC_API_KEY_PATH` 3종을 심어야 한다. 이 키가 이후 모든 자동화의 신뢰 뿌리이므로 자동화로 부트스트랩할 수 없다. (`/autobot:setup`이 한 번 안내)

2. **주기적 ASC 라이선스 약관 수락** — Apple이 새 Paid/Free Apps Agreement나 갱신된 약관을 게시하면, **인간이 ASC 웹에서 수락할 때까지 모든 제출이 차단된다.** API 우회 없음. 첫 실행뿐 아니라 **예측 불가능한 시점에** (Apple이 약관을 바꿀 때마다) 발화한다 — 잘 돌던 자율 파이프라인이 어느 날 멈추는 #1 원인. 발생 시 `deliver`가 약관 관련 에러를 뱉으며, 유일한 복구는 계정 담당자가 ASC → Agreements에서 수락하는 것.

3. **머신의 서명 아이덴티티 최초 설치 (부분)** — archive는 `-allowProvisioningUpdates`로 프로비저닝을 자동 생성하지만, 키체인에 유효한 서명 인증서(Apple Development/Distribution)가 있어야 한다. Xcode → Settings → Accounts에서 1회 생성. 이후는 자율.

---

## CONDITIONAL — 앱 성격에 따라 조건부 (기본 Autobot 스캐폴드엔 불필요)

이들은 **제출("Waiting for Review" 도달)을 막지 않는다** — 심사 통과/승인에만 영향. "첫 심사까지 넣는다"는 제출이지 승인이 아니므로 범위 밖. 필요 시 후속 작업.

- **데모 계정 + review notes** — 앱이 로그인을 요구할 때만. 제출은 데모 계정 없이도 도달한다; 없으면 Apple이 심사 중 리젝하거나 정보를 요청할 뿐. Autobot 스캐폴드는 기본적으로 로그인 게이트가 없다. → **후속 개선 후보** (`review_information` demo_user/demo_password + notes 자동 주입). 지금은 미구현.
- **개인정보처리방침 URL** — 이제 항상 `https://axi-homepage.vercel.app/en/privacy`로 자동 주입(CLOSED). 별도 인간 개입 없음.
- **개인정보 영양표시(privacy nutrition labels, 데이터 수집 선언)** — 앱이 데이터를 수집할 때만. 기본 스캐폴드는 수집 안 함. 데이터 수집이 추가되면 ASC가 데이터 수집 선언을 요구(URL은 위에서 이미 충족).
- **상향된 연령 등급** — `architecture.md`가 폭력/도박/UGC/무제한 웹/채팅 콘텐츠를 명시하면 Phase B의 `app_store_rating_config.json`을 그에 맞게 조정해야 한다(과소 선언은 리젝 사유). 판단 근거가 명확할 때만 상향, 애매하면 무콘텐츠 기본 유지.

---

## 검증 방법

```bash
# rating config 있으면 deliver에 플래그가 붙는지 (dry-run)
bash skills/autobot-upload-metadata/scripts/upload-metadata.sh \
  --bundle-id <id> --metadata-path fastlane/metadata --dry-run \
  | grep app_rating_config_path

# 없으면 legacy 무변경 (플래그 0회)
```
