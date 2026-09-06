"""
scripts/fetch_deblur_assets.py

core/deblur.py("디블러/디노이즈")가 쓰는 NAFNet-GoPro-width32 체크포인트를
assets/deblur/에 받아온다. 이 파일은 크기(약 68MB) 때문에 git에는 커밋하지
않으므로(.gitignore 참고), 새로 체크아웃했거나 지웠다면 이 스크립트로 다시
받으면 된다.

megvii-research/NAFNet 공식 저장소가 이 가중치를 GitHub Releases가 아니라
구글드라이브로만 배포해서(scripts/fetch_realesrgan_assets.py·
fetch_face_restore_assets.py처럼 단순 urlretrieve로는 안 됨 — 대용량 파일의
"바이러스 검사 못 함" 확인 페이지를 gdown이 대신 처리해준다), 이 스크립트만
gdown이 추가로 필요하다:
    pip install gdown

실행:
    python scripts/fetch_deblur_assets.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# megvii-research/NAFNet 공식 README의 Google Drive 링크(NAFNet-GoPro-width32.pth)
GDRIVE_FILE_ID = "1Fr2QadtDCEXg6iwWX8OzeZLbHOx2t5Bj"

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets" / "deblur"
DEST_PATH = ASSETS_DIR / "NAFNet-GoPro-width32.pth"


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
