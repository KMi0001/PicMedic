"""
utils/logger.py

PRD 22장 FR-006 "로그" 구현.
스캔/복구 작업 결과를 logs/picmedic_log.jsonl에 한 줄씩(JSON Lines) 기록한다.

예시(PRD FR-006):
    2026-08-28 16:20
    IMG_001.jpg
    Detected: HEIC
    Action: Converted to JPEG
    Result: SUCCESS
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


def _user_data_dir() -> Path:
    """사용자별로 앱이 자유롭게 쓸 수 있는 데이터 폴더.

    CLAUDE.md는 기본 경로를 QStandardPaths로 가져오라고 하지만, 이 모듈은
    core/scanner.py·core/converter.py가 import하는 경로에 있어서 여기서 PySide6를
    import하면 "core/에 Qt 의존이 없다"는 보장(PLATFORM_EXPANSION.md의 웹 확장
    계획이 통째로 이 보장 위에 서 있다)이 깨진다. 그래서 여기서만 예외적으로
    표준 환경변수로 직접 구한다 — CLAUDE.md가 허용하는 "최소 범위 sys.platform 분기".
    """
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            return Path(base) / "PicMedic"
    elif sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "PicMedic"
    xdg = os.environ.get("XDG_DATA_HOME")
    return (Path(xdg) if xdg else Path.home() / ".local" / "share") / "PicMedic"


if getattr(sys, "frozen", False):
    # PyInstaller로 패키징된 실행 파일: 실행 파일 옆(sys.executable 기준)에 쓰면
    # 안 된다 — MS 스토어(MSIX/WindowsApps)나 Program Files에 설치되면 그 폴더가
    # 읽기 전용이라 mkdir/open이 PermissionError를 던지고, 그 예외가 아래
    # log_scan()을 호출하는 core/scanner.py::scan_paths까지 그대로 올라가
    # "검사가 끝나는 순간 조용히 멈추는" 증상이 된다(2026-09-11 리뷰에서 발견).
    # 로컬에서 zip으로 풀어 쓰는 배포에서는 재현되지 않아서 놓치기 쉬운 경로다.
    _BASE_DIR = _user_data_dir()
else:
    _BASE_DIR = Path(__file__).resolve().parent.parent

LOG_DIR = _BASE_DIR / "logs"
LOG_FILE = LOG_DIR / "picmedic_log.jsonl"


def _write(entry: dict[str, Any]) -> None:
    # 로그는 FR-006의 부가 기능이라, 기록에 실패한다고 해서 진행 중인 검사·복구
    # 자체가 실패하면 안 된다(위 _BASE_DIR 주석 참고 — 쓰기 금지 폴더, 디스크
    # 가득 참, 권한 없음 등). 실패하면 조용히 넘어간다.
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        entry = {"timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"), **entry}
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        return


def log_scan(root_path: str, result) -> None:
    """PRD 12장 '일괄 처리' — 폴더 스캔 1회의 결과를 기록한다."""
    _write(
        {
            "type": "scan",
            "path": root_path,
            "total": result.total,
            "normal": result.normal,
            "mismatch": result.mismatch,
            "partial_corruption": result.partial_corruption,
            "corrupted": result.corrupted,
            "unsupported": result.unsupported,
        }
    )


def log_recovery(outcome) -> None:
    """PRD FR-006 예시(파일별 Detected/Action/Result)를 그대로 기록한다."""
    _write(
        {
            "type": "recovery",
            "filename": outcome.original.filename,
            "detected": outcome.original.detected_format,
            "action": outcome.mode.value,
            "target_format": getattr(outcome, "target_format", None),
            "result": outcome.label,
            "output_path": outcome.output_path,
            "error": outcome.error_message,
        }
    )


def log_rename(outcome) -> None:
    """"이름 일괄변경"(core/renamer.py::rename_batch) 파일 하나의 결과를 기록한다."""
    _write(
        {
            "type": "rename",
            "filename": outcome.original.filename,
            "new_path": outcome.new_path,
            "result": "SUCCESS" if outcome.success else "FAILED",
            "error": outcome.error_message,
        }
    )


def read_recent_entries(limit: int = 200) -> list[dict[str, Any]]:
    """로그 파일에서 최근 항목을 읽어온다 (KPI 집계·로그 뷰어 등에서 재사용)."""
    try:
        if not LOG_FILE.exists():
            return []
        lines = LOG_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:  # _write와 같은 이유 — 로그를 못 읽는다고 화면이 깨지면 안 된다
        return []
    entries = []
    for line in lines[-limit:]:
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def format_entry_text(entry: dict[str, Any]) -> str:
    """항목 하나를 PRD FR-006 예시와 같은 사람이 읽기 쉬운 텍스트 블록으로 바꾼다."""
    lines = [entry.get("timestamp", "")]
    if entry.get("type") == "recovery":
        lines.append(entry.get("filename", ""))
        lines.append(f"Detected: {entry.get('detected') or '알 수 없음'}")
        action = entry.get("action", "")
        if entry.get("target_format"):
            action += f" ({entry['target_format']})"
        lines.append(f"Action: {action}")
        lines.append(f"Result: {entry.get('result', '')}")
    elif entry.get("type") == "rename":
        lines.append(entry.get("filename", ""))
        lines.append(f"Action: 이름 변경 -> {entry.get('new_path') or '(실패)'}")
        lines.append(f"Result: {entry.get('result', '')}")
    else:
        lines.append(f"Scan: {entry.get('path', '')}")
        lines.append(
            f"Total={entry.get('total', 0)} Normal={entry.get('normal', 0)} "
            f"Mismatch={entry.get('mismatch', 0)} Corrupted={entry.get('corrupted', 0)}"
        )
    return "\n".join(lines)
