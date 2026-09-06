"""
scripts/fetch_face_restore_assets.py

core/face_restorer.py("얼굴 복원")가 쓰는 RestoreFormer++ 체크포인트와
facexlib(얼굴 탐지/파싱) 가중치를 assets/face_restore/에 받아온다. 이 파일들은
크기(수백MB) 때문에 git에는 커밋하지 않으므로(.gitignore 참고), 새로
체크아웃했거나 지웠다면 이 스크립트로 다시 받으면 된다.

전부 공식 GitHub Releases에서 받는다(서드파티 미러 아님):
- RestoreFormer++.ckpt — wzhouxiff/RestoreFormerPlusPlus
- detection_Resnet50_Final.pth, parsing_parsenet.pth — xinntao/facexlib
  (facexlib 패키지 자체가 런타임에 자동 다운로드하는 것과 같은 파일이지만,
  PicMedic은 오프라인에서도 동작해야 하므로 빌드 시점에 미리 받아 둔다 —
  core/face_restorer.py가 facexlib에 이 로컬 경로를 먼저 쓰라고 알려준다.)

실행:
    python scripts/fetch_face_restore_assets.py
"""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets" / "face_restore"
FACEXLIB_DIR = ASSETS_DIR / "facexlib"

FILES = {
    ASSETS_DIR / "RestoreFormer++.ckpt": (
        "https://github.com/wzhouxiff/RestoreFormerPlusPlus/releases/download/v1.0.0/RestoreFormer++.ckpt"
    ),
    FACEXLIB_DIR / "detection_Resnet50_Final.pth": (
        "https://github.com/xinntao/facexlib/releases/download/v0.1.0/detection_Resnet50_Final.pth"
    ),
    FACEXLIB_DIR / "parsing_parsenet.pth": (
        "https://github.com/xinntao/facexlib/releases/download/v0.2.2/parsing_parsenet.pth"
    ),
}


def _download(url: str, dest: Path) -> None:
    if dest.exists():
        print(f"  이미 있음, 건너뜀: {dest.relative_to(ASSETS_DIR.parent.parent)}")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"다운로드 중: {url}")
    urllib.request.urlretrieve(url, dest)
    print(f"  저장: {dest.relative_to(ASSETS_DIR.parent.parent)}")


def main() -> int:
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    FACEXLIB_DIR.mkdir(parents=True, exist_ok=True)
    for dest, url in FILES.items():
        _download(url, dest)
    print("완료.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
