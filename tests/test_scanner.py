"""
core/scanner.py 테스트

심볼릭 링크 순환 스캔 시 무한 루프에 빠지지 않는지, 취소 신호가 파일 목록을
모으는 단계에서도 바로 전달되는지 확인한다. (PRD_MVP우선순위.md '남은 갭 #6')
"""

import os
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.scanner import iter_candidate_files, scan_paths

TIMEOUT_SEC = 5


def _run_with_timeout(fn):
    """fn이 무한 루프에 빠지면 테스트 프로세스 자체가 안 끝나버리므로,
    별도 스레드에서 실행하고 타임아웃이 지나면 실패로 처리한다."""
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(fn)
        try:
            return future.result(timeout=TIMEOUT_SEC), None
        except FutureTimeoutError:
            return None, f"{TIMEOUT_SEC}초 안에 안 끝남 (심볼릭 링크 순환에서 멈춘 것으로 보임)"


def run():
    passed = 0
    failed = 0
    skipped = 0

    def check(label, condition):
        nonlocal passed, failed
        status = "PASS" if condition else "FAIL"
        if condition:
            passed += 1
        else:
            failed += 1
        print(f"[{status}] {label}")

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "photo.jpg").write_bytes(b"fake")

        symlink_ok = True
        try:
            os.symlink(tmp, tmp / "loop", target_is_directory=True)
        except (OSError, NotImplementedError):
            symlink_ok = False

        if not symlink_ok:
            skipped += 1
            print("[SKIP] 심볼릭 링크 순환 테스트 (이 환경에서는 심볼릭 링크 생성 권한이 없음)")
        else:
            # 1) 자기 자신을 가리키는 심볼릭 링크가 있어도 무한 루프 없이 끝나야 한다
            files, err = _run_with_timeout(lambda: list(iter_candidate_files(tmp)))
            check("심볼릭 링크 순환 스캔이 타임아웃 없이 끝남", err is None)
            if err is None:
                names = [p.name for p in files]
                check("순환 링크를 타고 photo.jpg를 중복해서 찾지 않음", names.count("photo.jpg") == 1)

            # 2) scan_paths 전체 경로로도 마찬가지로 끝나야 한다
            (result_remaining, err2) = _run_with_timeout(lambda: scan_paths([str(tmp)]))
            check("scan_paths도 심볼릭 링크 순환에서 타임아웃 없이 끝남", err2 is None)
            if err2 is None:
                result, remaining = result_remaining
                check("scan_paths 결과가 파일 1개만 집계함", result.total == 1)
                check("취소 없이 끝까지 스캔했으니 remaining_paths는 비어있음", remaining == [])

    # 3) 취소 신호가 파일 목록을 모으는 단계(iter_candidate_files) 안에서도 바로 먹혀야 한다
    #    (예전엔 이 단계엔 취소를 체크할 지점이 아예 없어서, 전체 글롭이 끝나야만 취소가 반영됐음)
    with tempfile.TemporaryDirectory() as tmp2:
        tmp2 = Path(tmp2)
        for i in range(20):
            (tmp2 / f"photo_{i}.jpg").write_bytes(b"fake")

        seen = []

        def should_cancel():
            return len(seen) >= 3

        for path in iter_candidate_files(tmp2, should_cancel=should_cancel):
            seen.append(path)

        check("취소 신호 후 파일 수집이 즉시 멈춤 (3개 이하)", len(seen) <= 3)

    print(f"\n총 {passed + failed}개 중 {passed}개 통과, {failed}개 실패 ({skipped}개 스킵)")
    return failed == 0


if __name__ == "__main__":
    success = run()
    sys.exit(0 if success else 1)
