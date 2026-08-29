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

    print(f"\n총 {passed + failed}개 중 {passed}개 통과, {failed}개 실패")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
