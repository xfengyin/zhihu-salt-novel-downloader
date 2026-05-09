"""Cookie管理测试"""

import pytest
import json
from pathlib import Path
from auth.cookie_manager import CookieManager, SecureCookieManager


class TestCookieManager:
    """Cookie管理器测试"""

    @pytest.fixture
    def cookie_mgr(self):
        return CookieManager()

    def test_initialization(self, cookie_mgr):
        """测试初始化"""
        assert cookie_mgr._cookies == {}
        assert cookie_mgr._z_c0_token is None

    def test_set_token(self, cookie_mgr):
        """测试设置Token"""
        cookie_mgr.set_token("test_token_123")

        assert cookie_mgr.has_z_c0 is True
        assert cookie_mgr.get_cookies()['z_c0'] == "test_token_123"

    def test_set_cookie(self, cookie_mgr):
        """测试设置单个Cookie"""
        cookie_mgr.set_cookie("session_id", "abc123")

        assert cookie_mgr.get_cookies()['session_id'] == "abc123"

    def test_get_cookie_header(self, cookie_mgr):
        """测试获取Cookie头"""
        cookie_mgr.set_cookie("key1", "value1")
        cookie_mgr.set_cookie("key2", "value2")

        header = cookie_mgr.get_cookie_header()

        assert "key1=value1" in header
        assert "key2=value2" in header

    def test_load_json_cookie(self, cookie_mgr, tmp_path):
        """测试加载JSON格式Cookie"""
        cookie_file = tmp_path / "cookies.json"

        cookies_data = [
            {"name": "z_c0", "value": "token123"},
            {"name": "session_id", "value": "sess456"}
        ]

        with open(cookie_file, 'w') as f:
            json.dump(cookies_data, f)

        cookie_mgr.load_from_file(str(cookie_file))

        assert cookie_mgr.has_z_c0 is True
        assert cookie_mgr.get_cookies()['z_c0'] == "token123"
        assert cookie_mgr.get_cookies()['session_id'] == "sess456"

    def test_load_text_cookie(self, cookie_mgr, tmp_path):
        """测试加载文本格式Cookie"""
        cookie_file = tmp_path / "cookies.txt"

        cookie_file.write_text("key1=value1\nkey2=value2\n")

        cookie_mgr.load_from_file(str(cookie_file))

        assert cookie_mgr.get_cookies()['key1'] == "value1"
        assert cookie_mgr.get_cookies()['key2'] == "value2"

    def test_save_cookie(self, cookie_mgr, tmp_path):
        """测试保存Cookie"""
        cookie_mgr.set_cookie("key1", "value1")
        cookie_mgr.set_token("token123")

        output_path = tmp_path / "saved_cookies.json"
        cookie_mgr.save_to_file(str(output_path))

        assert output_path.exists()

        with open(output_path, 'r') as f:
            saved = json.load(f)

        assert len(saved) == 2
        assert any(c['name'] == 'z_c0' for c in saved)

    def test_file_not_found(self, cookie_mgr):
        """测试文件不存在"""
        with pytest.raises(FileNotFoundError):
            cookie_mgr.load_from_file("/nonexistent/path.json")


class TestSecureCookieManager:
    """安全Cookie管理器测试"""

    @pytest.fixture
    def secure_cookie_mgr(self):
        return SecureCookieManager(encryption_key="test_key_123")

    def test_initialization(self, secure_cookie_mgr):
        """测试初始化"""
        assert secure_cookie_mgr._fernet is not None
        assert secure_cookie_mgr._cookies == {}

    def test_encryption(self, secure_cookie_mgr):
        """测试加密解密"""
        original = "sensitive data"
        encrypted = secure_cookie_mgr._encrypt(original)
        decrypted = secure_cookie_mgr._decrypt(encrypted)

        assert encrypted != original
        assert decrypted == original

    def test_save_encrypted_cookie(self, secure_cookie_mgr, tmp_path):
        """测试保存加密Cookie"""
        secure_cookie_mgr.set_token("secret_token")

        output_path = tmp_path / "encrypted_cookies.json"
        secure_cookie_mgr.save_to_file(str(output_path), encrypt=True)

        assert output_path.exists()

        with open(output_path, 'r') as f:
            saved = json.load(f)

        assert saved.get('encrypted') is True
        assert 'data' in saved
