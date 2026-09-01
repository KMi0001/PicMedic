import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.duplicate_resolver import suggest_keep, suggest_keep_folder
from models.file_info import FileInfo


def _info(path: str) -> FileInfo:
    p = Path(path)
    return FileInfo(path=path, filename=p.name, extension=p.suffix)


def _times(mapping: dict[str, float]):
    def fn(path: str):
        return mapping.get(path)

    return fn


def run():
    passed = failed = 0

    def check(label, cond, extra=""):
        nonlocal passed, failed
        print(f"[{'PASS' if cond else 'FAIL'}] {label} {extra}")
        if cond:
            passed += 1
        else:
            failed += 1

    # 1) 파일명 패턴으로 정해지는 경우 — "복사본" 표시 없는 유일한 파일을 추천
    group = [_info("C:/a/IMG_0284.jpg"), _info("C:/b/IMG_0284_복사본.jpg")]
    result = suggest_keep(group, creation_time_fn=_times({}))
    check(
        "복사본 표시 없는 파일을 추천함",
        result is not None and result[0].path == "C:/a/IMG_0284.jpg",
        f"실제={result}",
    )
    check("사유에 '복사본'이 언급됨", result is not None and "복사본" in result[1])

    # 2) 파일명으로 못 정하면(둘 다 깨끗함) 생성일이 유일하게 이른 파일을 추천
    group2 = [_info("C:/a/IMG_0001.jpg"), _info("C:/b/IMG_0001.jpg")]
    times2 = _times({"C:/a/IMG_0001.jpg": 200.0, "C:/b/IMG_0001.jpg": 100.0})
    result2 = suggest_keep(group2, creation_time_fn=times2)
    check(
        "생성일이 더 이른 파일을 추천함",
        result2 is not None and result2[0].path == "C:/b/IMG_0001.jpg",
        f"실제={result2}",
    )

    # 3) 생성일까지 동점이면 추천 안 함(None)
    group3 = [_info("C:/a/IMG_0002.jpg"), _info("C:/b/IMG_0002.jpg")]
    times3 = _times({"C:/a/IMG_0002.jpg": 100.0, "C:/b/IMG_0002.jpg": 100.0})
    result3 = suggest_keep(group3, creation_time_fn=times3)
    check("생성일 동점이면 추천 안 함", result3 is None, f"실제={result3}")

    # 4) 둘 다 복사본류 이름이면 파일명 기준으로 못 정하고 생성일로 넘어감
    group4 = [_info("C:/a/IMG_0003_copy.jpg"), _info("C:/b/IMG_0003 (1).jpg")]
    times4 = _times({"C:/a/IMG_0003_copy.jpg": 50.0, "C:/b/IMG_0003 (1).jpg": 80.0})
    result4 = suggest_keep(group4, creation_time_fn=times4)
    check(
        "둘 다 복사본류면 생성일로 넘어감",
        result4 is not None and result4[0].path == "C:/a/IMG_0003_copy.jpg",
        f"실제={result4}",
    )

    # 5) 생성일을 알 수 없으면(None 포함) 추천 안 함
    group5 = [_info("C:/a/IMG_0004.jpg"), _info("C:/b/IMG_0004.jpg")]
    times5 = _times({"C:/a/IMG_0004.jpg": 10.0})  # b는 없음(None)
    result5 = suggest_keep(group5, creation_time_fn=times5)
    check("생성일을 모르면 추천 안 함", result5 is None, f"실제={result5}")

    # 6) 파일 1개짜리 그룹은 애초에 대상 아님
    check("파일 1개 그룹은 None", suggest_keep([_info("C:/a/x.jpg")], creation_time_fn=_times({})) is None)

    # 7) suggest_keep_folder — 클러스터 안 모든 그룹이 같은 폴더를 추천하면 그 폴더 추천
    cluster_group1 = [_info("C:/folderA/1.jpg"), _info("C:/folderB/1.jpg")]
    cluster_group2 = [_info("C:/folderA/2.jpg"), _info("C:/folderB/2.jpg")]
    cluster_times = _times(
        {
            "C:/folderA/1.jpg": 10.0,
            "C:/folderB/1.jpg": 20.0,
            "C:/folderA/2.jpg": 10.0,
            "C:/folderB/2.jpg": 20.0,
        }
    )
    folder_result = suggest_keep_folder([cluster_group1, cluster_group2], creation_time_fn=cluster_times)
    check(
        "클러스터 전체가 동의하면 그 폴더를 추천",
        folder_result is not None and folder_result[0] == Path("C:/folderA"),
        f"실제={folder_result}",
    )

    # 8) 클러스터 안 그룹들이 서로 다른 폴더를 추천하면 클러스터 전체는 추천 안 함
    cluster_group3 = [_info("C:/folderA/3.jpg"), _info("C:/folderB/3.jpg")]
    disagree_times = _times(
        {
            "C:/folderA/1.jpg": 10.0,
            "C:/folderB/1.jpg": 20.0,
            "C:/folderA/3.jpg": 30.0,
            "C:/folderB/3.jpg": 5.0,  # 이 그룹은 folderB가 더 이름
        }
    )
    folder_result2 = suggest_keep_folder([cluster_group1, cluster_group3], creation_time_fn=disagree_times)
    check("클러스터 안 그룹들이 불일치하면 추천 안 함", folder_result2 is None, f"실제={folder_result2}")

    print(f"\n총 {passed + failed}개 중 {passed}개 통과, {failed}개 실패")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
