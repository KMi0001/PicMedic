"""
scripts/fetch_photo_category_assets.py

core/photo_category.py("사진 진단"의 카테고리 판단)가 쓰는 CLIP ViT-B/32
가중치를 assets/photo_category/에 받아온다. OpenAI 공식 CDN에서 바로 받을 수
있어(구글드라이브 아님) 다른 fetch 스크립트들처럼 단순 urlretrieve로 된다.

실행:
    python scripts/fetch_photo_category_assets.py
"""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

# open_clip.get_pretrained_cfg("ViT-B-32", "openai")["url"]과 동일(OpenAI 공식 CDN).
CLIP_URL = (
    "https://openaipublic.azureedge.net/clip/models/"
    "40d365715913c9da98579312b702a82c18be219cc2a73407c4526f58eba950af/ViT-B-32.pt"
)

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets" / "photo_category"
DEST_PATH = ASSETS_DIR / "ViT-B-32.pt"


def main() -> int:
    if DEST_PATH.exists():
        print(f"이미 있음, 건너뜀: {DEST_PATH.relative_to(ASSETS_DIR.parent.parent)}")
        return 0

    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"다운로드 중: {CLIP_URL}")
    urllib.request.urlretrieve(CLIP_URL, DEST_PATH)
    print(f"저장: {DEST_PATH.relative_to(ASSETS_DIR.parent.parent)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
