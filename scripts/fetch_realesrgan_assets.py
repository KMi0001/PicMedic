"""
scripts/fetch_realesrgan_assets.py

core/quality_enhancer.py(화질 개선)가 쓰는 Real-ESRGAN 실행 파일 + 모델을
assets/realesrgan/에 받아온다. 이 파일들은 크기(수십MB) 때문에 git에는
커밋하지 않으므로(.gitignore 참고), 새로 체크아웃했거나 지웠다면 이 스크립트로
다시 받으면 된다.

주의: 최신 xinntao/Real-ESRGAN-ncnn-vulkan 저장소의 공식 릴리스는 실행 파일만
있고 모델 가중치가 빠져 있어서, 모델까지 같이 묶여 있던 마지막 버전인
원조 저장소(xinntao/Real-ESRGAN) v0.2.5.0 릴리스에서 받는다(둘 다 같은
제작자의 공식 GitHub — 서드파티 미러 아님).

실행:
    python scripts/fetch_realesrgan_assets.py

현재 Windows용 실행 파일만 지원한다. macOS는 별도 바이너리가 필요하며 아직
준비되지 않았다(PLATFORM_EXPANSION 관련 — 이 기능을 macOS에서도 쓰려면 추가
조사 필요).
"""

from __future__ import annotations

import sys
import urllib.request
import zipfile
from pathlib import Path

RELEASE_URL = (
    "https://github.com/xinntao/Real-ESRGAN/releases/download/"
    "v0.2.5.0/realesrgan-ncnn-vulkan-20220424-windows.zip"
)

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets" / "realesrgan"

# zip 안에서 실제로 필요한 파일만 골라 받는다(애니메이션 모델·데모 이미지 등은
# 안 씀 — core/quality_enhancer.py가 realesrgan-x4plus만 사용).
WANTED = {
    "realesrgan-ncnn-vulkan.exe": ASSETS_DIR / "realesrgan-ncnn-vulkan.exe",
    "vcomp140.dll": ASSETS_DIR / "vcomp140.dll",
    "vcomp140d.dll": ASSETS_DIR / "vcomp140d.dll",
    "models/realesrgan-x4plus.bin": ASSETS_DIR / "models" / "realesrgan-x4plus.bin",
    "models/realesrgan-x4plus.param": ASSETS_DIR / "models" / "realesrgan-x4plus.param",
}


def main() -> int:
    if sys.platform != "win32":
        print("이 스크립트는 현재 Windows용 자산만 받아옵니다. macOS 바이너리는 아직 준비되지 않았습니다.")
        return 1

    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    (ASSETS_DIR / "models").mkdir(parents=True, exist_ok=True)

    zip_path = ASSETS_DIR / "_download.zip"
    print(f"다운로드 중: {RELEASE_URL}")
    urllib.request.urlretrieve(RELEASE_URL, zip_path)

    print("압축 해제 중...")
    with zipfile.ZipFile(zip_path) as z:
        for member, dest in WANTED.items():
            dest.parent.mkdir(parents=True, exist_ok=True)
            with z.open(member) as src, open(dest, "wb") as out:
                out.write(src.read())
            print(f"  {dest.relative_to(ASSETS_DIR.parent.parent)}")

    zip_path.unlink()
    print("완료.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
