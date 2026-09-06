"""
experiments/restore_prototype/make_test_image.py

"흐리거나 오래된 사진"을 흉내낸 합성 테스트 이미지를 만든다. 실제 인물 사진이
저장소에 없고, 외부에서 사진을 받아오지 않기 위해(다운로드 승인 필요 사항) 직접
그린 일러스트풍 인물을 인위적으로 열화시키는 방식을 쓴다.

주의: PIL로 그린 그림이라 GFPGAN 같은 "실제 얼굴" 학습 모델에는 불리할 수 있음
— 그래도 블러/노이즈/저해상도/색바램이 섞인 "오래된 사진" 열화를 일관되게
재현할 수 있어 세 가지 복원 방식을 같은 조건에서 비교하기엔 충분하다.

실행:
    python experiments/restore_prototype/make_test_image.py

출력: experiments/restore_prototype/test_images/old_blurry_portrait.jpg
"""

from __future__ import annotations

import random
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT_DIR = Path(__file__).resolve().parent / "test_images"
OUT_PATH = OUT_DIR / "old_blurry_portrait.jpg"

CANVAS_SIZE = (720, 900)  # (w, h) -- 최종 저장 크기


def _draw_sharp_portrait() -> Image.Image:
    """열화시키기 전의 "원본" 일러스트 인물화를 그린다(선명한 상태)."""
    w, h = CANVAS_SIZE
    img = Image.new("RGB", (w, h), (214, 224, 232))  # 밝은 배경
    draw = ImageDraw.Draw(img)

    # 배경 바닥/벽 경계선(단순 실내 배경 느낌)
    draw.rectangle([0, int(h * 0.7), w, h], fill=(196, 188, 168))

    # 어깨/상의
    shoulder_top = int(h * 0.62)
    draw.polygon(
        [
            (w * 0.22, h),
            (w * 0.30, shoulder_top),
            (w * 0.70, shoulder_top),
            (w * 0.78, h),
        ],
        fill=(70, 92, 120),
    )

    # 목
    cx = w * 0.5
    draw.rectangle([cx - 28, shoulder_top - 40, cx + 28, shoulder_top + 10], fill=(226, 190, 162))

    # 얼굴(타원)
    face_cy = h * 0.38
    face_w, face_h = 190, 240
    face_box = [cx - face_w / 2, face_cy - face_h / 2, cx + face_w / 2, face_cy + face_h / 2]
    draw.ellipse(face_box, fill=(230, 195, 168))

    # 귀
    draw.ellipse([cx - face_w / 2 - 14, face_cy - 20, cx - face_w / 2 + 10, face_cy + 30], fill=(226, 190, 162))
    draw.ellipse([cx + face_w / 2 - 10, face_cy - 20, cx + face_w / 2 + 14, face_cy + 30], fill=(226, 190, 162))

    # 머리카락
    hair_box = [cx - face_w / 2 - 16, face_cy - face_h / 2 - 70, cx + face_w / 2 + 16, face_cy - 10]
    draw.pieslice(hair_box, 180, 360, fill=(45, 35, 30))
    draw.rectangle([cx - face_w / 2 - 16, face_cy - face_h / 2 + 20, cx - face_w / 2 + 6, face_cy + 20], fill=(45, 35, 30))
    draw.rectangle([cx + face_w / 2 - 6, face_cy - face_h / 2 + 20, cx + face_w / 2 + 16, face_cy + 20], fill=(45, 35, 30))

    # 눈썹
    draw.line([(cx - 68, face_cy - 30), (cx - 20, face_cy - 36)], fill=(60, 45, 40), width=6)
    draw.line([(cx + 20, face_cy - 36), (cx + 68, face_cy - 30)], fill=(60, 45, 40), width=6)

    # 눈(흰자+눈동자)
    for sign in (-1, 1):
        ex = cx + sign * 42
        ey = face_cy - 8
        draw.ellipse([ex - 22, ey - 12, ex + 22, ey + 12], fill=(250, 250, 248), outline=(120, 100, 90))
        draw.ellipse([ex - 8, ey - 8, ex + 8, ey + 8], fill=(60, 42, 30))
        draw.ellipse([ex - 3, ey - 3, ex + 2, ey + 2], fill=(255, 255, 255))

    # 코
    draw.line([(cx, face_cy - 4), (cx - 10, face_cy + 42)], fill=(190, 150, 128), width=4)
    draw.arc([cx - 22, face_cy + 30, cx + 4, face_cy + 54], 20, 160, fill=(170, 130, 108), width=3)

    # 입
    draw.arc([cx - 34, face_cy + 62, cx + 34, face_cy + 96], 10, 170, fill=(150, 70, 70), width=5)

    # 볼 홍조
    for sign in (-1, 1):
        bx = cx + sign * 74
        by = face_cy + 34
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(overlay).ellipse([bx - 22, by - 14, bx + 22, by + 14], fill=(220, 120, 110, 60))
        img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
        draw = ImageDraw.Draw(img)

    # 날짜 스탬프(오래된 사진 특유의 주황색 타임스탬프 느낌)
    stamp_pos = (w - 150, h - 40)
    try:
        font = ImageFont.load_default(size=26)
    except TypeError:
        font = ImageFont.load_default()
    draw.text(stamp_pos, "'98 8 15", fill=(255, 140, 30), font=font)

    return img


def _apply_old_photo_degradation(img: Image.Image, seed: int = 7) -> Image.Image:
    """선명한 원본에 블러+저해상도+노이즈+색바램+빈티지 스크래치를 입혀 "오래되고
    흐릿한 사진"처럼 만든다."""
    rng = random.Random(seed)
    w, h = img.size

    # 1) 진짜 오래된 사진처럼 원래 해상도가 낮았던 것을 흉내: 작게 줄였다가
    #    다시 늘려서 디테일 손실을 만든다.
    small = img.resize((w // 5, h // 5), Image.BILINEAR)
    img = small.resize((w, h), Image.BILINEAR)

    # 2) 초점이 안 맞은 느낌의 가우시안 블러
    img = img.filter(ImageFilter.GaussianBlur(radius=3.2))

    # 3) 세피아톤(오래된 인화지 색바램)
    arr = np.asarray(img).astype(np.float32)
    sepia_matrix = np.array(
        [
            [0.393, 0.769, 0.189],
            [0.349, 0.686, 0.168],
            [0.272, 0.534, 0.131],
        ]
    )
    sepia = arr @ sepia_matrix.T
    arr = arr * 0.35 + sepia * 0.65
    arr = np.clip(arr, 0, 255)

    # 4) 필름 그레인(노이즈)
    noise = rng.gauss  # 재현 가능한 노이즈를 위해 numpy 대신 seeded random 사용
    noise_arr = np.random.RandomState(seed).normal(0, 9, arr.shape)
    arr = np.clip(arr + noise_arr, 0, 255).astype(np.uint8)
    img = Image.fromarray(arr, mode="RGB")

    # 5) 비네트(가장자리 어둡게)
    yy, xx = np.mgrid[0:h, 0:w]
    cx, cy = w / 2, h / 2
    dist = np.sqrt(((xx - cx) / (w / 2)) ** 2 + ((yy - cy) / (h / 2)) ** 2)
    vignette = np.clip(1.15 - 0.35 * dist, 0.6, 1.0)
    arr = np.asarray(img).astype(np.float32) * vignette[..., None]
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), mode="RGB")

    # 6) 랜덤 스크래치 몇 개(밝은 얇은 선)
    draw = ImageDraw.Draw(img)
    for _ in range(6):
        x0 = rng.uniform(0, w)
        y0 = rng.uniform(0, h)
        length = rng.uniform(60, h * 0.6)
        angle = rng.uniform(-0.3, 0.3) + 1.5708
        x1 = x0 + length * np.cos(angle)
        y1 = y0 + length * np.sin(angle)
        brightness = rng.randint(200, 245)
        draw.line([(x0, y0), (x1, y1)], fill=(brightness, brightness, brightness - 10), width=1)

    return img


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sharp = _draw_sharp_portrait()
    degraded = _apply_old_photo_degradation(sharp)
    degraded.save(OUT_PATH, quality=72)  # 낮은 JPEG 품질로 압축 손상까지 더함
    print(f"생성 완료: {OUT_PATH} ({degraded.size[0]}x{degraded.size[1]})")


if __name__ == "__main__":
    main()
