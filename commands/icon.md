---
name: icon
description: "imagegen으로 코너 라운드 없는 1024×1024 PNG 앱 아이콘을 생성합니다. 빌드 파이프라인 없이 독립 실행할 수 있습니다."
argument-hint: "<앱 설명과 원하는 스타일> [저장 경로]"
---

# Autobot Icon

`autobot-app-icon` 스킬을 로드하고 **Standalone: `/autobot:icon`** 절차를 실행한다.

사용자 입력: $ARGUMENTS

생성·프롬프트·저장·검증 계약의 SSOT는 `$CLAUDE_PLUGIN_ROOT/skills/autobot-app-icon/SKILL.md`다. 커맨드는 진입점만 제공한다. 도구 권한은 런타임에서 상속해 설치된 imagegen 도구를 사용할 수 있게 한다.
