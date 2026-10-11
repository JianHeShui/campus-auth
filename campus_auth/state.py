"""认证状态模型与静默重试策略。

三态区分"确定失败"与"暂时无法确认"，避免把超时误判成登录失败。
"""
from __future__ import annotations

import enum
import time


class AuthState(enum.Enum):
    """一次认证尝试的结果状态。"""

    ONLINE = "online"        # 已联网（门户在线 + 外网可达）
    OFFLINE = "offline"      # 明确未联网
    PENDING = "pending"      # 无法确认（超时 / 站点不可达 / 入口失效）
    ERROR = "error"          # 明确失败（账号密码错误 / 需验证码 / 账号失效）


class RetryPolicy:
    """指数退避：60, 120, 240, 300, 300... 秒；恢复后立即重置。"""

    _BACKOFF = (60, 120, 240, 300)

    def __init__(self, cap: int = 300):
        self.cap = cap
        self.failures = 0
        self.next_attempt = 0.0

    def should_try(self, now: float | None = None) -> bool:
        now = now if now is not None else time.monotonic()
        return now >= self.next_attempt

    def on_success(self, now: float | None = None) -> None:
        now = now if now is not None else time.monotonic()
        self.failures = 0
        # 成功后进入低频复核，而不是频繁重登
        self.next_attempt = now + self.cap

    def on_failure(self, now: float | None = None) -> None:
        now = now if now is not None else time.monotonic()
        self.failures += 1
        index = min(self.failures - 1, len(self._BACKOFF) - 1)
        delay = self._BACKOFF[index] if index < len(self._BACKOFF) else self.cap
        self.next_attempt = now + min(delay, self.cap)

    def on_pending(self, now: float | None = None) -> None:
        """无法确认：按失败退避，但不累计硬失败次数（避免快速耗尽档位）。"""
        now = now if now is not None else time.monotonic()
        self.failures = max(0, self.failures - 1)
        self.on_failure(now)

    def reset(self) -> None:
        self.failures = 0
        self.next_attempt = 0.0

    def seconds_until_next(self, now: float | None = None) -> int:
        now = now if now is not None else time.monotonic()
        return max(0, round(self.next_attempt - now))
