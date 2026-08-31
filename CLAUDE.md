# PicMedic

PySide6(Qt) 기반 데스크톱 앱. 사진 파일 진단(형식 탐지/손상 검사) 및 복구.

## 크로스플랫폼 원칙 (Windows + macOS)

이 저장소는 Windows/macOS 양쪽에서 하나의 코드베이스로 개발한다. **OS별로 코드를 분기하지 않는다** —
PySide6가 UI 차이를 흡수하므로, 필요한 경우에만 `sys.platform` 분기를 최소 범위로 추가한다.
패키징(PyInstaller)만 OS마다 각각 빌드해야 한다(크로스 컴파일 불가): Windows는 `.exe`, macOS는 `.app`.

## 기능 추가/수정 시 체크리스트 (매 업데이트마다 확인)

- **경로 처리**: `pathlib.Path` 사용 유지, 문자열 경로 결합(`+`, `"\\"` 하드코딩) 금지.
- **OS 전용 API 금지**: `os.startfile`, `winreg` 등 Windows 전용 호출 추가하지 않기. 폴더 열기는
  `QDesktopServices.openUrl` 사용 (이미 [gui/recovery_result_screen.py](gui/recovery_result_screen.py) 참고).
- **기본 경로**: 사진/문서 폴더 등은 `QStandardPaths`로 가져오기 (하드코딩 금지).
- **파일 스캔 시 OS 잡파일 제외**: `core/scanner.py`의 `iter_candidate_files`에서
  macOS AppleDouble(`._*`) 파일을 이미 걸러내고 있음 — 스캔 대상 필터를 바꿀 때 이 로직이
  살아있는지 확인. 확장자 필터를 새로 추가할 때도 같은 함수에 유지할 것.
- **`.gitignore`**: 새로운 OS 전용 잡파일(예: `.DS_Store`, `Thumbs.db`)이 생기면 즉시 추가.
- **폰트**: [gui/theme.py](gui/theme.py)의 `font-family` 폴백 목록(Windows/macOS 한글 폰트 포함)에
  새 폰트를 쓸 경우 양쪽 OS에 실제로 존재하는지 확인 후 추가.
- **아이콘**: 런타임 창 아이콘은 `assets/icon.ico`(Qt가 크로스플랫폼으로 읽음)로 충분. macOS 앱 번들(`.app`)
  빌드용 `assets/icon.icns`는 준비되어 있음 (`PicMedic-mac.spec`에서 사용).

## 빌드

- Windows: `pyinstaller PicMedic.spec` (또는 README.md의 전체 커맨드)
- macOS: `pyinstaller PicMedic-mac.spec` (`.icns` 아이콘 + `.app` 번들 생성용 별도 spec).
  크로스 컴파일 불가 — 반드시 macOS에서 빌드. macOS 하드웨어가 없을 때는
  `.github/workflows/build-macos.yml`(GitHub Actions macOS 러너)로 빌드해 아티팩트로 받을 수 있음.

## 참고 문서

- [README.md](README.md) — 설치/실행/테스트/빌드 방법
- [PicMedic_PRD_v2.md](PicMedic_PRD_v2.md) — 기획서
- [PRD_MVP우선순위.md](PRD_MVP우선순위.md) — 우선순위별 구현 체크리스트
- [DESIGN.md](DESIGN.md) — 색상/아이콘/팝업 등 UI 디자인 가이드 (새 화면·컴포넌트 추가 시 참고)
- [PLATFORM_EXPANSION.md](PLATFORM_EXPANSION.md) — 웹/앱(모바일) 확장 검토 메모 (아직 미착수, 방향만 정리됨)
