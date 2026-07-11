from __future__ import annotations

from datetime import datetime
from typing import Any
from pathlib import Path


def _ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _log_file() -> Path:
    base_dir = Path(__file__).resolve().parent
    logs_dir = base_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir / "run.log"


def _write(line: str) -> None:
    # 终端打印：确保在任何情况下都能看到输出
    print(line)
    # 文件追加写入：尽最大努力，但不影响主流程
    try:
        fpath = _log_file()
        with fpath.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def log_start(msg: str = "开始") -> None:
    _write(f"[{_ts()}] {msg}")


def log_success(msg: str = "成功") -> None:
    _write(f"[{_ts()}] {msg}")


def log_failure(err: Any, msg: str = "失败") -> None:
    # 只负责记录，不吞异常；由 main.py 决定是否 raise
    _write(f"[{_ts()}] {msg}: {err}")

