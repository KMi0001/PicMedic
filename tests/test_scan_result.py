import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.helpers import check

from models.file_info import FileInfo
from models.scan_result import ScanResult


def _info(path: str, phash: str | None = None, content_hash: str | None = None) -> FileInfo:
    p = Path(path)
    return FileInfo(path=path, filename=p.name, extension=p.suffix, perceptual_hash=phash, content_hash=content_hash)


def test_scan_result():
    # 1) 파일명 패턴 — 접미사를 뗀 이름이 실제 존재하는 파일과 일치하면 그룹핑
    f_base = _info("C:/x/a.jpg", content_hash="h1")
    f_suffix = _info("C:/x/a_1.jpg", content_hash="h2")
    result = ScanResult(total=2, files=[f_base, f_suffix])
    groups = result.similar_groups()
    check("파일명 패턴(a.jpg/a_1.jpg) 그룹핑됨", len(groups) == 1 and len(groups[0]) == 2, f"실제={groups}")

    # 2) 카메라 원본 번호(IMG_0284/IMG_0285)는 접미사 모양이 비슷해도 오탐 안 됨
    # — 접미사를 뗀 "IMG"라는 파일이 실제로 없기 때문
    f_cam1 = _info("C:/x/IMG_0284.jpg", content_hash="h3")
    f_cam2 = _info("C:/x/IMG_0285.jpg", content_hash="h4")
    result2 = ScanResult(total=2, files=[f_cam1, f_cam2])
    check("카메라 원본 번호는 오탐 안 됨", result2.similar_groups() == [])

    # 3) 이미지 지문(퍼셉추얼 해시) 유사도로 그룹핑 — 재압축본처럼 해밍 거리가 가까움
    close_a = _info("C:/y/pic.jpg", phash="cf3032c1b1cecf26", content_hash="h5")
    close_b = _info("C:/y/pic_web.jpg", phash="cf3032c1b1cecf26", content_hash="h6")  # 거리 0
    far = _info("C:/y/other.jpg", phash="802a7f2a7f2a7f80", content_hash="h7")  # 거리 큼
    result3 = ScanResult(total=3, files=[close_a, close_b, far])
    groups3 = result3.similar_groups(threshold=10)
    check("거리가 가까운 두 사진만 그룹핑됨", len(groups3) == 1 and len(groups3[0]) == 2, f"실제={groups3}")
    check("먼 사진은 그룹에 안 들어감", not any(far in g for g in groups3))

    # 4) 임계값을 넘는 거리는 그룹핑 안 됨
    result4 = ScanResult(total=1, files=[close_a, far])
    check("임계값보다 먼 거리는 그룹핑 안 됨", result4.similar_groups(threshold=10) == [])

    # 5) 이미 완전 중복(같은 content_hash)인 파일은 similar_groups에서 제외됨
    # — gui/duplicate_screen.py("중복 파일 보기")가 이미 다루는 영역이라 중복 표시 방지
    dup1 = _info("C:/z/dup1.jpg", content_hash="SAME")
    dup2 = _info("C:/z/dup2.jpg", content_hash="SAME")
    result5 = ScanResult(total=2, files=[dup1, dup2])
    check("완전 중복 파일은 유사 중복 결과에서 제외됨", result5.similar_groups() == [])

    # 6) 파일 하나뿐이면 그룹 없음
    check("파일 1개면 그룹 없음", ScanResult(total=1, files=[close_a]).similar_groups() == [])

    # 7) 서로 다른 신호(파일명 패턴 + 퍼셉추얼 해시)가 전이적으로 하나로 합쳐질 수 있음
    chain_a = _info("C:/w/photo.jpg", phash="cf3032c1b1cecf26", content_hash="hA")
    chain_b = _info("C:/w/photo_1.jpg", phash=None, content_hash="hB")  # 이름 패턴으로만 photo.jpg와 연결
    result7 = ScanResult(total=2, files=[chain_a, chain_b])
    groups7 = result7.similar_groups()
    check("퍼셉추얼 해시 없어도 파일명 패턴만으로 그룹핑됨", len(groups7) == 1 and len(groups7[0]) == 2)


if __name__ == "__main__":  # pytest 없이 이 파일 하나만 돌려보고 싶을 때
    test_scan_result()
    print("OK")
