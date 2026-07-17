"""限流中间件 - 支持用户/IP双维度限流与爆破防护"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict

from fastapi import Request
from pydantic_settings import BaseSettings, SettingsConfigDict
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)


class RateLimitConfig(BaseSettings):
    """限流配置"""

    model_config = SettingsConfigDict(
        env_prefix="RATE_LIMIT_",
        env_file=".env",
        extra="ignore",
    )

    enabled: bool = True
    requests_per_minute: int = 60
    burst_limit: int = 10
    block_threshold: int = 5
    block_duration_seconds: int = 60
    whitelist_ips: list[str] = []


class TokenBucket:
    """令牌桶算法实现"""

    def __init__(self, rate: float, capacity: int) -> None:
        self.rate = rate
        self.capacity = capacity
        self._tokens: float = float(capacity)
        self._last_update: float = time.monotonic()
        self._lock: asyncio.Lock = asyncio.Lock()

    async def try_acquire(self, tokens: int = 1) -> tuple[bool, float]:
        """
        尝试获取令牌

        Args:
            tokens: 需要获取的令牌数

        Returns:
            (是否成功, 剩余令牌数)
        """
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_update

            self._tokens = min(
                self.capacity,
                self._tokens + elapsed * self.rate,
            )
            self._last_update = now

            if self._tokens >= tokens:
                self._tokens -= tokens
                return True, self._tokens

            return False, self._tokens

    def reset(self) -> None:
        """重置令牌桶"""
        self._tokens = float(self.capacity)
        self._last_update = time.monotonic()

    @property
    def available_tokens(self) -> float:
        """当前可用令牌数"""
        now = time.monotonic()
        elapsed = now - self._last_update
        return min(
            self.capacity,
            self._tokens + elapsed * self.rate,
        )


class RateLimiter:
    """限流管理器 - 支持用户和IP双维度限流"""

    def __init__(self, config: RateLimitConfig) -> None:
        self.config = config

        self._ip_buckets: defaultdict[str, TokenBucket] = defaultdict(
            lambda: TokenBucket(
                rate=config.requests_per_minute / 60.0,
                capacity=config.burst_limit,
            )
        )
        self._user_buckets: defaultdict[str, TokenBucket] = defaultdict(
            lambda: TokenBucket(
                rate=config.requests_per_minute / 60.0,
                capacity=config.burst_limit,
            )
        )

        self._blocked_ips: dict[str, float] = {}
        self._blocked_users: dict[str, float] = {}

        self._failed_attempts_ip: dict[str, tuple[int, float]] = {}
        self._failed_attempts_user: dict[str, tuple[int, float]] = {}

        self._lock: asyncio.Lock = asyncio.Lock()

    async def check_rate_limit(
        self,
        client_ip: str | None = None,
        user_id: str | None = None,
        is_failed_auth: bool = False,
    ) -> tuple[bool, int, float | None]:
        """
        检查限流

        Args:
            client_ip: 客户端IP
            user_id: 用户ID
            is_failed_auth: 是否为认证失败

        Returns:
            (是否允许, 剩余令牌数, 重试等待时间(秒))
        """
        if not self.config.enabled:
            return True, self.config.burst_limit, None

        if client_ip and client_ip in self.config.whitelist_ips:
            return True, self.config.burst_limit, None

        await self._cleanup_blocked()

        if client_ip and client_ip in self._blocked_ips:
            block_end = self._blocked_ips[client_ip]
            retry_after = max(0, block_end - time.monotonic())
            return False, 0, retry_after

        if user_id and user_id in self._blocked_users:
            block_end = self._blocked_users[user_id]
            retry_after = max(0, block_end - time.monotonic())
            return False, 0, retry_after

        if is_failed_auth:
            await self._track_failed_attempt(client_ip, user_id)

            if client_ip and await self._should_block_ip(client_ip):
                await self._block_ip(client_ip)
                return False, 0, self.config.block_duration_seconds

            if user_id and await self._should_block_user(user_id):
                await self._block_user(user_id)
                return False, 0, self.config.block_duration_seconds

        min_remaining = self.config.burst_limit

        if client_ip:
            ip_bucket = self._ip_buckets[client_ip]
            ip_allowed, ip_remaining = await ip_bucket.try_acquire()
            min_remaining = min(min_remaining, int(ip_remaining))
            if not ip_allowed:
                return False, min_remaining, (1 - ip_remaining) * 60 / self.config.requests_per_minute

        if user_id:
            user_bucket = self._user_buckets[user_id]
            user_allowed, user_remaining = await user_bucket.try_acquire()
            min_remaining = min(min_remaining, int(user_remaining))
            if not user_allowed:
                return False, min_remaining, (1 - user_remaining) * 60 / self.config.requests_per_minute

        return True, min_remaining, None

    async def _track_failed_attempt(
        self,
        client_ip: str | None,
        user_id: str | None,
    ) -> None:
        """记录失败尝试"""
        now = time.monotonic()

        if client_ip:
            count, start_time = self._failed_attempts_ip.get(client_ip, (0, now))
            if now - start_time > 60:
                self._failed_attempts_ip[client_ip] = (1, now)
            else:
                self._failed_attempts_ip[client_ip] = (count + 1, start_time)

        if user_id:
            count, start_time = self._failed_attempts_user.get(user_id, (0, now))
            if now - start_time > 60:
                self._failed_attempts_user[user_id] = (1, now)
            else:
                self._failed_attempts_user[user_id] = (count + 1, start_time)

    async def _should_block_ip(self, client_ip: str) -> bool:
        """检查IP是否应被封禁"""
        count, _ = self._failed_attempts_ip.get(client_ip, (0, 0))
        return count >= self.config.block_threshold

    async def _should_block_user(self, user_id: str) -> bool:
        """检查用户是否应被封禁"""
        count, _ = self._failed_attempts_user.get(user_id, (0, 0))
        return count >= self.config.block_threshold

    async def _block_ip(self, client_ip: str) -> None:
        """封禁IP"""
        block_until = time.monotonic() + self.config.block_duration_seconds
        self._blocked_ips[client_ip] = block_until
        logger.warning("IP %s 因爆破攻击被封禁，直到 %s", client_ip, block_until)

    async def _block_user(self, user_id: str) -> None:
        """封禁用户"""
        block_until = time.monotonic() + self.config.block_duration_seconds
        self._blocked_users[user_id] = block_until
        logger.warning("用户 %s 因爆破攻击被封禁，直到 %s", user_id, block_until)

    async def _cleanup_blocked(self) -> None:
        """清理过期的封禁记录"""
        now = time.monotonic()
        self._blocked_ips = {
            ip: end_time
            for ip, end_time in self._blocked_ips.items()
            if end_time > now
        }
        self._blocked_users = {
            user: end_time
            for user, end_time in self._blocked_users.items()
            if end_time > now
        }

    def reset(self, client_ip: str | None = None, user_id: str | None = None) -> None:
        """重置限流状态"""
        if client_ip:
            self._ip_buckets[client_ip].reset()
            self._failed_attempts_ip.pop(client_ip, None)
            self._blocked_ips.pop(client_ip, None)
        if user_id:
            self._user_buckets[user_id].reset()
            self._failed_attempts_user.pop(user_id, None)
            self._blocked_users.pop(user_id, None)


class FastAPIRateLimitMiddleware:
    """FastAPI限流中间件"""

    def __init__(self, app: ASGIApp, config: RateLimitConfig | None = None) -> None:
        self.app = app
        self.config = config or RateLimitConfig()
        self.rate_limiter = RateLimiter(self.config)

    async def __call__(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)
        client_ip = self._get_client_ip(request)
        user_id = self._get_user_id(request)

        allowed, remaining, retry_after = await self.rate_limiter.check_rate_limit(
            client_ip=client_ip,
            user_id=user_id,
        )

        if not allowed:
            headers = {
                "X-RateLimit-Remaining": str(remaining),
            }
            if retry_after:
                headers["Retry-After"] = str(int(retry_after))

            await send(
                {
                    "type": "http.response.start",
                    "status": 429,
                    "headers": [
                        (k.encode(), v.encode()) for k, v in headers.items()
                    ],
                }
            )
            await send({"type": "http.response.body", "body": b""})
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                message["headers"] = [
                    *message.get("headers", []),
                    (b"x-ratelimit-remaining", str(remaining).encode()),
                ]
            await send(message)

        await self.app(scope, receive, send_wrapper)

    def _get_client_ip(self, request: Request) -> str | None:
        """获取客户端IP"""
        x_forwarded_for = request.headers.get("X-Forwarded-For")
        if x_forwarded_for:
            return x_forwarded_for.split(",")[0].strip()

        x_real_ip = request.headers.get("X-Real-IP")
        if x_real_ip:
            return x_real_ip

        host = request.scope.get("client")
        if host is not None:
            return str(host[0])

        return None

    def _get_user_id(self, request: Request) -> str | None:
        """从请求中提取用户ID"""
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            return auth_header[7:]

        return None


def create_rate_limit_middleware(
    config: RateLimitConfig | None = None,
) -> type[FastAPIRateLimitMiddleware]:
    """创建限流中间件工厂"""

    class ConfiguredRateLimitMiddleware(FastAPIRateLimitMiddleware):
        def __init__(self, app: ASGIApp) -> None:
            super().__init__(app, config=config)

    return ConfiguredRateLimitMiddleware
