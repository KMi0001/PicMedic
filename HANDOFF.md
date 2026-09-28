# PicMedic 인수인계 (Handoff)

> 작성: 2026-09-28. 이 저장소를 처음 맡는 사람/AI 에이전트가 **가장 먼저 읽을 문서**.
> 규칙(크로스플랫폼 원칙·체크리스트)은 [CLAUDE.md](CLAUDE.md)에 있고, 어떤 AI 도구를 쓰든
> 똑같이 적용된다([AGENTS.md](AGENTS.md)는 그 파일로 안내만 한다).

---

## 1. 한 줄 요약

PySide6(Qt) 데스크톱 앱. 사진 폴더를 **검사**(실제 형식 탐지·손상 판정) → **복구**(확장자 복원/형식 변환)
→ **정리**(중복·유사·날짜별·도시별·AI 카테고리)까지 한 흐름으로 한다. 모든 처리는 **로컬에서만**
(서버 전송 없음, GPS 좌표도 프로세스 밖으로 안 나감). Windows + macOS 단일 코드베이스.

## 2. 5분 안에 돌려보기

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

- Python **3.11** 기준(CI도 3.11).
- AI 카테고리(동물·음식·스크린샷·야경·풍경) 기능은 모델 자산이 있어야 동작한다 — 없으면 해당
  기능만 비활성, 나머지는 정상. 받는 법은 [4-3](#4-3-ai-모델-자산-clip) 참고.

테스트:

```bash
pip install -r requirements.txt -r requirements-dev.txt
QT_QPA_PLATFORM=offscreen python -m pytest      # Windows PowerShell: $env:QT_QPA_PLATFORM="offscreen"
```

- 21개 파일 / 테스트 함수 53개(2026-09-28 기준 `def test_` 개수). 자산이 필요한 케이스는
  `tests/helpers.py`의 `skip()`으로 [SKIP] 처리되며, 순수 로직은 자산 없이도 전부 통과해야 한다.
- `requirements-dev.txt`에 torch/open_clip이 있지만 **변환 스크립트 전용**이다. 앱 런타임은 torch를 안 쓴다.

## 3. 코드 지도

```
main.py                     진입점 (단일 인스턴스 → MainWindow)
core/   (Qt 의존 금지 — 웹 확장 가능성을 위해 순수 Python 유지)
  detector.py               매직 넘버 기반 실제 형식 탐지
  analyzer.py               detector + Pillow 디코딩 → FileInfo (상태/복구 가능성/EXIF/GPS)
  scanner.py                폴더 재귀 스캔, 증분 스캔(scan_paths_incremental), OS 잡파일(._*) 제외
  converter.py              확장자 복원 / 형식 변환 / 복구 후 재검증
  session_store.py          검사 결과 자동 저장·불러오기(사용자 데이터 폴더/sessions, gzip JSON)
  duplicate_resolver.py     중복(완전 동일) + 유사(ImageHash) 사진 그룹
  date_organizer.py         촬영일 기준 정리
  geocoder.py               GPS → 도시명 (오프라인, assets/geonames_cities1000.csv + scipy cKDTree)
  location_inference.py     GPS 없는 사진의 위치를 주변 사진으로 추정
  country_names_ko.py       국가명 한글화
  category_finder.py        AI 카테고리 찾기 (CLIP 이미지 임베딩 × 사전계산 텍스트 임베딩)
  image_embedding_cache.py  CLIP ONNX 로딩 + 세션 내 임베딩 캐시
  text_embeddings.py        assets/photo_category/text_embeddings.json 로더
  live_photo_finder.py      아이폰 라이브 포토(사진+MOV 짝) 찾기
  renamer.py                이름 일괄변환
models/                     FileInfo, ScanResult 데이터 클래스
gui/
  main_window.py            홈 화면만 상주, 폴더마다 ScanSessionWindow를 독립 창으로 띄움
  home_screen.py            드롭존 + 변환/라이브포토/이름변환 카드 + 임시 휴지통 + 개인정보처리방침 링크
  scan_session_window.py    검사~복구~정리 한 세션 (기능별 *_mixin.py로 분할)
  scan_session_workers.py   QThread 워커들
  scanning/result/detail/recovery/recovery_result_screen.py  기본 6화면 흐름
  duplicate/similar/date_organize/city_organize/category_finder_screen.py  정리 기능 화면
  city_map_view.py          도시별 정리 지도(TopoJSON 직접 렌더)
  theme.py / icons.py / common_dialogs.py  디자인 시스템 (→ DESIGN.md)
  help_dialog.py            사용방법/활용법/Q&A — 기능 설명을 사용자 관점에서 가장 잘 요약한 곳
utils/
  assets.py                 개발/빌드 공통 assets 경로 (frozen이면 sys._MEIPASS)
  logger.py                 작업 로그 + _user_data_dir() (core가 Qt 없이 쓰는 사용자 데이터 경로)
  trash.py                  임시 휴지통(원본 폴더 안 '임시휴지통/' + .trash_manifest.json)
  single_instance.py        QLocalServer 기반 중복 실행 방지
  native_titlebar.py        타이틀바 색상(OS 네이티브)
  topojson.py               TopoJSON 디코더
scripts/                    AI 자산 받기/변환 (빌드 전 1회)
experiments/                기능별 프로토타입·실측 스크립트. 앱은 import하지 않음(빌드에 안 들어감)
tests/                      pytest (Qt 위젯 테스트 포함)
```

### 사용자 데이터가 쌓이는 곳

| 무엇 | 개발 실행(`python main.py`) | 패키징된 앱 |
|---|---|---|
| 작업 로그 `picmedic_log.jsonl` | 저장소 `logs/` | Win `%LOCALAPPDATA%\PicMedic\logs\` / mac `~/Library/Application Support/PicMedic/logs/` |
| 세션 저장본 | 위 사용자 데이터 폴더 `sessions/` (개발/패키징 동일) | 〃 |
| 복구 결과 | 원본 폴더 옆 `Recovered/` | 〃 |
| 정리에서 "삭제"한 사진 | 원본 폴더 안 `임시휴지통/` (홈 → 임시 휴지통에서 복원) | 〃 |

## 4. 패키징 (배포 빌드)

PyInstaller는 **크로스 컴파일 불가** — Windows 빌드는 Windows에서, macOS 빌드는 macOS에서.
두 spec 모두 **onedir**(폴더째 배포) 방식이다.

### 4-1. 빌드 전 준비 (양 OS 공통)

```bash
pip install -r requirements.txt -r requirements-dev.txt
pip install pyinstaller
# AI 카테고리 자산 (없으면 그 기능만 빠진 빌드가 나옴)
python scripts/fetch_photo_category_assets.py      # ViT-B-32.pt 354MB 다운로드
python scripts/export_clip_onnx_assets.py          # → clip_visual_int8.onnx + text_embeddings.json
rm assets/photo_category/ViT-B-32.pt               # 변환 원본 — 지우지 않으면 번들에 딸려 들어감!
rm -rf build dist
```

### 4-2. 빌드

| | Windows | macOS |
|---|---|---|
| 명령 | `pyinstaller --noconfirm PicMedic.spec` | `pyinstaller --noconfirm PicMedic-mac.spec` |
| 결과 | `dist/PicMedic/` 폴더 전체 (`PicMedic.exe` + `_internal/`) | `dist/PicMedic.app` |
| 아이콘 | `assets/icon.ico` | `assets/icon.icns` |
| 배포 | **폴더 통째로** zip 또는 설치 프로그램(MSIX 등). exe만 떼면 실행 안 됨 | `ditto -c -k --sequesterRsrc --keepParent PicMedic.app PicMedic-macOS.zip` |
| CI | `.github/workflows/build-windows.yml` | `.github/workflows/build-macos.yml` |

CI 빌드는 `main`·`claude/**` 푸시(코드/spec 변경 시) 또는 Actions 탭 "Run workflow"로 돌고,
결과는 Artifacts(`PicMedic-Windows` / `PicMedic-macOS`, 14일 보관)로 받는다.
**아티팩트 안 `BUILD_INFO.txt`**에 커밋 해시와 AI 자산 포함 여부가 기록된다 — 받은 앱에서 AI
카테고리가 안 보이면 그 파일부터 확인.

### 4-3. AI 모델 자산 (CLIP)

- `assets/photo_category/`는 `.gitignore` 대상 — git에 없다. 위 스크립트로 매번 만든다.
- 런타임에 필요한 건 `clip_visual_int8.onnx`(~89MB) + `text_embeddings.json` 두 개뿐.
- 카테고리 프롬프트(텍스트)를 바꾸면 `export_clip_onnx_assets.py`를 다시 돌려 임베딩을 재생성해야 한다.

### 4-4. spec에서 건드리면 안 되는 것

- `collect_all('pillow_heif')` — 빠지면 HEIC 처리가 **조용히** 실패.
- `collect_all('onnxruntime')` — AI 카테고리용 네이티브 모듈.
- `upx=False` — UPX는 네이티브 DLL 로딩 실패·백신 오탐·macOS 코드서명 충돌 사례가 있어 끔.
- `datas=[('assets','assets')]` — 아이콘·지도·도시 좌표·AI 자산이 전부 여기로 실린다.
  `THIRD_PARTY_NOTICES.txt`도 번들 루트에 같이 실린다(라이선스 고지).

### 4-5. 아직 안 된 배포 작업 (유료/공개 배포 전 필수)

- [ ] **코드 서명**: Windows(Authenticode) 미서명 → SmartScreen 경고. macOS 미서명·미공증 →
      Gatekeeper가 "확인되지 않은 개발자"로 차단(우클릭 → 열기로만 실행). `PicMedic-mac.spec`의
      `codesign_identity`/`entitlements_file`이 `None`, 공증(notarytool) 단계 없음.
- [ ] **버전 번호 정리**: `CHANGELOG.md` 최신 섹션은 v1.2.0(2026-08-31)인데 그 뒤 정리 기능 전체·
      세션 자동 저장·리브랜딩 등이 CHANGELOG에 없다. `PicMedic-mac.spec`의
      `CFBundleShortVersionString`은 `1.0.0`으로 남아 있고, Windows exe엔 버전 리소스가 없다.
      코드 안에 `__version__` 같은 단일 버전 소스도 없음 → 다음 릴리즈 때 한 곳으로 모을 것.
- [ ] **THIRD_PARTY_NOTICES.txt 최종 검토**: 아직 "초안" 표기. 특히 **PySide6/Qt는 LGPLv3** —
      onedir(동적 링크, 사용자가 Qt 라이브러리 교체 가능)라 조건 충족에 유리하지만 배포 전 확인 필요.
- [ ] Windows 설치 프로그램(MSIX/Inno Setup 등) 없음 — 현재는 zip 배포 전제.
      MSIX 설치 시 설치 폴더가 읽기 전용이라 로그를 사용자 데이터 폴더에 쓰도록 이미 처리돼 있다.

## 5. 기능 현황 (2026-09-28)

**동작 중**: 검사(JPG/PNG/HEIC·HEIF/WEBP/GIF/TIFF/BMP) · 확장자 복원 · 형식 변환(화질 선택) ·
복구 후 재검증 · 여러 폴더 동시 검사(창 분리) · 검사 결과 자동 저장/증분 재검사 · 중복 파일 ·
유사 사진 · 날짜별 정리 · 도시별 정리(지도, 대한민국 시/도 경계 포함) · AI 카테고리 5종 ·
라이브 포토 찾기/내보내기 · 이름 일괄변환 · 임시 휴지통(복원 가능) · 도움말 팝업 · 중복 실행 방지.

**제거됨(되살리지 말 것, 2026-09-13)**: 화질 개선(Real-ESRGAN)·얼굴 복원·디블러·디노이즈,
사진 진단의 얼굴 탐지(facexlib). torch 의존성 제거가 목적이었다. 코드 주석과 `experiments/`,
`.gitignore`에 흔적이 남아 있는데 히스토리 설명일 뿐이다.

## 6. 문서 위치 — 저장소 vs Notion

- 저장소: `README.md`(설치·테스트·빌드), `DESIGN.md`(UI 가이드), `CHANGELOG.md`, `CLAUDE.md`(규칙),
  이 문서, `THIRD_PARTY_NOTICES.txt`, `PicMedic Product Requirements.pdf`(최초 PRD 원본).
- **Notion "PicMedic 기획문서"** (2026-09-17 이전): PRD v2, PRD MVP 우선순위, Phase2 사진정리 기획,
  웹/앱 확장 검토, 웹버전 기획, 복원 기능 퀄리티업 계획, 개인정보처리방침 초안.
- 코드 주석에 나오는 `PicMedic_PRD_v2.md`, `PRD_MVP우선순위.md`("갭 #N"), `RESTORATION_QUALITY_PLAN.md`,
  `PLATFORM_EXPANSION.md` 같은 **.md 파일은 저장소에 없다** — 모두 위 Notion 페이지로 옮겨진 문서다.
  링크가 깨졌다고 새로 만들지 말고 Notion에서 찾을 것.
- 개인정보처리방침 공개 페이지는 별도 저장소 **PicMedic-Web**(GitHub Pages)에 있다:
  `https://kmi0001.github.io/PicMedic-Web/privacy-policy.html` (`gui/home_screen.py`의 `PRIVACY_POLICY_URL`).

## 7. 작업 방식 / 주의사항 (지금까지의 관례)

1. **OS 분기 최소화**. 경로는 `pathlib`, 폴더 열기는 `QDesktopServices.openUrl`, 기본 폴더는
   `QStandardPaths`. 예외는 `utils/logger.py::_user_data_dir` 하나(core에 Qt를 들이지 않기 위해).
2. **`core/`에 PySide6 import 금지**. 백그라운드 작업은 `gui/scan_session_workers.py`의 QThread로.
3. **원본 불변**. 복구는 `Recovered/`에 새 파일, 정리의 삭제는 `임시휴지통/`으로 이동. 영구 삭제 경로를 만들지 않는다.
4. **UI**: 이모지 금지(QPainter 벡터 아이콘, `gui/icons.py`), 색은 `gui/theme.py`의 `COLORS`만,
   팝업은 `common_dialogs.py` 카드형, 모달은 `Qt.WindowModal`. 세부는 `DESIGN.md`.
5. **주석 스타일**: "왜 이렇게 했는지 + 날짜"를 한국어로 길게 남기는 것이 이 저장소 관례다(실측 수치 포함).
   결정을 바꿀 땐 옛 주석을 지우지 말고 날짜를 붙여 갱신.
6. **새 기능은 먼저 `experiments/<이름>_prototype/`에서 실측** → 수치를 근거로 본 코드에 반영하는 흐름.
7. **테스트는 Windows + macOS CI 둘 다 통과**해야 한다(`.github/workflows/tests.yml`).
   macOS에서만 재현된 버그(심볼릭 링크 순환 스캔)가 실제로 있었다.
8. **절대 커밋하지 않을 것**: 실제 개인 사진(`experiments/*/user_photos/` 등), 모델 가중치, `build/`·`dist/`.
9. 브랜치: 기본 `main`, AI 작업 브랜치는 `claude/*` 패턴(CI 트리거도 이 패턴 기준 — 다른 AI 도구를
   쓰면 브랜치 이름 규칙에 맞게 두 워크플로의 `branches:`를 같이 고칠 것).

## 8. 알려진 이슈 / 다음 할 일 후보

- 위 4-5의 배포 작업(서명·공증·버전·라이선스 검토).
- README "남은 항목": 예외 메시지 문구 정합화, 검색/정렬 범위 확장 등(상세는 Notion PRD MVP 우선순위).
- `scripts/fetch_photo_category_assets.py` 독스트링이 이미 없어진 `core/photo_category.py`를 언급(동작엔 영향 없음).
- Linux는 공식 지원 대상이 아니다(개발 컨테이너에서 테스트만 돈다).
