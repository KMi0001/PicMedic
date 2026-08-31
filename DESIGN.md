# PicMedic 디자인 가이드

UI 스타일/컴포넌트 관련 결정을 기록하는 문서. 코드 값 자체(색상 hex 등)의 기준은
언제나 [gui/theme.py](gui/theme.py)이며, 이 문서는 그 값을 왜 이렇게 정했고 어디에
써야 하는지를 설명한다. 새로운 화면/팝업/아이콘을 추가할 때 참고하고, 디자인 방향이
바뀌면 이 문서도 같이 갱신할 것.

## 색상 팔레트

기준: [gui/theme.py](gui/theme.py)의 `COLORS`. "민트 케어" 톤 — 의료/케어 앱 느낌을
주기 위해 차갑지 않은 민트-그린을 primary로 쓴다.

| 이름 | 값 | 용도 |
|---|---|---|
| `primary` | `#12B5A6` | 브랜드 색, 주요 버튼, 안내/확인 아이콘 |
| `success` | `#2FAF66` | 성공 상태 (정상, 복구 완료) |
| `warning` | `#D9A441` | 주의 필요 (부분 손상, 형식 불일치) |
| `danger` | `#DA5A5A` | 오류/실패 (손상, 복구 실패) |
| `muted` | `#8FAFA0` | 중립/제외 (건너뜀, 지원 안 함) |

## 아이콘 시스템

**원칙: 이모지 폰트를 쓰지 않는다.** Windows/macOS에서 컬러 이모지 렌더링이 서로 달라
같은 아이콘이 OS마다 다르게 보이는 문제를 피하기 위해, 항상 `QPainter`로 직접 그린
벡터 아이콘을 쓴다 — **색이 있는 원 배경 + 흰색 글리프**.

기준 구현: [gui/home_screen.py:141](gui/home_screen.py:141) `_status_icon_pixmap`
(최근 검사 목록에서 사용). 원 24px 기준으로 안쪽 글리프는 13px 비율(`13/24`)로
중앙 정렬한다 — 새 아이콘을 추가할 때도 이 비율을 유지할 것.

| 종류 | 색 | 의미 | 사용 예 |
|---|---|---|---|
| 성공 (체크) | `success` | 완료 | 최근 검사 카드, 결과 요약 |
| 경고 (삼각형 `!`) | `warning` | 주의 필요 | 최근 검사 카드(중단/부분 손상) |
| 오류 (X) | `danger` | 실패 | 복구 실패 안내 (아직 미적용, 필요 시 추가) |
| 확인 필요 (`?`) | `primary` | 진행 여부를 물음 | [gui/recovery_screen.py](gui/recovery_screen.py) `_question_icon_pixmap` — 정상 파일 건너뛰기 확인 팝업 |
| 안내 (`i`) | `primary` | 단순 정보 전달 | 아직 미적용 |
| 건너뜀 (`-`) | `muted` | 처리 대상 제외 | 아직 미적용 |

성공/경고는 `_status_icon_pixmap`, 확인 필요는 `_confirm_dialog`용
`_question_icon_pixmap`처럼 **화면별로 필요한 것만 로컬 함수로 둔다** — 아직 2곳
이상에서 같은 걸 재사용하지 않는 한 공용 모듈로 미리 뽑아두지 않는다. 오류/안내/건너뜀
아이콘을 실제로 쓰는 곳이 생기면 그때 같은 패턴으로 추가.

## 섹션 헤더 강조

카드(`QFrame#Card`) 안에 여러 설정 묶음이 있을 때, 각 묶음의 제목(예: "복구 방식",
"저장 위치")은 본문(라디오 버튼, 입력창 등)과 시각적으로 구분돼야 한다. 일반 텍스트와
같은 굵기의 `text_secondary` 색만으로는 눈에 잘 안 띈다.

기준 구현: [gui/recovery_screen.py](gui/recovery_screen.py) `SECTION_HEADER_STYLE`
— 진한 글씨(`font-weight: 700`) + `color: text`(muted 아님) + 왼쪽 3px `primary`색
accent bar(`border-left`) + `padding-left: 8px`. 카드 안의 최상위 섹션 제목에만
적용하고, "화질"처럼 다른 컨트롤과 한 줄에 나란히 붙는 보조 라벨에는 적용하지 않는다
(줄 하나짜리 라벨에 accent bar를 붙이면 구분선처럼 보여 어색해진다).

## 상태 요약 카드 (SummaryChip)

여러 파일을 다루는 화면에서 "그 중 상태별로 몇 개씩인지"를 한눈에 보여줄 때 쓰는
카드형 위젯. 기준 구현: [gui/result_screen.py](gui/result_screen.py) `SummaryChip`
(검사 결과 화면에서 최초 도입) — 위: 큰 숫자(20px, bold, 상태 색), 아래: 작은 라벨.
[gui/recovery_screen.py](gui/recovery_screen.py)의 복구/변환 화면에서도 그대로
재사용해서 "선택 파일 중 상태별 개수"를 보여준다 — 같은 위젯을 화면마다 새로 만들지
않고 import해서 쓴다.

- **고정 폭 + 내부 중앙 정렬**: `CHIP_WIDTH = 96`(px)으로 고정한다. "정상"처럼 짧은
  라벨과 "형식 불일치"처럼 긴 라벨이 섞이면 폭이 들쭉날쭉해 보이므로, 항상 같은 폭에
  라벨은 `setWordWrap(True)`로 필요하면 두 줄까지 접는다. 숫자/라벨 둘 다
  `setAlignment(Qt.AlignCenter)`로 카드 안에서 가운데 정렬 — 왼쪽 정렬로 두면 짧은
  숫자만 왼쪽에 붙어 카드마다 시작 위치가 달라 보인다.
- **개수 0인 항목은 숨긴다**: 선택된 파일에 실제로 없는 상태의 칩은
  `chip.setVisible(count > 0)`으로 감춘다 (검사 결과 화면처럼 전체 상태를 항상 다
  보여줘야 하는 경우는 예외 — 그때는 0도 그대로 보여줌).
- **가운데 정렬**: 칩 묶음이 있는 `QHBoxLayout` 앞뒤에 `addStretch(1)`을 둘 다 넣어서,
  칩이 몇 개든 카드 폭 기준 가운데에 오게 한다(칩 개수에 따라 좌우 빈 공간이 균등하게
  분배됨).
- **클릭 가능한 카드 (선택적)**: `SummaryChip(..., clickable=True)`로 만들면 카드 자체가
  버튼처럼 동작한다 — 손 커서 + 호버 시 테두리가 `primary`색으로 바뀌고(`QFrame#Card[clickable="true"]:hover`,
  [gui/theme.py](gui/theme.py)), 누르면 `clicked` 시그널을 낸다. 기준 구현:
  [gui/recovery_result_screen.py](gui/recovery_result_screen.py) — "복구 완료" 화면에서
  "성공/건너뜀/실패 파일 보기" 버튼을 따로 두지 않고, 카드를 직접 눌러 해당 상태의
  파일 목록 팝업을 연다. 기본값은 `False`라서 검사 결과/복구 화면처럼 그냥 정보만
  보여주면 되는 곳은 지금처럼 손대지 않아도 그대로 동작한다.

## 팝업/다이얼로그 패턴

네이티브 `QMessageBox`는 OS 기본 스타일이라 앱 테마(민트 톤, 둥근 카드)와 겉돈다.
**확인이 필요한 팝업은 `QMessageBox` 대신 `QDialog` 기반 커스텀 컴포넌트를 쓴다.**

기준 구현: [gui/recovery_screen.py](gui/recovery_screen.py) `_confirm_dialog(parent, message, confirm_text="확인", cancel_text="취소")`.
- 왼쪽: 상황에 맞는 원형 아이콘 (위 아이콘 시스템 표 참고)
- 오른쪽: 메시지 + 버튼 행(취소 역할 / 확인 역할)
- 확인 쪽 버튼은 `objectName="Primary"` + `setDefault(True)` — [gui/theme.py](gui/theme.py)의
  `QPushButton#Primary` QSS를 그대로 상속받는다 (다이얼로그에 별도 스타일시트를 설정하지
  않아도 `main_window.py`에서 앱 전체에 건 `APP_STYLESHEET`가 자식 위젯까지 적용됨 —
  기존 "최근 검사 결과" 팝업[gui/home_screen.py:401](gui/home_screen.py:401)과 동일한 방식).
- 반환값: `bool` (확인 쪽=True, 취소/닫기=False) — 호출부는 `if not confirmed: return`으로
  진행을 막는다.
- **버튼 문구는 상황에 맞게 바꿔 쓴다** — "확인"/"취소"가 항상 맞는 건 아니다. 예:
  복구 취소 후 "복구된 파일을 유지하시겠습니까?"에는 `confirm_text="유지",
  cancel_text="삭제"`를 써서, 더 안전한 선택지(유지)가 항상 Primary+기본 버튼 자리에
  오게 한다 — 파괴적인 선택지(삭제)를 기본값으로 두지 않는다.

새로운 확인 팝업이 필요하면 `_confirm_dialog`와 같은 패턴(아이콘 + 메시지 + 취소/확인)을
그대로 따르고, 화면 간에 완전히 동일한 요구가 2번째로 생기면 그때 공용 컴포넌트로 옮긴다.

**모달 범위는 항상 `Qt.WindowModal`로 지정한다, `setModal(True)`/기본 `exec()`가 주는
`Qt.ApplicationModal`을 쓰지 않는다.** 검사 세션마다 독립된 창([gui/scan_session_window.py](gui/scan_session_window.py)
참고)이 여러 개 동시에 뜰 수 있어서, ApplicationModal 팝업 하나가 앱 전체를 막아버리면
다른 세션 창까지 조작 불가능해진다 — `_confirm_dialog`/`_ProgressDialog`/최근 검사
팝업/목록 팝업 전부 `dialog.setWindowModality(Qt.WindowModal)`을 명시해서 자기 창(부모
체인)만 막도록 되어 있다.

## 진행 상황 팝업 (모달)

여러 파일을 순차 처리하는 배치 작업(복구/변환)의 진행 상황은 화면에 인라인으로
박아두지 않고 **모달 `QDialog`** 로 띄운다. 기준 구현:
[gui/recovery_screen.py](gui/recovery_screen.py) `_ProgressDialog` +
`_start_recovery`.

- 왜 인라인이 아니라 모달인가: 인라인 진행 바만 쓰면 작업 중에도 모드 라디오·형식/화질·
  저장 위치·"← 뒤로" 등 나머지 설정을 계속 건드릴 수 있어 혼란스럽다
  (`PRD_MVP우선순위.md` 갭 #9). 컨트롤을 하나하나 `setEnabled(False)`로 잠그는 대신,
  `setModal(True)` + `exec()`로 띄운 팝업 하나가 화면 전체 입력을 자동으로 막아준다.
- **창 닫기(X) 버튼 없음, 취소는 전용 버튼으로만**: `Qt.WindowCloseButtonHint`를 제거해서
  타이틀바 X로 슬쩍 닫아버리는 걸 막는다. 취소는 팝업 안의 "취소" 버튼(`cancel_btn`,
  `objectName="Danger"`)을 통해서만 — 누르면 `cancel_requested` 시그널을 내보내고,
  `RecoveryWorker.cancel()`이 플래그를 세워 `core/converter.py::recover_batch`가
  `should_cancel` 콜백(`core/scanner.py::scan_paths`와 같은 방식)으로 다음 파일로
  넘어가기 전에 멈춘다 — 처리 중이던 파일은 끝까지 마친다. 버튼은 클릭 즉시
  `setEnabled(False)` + "취소하는 중..."으로 바꿔 중복 클릭을 막는다.
- **취소 후: 유지/삭제 확인**: 배치가 멈추면 위 `_confirm_dialog`를
  `confirm_text="유지", cancel_text="삭제"`로 띄운다. 유지를 고르면 그때까지의
  결과로 평소처럼 `recovery_finished`를 emit해 결과 화면으로 넘어가고, 삭제를 고르면
  `outcome.success`인 항목의 `output_path`를 지우고 결과 화면으로 넘어가지 않고 설정
  화면에 남는다(원본은 애초에 건드리지 않으므로 안전). 개별 파일 삭제 실패(권한 등)는
  조용히 넘어간다 — 정리 작업 하나 실패했다고 취소 자체를 막을 이유가 없다.
- **`exec()`는 안전하다**: 모달 다이얼로그를 `exec()`로 띄운 채로 있어도, `QThread`
  워커의 `progress`/`finished_batch` 시그널은 중첩 이벤트 루프 안에서 정상적으로
  전달된다 — 워커를 `start()`한 직후 곧바로 `dialog.exec()`를 호출해도 진행률 갱신이
  끊기지 않는다. 작업이 끝나면 `finished_batch` 핸들러에서 `dialog.accept()`를 호출해
  팝업을 닫고 `exec()` 호출부로 제어를 돌려준다. 실제로 200개 배치를 취소해서
  중첩 루프 안에서도 취소 버튼 클릭과 후속 유지/삭제 다이얼로그가 정상 동작함을
  확인함(부분 처리 결과 개수가 총 파일 수보다 작게 나옴, 삭제 시 출력 파일 0개).

## 다중 창 구조 (검사 세션)

`gui/main_window.py`의 `MainWindow`는 홈 화면 하나만 상주시킨다. 파일/폴더를 선택할
때마다 검사~복구 전체 흐름(검사 진행 → 검사 결과 → 상세 → 복구 → 복구 결과)을
[gui/scan_session_window.py](gui/scan_session_window.py) `ScanSessionWindow`라는
독립된 창으로 새로 띄운다 — 몇 개든 동시에 진행 가능(PRD_MVP우선순위.md 갭 #10).

- **세션 창 = `QWidget` + `Qt.Window` 플래그, 부모는 `MainWindow`.** 부모가 있어서
  `APP_STYLESHEET`를 그대로 물려받으면서도(별도로 스타일시트를 설정할 필요 없음),
  `Qt.Window` 플래그 덕분에 독립된 최상위 창(제목표시줄 + 자체 닫기 버튼)으로 뜬다.
- **살아있는 세션은 `MainWindow._sessions` 리스트로 붙잡아둔다.** 파이썬 참조가
  하나도 안 남으면 스캔/복구 워커가 도는 중에도 창이 GC될 수 있다
  (`QThread: Destroyed while thread is still running`로 죽음) — 세션이 끝나
  `closed` 시그널을 낼 때만 리스트에서 지운다.
- **`closeEvent`에서 워커가 도는 중이면 닫기를 막는다** — `ScanningScreen.worker`/
  `RecoveryScreen.worker`의 `isRunning()`을 확인해서, 취소 버튼으로 스레드가 실제로
  끝난 뒤에만 창이 닫히게 한다.
- **"최근 검사" 목록(`HomeScreen`)만 세션과 무관하게 전역 공유.** `ScanSessionWindow`
  생성자에 `home_screen` 인스턴스를 그대로 넘겨받아 `record_scan_outcome`/
  `record_recovery_outcome`을 호출한다 — 그 외 화면(`ResultScreen`, `DetailScreen`,
  `RecoveryScreen`, `RecoveryResultScreen`)은 세션마다 새로 만드는 인스턴스라 서로
  상태가 섞이지 않는다.
- 새 화면을 이 흐름에 추가할 때도 이 패턴을 따른다 — 화면 클래스 자체는 지금처럼
  상태 없이(`set_x()`로 데이터를 주입받는) 만들고, "어디서 생성되고 어떻게 연결되는지"만
  세션 단위로 관리한다.

## 폼 컨트롤 — QComboBox

기본 `QComboBox`는 OS 네이티브 드롭다운 화살표라 카드/버튼의 민트 톤과 겉돌고
투박해 보인다. [gui/theme.py](gui/theme.py) `APP_STYLESHEET`에서 전역으로
`QComboBox::drop-down`을 `primary` 색 둥근 버튼(20px, 4px 여백, radius 5px)으로,
그 안의 화살표는 흰색 삼각형 아이콘으로 바꿔서 통일했다. 펼침 목록
(`QComboBox QAbstractItemView`)도 흰 배경 + 둥근 테두리 + 선택 시 `selection`색
하이라이트로 카드 스타일을 맞췄다.

**화살표 아이콘은 반드시 실제 파일 에셋으로 참조한다** —
[assets/combo_arrow.png](assets/combo_arrow.png) (12px 흰색 삼각형, `utils.assets.asset_path()`로
경로를 구함, 기존 `icon.png` 아이콘과 동일한 방식). `QComboBox::down-arrow { image: url(...) }`에
`data:` URI(base64 인라인)를 직접 넣는 방법은 시도해봤지만 Qt 스타일시트가 `url()`에서
data URI를 지원하지 않아 렌더링되지 않는다(빈 사각형만 보임) — 이미지가 필요한 QSS
아이콘은 항상 `assets/`에 실제 파일로 두고 참조할 것.

전역 스타일이라 이 컴포넌트를 쓰는 화면(사진 복구/변환의 형식·화질 선택, 검사 결과의
필터 드롭다운 등) 전부에 자동 적용된다 — 화면마다 따로 스타일을 줄 필요 없음.

## 폰트

OS별 한글 폰트 폴백은 [CLAUDE.md](CLAUDE.md)의 크로스플랫폼 체크리스트와
[gui/theme.py](gui/theme.py) `font-family` 목록 참고. 새 폰트를 쓸 때는 Windows/macOS
양쪽에 실제로 설치돼 있는지 확인 후 추가.
