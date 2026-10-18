"""认证调试日志：统一脱敏、轮转与写入。

认证链路（client/cas）的所有日志都集中在这里，避免各模块各写一份：
- 写入前强制脱敏：账号、密码、AES 密钥、密文、sessionId、ticket、Cookie 等都不落明文；
- 按大小轮转：单文件超过 2MB 即转存为 auth-debug.log.1，避免日志无限增长；
- 写失败静默：日志绝不能影响认证主流程。
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path

LOG_PATH = Path(os.environ.get("CAMPUS_AUTH_LOG", Path.home() / ".campus-auth" / "auth-debug.log"))
MAX_BYTES = 2 * 1024 * 1024  # 单文件上限 2MB

# 日志里必须打码的字段：JSON、form 表单、URL 查询串、纯文本都覆盖
_SCRUB_RULES = (
    (re.compile(r'(?i)("?(?:username|userName|userid|userId)"?\s*[:=]\s*["\']?)([^"\',&\s}]{2,})'), r"\1***"),
    (re.compile(r'(?i)("?(?:password|userPwd|userpwd|passwd)"?\s*[:=]\s*["\']?)([^"\',&\s}]{2,})'), r"\1***"),
    (re.compile(r'(?i)("?(?:croypto|execution|login-page-flowkey)"?\s*[:=]\s*["\']?)([^"\',&\s}]{4,})'), r"\1***"),
    (re.compile(r'(?i)("?(?:sessionId|flowSessionId|flowKey|userIndex)"?\s*[:=]\s*["\']?)([^"\',&\s}]{4,})'), r"\1***"),
    (re.compile(r'(?i)("?ticket"?\s*[:=]\s*["\']?)([^"\',&\s}]{4,})'), r"\1***"),
    (re.compile(r'(?i)(cookie\s*[:=]\s*)([^\s"\']{4,})'), r"\1***"),
)


def mask(value: str, keep: int = 2) -> str:
    """把敏感值打码：保留首尾各 keep 个字符，中间用 *** 代替。"""
    if not value:
        return ""
    value = str(value)
    if len(value) <= keep * 2:
        return "***"
    return f"{value[:keep]}***{value[-keep:]}"


def scrub(text: str) -> str:
    """对一段日志文本做字段级脱敏（账号/密码/密钥/会话 token 等）。"""
    if not text:
        return text
    result = str(text)
    for pattern, replacement in _SCRUB_RULES:
        result = pattern.sub(replacement, result)
    return result


def _rotate_if_needed() -> None:
    """日志超过上限时轮转（保留最近一份 .1）。"""
    try:
        if LOG_PATH.exists() and LOG_PATH.stat().st_size > MAX_BYTES:
            backup = LOG_PATH.with_name(LOG_PATH.name + ".1")
            os.replace(LOG_PATH, backup)
    except OSError:
        pass


def write_log(msg: str) -> None:
    """追加写一条已脱敏的调试日志（失败静默，不影响认证）。"""
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        _rotate_if_needed()
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except OSError:
        pass


def write_scrubbed_log(msg: str) -> None:
    """先脱敏再写入（调用方无需自己处理敏感字段）。"""
    write_log(scrub(msg))
