import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.helpers import check

from core.duplicate_resolver import suggest_keep, suggest_keep_folder
from models.file_info import FileInfo


def _info(path: str) -> FileInfo:
    p = Path(path)
    return FileInfo(path=path, filename=p.name, extension=p.suffix)


def _times(mapping: dict[str, float]):
    def fn(path: str):
        return mapping.get(path)

    return fn


def test_duplicate_resolver():
    # 1) 파일명 패턴으로 정해지는 경우 - "복사본" 표시 없는 유일한 파일을 추천
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

    # 7) suggest_keep_folder - 클러스터 안 모든 그룹이 같은 폴더를 추천하면 그 폴더 추천
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

    # 9) 재정리 버그 시나리오 - a.jpg/a_1.jpg처럼 숫자 접미사만 다른 경우도
    # (그룹 안에 짝이 되는 원본이 실제로 있으면) 자동 추천됨
    group9 = [_info("C:/x/a.jpg"), _info("C:/x/a_1.jpg")]
    result9 = suggest_keep(group9, creation_time_fn=_times({}))
    check(
        "a.jpg/a_1.jpg - 접미사 없는 a.jpg를 추천함",
        result9 is not None and result9[0].path == "C:/x/a.jpg",
        f"실제={result9}",
    )

    # 10) 위와 같은 원리로 N장(3장 이상)도 한 번에 처리됨
    group10 = [_info("C:/x/b.jpg"), _info("C:/x/b_1.jpg"), _info("C:/x/b_2.jpg")]
    result10 = suggest_keep(group10, creation_time_fn=_times({}))
    check(
        "b.jpg/b_1.jpg/b_2.jpg(3장) - 접미사 없는 b.jpg를 추천함",
        result10 is not None and result10[0].path == "C:/x/b.jpg",
        f"실제={result10}",
    )

    # 11) 회귀 테스트 - "IMG_0284"처럼 카메라 원본 번호처럼 보이는 이름은,
    # 그룹 안에 짝이 되는 "IMG.jpg"가 실제로 없으면 여전히 오탐 안 됨
    group11 = [_info("C:/x/IMG_0284.jpg"), _info("C:/y/IMG_0284.jpg")]
    result11 = suggest_keep(group11, creation_time_fn=_times({"C:/x/IMG_0284.jpg": 5.0, "C:/y/IMG_0284.jpg": 9.0}))
    check(
        "IMG_0284 단독으로는 오탐 안 되고 생성일로 정해짐",
        result11 is not None and result11[0].path == "C:/x/IMG_0284.jpg",
        f"실제={result11}",
    )

    # 12) 짝이 되는 원본이 그룹 안에 없으면(a_1.jpg, a_2.jpg만 있고 a.jpg가
    # 없음) 둘 다 접미사 신호로는 안 걸리고 생성일로 넘어감
    group12 = [_info("C:/x/c_1.jpg"), _info("C:/x/c_2.jpg")]
    times12 = _times({"C:/x/c_1.jpg": 5.0, "C:/x/c_2.jpg": 9.0})
    result12 = suggest_keep(group12, creation_time_fn=times12)
    check(
        "짝이 되는 원본이 없으면 생성일로 넘어감",
        result12 is not None and result12[0].path == "C:/x/c_1.jpg",
        f"실제={result12}",
    )


if __name__ == "__main__":  # pytest 없이 이 파일 하나만 돌려보고 싶을 때
    test_duplicate_resolver()
    print("OK")
