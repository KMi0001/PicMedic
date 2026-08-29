# PicMedic — Phase 1 + GUI

PRD 기준 **핵심 로직**(파일 형식 탐지/이미지 유효성 검사/복구)과
**PySide6 GUI 6개 화면**(Home → Scanning → Scan Result → File Detail → Recovery → Recovery Result)을
모두 구현했습니다.

## 구조

```
PicMedic/
├── main.py               # 실행 진입점
├── assets/
│   ├── icon.ico           # 앱 아이콘 (exe 파일 아이콘 + 실행 중 창 아이콘)
│   └── icon.png
├── core/
│   ├── detector.py        # Magic Number/Signature 기반 실제 형식 탐지
│   ├── analyzer.py         # detector + Pillow 디코딩 -> FileInfo 진단
│   ├── scanner.py          # 폴더 재귀 스캔 -> ScanResult
│   └── converter.py        # 확장자 복원 / JPEG 변환 / 복구 후 재검증
├── models/
│   ├── file_info.py
│   └── scan_result.py
├── gui/
│   ├── theme.py             # 공통 스타일(QSS)
│   ├── home_screen.py       # Screen 01
│   ├── scanning_screen.py   # Screen 02 (백그라운드 QThread)
│   ├── result_screen.py     # Screen 03 (필터/검색/테이블)
│   ├── detail_screen.py     # Screen 04 (미리보기 + 복구 버튼)
│   ├── recovery_screen.py   # Screen 05 (배치 복구, QThread)
│   ├── recovery_result_screen.py  # Screen 06
│   └── main_window.py       # QStackedWidget으로 전체 화면 연결
├── utils/
│   ├── file_utils.py        # 복구 파일명 충돌 회피
│   └── logger.py            # FR-006 스캔/복구 작업 로그 (logs/picmedic_log.jsonl)
├── tests/
│   ├── test_detector.py
│   ├── test_analyzer.py
│   ├── test_converter.py
│   └── test_logger.py
└── requirements.txt
```

## 설치 및 실행

```bash
pip install -r requirements.txt
python main.py
```

## 테스트 실행

```bash
python tests/test_detector.py
python tests/test_analyzer.py
python tests/test_converter.py
python tests/test_logger.py
```
모두 [PASS]로 통과해야 합니다 (총 55개 케이스).

## 사용 흐름

1. Home 화면에서 폴더를 선택하거나 드래그 앤 드롭
2. 자동으로 스캔이 시작되고(백그라운드 스레드, UI 안 멈춤) 진행률 표시
3. 검사 결과 화면에서 정상/형식불일치/부분손상/손상 개수 확인, 필터·검색 가능
4. 파일을 더블클릭하면 상세 화면에서 미리보기 + 복구 버튼(확장자 복원/JPEG 변환)
5. 목록에서 여러 파일을 선택해 "선택 항목 복구"로 일괄 복구도 가능
6. 복구 실행 시 원본은 그대로 두고 별도 폴더(`Recovered/`)에 새 파일 생성, 완료 후 자동 재검증
7. 복구 결과 화면에서 성공/부분성공/실패 확인, 저장 폴더 바로 열기

## exe 빌드 (Windows 배포용)

```bash
pip install pyinstaller
pyinstaller --noconfirm --windowed --onefile --name PicMedic --icon assets/icon.ico --add-data "assets;assets" --collect-all pillow_heif main.py
```

- 결과물: `dist/PicMedic.exe` (단일 실행 파일, ~70MB)
- `--collect-all pillow_heif`가 반드시 필요합니다 (HEIC/HEIF 디코딩용 네이티브 DLL을 exe 안에 포함시키기 위함, 빠지면 HEIC 관련 기능이 조용히 실패함)
- `--icon assets/icon.ico`는 exe 파일 자체의 아이콘, `--add-data "assets;assets"`는 실행 중 창 아이콘(`main.py`에서 읽음)을 위해 필요합니다
- 로그(`logs/`)와 기본 복구 저장 위치는 실행 파일 기준 경로를 사용하므로, exe를 옮기면 그 위치에 새로 생성됩니다
- 두 번째 빌드부터는 `PicMedic.spec`이 위 설정을 기억하고 있어 `pyinstaller PicMedic.spec`만 실행해도 됩니다
- 재빌드 전 이전 산출물을 지우려면: `rm -rf build dist`

## 로그 (FR-006)

스캔 1회, 복구 파일 1개마다 `logs/picmedic_log.jsonl`에 한 줄씩(JSON Lines) 자동 기록됩니다.
(`logs/` 폴더는 첫 실행 시 자동 생성되며 git에는 포함하지 않습니다.)

## 기획서 / 다음 단계

- [PicMedic_PRD_v2.md](PicMedic_PRD_v2.md) — 실제 구현 내용을 반영한 기획서 개정판 (원본 PRD 구조 유지 + 변경점 표시 + 개선 제안 37장)
- [PRD_MVP우선순위.md](PRD_MVP우선순위.md) — 우선순위(P0~P3)별 세부 구현 체크리스트

남은 항목: PRD 23장 예외 메시지 문구 정합화, 검색/정렬 범위 확장, 중복 사진 탐지 등 Phase 2 기능. 자세한 내용은 위 두 문서 참고.

