"""安全工具与熔断器测试 - security / circuit_breaker / trace_context / logging_setup"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

import pytest

from zhihu_downloader.core.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerOpenError,
    CircuitState,
)
from zhihu_downloader.utils.logging_setup import get_logger, setup_logging
from zhihu_downloader.utils.security import (
    is_safe_path,
    mask_cookie,
    mask_token,
    sanitize_url,
    validate_url,
)
from zhihu_downloader.utils.trace_context import (
    get_trace_id,
    new_trace_id,
    reset_trace_id,
    set_trace_id,
    trace_context,
)

# ---------------------------------------------------------------------------
# security 测试
# ---------------------------------------------------------------------------


class TestMaskCookie:
    """Cookie 脱敏测试"""

    def test_mask_sensitive_keys(self) -> None:
        """敏感 key 应被脱敏"""
        result = mask_cookie(
            {"z_c0": "abcdefghijklmnopqrstuvwxyz", "other": "keep"}
        )
        assert result["z_c0"] == "abcd***wxyz"
        assert result["other"] == "keep"

    def test_mask_case_insensitive(self) -> None:
        """敏感 key 大小写不敏感"""
        result = mask_cookie({"Z_C0": "abcdefghijklmnopqrstuvwxyz"})
        assert "***" in result["Z_C0"]

    def test_mask_multiple_sensitive(self) -> None:
        """多个敏感 key 都应脱敏"""
        result = mask_cookie(
            {"z_c0": "abcdefghijklmnop", "d_c0": "abcdefghijklmnop", "token": "abcdefghijklmnop"}
        )
        for v in result.values():
            assert "***" in v


class TestMaskToken:
    """Token 脱敏测试"""

    def test_mask_long_token(self) -> None:
        """长 token 保留首尾各4"""
        assert mask_token("abcdefghijklmnopqrstuvwxyz") == "abcd***wxyz"

    def test_mask_short_token(self) -> None:
        """短 token 全部掩码"""
        assert mask_token("short") == "***"

    def test_mask_empty(self) -> None:
        """空 token 保持空"""
        assert mask_token("") == ""


class TestValidateUrl:
    """URL 校验测试（防 SSRF）"""

    def test_valid_zhihu(self) -> None:
        assert validate_url("https://www.zhihu.com/x") is True
        assert validate_url("https://zhihu.com/x") is True
        assert validate_url("https://zhuanlan.zhihu.com/p/123") is True

    def test_invalid_scheme(self) -> None:
        assert validate_url("ftp://zhihu.com/x") is False
        assert validate_url("file:///etc/passwd") is False

    def test_invalid_host(self) -> None:
        assert validate_url("http://127.0.0.1/x") is False
        assert validate_url("http://localhost/x") is False
        assert validate_url("http://evil.com/x") is False

    def test_subdomain_not_allowed(self) -> None:
        """非白名单子域名应拒绝"""
        assert validate_url("https://evil.zhihu.com/x") is False


class TestSanitizeUrl:
    """URL 敏感参数脱敏测试"""

    def test_sanitize_query(self) -> None:
        url = "https://www.zhihu.com/x?token=secret&keep=ok"
        result = sanitize_url(url)
        assert "secret" not in result
        # 脱敏值可能被 urlencode，检查原始 secret 已移除
        assert "keep=ok" in result

    def test_sanitize_password(self) -> None:
        url = "https://www.zhihu.com/x?password=mypass"
        result = sanitize_url(url)
        assert "mypass" not in result


class TestIsSafePath:
    """路径穿越防护测试"""

    def test_safe_path(self, tmp_path: Path) -> None:
        """正常路径应通过"""
        safe = is_safe_path(str(tmp_path / "file.txt"), str(tmp_path))
        assert safe is True

    def test_path_traversal(self, tmp_path: Path) -> None:
        """穿越路径应被拒绝"""
        unsafe = is_safe_path(str(tmp_path / ".." / "etc" / "passwd"), str(tmp_path))
        assert unsafe is False


# ---------------------------------------------------------------------------
# circuit_breaker 测试
# ---------------------------------------------------------------------------


class TestCircuitBreaker:
    """熔断器测试"""

    @pytest.mark.asyncio
    async def test_open_after_threshold(self) -> None:
        """达到失败阈值应熔断"""
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=60)

        async def fail() -> None:
            raise ValueError("fail")

        for _ in range(2):
            with pytest.raises(ValueError):
                await cb.call(fail)

        assert cb.state == CircuitState.OPEN

        with pytest.raises(CircuitBreakerOpenError):
            await cb.call(fail)

    @pytest.mark.asyncio
    async def test_reset_to_closed(self) -> None:
        """手动 reset 应恢复 CLOSED"""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=60)

        async def fail() -> None:
            raise ValueError("fail")

        with pytest.raises(ValueError):
            await cb.call(fail)

        assert cb.is_open
        cb.reset()
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_half_open_recovery(self) -> None:
        """超时后 HALF_OPEN 试探成功应恢复 CLOSED"""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.1)

        async def fail() -> None:
            raise ValueError("fail")

        async def success() -> str:
            return "ok"

        with pytest.raises(ValueError):
            await cb.call(fail)

        assert cb.is_open

        # 等待恢复超时
        await asyncio.sleep(0.15)

        # HALF_OPEN 试探成功
        result = await cb.call(success)
        assert result == "ok"
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_half_open_failure_reopens(self) -> None:
        """HALF_OPEN 试探失败应重新 OPEN"""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.1)

        async def fail() -> None:
            raise ValueError("fail")

        with pytest.raises(ValueError):
            await cb.call(fail)

        await asyncio.sleep(0.15)

        with pytest.raises(ValueError):
            await cb.call(fail)

        assert cb.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_success_resets_failure_count(self) -> None:
        """成功应重置失败计数"""
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60)

        async def fail() -> None:
            raise ValueError("fail")

        async def success() -> str:
            return "ok"

        with pytest.raises(ValueError):
            await cb.call(fail)

        # 成功重置计数
        await cb.call(success)

        # 再失败 2 次不应熔断（因为计数被重置）
        for _ in range(2):
            with pytest.raises(ValueError):
                await cb.call(fail)

        assert cb.state == CircuitState.CLOSED


# ---------------------------------------------------------------------------
# trace_context 测试
# ---------------------------------------------------------------------------


class TestTraceContext:
    """traceId 上下文测试"""

    def test_default_trace_id(self) -> None:
        """无设置时应返回占位符"""
        reset_trace_id(set_trace_id("-"))
        assert get_trace_id() == "-"

    def test_set_and_get(self) -> None:
        """set 后应能 get"""
        token = set_trace_id("my-trace")
        assert get_trace_id() == "my-trace"
        reset_trace_id(token)

    def test_new_trace_id_format(self) -> None:
        """new_trace_id 应为 32 位 hex"""
        tid = new_trace_id()
        assert len(tid) == 32
        int(tid, 16)  # 应为合法 hex

    def test_trace_context_manager(self) -> None:
        """上下文管理器应正确 set/reset"""
        with trace_context("ctx-id"):
            assert get_trace_id() == "ctx-id"
        # 退出后恢复
        assert get_trace_id() != "ctx-id"


# ---------------------------------------------------------------------------
# logging_setup 测试
# ---------------------------------------------------------------------------


class TestLoggingSetup:
    """结构化日志配置测试"""

    def test_setup_logging_human_readable(self) -> None:
        """人类可读格式应配置成功"""
        setup_logging(level="INFO", json_output=False)
        logger = get_logger("test.human")
        # 子 logger level 为 NOTSET，继承 root 的有效级别
        assert logger.getEffectiveLevel() == logging.INFO

    def test_setup_logging_json(self) -> None:
        """JSON 格式应配置成功"""
        setup_logging(level="DEBUG", json_output=True)
        logger = get_logger("test.json")
        # 不抛异常即成功
        logger.info("test message")

    def test_setup_logging_idempotent(self) -> None:
        """重复调用应幂等，不重复添加 handler"""
        setup_logging(level="INFO")
        before = len(logging.getLogger().handlers)
        setup_logging(level="WARNING")
        after = len(logging.getLogger().handlers)
        assert before == after

    def test_get_logger(self) -> None:
        """get_logger 应返回命名 logger"""
        logger = get_logger("my.module")
        assert logger.name == "my.module"
