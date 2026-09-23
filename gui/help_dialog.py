"""
gui/help_dialog.py

홈 화면 헤더의 "?" 버튼으로 여는 사용 안내 팝업 — "특별한 점 / 사용방법 / 활용법 / Q&A"
4개 탭. 내용은 아래 _HIGHLIGHTS / _USAGE_STEPS / _TIPS / _FAQ 데이터에만 있고, 화면은 그걸 카드로
풀어 그릴 뿐이라 문구를 고칠 때 레이아웃 코드를 건드릴 필요가 없다.

글자가 잘리지 않도록 모든 문구는 줄바꿈(word wrap) 라벨로 두고 카드가 내용에
맞춰 늘어나게 했다(고정 높이 없음, 넘치면 탭 안 스크롤).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from gui.theme import COLORS

# (제목, 설명) — 첫 탭. 2026-09-23 사용자 요청으로 셀링포인트를 전면에 둠:
# "오프라인 AI + 원본 안전"이 메인, "아이폰 사용자"가 타깃. 여기 적는 약속은
# 코드가 실제로 지키는 것만 쓴다(네트워크 요청 없음 — core/geocoder.py·
# core/image_embedding_cache.py, 정리 삭제는 utils/trash.py 임시휴지통 이동).
_HIGHLIGHTS: list[tuple[str, str]] = [
    (
        "사진은 한 장도 인터넷으로 나가지 않아요",
        "AI가 사진 내용을 보고 동물·음식·풍경을 찾아주고, GPS로 어느 도시에서 찍었는지도 "
        "알려주지만 이 모든 게 내 컴퓨터 안에서만 처리돼요. 서버에 올리지 않으니 가족사진, "
        "신분증 사진도 안심하고 맡기세요. 인터넷이 끊겨 있어도 똑같이 동작해요.",
    ),
    (
        "실수해도 되돌릴 수 있어요",
        "복구한 사진은 원본을 그대로 둔 채 'Recovered' 폴더에 새 파일로 만들어지고, 날짜·도시별 정리는 기본이 '복사'예요. "
        "중복·유사 사진을 지워도 완전히 삭제되지 않고 '임시 휴지통'으로 옮겨질 뿐이라, "
        "언제든 원래 자리로 되돌릴 수 있어요.",
    ),
    (
        "확장자가 아니라 파일 속을 들여다봐요",
        "안 열리는 사진, 사실은 이름표(확장자)만 잘못 붙은 경우가 많아요. PicMedic은 파일 "
        "안쪽의 실제 형식을 직접 읽어서 무엇이 문제인지 진단하고, 확장자 복원으로 대부분 바로 고쳐요.",
    ),
    (
        "아이폰 사진을 PC로 옮겼다면 딱이에요",
        "윈도우에서 안 열리는 HEIC는 JPG로 한 번에 바꾸고, 라이브 포토의 짝 동영상은 찾아서 "
        "영상으로 꺼내고, 카카오톡·백업으로 여기저기 생긴 중복 사진은 한꺼번에 정리해요.",
    ),
    (
        "수만 장도 이어서 정리해요",
        "검사 결과와 AI 분류는 창을 닫을 때 자동 저장돼요. 같은 폴더를 다시 열면 처음부터 "
        "다시 하지 않고, 새로 들어오거나 바뀐 사진만 확인해요.",
    ),
]

# (제목, 설명)
_USAGE_STEPS: list[tuple[str, str]] = [
    (
        "사진 올리기",
        "홈 화면의 '사진 · 폴더' 영역에 사진이나 폴더를 끌어다 놓거나, 영역을 클릭해서 "
        "'파일 선택' 또는 '폴더 선택'을 고르세요. 폴더를 고르면 안에 들어있는 하위 폴더까지 "
        "한꺼번에 검사해요.",
    ),
    (
        "검사 기다리기",
        "진행률이 표시되고, 중간에 취소할 수도 있어요. 폴더를 하나 더 올리면 새 창이 열려서 "
        "여러 폴더를 동시에 검사할 수 있어요. HEIC 사진이 많으면 시간이 더 걸릴 수 있어요.",
    ),
    (
        "검사 결과 확인",
        "정상 · 형식 불일치 · 부분 손상 · 손상 개수를 한눈에 볼 수 있어요. 위쪽 요약 카드를 "
        "누르면 그 상태의 사진만 골라 보여주고, 목록에서 사진을 더블클릭하면 미리보기와 "
        "자세한 정보가 열려요.",
    ),
    (
        "복구하기",
        "복구할 사진을 목록에서 선택하고 '확장자 변환'을 누르세요. 확장자만 바로잡거나 다른 "
        "형식으로 변환할 수 있고, 기본 설정에선 원본은 그대로 둔 채 'Recovered' 폴더에 새 파일이 "
        "만들어져요. "
        "끝나면 결과를 자동으로 다시 검사해서 성공·건너뜀·실패를 알려줘요.",
    ),
    (
        "정리하기",
        "검사 결과 화면 아래쪽 '정리' 카드에서 중복 파일, 유사 사진, 날짜별, 도시별, "
        "카테고리(동물·음식·스크린샷·야경·풍경) 정리를 시작할 수 있어요. 어떤 정리든 먼저 "
        "미리보기를 보여주고, 직접 실행 버튼을 눌러야만 파일이 움직여요.",
    ),
]

# (제목, 설명) — 홈 화면의 다른 카드와 상황별 활용 팁
_TIPS: list[tuple[str, str]] = [
    (
        "아이폰에서 옮긴 사진을 정리할 때",
        "HEIC라서 안 열리는 사진은 홈의 '변환' 카드에 끌어놓으면 JPG로 바로 바뀌어요. 짝 동영상이 "
        "같이 넘어왔다면 '라이브 포토' 카드로 움직이는 사진을 영상으로 꺼낼 수 있고, 여러 번 "
        "백업하다 쌓인 중복 사진은 폴더를 검사한 뒤 '중복 파일' 정리로 한 번에 비울 수 있어요.",
    ),
    (
        "저장 공간이 부족할 때",
        "'중복 파일'은 완전히 똑같은 사진을, '유사 사진'은 크기를 줄였거나 다시 저장해서 "
        "약간 달라진 사진을 찾아줘요. 그룹마다 남길 사진을 고르면 나머지는 삭제되지 않고 "
        "'임시 휴지통'으로 옮겨져요. 유사 사진은 추정이라서 썸네일을 직접 보고 고르세요.",
    ),
    (
        "여행·행사 사진을 폴더로 정리하고 싶을 때",
        "'날짜별'은 촬영일 기준으로, '도시별'은 GPS 위치를 기준으로 사진을 묶어요. 지도에서 "
        "훑어본 뒤 '정리하기'를 누르면 복사하거나 이동할 수 있어요. 위치 정보가 없는 사진은 "
        "'위치없음' 폴더로 모여요.",
    ),
    (
        "특정한 사진만 모아보고 싶을 때",
        "카테고리 카드(동물친구들, 음식 사진, 스크린샷/문서, 야경 사진, 풍경 사진)는 AI가 "
        "사진 내용을 보고 찾아줘요. 처음엔 시간이 걸리지만, 작업 내용은 창을 닫을 때 자동 저장돼서 "
        "같은 폴더를 다시 열면 바뀐 사진만 새로 분석해요. 잘못 분류된 사진은 우클릭 → "
        "'다른 카테고리로 옮기기'로 고칠 수 있어요.",
    ),
    (
        "파일이 안 열리거나 확장자가 이상할 때",
        "'형식 불일치'는 내용은 멀쩡한데 확장자만 틀린 사진이에요. 확장자 복원으로 대부분 바로 "
        "고쳐져요. 사진 형식 자체를 바꾸고 싶다면(예: HEIC → JPG) 홈의 '변환' 카드를 쓰세요. "
        "검사 없이 곧장 변환할 수 있고 여러 장도 한 번에 돼요.",
    ),
    (
        "파일 이름을 통일하고 싶을 때",
        "홈의 '이름 일괄변경' 카드(또는 검사 결과에서 사진 선택 후 '이름 일괄변경')로 여러 장의 "
        "이름을 '기본이름_순번' 규칙으로 한 번에 바꿔요.",
    ),
    (
        "아이폰 라이브 포토를 모으고 싶을 때",
        "홈의 '라이브 포토' 카드는 사진과 짝이 되는 MOV 동영상이 남아있는 라이브 포토를 찾아줘요. "
        "동영상으로 내보내거나, 확인된 사진들만 새 폴더로 모을 수 있어요.",
    ),
]

# (질문, 답변)
_FAQ: list[tuple[str, str]] = [
    (
        "사진이 서버로 전송되나요?",
        "아니요. 검사·복구·정리는 물론 AI 카테고리 분류와 GPS 위치 → 도시 이름 찾기까지 전부 "
        "내 컴퓨터 안에서 처리되고, 사진이나 위치 정보를 인터넷으로 보내지 않아요. 자세한 내용은 "
        "홈 화면 아래의 '개인정보처리방침'에서 볼 수 있어요.",
    ),
    (
        "복구하면 원본 사진이 바뀌나요?",
        "기본 설정에선 바뀌지 않아요. 원본은 그대로 두고 'Recovered' 폴더에 새 파일을 만들어요. "
        "결과가 마음에 들지 않으면 그 폴더만 지우면 돼요. 저장 방식에서 '원본 교체'를 고르면 결과물이 "
        "원본 자리를 대신하는데, 이때도 원본은 지워지지 않고 임시휴지통으로 옮겨져서 다시 꺼낼 수 있어요.",
    ),
    (
        "정리에서 삭제한 사진은 어디로 가나요?",
        "완전히 지워지지 않고, 사진이 있던 폴더 안의 '임시휴지통' 폴더로 옮겨져요. 홈 화면의 "
        "'임시 휴지통' 버튼에서 언제든 원래 자리로 복원할 수 있어요.",
    ),
    (
        "어떤 사진 형식을 지원하나요?",
        "JPG(JPEG), PNG, HEIC/HEIF, WEBP, GIF, TIFF, BMP를 검사해요. 이 밖의 파일은 검사 대상에서 "
        "제외돼요.",
    ),
    (
        "카테고리 찾기가 왜 오래 걸리나요?",
        "AI가 사진을 한 장씩 보고 내용을 판단하기 때문이에요. 사진이 많을수록 오래 걸리지만, "
        "한 번 분석한 결과는 저장돼서 다음에 같은 폴더를 열면 새로 추가되거나 바뀐 사진만 "
        "분석해요.",
    ),
    (
        "'형식 불일치'와 '손상'은 어떻게 다른가요?",
        "'형식 불일치'는 파일 내용은 정상인데 확장자가 실제 형식과 다른 경우예요(예: PNG인데 "
        "이름이 .jpg). '부분 손상'은 일부만 읽히는 경우, '손상'은 열 수 없는 경우예요. 손상이 "
        "심하면 복구가 안 될 수 있어요.",
    ),
    (
        "검사 결과 창을 닫으면 결과가 사라지나요?",
        "창을 닫을 때 검사 결과와 카테고리 분류가 자동 저장돼요. 같은 폴더를 다시 올리면 "
        "저장본을 불러오고 바뀐 사진만 새로 확인해요.",
    ),
    (
        "검사 중에 프로그램을 닫아도 되나요?",
        "진행 중인 검사나 복구가 있으면 홈 화면을 닫을 수 없어요. 끝날 때까지 기다리거나 "
        "취소한 뒤 닫아주세요.",
    ),
]

# "Q&A"를 그대로 쓰면 Qt가 & 뒤 글자를 단축키로 해석해 "QA"로 보인다 — "&&"로 이스케이프.
_TABS = ("특별한 점", "사용방법", "활용법", "Q&&A")


def _card() -> QFrame:
    card = QFrame()
    card.setObjectName("Card")
    return card


def _wrapped_label(text: str, style: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet(f"{style} background: transparent;")
    return label


def _number_badge(number: int) -> QLabel:
    badge = QLabel(str(number))
    badge.setFixedSize(26, 26)
    badge.setAlignment(Qt.AlignCenter)
    badge.setStyleSheet(
        f"background-color: {COLORS['primary']}; color: {COLORS['on_primary']}; "
        "border-radius: 13px; font-weight: 700; font-size: 12px;"
    )
    return badge


def _step_card(number: int, title: str, desc: str) -> QFrame:
    card = _card()
    layout = QHBoxLayout(card)
    layout.setContentsMargins(16, 14, 16, 14)
    layout.setSpacing(12)
    layout.addWidget(_number_badge(number), alignment=Qt.AlignTop)

    text_col = QVBoxLayout()
    text_col.setSpacing(4)
    text_col.addWidget(_wrapped_label(title, "font-size: 14px; font-weight: 700;"))
    text_col.addWidget(_wrapped_label(desc, f"color: {COLORS['text_secondary']}; font-size: 12px;"))
    layout.addLayout(text_col, 1)
    return card


def _tip_card(title: str, desc: str) -> QFrame:
    card = _card()
    layout = QVBoxLayout(card)
    layout.setContentsMargins(16, 14, 16, 14)
    layout.setSpacing(4)
    # DESIGN.md "섹션 헤더 강조" — 굵은 글씨 + 왼쪽 primary accent bar
    header = _wrapped_label(
        title,
        f"font-size: 14px; font-weight: 700; border-left: 3px solid {COLORS['primary']}; padding-left: 8px;",
    )
    layout.addWidget(header)
    layout.addWidget(_wrapped_label(desc, f"color: {COLORS['text_secondary']}; font-size: 12px;"))
    return card


def _faq_card(question: str, answer: str) -> QFrame:
    card = _card()
    layout = QVBoxLayout(card)
    layout.setContentsMargins(16, 14, 16, 14)
    layout.setSpacing(6)

    q_row = QHBoxLayout()
    q_row.setSpacing(8)
    q_mark = QLabel("Q")
    q_mark.setStyleSheet(
        f"color: {COLORS['primary']}; font-size: 15px; font-weight: 800; background: transparent;"
    )
    q_row.addWidget(q_mark, alignment=Qt.AlignTop)
    q_row.addWidget(_wrapped_label(question, "font-size: 13.5px; font-weight: 700;"), 1)
    layout.addLayout(q_row)

    a_row = QHBoxLayout()
    a_row.setSpacing(8)
    a_mark = QLabel("A")
    a_mark.setStyleSheet(
        f"color: {COLORS['muted']}; font-size: 15px; font-weight: 800; background: transparent;"
    )
    a_row.addWidget(a_mark, alignment=Qt.AlignTop)
    a_row.addWidget(_wrapped_label(answer, f"color: {COLORS['text_secondary']}; font-size: 12px;"), 1)
    layout.addLayout(a_row)
    return card


def _scroll_page(cards: list[QFrame], intro: str = "") -> QScrollArea:
    content = QWidget()
    layout = QVBoxLayout(content)
    layout.setContentsMargins(0, 0, 8, 0)  # 오른쪽 8px은 스크롤바와 카드가 붙지 않게
    layout.setSpacing(10)
    if intro:
        layout.addWidget(_wrapped_label(intro, f"color: {COLORS['text_secondary']}; font-size: 12px;"))
    for card in cards:
        layout.addWidget(card)
    layout.addStretch(1)

    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    scroll.setWidget(content)
    return scroll


class HelpDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("PicMedic 사용 안내")
        # 이 창(부모 체인)만 막는다 — DESIGN.md "모달 범위는 항상 WindowModal".
        self.setWindowModality(Qt.WindowModal)
        self.resize(560, 640)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        title = QLabel("사용 안내")
        title.setObjectName("Title")
        layout.addWidget(title)

        tab_row = QHBoxLayout()
        tab_row.setSpacing(6)
        self._tab_group = QButtonGroup(self)
        self._tab_group.setExclusive(True)
        self._tab_buttons: list[QPushButton] = []
        for index, name in enumerate(_TABS):
            btn = QPushButton(name)
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            self._tab_group.addButton(btn, index)
            self._tab_buttons.append(btn)
            tab_row.addWidget(btn)
        tab_row.addStretch(1)
        layout.addLayout(tab_row)
        self._apply_tab_style()

        self._stack = QStackedWidget()
        self._stack.addWidget(
            _scroll_page(
                [_tip_card(t, d) for t, d in _HIGHLIGHTS],
                "고장 난 사진은 고치고, 쌓인 사진은 정리해요. 전부 내 컴퓨터 안에서, 안전하게.",
            )
        )
        self._stack.addWidget(
            _scroll_page(
                [_step_card(i, t, d) for i, (t, d) in enumerate(_USAGE_STEPS, start=1)],
                "사진을 올리면 검사 → 확인 → 복구·정리 순서로 진행돼요.",
            )
        )
        self._stack.addWidget(
            _scroll_page(
                [_tip_card(t, d) for t, d in _TIPS],
                "이럴 땐 이렇게 써보세요.",
            )
        )
        self._stack.addWidget(_scroll_page([_faq_card(q, a) for q, a in _FAQ]))
        layout.addWidget(self._stack, 1)

        self._tab_group.idClicked.connect(self._stack.setCurrentIndex)
        self._tab_buttons[0].setChecked(True)

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_btn = QPushButton("닫기")
        close_btn.setObjectName("Primary")
        close_btn.setDefault(True)
        close_btn.clicked.connect(self.accept)
        close_row.addWidget(close_btn)
        layout.addLayout(close_row)

    def _apply_tab_style(self) -> None:
        # 선택된 탭만 primary로 채운다(테마 기본 QPushButton 스타일 위에 덮어씀).
        style = (
            "QPushButton { border-radius: 16px; padding: 7px 18px; font-weight: 600; }"
            f"QPushButton:checked {{ background-color: {COLORS['primary']}; "
            f"color: {COLORS['on_primary']}; border-color: {COLORS['primary']}; }}"
        )
        for btn in self._tab_buttons:
            btn.setStyleSheet(style)


def show_help(parent: QWidget) -> None:
    HelpDialog(parent).exec()
