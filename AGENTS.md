# AGENTS.md

이 저장소에서 작업하는 AI 코딩 에이전트(도구 종류 무관)용 안내.

1. 먼저 [HANDOFF.md](HANDOFF.md)를 읽는다 — 프로젝트 개요, 실행/테스트/빌드, 코드 지도, 관례, 남은 일.
2. 작업 규칙은 [CLAUDE.md](CLAUDE.md)를 그대로 따른다 (파일 이름만 Claude용일 뿐, 크로스플랫폼 원칙과
   매 업데이트 체크리스트는 모든 에이전트에 적용된다).
3. UI를 건드리면 [DESIGN.md](DESIGN.md)를 따른다.

빠른 확인 명령:

```bash
pip install -r requirements.txt -r requirements-dev.txt
QT_QPA_PLATFORM=offscreen python -m pytest
```
