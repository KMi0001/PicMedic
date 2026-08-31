"""
models/scan_result.py

PRD 27장 "데이터 모델" ScanResult 구현.
폴더 검사 한 번의 전체 결과(집계 + 개별 파일 목록)를 담는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from models.file_info import FileInfo, FileStatus

_COUNTER_BY_STATUS = {
    FileStatus.NORMAL: "normal",
    FileStatus.MISMATCH: "mismatch",
    FileStatus.PARTIAL_CORRUPTION: "partial_corruption",
    FileStatus.CORRUPTED: "corrupted",
    FileStatus.UNSUPPORTED: "unsupported",
    FileStatus.NOT_AN_IMAGE: "not_an_image",
    FileStatus.RECOVERED: "recovered",
}


@dataclass
class ScanResult:
    total: int = 0
    normal: int = 0
    mismatch: int = 0
    partial_corruption: int = 0
    corrupted: int = 0
    unsupported: int = 0
    not_an_image: int = 0
    recovered: int = 0
    files: list[FileInfo] = field(default_factory=list)

    def add(self, info: FileInfo) -> None:
        self.total += 1
        self.files.append(info)
        counter = _COUNTER_BY_STATUS.get(info.status)
        if counter:
            setattr(self, counter, getattr(self, counter) + 1)

    def mark_recovered(self, info: FileInfo) -> None:
        """복구가 성공한 파일의 상태를 '복구 완료'로 바꾸고 집계도 맞춰 조정한다."""
        old_counter = _COUNTER_BY_STATUS.get(info.status)
        if old_counter and old_counter != "recovered":
            setattr(self, old_counter, max(0, getattr(self, old_counter) - 1))
        info.status = FileStatus.RECOVERED
        self.recovered += 1

    def recoverable_files(self) -> list[FileInfo]:
        """복구 가능/부분 복구 가능한 파일만 반환 (PRD '복구 가능한 파일 보기')"""
        return [
            f
            for f in self.files
            if f.status in (FileStatus.MISMATCH, FileStatus.PARTIAL_CORRUPTION)
        ]

    def by_status(self, status: FileStatus) -> list[FileInfo]:
        return [f for f in self.files if f.status == status]

    def remove(self, info: FileInfo) -> None:
        """파일 하나를 결과에서 완전히 뺀다(Phase 2 중복 정리로 임시 휴지통에
        옮겼을 때 사용). 이걸 안 하면 content_hash는 그대로 남아있어서, 옮긴
        파일을 다시 검사한 적도 없는데 duplicate_groups()가 계속 같은 그룹을
        보여준다 — 원본은 항상 보존되니 이건 '검사 결과 목록'에서만 지우는
        것이지 실제 파일 삭제가 아니다."""
        try:
            self.files.remove(info)
        except ValueError:
            return
        self.total = max(0, self.total - 1)
        counter = _COUNTER_BY_STATUS.get(info.status)
        if counter:
            setattr(self, counter, max(0, getattr(self, counter) - 1))

    def duplicate_groups(self) -> list[list[FileInfo]]:
        """content_hash가 같은 파일들을 그룹으로 묶어 반환한다(Phase 2 '정확 중복'
        탐지). 파일이 2개 이상 모인 그룹만 반환 — 혼자인 해시는 중복이 아니므로
        제외."""
        groups: dict[str, list[FileInfo]] = {}
        for f in self.files:
            if f.content_hash:
                groups.setdefault(f.content_hash, []).append(f)
        return [group for group in groups.values() if len(group) > 1]

    def merge(self, other: "ScanResult") -> "ScanResult":
        """이어서 검사한 결과(other)를 이 결과 뒤에 합친 새 ScanResult를 반환한다."""
        return ScanResult(
            total=self.total + other.total,
            normal=self.normal + other.normal,
            mismatch=self.mismatch + other.mismatch,
            partial_corruption=self.partial_corruption + other.partial_corruption,
            corrupted=self.corrupted + other.corrupted,
            unsupported=self.unsupported + other.unsupported,
            not_an_image=self.not_an_image + other.not_an_image,
            recovered=self.recovered + other.recovered,
            files=list(self.files) + list(other.files),
        )
