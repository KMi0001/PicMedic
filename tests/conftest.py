"""
tests/conftest.py

pytest 설정. 단언 헬퍼 자체는 tests/helpers.py에 있다(그쪽 docstring에 왜
분리했는지 적어뒀다).
"""

from __future__ import annotations

import sys
from pathlib import Path

# 테스트가 core/·gui/를 import할 수 있도록 저장소 루트를 경로에 넣는다
# (각 테스트 파일도 예전부터 같은 줄을 갖고 있어서 파일 단독 실행도 된다 —
# 중복 삽입은 무해하다).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.helpers import COUNTS


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """예전 `python tests/test_x.py`가 파일마다 찍던 "총 N개 중 M개 통과"를
    전체 기준으로 한 번 찍어준다 — README에 적어둔 케이스 수와 대조하기 위함.
    (pytest가 세는 건 테스트 '함수' 개수라 단언 개수와 다르다.)"""
    passed = COUNTS["passed"]
    skipped = COUNTS["skipped"]
    if not passed and not skipped:
        return
    summary = f"단언 {passed}개 통과"
    if skipped:
        summary += f", {skipped}개 건너뜀(자산/권한 없음)"
    terminalreporter.write_sep("-", summary)
