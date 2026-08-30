# PicMedic PRD — MVP 우선순위별 정리

> 원본: `PicMedic Product Requirements.pdf` (전체 36장)
> 이 문서는 원본 PRD의 내용을 그대로 유지하되, **"무엇을 먼저 만들어야 하는가"** 기준(PRD 35장 개발 우선순위: P0→P1→P2→P3)으로 재배열한 작업용 체크리스트입니다.
> 개발이 진행될 때마다 이 문서의 체크박스(`[ ]` → `[x]`)를 갱신해 진행 상황을 추적하세요.

**상태 범례**: ✅ 완료 · 🟡 부분 완료 · ⬜ 미구현

---

## 0. 제품 한 줄 정의 (36장)

> "사진 파일의 상태를 진단하고, 사용자가 안전하게 복구할 수 있도록 도와주는 사진 파일 진단·복구 도구"

**핵심 경험**: 선택한다 → 검사한다 → 문제를 알려준다 → 복구 방법을 제안한다 → 복구한다 → 결과를 검증한다.

**Product Principle**
- Diagnose before Recovery — 복구하기 전에 먼저 진단한다.
- Protect the Original — 원본은 기본적으로 변경하지 않는다.
- Verify the Result — 파일을 만들었다고 끝이 아니다, 실제로 정상 읽히는지 검증한다.
- Fail Safely — 문제가 발생해도 원본과 다른 파일에 영향을 주지 않는다.

**타깃 사용자** (4장): 사진 백업 중 파일 문제를 겪은 일반 사용자(Primary), 대량 사진을 관리하는 사용자(Secondary)

---

## P0 — 핵심 (완료)

### [x] FR-001 파일/폴더 선택 (6장)
- [x] 단일 파일 선택
- [x] **여러 파일 동시 선택** (다이얼로그 다중 선택, 드래그앤드롭 여러 개)
- [x] 폴더 선택
- [x] 하위 폴더 포함 검사
- [x] 드래그 앤 드롭
- [x] 지원하지 않는 파일은 자동 필터링
- [x] 폴더/파일 선택 시 **마지막 사용 위치(없으면 시스템 "사진" 폴더)** 기본 표시
- **지원 확장자**: `.jpg` `.jpeg` `.png` `.heic` `.heif` `.webp`(복구 변환 대상으로 승격) `.gif` `.tiff` `.tif` `.bmp`(PRD 37.6, 스캔·변환 대상 모두 포함)
- **구현 위치**: `gui/home_screen.py`, `core/scanner.py`
- **상태**: ✅ 완료

### [x] FR-002 파일 형식 탐지 (7장) / [x] FR-003 이미지 유효성 검사 (7장)
- **구현 위치**: `core/detector.py`, `core/analyzer.py`
- **테스트**: `test_detector.py` 10/10, `test_analyzer.py` 12/12
- **상태**: ✅ 완료

### [x] 파일 상태 분류 (8장) — **"복구 완료" 상태 추가됨**
- [x] 정상 / 형식 불일치 / 부분 손상 / 손상 / 지원되지 않는 형식 / 이미지가 아닌 파일
- [x] **복구 완료** (신규) — 복구가 성공한 파일은 상태가 자동으로 전환됨
- **구현 위치**: `models/file_info.py` (`FileStatus` Enum)
- **상태**: ✅ 완료

### [x] 결과 표시 — Screen 03 Scan Result (18장)
- [x] 요약 카드(총 파일/정상/형식불일치/부분손상/손상/**복구완료**)
- [x] 검사 결과 테이블 + **체크박스 선택 칸**
- [x] **헤더 체크박스로 전체선택/해제** (개별 체크·행 클릭 선택과 완전히 양방향 동기화)
- [x] **컬럼 클릭 정렬** (상태/파일명/실제형식/확장자)
- **구현 위치**: `gui/result_screen.py`
- **상태**: ✅ 완료

### [x] Screen 01 Home / Screen 02 Scanning (16~17장)
- [x] 폴더/파일 선택, 드래그앤드롭
- [x] **최근 검사 목록** — 완료/중단 여부와 처리 개수 표시, 더블클릭 시 재스캔 없이 **요약 팝업**으로 바로 확인 ("다시 검사" 버튼도 제공)
- [x] 진행률 바, 취소 버튼
- [x] **검사 중단 시**: 그때까지 결과를 결과 화면에 그대로 표시(예전엔 버려지고 홈으로 감 — 수정됨) + 배너 표시
- [x] **"이어서 검사"** — 중단된 지점부터 나머지 파일만 마저 스캔해 이전 결과와 자동 병합 (같은 세션 한정)
- [x] 검사 결과 파일이 0개면 "이미지 파일이 없습니다" 안내 후 홈으로 복귀
- **구현 위치**: `gui/home_screen.py`, `gui/scanning_screen.py`, `gui/main_window.py`
- **상태**: ✅ 완료 (PRD 원 범위를 넘는 UX 개선 다수 포함)

---

## P1 — 복구 (완료)

### [x] 원본 보호 / 복구 가능성 표시 / FR-004 복구 / 복구 결과 검증
- **상태**: ✅ 완료 (변경 없음, 기존과 동일)

### [x] 이미지 변환 (11장) — **JPEG 고정 → JPEG/PNG/WEBP/GIF/TIFF/BMP 선택 가능으로 일반화**
- [x] HEIC/HEIF → JPEG·PNG·WEBP·GIF·TIFF·BMP
- [x] PNG → JPEG (PRD 예시 충족) / **PNG → WEBP** (PRD 범위 밖, 웹 업로드용으로 추가)
- [x] **GIF/TIFF/BMP 스캔·변환 지원 추가** (PRD 37.6) — `core/detector.py`/`core/analyzer.py`의 하드코딩된 지원 형식 목록에 추가
- [x] 알파(투명) 채널: PNG/WEBP/TIFF는 유지, JPEG/GIF/BMP는 자동으로 RGB 변환 후 저장
- [x] **정상 파일을 변환해도 "복구 완료"로 잘못 표시되지 않음** — 복구(고장난 파일 수정)와 단순 변환을 구분
- [x] **품질(quality) 조절 UI 추가** — `gui/recovery_screen.py`에 고화질/보통/저용량 프리셋 콤보 (JPEG/WEBP일 때만 활성화)
- **구현 위치**: `core/converter.py::convert_to_format`, `gui/recovery_screen.py`
- **테스트**: `test_converter.py` 39/39 (PNG 알파 유지, WEBP/GIF/TIFF/BMP 변환, quality 적용 확인, 예외 메시지, 미지원 형식 처리 등 포함)
- **상태**: ✅ 완료 (품질 UI만 남음, 우선순위 낮음)

### [x] Screen 04/05/06 (19~21장) — **UX 개선**
- [x] 복구 방식(라디오)에 따라 화면 제목이 "사진 복구" / "사진 변환"으로 자동 전환
- [x] 시작 버튼은 **"Medic!"** 으로 통일 (복구/변환 어느 쪽이든)
- [x] "형식 변환" 선택 시 출력 형식(JPEG/PNG/WEBP) 드롭다운 노출
- [x] "원본 파일 유지" 체크박스 제거 → 작은 안내 문구로 대체 (원본은 항상 보존되므로 토글 자체가 무의미했음)
- [x] **파일명에 붙는 문구를 사용자가 직접 입력 가능** (기본값 `recovered`, 자유 수정, 특수문자 자동 제거)
- [x] 라디오/체크박스 시각 스타일 개선 (선택 시 링+점 표시로 명확하게)
- **상태**: ✅ 완료

---

## P2 — 사용성

### [x] FR-005 일괄 복구 (12장)
- [x] 다중 선택 (체크박스, 행 클릭과 동기화)
- [x] 상태별 복구
- [x] **전체 복구** — 헤더 체크박스로 전체 선택 후 일괄 복구 가능 (별도 원클릭 버튼 대신 이 방식으로 충족)
- [x] 진행률 표시
- [x] 실패 파일 별도 표시
- **상태**: ✅ 완료

### [x] 필터 (12장)
- [x] 전체 / 정상 / 형식 불일치 / 부분 손상 / 손상 / **복구 완료**(신규) / 복구 가능 / 지원안함·오류
- **상태**: ✅ 완료

### [x] 검색 (14장)
- [x] 파일명 검색
- [x] 확장자/실제 형식 검색 — `gui/result_screen.py::_apply_filters`에서 파일명뿐 아니라 확장자·실제 형식도 매칭
- **상태**: ✅ 완료

### [x] 정렬 (14장)
- [x] 파일명 / 상태 / 실제 형식 / 확장자 — 헤더 클릭으로 오름차순·내림차순
- [x] 파일 크기 / 수정 날짜 — "크기"/"수정일" 컬럼 추가, `_NumericSortItem`으로 문자열이 아닌 실제 값(바이트/타임스탬프) 기준 정렬
- **상태**: ✅ 완료

### [x] 미리보기 (13장) / 진행률 표시
- **상태**: ✅ 완료 (변경 없음)

### [x] FR-006 로그 (22장)
- **상태**: ✅ 완료 (변경 없음) — **PRD상 MVP 필수 항목 전부 충족**

---

## P3 — 확장 (Phase 2~4, MVP 범위 아님 — 아직 손대지 않음)

### Phase 2 — 사진 정리 (31장)
- [ ] 중복/유사 사진 탐지, 날짜·장소별 분류, EXIF 기반 정리, 자동 폴더 구성

### Phase 3 — AI 기능 (31, 32장)
- [ ] 사진 그룹화, 흐림/흔들림/눈감음 탐지, 스크린샷 자동 분류, AI 진단

### Phase 4 — 고급 복구 (31장)
- [ ] 부분 손상 JPEG 복구, Thumbnail 추출, EXIF 복구, RAW 분석, 복구 가능성 점수화

### MVP에서 명시적으로 제외 (30장)
AI 이미지 복원, 얼굴 인식, 이미지 내용 분석, 자동 사진 분류, 클라우드 연동, RAW 복구, 삭제된 파일 복구, 디스크 섹터 단위 복구, 전문 데이터 복구 기능

---

## 🔴 남은 갭

### ~~1. 복구 완료 상태가 Scan Result에 반영되지 않음~~ → ✅ 해결됨
`FileStatus.RECOVERED` 추가, 복구 성공 시 자동 반영, 필터·요약카드에도 반영. (단, 원래 "정상"이던 파일을 변환한 경우는 상태를 바꾸지 않음 — 복구가 아니라 단순 변환이므로.)

### ~~2. PRD 23장 예외 처리 문구/동작 불일치~~ → ✅ 해결됨
| PRD 요구 | 현재 상태 |
|---|---|
| 23.1 권한 없음 → "이 파일에 접근할 수 없습니다." | ✅ `core/converter.py::_classify_os_error`로 `PermissionError` 분류 |
| 23.3 파일 잠금 → "다른 프로그램에서 사용 중인 파일입니다." | ✅ Windows `winerror=32`(ERROR_SHARING_VIOLATION) 분류 |
| 23.5 저장 공간 부족 → 이후 작업 중단, 기존 성공분 유지 | ✅ `winerror=112`/`errno.ENOSPC` 감지 시 `RecoveryOutcome.abort_batch=True` → `recover_batch`가 그 즉시 루프 중단 (이미 처리된 파일은 그대로 유지) |
| 23.2 / 23.4 / 23.6 / 23.7 / 23.8 | ✅ 충족 (변경 없음) |

`tests/test_converter.py`에 `shutil.copy2`를 모킹해 세 시나리오(권한/잠금/저장공간)와 배치 중단 동작까지 회귀 테스트 추가 (27개 전부 PASS).

### 3. (신규, 참고용) "이어서 검사"는 같은 세션 안에서만 동작
앱을 껐다 켜면 이어서 검사 정보가 사라져 처음부터 다시 스캔해야 함. 앱 재시작 후에도 이어가려면 스캔 결과 전체를 파일로 저장해야 해서 별도로 논의 필요(범위가 커짐).

### ~~4. [버그] 부분 손상 파일 복구가 항상 실패함~~ → ✅ 해결됨
`core/converter.py::convert_to_format`에도 `core/analyzer.py`와 동일하게 `ImageFile.LOAD_TRUNCATED_IMAGES = True`를 (try/finally로 전역 플래그를 되돌리는 방식으로) 적용해, 분석 단계에서 "부분_손상/부분_복구_가능"으로 판정된 파일이 실제 변환 시도에서도 실패하지 않도록 고쳤다. `test_samples/09_손상_부분손상/partial_broken_1.jpg`로 직접 검증했고, `tests/test_converter.py`에 합성 잘림 파일로 회귀 테스트를 추가했다 (기존 19개 + 신규 2개 = 21개 전부 PASS).

### ~~5. [UX 개선] 완전 손상 파일 선택 시 강조 부족~~ → ✅ 해결됨
`gui/result_screen.py`에서 `info.recoverable == RecoveryPossibility.NOT_RECOVERABLE`인 행은 체크박스를 비활성화(`Qt.ItemIsEnabled` 제거)하고 "복구할 수 없는 파일입니다." 툴팁을 달았다. 헤더 "전체 선택"이나 행 클릭 등 다른 경로로도 체크 상태가 되지 않도록 `_selected_files`/`_on_selection_changed`/`_set_all_checked`에 안전장치를 추가했다. `tests/test_result_screen.py`로 회귀 테스트 추가(5개 PASS).

### ~~6. [버그, macOS에서 재현] 폴더 재귀 스캔이 심볼릭 링크 순환에서 무한 루프 + 취소 안 됨~~ → ✅ 해결됨
`core/scanner.py::iter_candidate_files`가 `Path.glob("**/*")`로 재귀 스캔하던 걸 `os.walk(followlinks=True)` 기반으로 바꾸고, 방문한 디렉터리의 실제 경로(`resolve()`)를 추적해 이미 방문한 곳은 `dirnames`에서 제거하는 방식으로 순환을 차단했다. 또한 `iter_candidate_files`/`scan_paths`에도 `should_cancel`을 전달해, 파일 목록을 모으는 단계(예전엔 취소를 체크할 지점 자체가 없던 곳)에서도 즉시 중단되도록 고쳤다. `tests/test_scanner.py`에 실제 순환 디렉터리(윈도우 junction)로 회귀 테스트 추가.

### ~~7. [버그, 실사용 재현] 대량 스캔 결과에서 전체선택/해제 시 응답 없음~~ → ✅ 해결됨
16,965장 스캔 후 검사 결과 화면에서 헤더 "전체 선택"을 누르고 다시 해제하니 각각 7~10초씩 걸리며 "응답 없음"이 뜸. 원인 두 가지:
1. `_set_all_checked`가 체크박스를 다 갱신한 뒤 `selectAll()`/`clearSelection()`을 부르면 Qt의 `selectionChanged`가 다시 발생해 `_on_selection_changed`가 방금 한 것과 같은 O(행 수) 루프를 또 한 번 돌림 (재진입 가드 `_syncing`이 이 경로에만 빠져 있었음).
2. **더 큰 원인**: 테이블 정렬(`setSortingEnabled(True)`)이 켜진 채로 수만 번 `setCheckState`/`selectAll`/`clearSelection`을 부르면 Qt가 매번 재정렬 여부를 검토해 기하급수적으로 느려짐 — 실측 결과 정렬을 잠깐 꺼두는 것만으로 6.7초 → 0.19초로 단축됨.

`_set_all_checked`/`_on_selection_changed`에 `setSortingEnabled(False)`+`setUpdatesEnabled(False)`+`_syncing` 가드를 모두 적용. `tests/test_result_screen.py`에 5,000행 규모 회귀 테스트 추가(3초 제한, 실측 0.1~0.2초).

---

## 부록 A — 비기능 요구사항 (24장)
- 성능 / 안정성 / 안전성: ✅ 충족 (변경 없음)
- 사용성: 🟡 갭 #2(예외 메시지) 제외하면 대부분 충족, 오히려 PRD 이상으로 개선된 부분 다수(취소·재개, 최근 검사 요약, 상태 동기화 등)

## 부록 B — 기술 구성 (25장)
- Application: Python / GUI: PySide6 / Image: Pillow + pillow-heif / File Analysis: Signature·MIME·디코딩 검증
- Logger 포함 Application Core 전 구성요소 구현 완료
- **exe 배포**: PyInstaller로 단일 실행 파일(`dist/PicMedic.exe`) 빌드 가능 (README 참고)

## 부록 C — 데이터 모델 (27장)
- `FileInfo`: 기존 필드 + `status`에 `RECOVERED` 값 추가
- `ScanResult`: 기존 필드 + `recovered` 카운터, `merge()`(이어서 검사 결과 병합), `mark_recovered()` 추가

## 부록 D — KPI (33장) / 품질 검증 (34장)
- 로그(`logs/picmedic_log.jsonl`)에 스캔/복구 결과가 다 쌓이므로 KPI 집계는 로그 분석 스크립트만 추가하면 가능
- 테스트: `test_detector.py`(19) + `test_analyzer.py`(17) + `test_converter.py`(39) + `test_logger.py`(14) + `test_scanner.py`(1~5, 심볼릭 링크 권한에 따라) + `test_result_screen.py`(5) = **총 95~99개, 전부 PASS**

---

## 다음 액션 제안 (우선순위 순)

1. ~~**[갭 #6, 버그, 최우선] 심볼릭 링크 순환 시 스캔 무한 루프 + 취소 불가 수정**~~ → ✅ 해결됨
2. ~~**[갭 #4, 버그] 부분 손상 파일 복구 안 되는 문제 수정**~~ → ✅ 해결됨
3. ~~**[갭 #2] 예외 메시지 PRD 문구 정합화**~~ → ✅ 해결됨
4. ~~**[갭 #5, UX] 완전 손상 파일 체크박스 비활성화/경고 강조**~~ → ✅ 해결됨
5. ~~**[P2 마무리] 확장자/형식 검색 확장, 파일 크기·날짜 컬럼 추가 후 정렬 지원**~~ → ✅ 해결됨
6. ~~**변환 품질(quality) 조절 UI 노출**~~ → ✅ 해결됨
7. ~~**추가 포맷 지원 (GIF/TIFF/BMP)**~~ → ✅ 해결됨
8. **[P3] Phase 2 이후** — 이 문서의 P3 섹션 참고, MVP 완결 후 착수
