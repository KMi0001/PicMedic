"""
scripts/fetch_denoise_assets.py

core/denoise.py("디노이즈")가 쓰는 NAFNet-SIDD-width32 체크포인트를
assets/denoise/에 받아온다. scripts/fetch_deblur_assets.py와 같은 이유로
gdown이 필요하다:
    pip install gdown

실행:
    python scripts/fetch_denoise_assets.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# megvii-research/NAFNet 공식 README의 Google Drive 링크(NAFNet-SIDD-width32.pth)
GDRIVE_FILE_ID = "1lsByk21Xw-6aW7epCwOQxvm6HYCQZPHZ"

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets" / "denoise"
DEST_PATH = ASSETS_DIR / "NAFNet-SIDD-width32.pth"


def main() -> int:
    if DEST_PATH.exists():
        print(f"이미 있음, 건너뜀: {DEST_PATH.relative_to(ASSETS_DIR.parent.parent)}")
        return 0

    try:
        import gdown
    except ImportError:
        print("gdown이 필요합니다: pip install gdown")
        return 1

    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"다운로드 중: Google Drive 파일 {GDRIVE_FILE_ID}")
    gdown.download(id=GDRIVE_FILE_ID, output=str(DEST_PATH), quiet=False)

    if not DEST_PATH.exists():
        print("다운로드에 실패했습니다.")
        return 1

    print(f"저장: {DEST_PATH.relative_to(ASSETS_DIR.parent.parent)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
