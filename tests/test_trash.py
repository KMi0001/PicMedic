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

        # 1) group_id 없이 옮기기(개별 이동 — group_id/reason/kept_path 생략 가능)
        flat_file = source_dir / "flat.jpg"
        flat_file.write_text("flat")
        flat_dest = trash.move_to_trash(flat_file)
        check("파일이 TRASH_DIR 바로 아래로 이동함(폴더 없이 평평하게)", flat_dest.parent == trash.TRASH_DIR)
        entry = trash.entry_for(flat_dest)
        check("group_id 없이 옮긴 파일은 entry에 group_id가 없음", entry is not None and "group_id" not in entry)

        # 2) group_id로 묶어서 옮기기 — 폴더는 전혀 생기지 않아야 함
        keep_file = source_dir / "keep.jpg"
        keep_file.write_text("keep")
        remove_a = source_dir / "dup_a.jpg"
        remove_a.write_text("dup a")
        remove_b = source_dir / "dup_b.jpg"
        remove_b.write_text("dup b")

        group_id = trash.new_group_id()
        reason_text = "테스트 사유: 메타데이터 없음"
        dest_a = trash.move_to_trash(remove_a, group_id=group_id, reason=reason_text, kept_path=str(keep_file))
        dest_b = trash.move_to_trash(remove_b, group_id=group_id, reason=reason_text, kept_path=str(keep_file))
        check("그룹으로 옮긴 파일도 TRASH_DIR 바로 아래에 있음(폴더 안 생김)", dest_a.parent == trash.TRASH_DIR and dest_b.parent == trash.TRASH_DIR)
        check("TRASH_DIR 안에 서브폴더가 하나도 없음", not any(p.is_dir() for p in trash.TRASH_DIR.iterdir()))

        entry_a = trash.entry_for(dest_a)
        check("그룹 파일의 group_id를 읽을 수 있음", entry_a is not None and entry_a.get("group_id") == group_id)
        check("그룹 파일의 사유를 읽을 수 있음", entry_a is not None and entry_a.get("reason") == reason_text)
        check("사유와 별개로 남긴 파일 경로도 읽을 수 있음", entry_a is not None and entry_a.get("kept_path") == str(keep_file))

        # 3) list_trash가 평평한 파일 전체를 찾음(매니페스트 제외)
        listed = trash.list_trash()
        listed_names = {p.name for p in listed}
        check("list_trash에 개별 이동 파일 포함", "flat.jpg" in listed_names)
        check("list_trash에 그룹 파일 포함", {"dup_a.jpg", "dup_b.jpg"} <= listed_names)
        check("list_trash 개수 = 3", len(listed) == 3, f"실제={len(listed)}")

        # 4) 그룹 파일 하나 복원
        restored_a = trash.restore_from_trash(dest_a)
        check("복원된 파일이 원래 경로로 돌아감", restored_a == remove_a and restored_a.exists())
        check("복원 후 매니페스트에서도 빠짐", trash.entry_for(dest_a) is None)

        # 5) 그룹의 나머지 파일도 복원 가능(폴더가 없으니 정리할 것도 없음)
        trash.restore_from_trash(dest_b)
        check("그룹의 나머지 파일도 복원됨", not dest_b.exists())

        # 6) group_id 없이 옮긴 파일도 여전히 복원 가능
        restored_flat = trash.restore_from_trash(flat_dest)
        check("개별 이동 파일도 복원됨", restored_flat == flat_file and restored_flat.exists())

        # 7) 매니페스트에 없는 파일 복원 시도 -> ValueError
        stray = trash.TRASH_DIR / "stray.jpg"
        trash.TRASH_DIR.mkdir(parents=True, exist_ok=True)
        stray.write_text("stray")
        try:
            trash.restore_from_trash(stray)
            check("매니페스트에 없는 파일은 ValueError", False)
        except ValueError:
            check("매니페스트에 없는 파일은 ValueError", True)

        # 8) 이름이 겹치면 번호를 붙여 원본을 덮어쓰지 않음
        first = source_dir / "same_name.jpg"
        first.write_text("first")
        second_dir = tmp / "sources2"
        second_dir.mkdir()
        second = second_dir / "same_name.jpg"
        second.write_text("second")
        dest_first = trash.move_to_trash(first)
        dest_second = trash.move_to_trash(second)
        check("같은 이름이면 번호를 붙여 구분함", dest_first != dest_second and dest_first.exists() and dest_second.exists())

        # 9) 옛 폴더 구조(그룹 서브폴더 + _사유.txt) 마이그레이션
        old_group_dir = trash.TRASH_DIR / "2026-09-01_1430_그룹0001"
        old_group_dir.mkdir(parents=True)
        old_file = old_group_dir / "old_dup.jpg"
        old_file.write_text("old")
        old_kept_source = source_dir / "old_keep.jpg"
        old_kept_source.write_text("old keep")
        (old_group_dir / "_사유.txt").write_text(
            f"옛날 방식 사유\n\n남긴 파일: {old_kept_source}", encoding="utf-8"
        )
        manifest = trash._load_manifest()
        manifest["2026-09-01_1430_그룹0001/old_dup.jpg"] = {"original": "C:/원본/old_dup.jpg"}
        trash._save_manifest(manifest)

        moved_count, migrate_failed = trash.migrate_group_folders_to_flat()
        check("마이그레이션이 옛 폴더의 파일 1개를 옮김", moved_count == 1, f"실제={moved_count}")
        check("마이그레이션 실패 없음", migrate_failed == [], f"실제={migrate_failed}")
        check("옛 그룹 폴더가 삭제됨(비었으므로)", not old_group_dir.exists())
        migrated_path = trash.TRASH_DIR / "old_dup.jpg"
        check("마이그레이션된 파일이 평평한 위치에 있음", migrated_path.exists())
        migrated_entry = trash.entry_for(migrated_path)
        check(
            "마이그레이션된 파일의 사유/남긴 파일 정보가 보존됨",
            migrated_entry is not None
            and migrated_entry.get("reason") == "옛날 방식 사유"
            and migrated_entry.get("kept_path") == str(old_kept_source)
            and migrated_entry.get("group_id") == "2026-09-01_1430_그룹0001",
        )
        check(
            "마이그레이션 후에도 원래 경로 정보가 유지됨(복원 가능)",
            migrated_entry is not None and migrated_entry.get("original") == "C:/원본/old_dup.jpg",
        )

        # 10) 마이그레이션을 다시 실행해도 안전함(옮길 옛 폴더가 없으므로 아무 일도 안 함)
        moved_count2, migrate_failed2 = trash.migrate_group_folders_to_flat()
        check("옮길 옛 폴더가 없으면 다시 실행해도 안전함", moved_count2 == 0 and migrate_failed2 == [])

    print(f"\n총 {passed + failed}개 중 {passed}개 통과, {failed}개 실패")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
