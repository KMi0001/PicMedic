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
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

if getattr(sys, "frozen", False):
    # PyInstaller로 패키징된 실행 파일: __file__은 임시 압축해제 폴더를 가리키므로
    # 실제 .exe 옆에 로그가 영구적으로 남도록 sys.executable 기준으로 잡는다.
    _BASE_DIR = Path(sys.executable).resolve().parent
else:
    _BASE_DIR = Path(__file__).resolve().parent.parent

LOG_DIR = _BASE_DIR / "logs"
LOG_FILE = LOG_DIR / "picmedic_log.jsonl"


def _write(entry: dict[str, Any]) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    entry = {"timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"), **entry}
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


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


def read_recent_entries(limit: int = 200) -> list[dict[str, Any]]:
    """로그 파일에서 최근 항목을 읽어온다 (KPI 집계·로그 뷰어 등에서 재사용)."""
    if not LOG_FILE.exists():
        return []
    lines = LOG_FILE.read_text(encoding="utf-8").splitlines()
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
    else:
        lines.append(f"Scan: {entry.get('path', '')}")
        lines.append(
            f"Total={entry.get('total', 0)} Normal={entry.get('normal', 0)} "
            f"Mismatch={entry.get('mismatch', 0)} Corrupted={entry.get('corrupted', 0)}"
        )
    return "\n".join(lines)
