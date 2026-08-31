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

## 팝업/다이얼로그 패턴

네이티브 `QMessageBox`는 OS 기본 스타일이라 앱 테마(민트 톤, 둥근 카드)와 겉돈다.
**확인이 필요한 팝업은 `QMessageBox` 대신 `QDialog` 기반 커스텀 컴포넌트를 쓴다.**

기준 구현: [gui/recovery_screen.py](gui/recovery_screen.py) `_confirm_dialog(parent, message)`.
- 왼쪽: 상황에 맞는 원형 아이콘 (위 아이콘 시스템 표 참고)
- 오른쪽: 메시지 + 버튼 행(취소 / 확인)
- 확인 버튼은 `objectName="Primary"` + `setDefault(True)` — [gui/theme.py](gui/theme.py)의
  `QPushButton#Primary` QSS를 그대로 상속받는다 (다이얼로그에 별도 스타일시트를 설정하지
  않아도 `main_window.py`에서 앱 전체에 건 `APP_STYLESHEET`가 자식 위젯까지 적용됨 —
  기존 "최근 검사 결과" 팝업[gui/home_screen.py:401](gui/home_screen.py:401)과 동일한 방식).
- 반환값: `bool` (확인=True, 취소/닫기=False) — 호출부는 `if not confirmed: return`으로
  진행을 막는다.

새로운 확인 팝업이 필요하면 `_confirm_dialog`와 같은 패턴(아이콘 + 메시지 + 취소/확인)을
그대로 따르고, 화면 간에 완전히 동일한 요구가 2번째로 생기면 그때 공용 컴포넌트로 옮긴다.

## 폰트

OS별 한글 폰트 폴백은 [CLAUDE.md](CLAUDE.md)의 크로스플랫폼 체크리스트와
[gui/theme.py](gui/theme.py) `font-family` 목록 참고. 새 폰트를 쓸 때는 Windows/macOS
양쪽에 실제로 설치돼 있는지 확인 후 추가.
