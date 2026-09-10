import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils import logger
from core.converter import RecoveryMode, RecoveryOutcome
from models.file_info import FileInfo
from models.scan_result import ScanResult


def run():
    passed = failed = 0

    def check(label, cond, extra=""):
        nonlocal passed, failed
        print(f"[{'PASS' if cond else 'FAIL'}] {label} {extra}")
        if cond:
            passed += 1
        else:
            failed += 1

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        # 실제 프로젝트 로그 폴더를 건드리지 않도록 임시 경로로 교체
        logger.LOG_DIR = tmp / "logs"
        logger.LOG_FILE = logger.LOG_DIR / "picmedic_log.jsonl"

        # 1) 스캔 로그
        result = ScanResult(total=3, normal=1, mismatch=1, partial_corruption=0, corrupted=1)
        logger.log_scan(str(tmp), result)
        entries = logger.read_recent_entries()
        check("스캔 로그 파일 생성됨", logger.LOG_FILE.exists())
        check("스캔 로그 항목 1개 기록됨", len(entries) == 1)
        check("스캔 로그 type=scan", entries[-1]["type"] == "scan")
        check("스캔 로그 total 값 일치", entries[-1]["total"] == 3)

        # 2) 복구 로그 (PRD FR-006 예시: Detected/Action/Result)
        info = FileInfo(path="IMG_1234.jpg", filename="IMG_1234.jpg", extension=".jpg", detected_format="HEIC")
        outcome = RecoveryOutcome(
            original=info,
            mode=RecoveryMode.CONVERT,
            output_path="Recovered/IMG_1234_recovered.jpg",
            success=True,
            verified=True,
            target_format="JPEG",
        )
        logger.log_recovery(outcome)
        entries = logger.read_recent_entries()
        check("복구 로그 항목 추가됨(총 2개)", len(entries) == 2)
        last = entries[-1]
        check("복구 로그 type=recovery", last["type"] == "recovery")
        check("복구 로그 filename 일치", last["filename"] == "IMG_1234.jpg")
        check("복구 로그 detected=HEIC", last["detected"] == "HEIC")
        check("복구 로그 action=형식_변환", last["action"] == RecoveryMode.CONVERT.value)
        check("복구 로그 target_format=JPEG", last["target_format"] == "JPEG")
        check("복구 로그 result=성공", last["result"] == "성공")

        # 3) 사람이 읽는 텍스트 포맷 (PRD FR-006 예시 형식)
        text = logger.format_entry_text(last)
        check("텍스트 포맷에 파일명 포함", "IMG_1234.jpg" in text)
        check("텍스트 포맷에 Detected 포함", "Detected: HEIC" in text)
        check("텍스트 포맷에 Result 포함", "Result: 성공" in text)

        # 4) 로그를 못 쓰는 위치여도 예외가 밖으로 새면 안 된다 (2026-09-11 리뷰)
        #
        # 패키징된 실행 파일이 MS 스토어(MSIX/WindowsApps)나 Program Files처럼
        # 읽기 전용 폴더에 설치되면 로그 폴더를 만들 수 없다. 그런데 log_scan()은
        # core/scanner.py::scan_paths가 검사를 다 마친 직후 try 없이 부르는
        # 지점이라, 여기서 예외가 나면 검사 결과가 통째로 날아가고 진행 화면이
        # 멈춘 것처럼 보인다. 로그는 부가 기능이므로 조용히 실패해야 한다.
        blocker = tmp / "blocked"
        blocker.write_text("파일이라 이 아래로는 폴더를 못 만든다", encoding="utf-8")
        saved_dir, saved_file = logger.LOG_DIR, logger.LOG_FILE
        logger.LOG_DIR = blocker / "logs"  # 파일 하위 경로 -> mkdir이 실패한다
        logger.LOG_FILE = logger.LOG_DIR / "picmedic_log.jsonl"
        try:
            logger.log_scan(str(tmp), ScanResult(total=1, normal=1))
            wrote_without_raising = True
        except Exception:
            wrote_without_raising = False
        check("쓰기 불가 경로에서도 log_scan()이 예외를 던지지 않는다", wrote_without_raising)
        check("쓰기 불가 경로에서 read_recent_entries()는 빈 목록", logger.read_recent_entries() == [])
        logger.LOG_DIR, logger.LOG_FILE = saved_dir, saved_file

    print(f"\n총 {passed + failed}개 중 {passed}개 통과, {failed}개 실패")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
