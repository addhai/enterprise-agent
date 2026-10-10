"""登录失败锁定（2026-10 P0-6 收口 H4 暴力破解面）

按用户名维度记录连续失败次数：达到阈值后在锁定窗口内直接拒绝登录尝试，
无论密码是否正确（防止挂着密码字典反复试）。

部署形态的诚实说明：
    本实现为进程内计数，单副本 / gunicorn 单 worker 部署有效；
    多副本或多 worker 下计数不共享，阈值会按副本数被放大。
    当前生产为单副本部署，满足收敛目标；多副本化时应把存储换成
    Redis INCR + EX（配置项与阈值已在 settings 暴露，便于平滑迁移）。

计数器只保留窗口内时间戳，成功登录即清空，锁定状态由最近一次失败时间
推导，进程重启后锁定解除（可接受的可用性取舍，优先避免锁死运维）。
"""

from __future__ import annotations

import threading
import time


class LoginGuard:
    def __init__(self, max_failures: int = 5, lockout_seconds: int = 900) -> None:
        self._max_failures = max(1, max_failures)
        self._lockout_seconds = lockout_seconds
        self._failures: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _now(self) -> float:
        return time.monotonic()

    def _recent_failures(self, key: str) -> list[float]:
        """剔除超出锁定窗口的旧记录，返回窗口内失败时间戳。"""
        now = self._now()
        timeline = self._failures.get(key, [])
        fresh = [t for t in timeline if now - t < self._lockout_seconds]
        if fresh:
            self._failures[key] = fresh
        else:
            self._failures.pop(key, None)
        return fresh

    def locked_seconds(self, key: str) -> int:
        """剩余锁定秒数；未锁定返回 0。"""
        with self._lock:
            timeline = self._recent_failures(key)
            if len(timeline) < self._max_failures:
                return 0
            elapsed = self._now() - timeline[-1]
            remaining = self._lockout_seconds - elapsed
            if remaining <= 0:
                return 0
            # 向上取整，避免界面显示「剩余 0 秒」却仍在锁
            return int(remaining) + 1

    def is_locked(self, key: str) -> bool:
        return self.locked_seconds(key) > 0

    def record_failure(self, key: str) -> int:
        """记一次失败，返回当前窗口内连续失败次数。"""
        with self._lock:
            timeline = self._recent_failures(key)
            timeline.append(self._now())
            self._failures[key] = timeline
            return len(timeline)

    def record_success(self, key: str) -> None:
        """登录成功后清空计数。"""
        with self._lock:
            self._failures.pop(key, None)

    def reset(self) -> None:
        """测试/运维用：清空全部计数。"""
        with self._lock:
            self._failures.clear()


# 模块级单例（settings 在首次构造时读取，测试可直接 reset）
def _build_default_guard() -> LoginGuard:
    from src.config import settings

    return LoginGuard(
        max_failures=getattr(settings, "login_max_failures", 5),
        lockout_seconds=getattr(settings, "login_lockout_minutes", 15) * 60,
    )


_guard: LoginGuard | None = None


def get_login_guard() -> LoginGuard:
    global _guard
    if _guard is None:
        _guard = _build_default_guard()
    return _guard
