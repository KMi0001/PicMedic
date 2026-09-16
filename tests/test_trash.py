import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.helpers import check

from utils import trash


def test_trash():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)

        source_dir = tmp / "sources"
        source_dir.mkdir()
        trash_dir = source_dir / trash.TRASH_FOLDER_NAME

        # 0) 임시휴지통은 옮기려는 파일이 있던 폴더 바로 밑에 생긴다(전역 폴더 아님)
        check("trash_dir_for가 파일의 부모 폴더 밑을 가리킴", trash.trash_dir_for(source_dir / "x.jpg") == trash_dir)

        # 1) group_id 없이 옮기기(개별 이동 — group_id/reason/kept_path 생략 가능)
        flat_file = source_dir / "flat.jpg"
        flat_file.write_text("flat")
        flat_dest = trash.move_to_trash(flat_file)
        check("파일이 원래 폴더 밑 임시휴지통으로 이동함(폴더 없이 평평하게)", flat_dest.parent == trash_dir)
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
        check("그룹으로 옮긴 파일도 같은 임시휴지통 바로 아래에 있음(폴더 안 생김)", dest_a.parent == trash_dir and dest_b.parent == trash_dir)
        check("임시휴지통 안에 서브폴더가 하나도 없음", not any(p.is_dir() for p in trash_dir.iterdir()))

        entry_a = trash.entry_for(dest_a)
        check("그룹 파일의 group_id를 읽을 수 있음", entry_a is not None and entry_a.get("group_id") == group_id)
        check("그룹 파일의 사유를 읽을 수 있음", entry_a is not None and entry_a.get("reason") == reason_text)
        check("사유와 별개로 남긴 파일 경로도 읽을 수 있음", entry_a is not None and entry_a.get("kept_path") == str(keep_file))

        # 3) list_trash가 평평한 파일 전체를 찾음(매니페스트 제외)
        listed = trash.list_trash(trash_dir)
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
        stray = trash_dir / "stray.jpg"
        trash_dir.mkdir(parents=True, exist_ok=True)
        stray.write_text("stray")
        try:
            trash.restore_from_trash(stray)
            check("매니페스트에 없는 파일은 ValueError", False)
        except ValueError:
            check("매니페스트에 없는 파일은 ValueError", True)

        # 8) 같은 폴더에서 같은 이름으로 두 번 옮기면 번호를 붙여 원본을 덮어쓰지 않음
        first = source_dir / "same_name.jpg"
        first.write_text("first")
        dest_first = trash.move_to_trash(first)
        second = source_dir / "same_name.jpg"
        second.write_text("second")
        dest_second = trash.move_to_trash(second)
        check("같은 이름이면 번호를 붙여 구분함", dest_first != dest_second and dest_first.exists() and dest_second.exists())

        # 9) 옛 폴더 구조(그룹 서브폴더 + _사유.txt) 마이그레이션
        old_group_dir = trash_dir / "2026-09-01_1430_그룹0001"
        old_group_dir.mkdir(parents=True)
        old_file = old_group_dir / "old_dup.jpg"
        old_file.write_text("old")
        old_kept_source = source_dir / "old_keep.jpg"
        old_kept_source.write_text("old keep")
        (old_group_dir / "_사유.txt").write_text(
            f"옛날 방식 사유\n\n남긴 파일: {old_kept_source}", encoding="utf-8"
        )
        # trash_dir은 이 테스트에서 이미 여러 번 move_to_trash/restore_from_trash를
        # 거쳐서 매니페스트가 메모리 캐시에 있다(utils/trash.py — 대량 배치 성능
        # 개선으로 파일마다 디스크에 바로 쓰지 않음, 2026-09-17). 그래서 여기서도
        # _load_manifest/_save_manifest로 디스크를 직접 건드리면 캐시와 어긋나
        # 방금 쓴 내용이 무시된다 — 캐시를 거치는 함수로 맞춰야 한다.
        manifest = trash._get_manifest(trash_dir)
        manifest["2026-09-01_1430_그룹0001/old_dup.jpg"] = {"original": "C:/원본/old_dup.jpg"}
        trash._mark_dirty(trash_dir)

        moved_count, migrate_failed = trash.migrate_group_folders_to_flat(trash_dir)
        check("마이그레이션이 옛 폴더의 파일 1개를 옮김", moved_count == 1, f"실제={moved_count}")
        check("마이그레이션 실패 없음", migrate_failed == [], f"실제={migrate_failed}")
        check("옛 그룹 폴더가 삭제됨(비었으므로)", not old_group_dir.exists())
        migrated_path = trash_dir / "old_dup.jpg"
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
        moved_count2, migrate_failed2 = trash.migrate_group_folders_to_flat(trash_dir)
        check("옮길 옛 폴더가 없으면 다시 실행해도 안전함", moved_count2 == 0 and migrate_failed2 == [])

        # 11) 서로 다른 폴더는 각자 독립된 임시휴지통을 가진다
        other_dir = tmp / "other_source"
        other_dir.mkdir()
        other_file = other_dir / "same_name.jpg"
        other_file.write_text("other")
        other_dest = trash.move_to_trash(other_file)
        check(
            "다른 폴더의 파일은 자기 폴더 밑의 별도 임시휴지통으로 감",
            other_dest.parent == other_dir / trash.TRASH_FOLDER_NAME and other_dest.parent != trash_dir,
        )

def test_trash_manifest_batching():
    """2026-09-17 실사용 리포트: 중복 파일 22,132개 정리가 "응답없음"처럼
    보임 — move_to_trash()가 파일마다 매니페스트 전체를 다시 읽고 다시 써서
    (utils/trash.py) 매니페스트가 커질수록 갈수록 느려지는(사실상 O(n^2))
    구조였다. 파일마다 디스크에 쓰지 않고 메모리에 모아뒀다가
    flush_trash_manifests()가 한 번에 쓰도록 고쳤다 — 이 테스트는 실제로
    디스크 쓰기 횟수가 파일 개수보다 훨씬 적은지 직접 센다."""
    import time

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        source_dir = tmp / "many_dups"
        source_dir.mkdir()

        save_calls = {"count": 0}
        original_save = trash._save_manifest

        def counting_save(trash_dir, manifest):
            save_calls["count"] += 1
            original_save(trash_dir, manifest)

        trash._save_manifest = counting_save
        try:
            N = 450  # 자동 플러시 기준(200)을 두 번 넘기는 수
            group_id = trash.new_group_id()
            for i in range(N):
                f = source_dir / f"dup_{i}.jpg"
                f.write_text(f"content {i}")
                trash.move_to_trash(f, group_id=group_id, reason="배치 테스트")
            before_final_flush = save_calls["count"]
            trash.flush_trash_manifests()
            after_final_flush = save_calls["count"]
        finally:
            trash._save_manifest = original_save

        check(
            f"파일마다 디스크에 쓰지 않고 훨씬 적게 씀({N}개 옮겼는데 디스크 쓰기 {before_final_flush}회)",
            before_final_flush < N / 2,
            f"실제 쓰기 횟수={before_final_flush}",
        )
        check("배치 끝 flush로 최종 반영됨(추가로 최소 1번 더 씀)", after_final_flush > before_final_flush)

        trash_dir = trash.trash_dir_for(source_dir)
        on_disk = trash._load_manifest(trash_dir)  # 캐시를 거치지 않고 진짜 디스크 상태를 직접 확인
        check(f"플러시 후 디스크 매니페스트에 {N}개 전부 반영됨", len(on_disk) == N, f"실제={len(on_disk)}")


if __name__ == "__main__":  # pytest 없이 이 파일 하나만 돌려보고 싶을 때
    test_trash()
    test_trash_manifest_batching()
    print("OK")
