"""doctor 命令测试 - 全部本地检查（网络探测用 --no-network 跳过）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from zhihu_downloader.cli import _build_parser, cmd_doctor


def _doctor_args(cookie_file: str | None = None, **extra) -> pytest.fixture:  # noqa: ANN001 - 简化
    argv = ["doctor", "--no-network"]
    if cookie_file:
        argv += ["--cookie-file", cookie_file]
    args = _build_parser().parse_args(argv)
    for key, value in extra.items():
        setattr(args, key, value)
    return args


class TestDoctor:
    def test_no_cookie_warns_but_ok(self, tmp_path: Path, capsys) -> None:
        missing = tmp_path / "no_such_cookies.json"
        rc = cmd_doctor(_doctor_args(str(missing)))
        out = capsys.readouterr().out
        assert rc == 0  # 无 Cookie 只告警不报错
        assert "⚠️ [Cookie]" in out
        assert "Cookie 文件不存在" in out

    def test_valid_cookie_ok(self, tmp_path: Path, capsys) -> None:
        f = tmp_path / "cookies.json"
        f.write_text(json.dumps({"z_c0": "z", "zse_ck": "s"}), encoding="utf-8")
        rc = cmd_doctor(_doctor_args(str(f)))
        out = capsys.readouterr().out
        assert rc == 0
        assert "✅ [Cookie]" in out
        assert "Cookie 有效" in out

    def test_corrupt_cookie_errors(self, tmp_path: Path, capsys) -> None:
        f = tmp_path / "cookies.json"
        f.write_text("{not valid json", encoding="utf-8")
        rc = cmd_doctor(_doctor_args(str(f)))
        out = capsys.readouterr().out
        assert rc == 1  # 存在错误 → 非 0 退出码
        assert "❌ [Cookie]" in out
        assert "无法解析" in out

    def test_cookie_missing_keys_warns(self, tmp_path: Path, capsys) -> None:
        f = tmp_path / "cookies.json"
        f.write_text(json.dumps({"foo": "bar"}), encoding="utf-8")
        rc = cmd_doctor(_doctor_args(str(f)))
        out = capsys.readouterr().out
        assert rc == 0
        assert "⚠️ [Cookie]" in out
        assert "缺少关键字段" in out

    def test_rate_limit_high_warns(self, tmp_path: Path, capsys) -> None:
        rc = cmd_doctor(_doctor_args(str(tmp_path / "x.json"), rate_limit=10.0))
        out = capsys.readouterr().out
        assert rc == 0
        assert "⚠️ [限速]" in out
        assert "偏高" in out

    def test_rate_limit_default_ok(self, tmp_path: Path, capsys) -> None:
        rc = cmd_doctor(_doctor_args(str(tmp_path / "x.json")))
        out = capsys.readouterr().out
        assert rc == 0
        assert "✅ [限速]" in out

    def test_network_skipped_with_flag(self, tmp_path: Path, capsys) -> None:
        rc = cmd_doctor(_doctor_args(str(tmp_path / "x.json")))
        out = capsys.readouterr().out
        assert rc == 0
        assert "已跳过网络探测" in out

    def test_version_info_shown(self, tmp_path: Path, capsys) -> None:
        cmd_doctor(_doctor_args(str(tmp_path / "x.json")))
        out = capsys.readouterr().out
        assert "ℹ️ [版本]" in out
        assert "4.3.0" in out

    def test_python_ok(self, tmp_path: Path, capsys) -> None:
        rc = cmd_doctor(_doctor_args(str(tmp_path / "x.json")))
        out = capsys.readouterr().out
        assert rc == 0
        assert "✅ [Python/系统]" in out
