import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils import trash


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
        # 실제 프로젝트의 임시휴지통 폴더를 건드리지 않도록 임시 경로로 교체
        trash.TRASH_DIR = tmp / "임시휴지통"

        source_dir = tmp / "sources"
        source_dir.mkdir()

        # 1) 그룹 없이 옮기기(기존 flat 동작 — 다른 호출부와의 호환용)
        flat_file = source_dir / "flat.jpg"
        flat_file.write_text("flat")
        flat_dest = trash.move_to_trash(flat_file)
        check("flat 파일이 TRASH_DIR 바로 아래로 이동함", flat_dest.parent == trash.TRASH_DIR)
        check("flat 파일 사유는 없음(그룹 아님)", trash.group_reason(flat_dest) is None)

        # 2) 그룹 단위로 옮기기
        keep_file = source_dir / "keep.jpg"
        keep_file.write_text("keep")
        remove_a = source_dir / "dup_a.jpg"
        remove_a.write_text("dup a")
        remove_b = source_dir / "dup_b.jpg"
        remove_b.write_text("dup b")

        session_ts = trash.new_session_timestamp()
        group_dir = trash.create_trash_group(session_ts, 1, str(keep_file), "테스트 사유: 메타데이터 없음")
        check("그룹 폴더가 세션 타임스탬프로 시작함", group_dir.name.startswith(session_ts))
        check("그룹 폴더에 _사유.txt 생성됨", (group_dir / "_사유.txt").exists())

        dest_a = trash.move_to_trash(remove_a, group_dir=group_dir)
        dest_b = trash.move_to_trash(remove_b, group_dir=group_dir)
        check("그룹 파일이 그룹 서브폴더 안에 있음", dest_a.parent == group_dir and dest_b.parent == group_dir)

        reason_a = trash.group_reason(dest_a)
        check("그룹 파일의 사유를 읽을 수 있음", reason_a is not None and "메타데이터 없음" in reason_a)
        check("사유에 남긴 파일 경로가 포함됨", str(keep_file) in reason_a)

        # 3) list_trash가 재귀적으로 flat + 그룹 파일을 모두 찾음(사유/매니페스트 제외)
        listed = trash.list_trash()
        listed_names = {p.name for p in listed}
        check("list_trash에 flat 파일 포함", "flat.jpg" in listed_names)
        check("list_trash에 그룹 파일 포함", {"dup_a.jpg", "dup_b.jpg"} <= listed_names)
        check("list_trash에 _사유.txt는 제외됨", "_사유.txt" not in listed_names)
        check("list_trash 개수 = 3(flat 1 + 그룹 2)", len(listed) == 3, f"실제={len(listed)}")

        # 4) 그룹 파일 하나 복원 — 그룹 폴더는 아직 남아있어야 함(파일 하나 더 있으므로)
        restored_a = trash.restore_from_trash(dest_a)
        check("복원된 파일이 원래 경로로 돌아감", restored_a == remove_a and restored_a.exists())
        check("그룹 폴더가 아직 남아있음(dup_b 있음)", group_dir.exists())

        # 5) 그룹의 마지막 파일 복원 — 그룹 폴더(+ 사유 파일)가 같이 정리돼야 함
        trash.restore_from_trash(dest_b)
        check("그룹의 마지막 파일 복원 후 그룹 폴더가 삭제됨", not group_dir.exists())

        # 6) flat 파일 복원도 여전히 동작함(하위 호환)
        restored_flat = trash.restore_from_trash(flat_dest)
        check("flat 파일도 복원됨", restored_flat == flat_file and restored_flat.exists())

        # 7) 매니페스트에 없는 파일 복원 시도 -> ValueError
        stray = trash.TRASH_DIR / "stray.jpg"
        trash.TRASH_DIR.mkdir(parents=True, exist_ok=True)
        stray.write_text("stray")
        try:
            trash.restore_from_trash(stray)
            check("매니페스트에 없는 파일은 ValueError", False)
        except ValueError:
            check("매니페스트에 없는 파일은 ValueError", True)

    print(f"\n총 {passed + failed}개 중 {passed}개 통과, {failed}개 실패")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
