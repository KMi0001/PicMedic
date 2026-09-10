"""
tests/helpers.py

테스트 공용 단언 헬퍼.

2026-09-11까지 이 저장소의 테스트는 파일마다 `run()` 안에 똑같은 check() 클로저를
직접 정의하고 통과/실패를 세어 출력하는 구조였다. 케이스가 230개까지 늘면서
두 가지가 불편해졌다:
  - 한 번에 다 돌릴 러너가 없어 README에 14줄짜리 실행 목록이 있었고, CI에
    붙이기도 어려웠다.
  - 실패해도 어느 줄에서 깨졌는지 stack trace가 안 나와서, 라벨만 보고 파일을
    뒤져야 했다.

그래서 pytest로 옮기되 **테스트 본문은 한 글자도 바꾸지 않았다** — check() 호출
230개가 그대로 남아있고, 이 모듈이 각 파일의 지역 클로저를 대신한다. 라벨 텍스트가
그대로라 예전 출력과 그대로 비교된다.

`conftest.py`가 아니라 별도 모듈인 이유: `tests/`에 `__init__.py`가 있어서 패키지로
잡히는데, 그러면 pytest가 sys.path에 넣는 건 저장소 루트라 `conftest`를 최상위
모듈로 import할 수 없다(`ModuleNotFoundError`). 일반 모듈로 두고
`from tests.helpers import check`로 가져오면 pytest로 돌리든 파일을 직접 실행하든
똑같이 동작한다.
"""

from __future__ import annotations

# 전체 실행에서 단언이 몇 개나 돌았는지 세어, conftest.py가 마지막에 요약을 찍는다
# (예전 `python tests/test_x.py`가 파일마다 찍던 "총 N개 중 M개 통과"의 대체).
COUNTS = {"passed": 0, "skipped": 0}


def check(label: str, condition, extra: str = "") -> None:
    """단언 하나. 예전 구조와 같은 [PASS] 줄을 찍고, 실패하면 그 자리에서 멈춘다.

    예전 check()는 실패를 세기만 하고 계속 진행했지만, 여기서는 바로
    AssertionError를 던진다 — pytest가 그 지점의 stack trace와 지역 변수를
    그대로 보여주는 게 이 이전의 주된 목적이기 때문이다.
    """
    if condition:
        COUNTS["passed"] += 1
        print(f"[PASS] {label} {extra}".rstrip())
        return
    print(f"[FAIL] {label} {extra}".rstrip())
    raise AssertionError(f"{label} {extra}".rstrip())


def skip(label: str) -> None:
    """자산(수백MB 모델 가중치)이나 권한이 없어 건너뛰는 케이스 — 예전과 같은
    의미로, 테스트 자체를 실패시키지 않고 [SKIP]만 남긴다."""
    COUNTS["skipped"] += 1
    print(f"[SKIP] {label}")
