import os
from PIL import Image
from pillow_heif import register_heif_opener

register_heif_opener()


def convert_heic_to_jpg(path):
    """
    HEIC -> JPG 변환 (기존 파일 유지)
    """
    try:
        img = Image.open(path)

        new_path = os.path.splitext(path)[0] + ".jpg"
        img.convert("RGB").save(new_path, "JPEG")

        return new_path

    except Exception as e:
        print("HEIC 변환 실패:", e)
        return path