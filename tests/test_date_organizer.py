import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.date_organizer import organize_by_date, NO_DATE_LABEL, NO_DATE_FOLDER_NAME
from models.file_info import FileInfo
from models.scan_result import ScanResult


def _make_file(tmp: Path, name: str, captured_at, content: str = "data") -> FileInfo:
    path = tmp / name
    path.write_text(content)
    return FileInfo(
        path=str(path),
        filename=name,
        extension=path.suffix,
        captured_at=captured_at,
        file_size=path.stat().st_size,
    )


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
        source = tmp / "source"
        source.mkdir()

        f1 = _make_file(source, "a.jpg", datetime(2024, 3, 15))
        f2 = _make_file(source, "b.jpg", datetime(2024, 3, 20))
        f3 = _make_file(source, "c.jpg", datetime(2024, 12, 1))
        f4 = _make_file(source, "d.jpg", None)  # 날짜 정보 없음

        result = ScanResult(total=4, files=[f1, f2, f3, f4])

        # 1) ScanResult.date_groups() — 최신 달 먼저, 날짜 없음은 맨 뒤
        groups = result.date_groups()
        labels = [label for label, _ in groups]
        check("최신 달이 먼저 옴", labels == ["2024년 12월", "2024년 3월", NO_DATE_LABEL], f"실제={labels}")
        check("3월 그룹에 파일 2개", len(dict(groups)["2024년 3월"]) == 2)
        check("날짜 없음 그룹에 파일 1개", len(dict(groups)[NO_DATE_LABEL]) == 1)

        # 2) organize_by_date — 복사 모드, 날짜 정보 없는 그룹도 전용 폴더로 정리됨
        output_root = tmp / "정리됨"
        outcomes = organize_by_date(groups, "copy", output_root)
        check("날짜 있는 파일 3개 + 날짜없음 1개 = 4개 처리됨", len(outcomes) == 4, f"실제={len(outcomes)}")
        check("전부 성공", all(o.success for o in outcomes))
        check("2024/03 폴더에 2개 복사됨", len(list((output_root / "2024" / "03").glob("*.jpg"))) == 2)
        check("2024/12 폴더에 1개 복사됨", len(list((output_root / "2024" / "12").glob("*.jpg"))) == 1)
        check(
            f"날짜없음 파일은 {NO_DATE_FOLDER_NAME} 폴더로 복사됨",
            len(list((output_root / NO_DATE_FOLDER_NAME).glob("*.jpg"))) == 1,
        )
        check("복사 모드라 원본이 그대로 남아있음", f1.path and Path(f1.path).exists())
        check("복사 모드라 날짜 없는 원본도 그대로 있음", Path(f4.path).exists())

        # 2a) 같은 저장 위치로 "정리하기"를 실수로 두 번 눌러도(또는 나중에
        # 몇 장을 더 추가해도) 이미 있는 파일은 다시 복사하지 않고 건너뛴다 —
        # 사진이 두 배로 늘어나던 문제의 재발 방지.
        outcomes_rerun = organize_by_date(groups, "copy", output_root)
        check("재실행 시 4개 전부 '이미 있음'으로 건너뜀", all(o.skipped for o in outcomes_rerun))
        check("재실행해도 실제로는 성공 처리됨(파일이 그 자리에 있으니)", all(o.success for o in outcomes_rerun))
        check(
            "재실행 후에도 2024/03 폴더엔 여전히 2개뿐(중복 안 생김)",
            len(list((output_root / "2024" / "03").glob("*.jpg"))) == 2,
        )

        # 다른 사진이 우연히 같은 이름이지만 용량이 다르면 건너뛰지 않고
        # 번호를 붙여 별개 파일로 복사한다.
        source_dup_name = tmp / "source_dup_name"
        source_dup_name.mkdir()
        f1_conflict = _make_file(source_dup_name, "a.jpg", datetime(2024, 3, 15), content="different-content-longer")
        outcomes_conflict = organize_by_date([("2024년 3월", [f1_conflict])], "copy", output_root)
        check("이름은 같지만 용량이 다르면 건너뛰지 않음", not outcomes_conflict[0].skipped)
        check(
            "용량 다른 동명 파일은 번호를 붙여 별도로 복사됨",
            len(list((output_root / "2024" / "03").glob("*.jpg"))) == 3,
        )

        # 2b) granularity="year" — 월 없이 연 단위 폴더로만 묶임
        output_root_year = tmp / "정리됨_연도"
        organize_by_date(groups, "copy", output_root_year, granularity="year")
        check(
            "연도별 모드에서는 2024 폴더 바로 아래 3장",
            len(list((output_root_year / "2024").glob("*.jpg"))) == 3,
        )
        check(
            "연도별 모드에서도 하위 월 폴더는 안 생김",
            not (output_root_year / "2024" / "03").exists(),
        )

        # 3) organize_by_date — 이동 모드에서는 원본이 사라짐
        output_root2 = tmp / "정리됨_이동"
        organize_by_date(groups, "move", output_root2)
        check("이동 모드에서는 원본이 사라짐", not Path(f1.path).exists())
        check("이동된 파일이 새 위치에 있음", len(list((output_root2 / "2024" / "03").glob("*.jpg"))) == 2)

        # 4) 진행률 콜백 호출 확인
        source2 = tmp / "source2"
        source2.mkdir()
        g1 = _make_file(source2, "e.jpg", datetime(2023, 1, 5))
        progress_calls = []
        organize_by_date(
            [("2023년 1월", [g1])],
            "copy",
            tmp / "정리됨3",
            progress_callback=lambda cur, total, name: progress_calls.append((cur, total, name)),
        )
        check("progress_callback이 (1,1,파일명)으로 호출됨", progress_calls == [(1, 1, "e.jpg")], f"실제={progress_calls}")

        # 5) should_cancel — 취소 시 즉시 중단
        source3 = tmp / "source3"
        source3.mkdir()
        h1 = _make_file(source3, "h1.jpg", datetime(2023, 5, 1))
        h2 = _make_file(source3, "h2.jpg", datetime(2023, 5, 2))
        outcomes_cancel = organize_by_date(
            [("2023년 5월", [h1, h2])], "copy", tmp / "정리됨4", should_cancel=lambda: True
        )
        check("취소하면 바로 중단(처리 0건)", outcomes_cancel == [])

    print(f"\n총 {passed + failed}개 중 {passed}개 통과, {failed}개 실패")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
