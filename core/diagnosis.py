import cv2
import numpy as np


class DiagnosisEngine:

    def analyze(self, image_path):

        image = cv2.imread(image_path)

        if image is None:
            raise ValueError("이미지를 읽을 수 없습니다.")

        height, width = image.shape[:2]

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        brightness = float(np.mean(gray))

        noise = float(np.std(gray))

        return {
            "width": width,
            "height": height,
            "brightness": brightness,
            "noise": noise,
        }