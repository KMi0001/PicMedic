"""
FileInfo 데이터 모델

PRD 27장 "데이터 모델" 기준으로 작성됨.
검사(스캔)된 파일 하나에 대한 모든 진단 정보를 담는다.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class FileStatus(str, Enum):
    """PRD 8장 '파일 상태 분류' 기준"""

    NORMAL = "정상"                      # 확장자와 실제 형식 일치 + 정상 디코딩
    MISMATCH = "형식_불일치"              # 확장자 != 실제 형식이지만 디코딩은 가능
    PARTIAL_CORRUPTION = "부분_손상"       # 일부만 디코딩 가능
    CORRUPTED = "손상"                    # 디코딩 완전 실패
    UNSUPPORTED = "지원되지_않는_형식"      # PicMedic이 다루지 않는 형식
    NOT_AN_IMAGE = "이미지가_아닌_파일"     # 확장자만 이미지, 실제로는 이미지가 아님
    UNKNOWN = "알_수_없음"                 # 분석 전/오류로 판단 불가
    RECOVERED = "복구_완료"                # 복구(확장자 복원/변환)가 성공적으로 끝난 파일


class RecoveryPossibility(str, Enum):
    """PRD 10.2 '복구 가능성 표시' 기준"""

    RECOVERABLE = "복구_가능"
    PARTIALLY_RECOVERABLE = "부분_복구_가능"
    NOT_RECOVERABLE = "복구_불가능"
    NOT_APPLICABLE = "해당없음"  # 이미 정상인 파일 등


@dataclass
class FileInfo:
    # --- 기본 정보 ---
    path: str
    filename: str
    extension: str                       # 파일명에서 추출한 확장자 (예: ".jpg")

    # --- 분석 결과 ---
    detected_format: Optional[str] = None    # 실제로 감지된 형식 (예: "HEIC")
    mime_type: Optional[str] = None
    file_size: int = 0                       # bytes
    content_hash: Optional[str] = None       # 파일 내용 SHA-256 (Phase 2 '정확 중복' 탐지용)

    # --- 이미지 속성 (디코딩 성공 시에만 채워짐) ---
    width: Optional[int] = None
    height: Optional[int] = None
    metadata: dict = field(default_factory=dict)   # EXIF 등

    # --- 진단 결과 ---
    status: FileStatus = FileStatus.UNKNOWN
    readable: bool = False
    is_mismatched: bool = False              # 확장자 vs 실제 형식 불일치 여부
    corruption_ratio: Optional[float] = None  # 0.0(정상) ~ 1.0(완전 손상) 추정치
    recoverable: RecoveryPossibility = RecoveryPossibility.NOT_APPLICABLE
    error_message: Optional[str] = None

    def summary(self) -> str:
        """사람이 읽기 쉬운 1줄 요약 (CLI/로그용)"""
        mismatch_note = ""
        if self.is_mismatched and self.detected_format:
            mismatch_note = f" (확장자={self.extension} / 실제={self.detected_format})"
        return f"[{self.status.value}] {self.filename}{mismatch_note}"
