"""cli 测试 - 参数解析与 rate-limit / version 行为（不触网）。"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from zhihu_downloader import __version__
from zhihu_downloader.cli import _build_parser, cmd_download


def _parse_download(argv: list[str] | None = None) -> MagicMock:
    args = _build_parser().parse_args(
        ["download", "--url", "https://example.com/x", *(argv or [])]
    )
    return args


class TestRateLimitArg:
    def test_default_is_2(self) -> None:
        assert _parse_download().rate_limit == 2.0

    def test_custom_value(self) -> None:
        assert _parse_download(["--rate-limit", "0.8"]).rate_limit == 0.8

    def test_default_passed_to_download(self) -> None:
        client = MagicMock()
        assert cmd_download(client, _parse_download()) == 0
        _, kwargs = client.download.call_args
        assert kwargs["rate_limit"] == 2.0

    def test_value_below_min_clamped_to_0_5(self) -> None:
        client = MagicMock()
        assert cmd_download(client, _parse_download(["--rate-limit", "0.1"])) == 0
        _, kwargs = client.download.call_args
        assert kwargs["rate_limit"] == 0.5

    def test_help_lists_rate_limit(self, capsys) -> None:
        with pytest.raises(SystemExit):
            _build_parser().parse_args(["download", "--help"])
        out = capsys.readouterr().out
        assert "--rate-limit" in out


class TestVersionArg:
    def test_version_prints_package_version(self, capsys) -> None:
        with pytest.raises(SystemExit) as exc:
            _build_parser().parse_args(["--version"])
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert f"zhihu-downloader {__version__}" in out
        assert "4.2.0" in out

    def test_help_lists_version(self, capsys) -> None:
        with pytest.raises(SystemExit):
            _build_parser().parse_args(["--help"])
        out = capsys.readouterr().out
        assert "--version" in out
