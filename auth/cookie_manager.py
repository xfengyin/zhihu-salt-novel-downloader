"""Cookie管理器 - 安全加密存储"""

import json
import logging
import base64
import hashlib
import secrets
from pathlib import Path
from typing import Dict, Optional, List
try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False


logger = logging.getLogger(__name__)


class SecureCookieManager:
    """安全的Cookie管理器 - 支持加密存储"""

    def __init__(self, encryption_key: Optional[str] = None):
        self._cookies: Dict[str, str] = {}
        self._z_c0_token: Optional[str] = None

        if CRYPTO_AVAILABLE and encryption_key:
            self._fernet = self._create_fernet(encryption_key)
        elif CRYPTO_AVAILABLE:
            self._fernet = self._create_fernet(secrets.token_hex(32))
        else:
            self._fernet = None
            logger.warning("cryptography库未安装，Cookie将以明文存储（仅用于开发环境）")

    def _create_fernet(self, password: str) -> Fernet:
        salt = hashlib.sha256(b"zhihu-downloader-salt").digest()
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=480000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
        return Fernet(key)

    def _encrypt(self, data: str) -> str:
        if not self._fernet:
            return data
        return self._fernet.encrypt(data.encode()).decode()

    def _decrypt(self, data: str) -> str:
        if not self._fernet:
            return data
        return self._fernet.decrypt(data.encode()).decode()

    def load_from_file(self, cookie_file: str, encrypted: bool = False) -> None:
        path = Path(cookie_file)

        if not path.exists():
            raise FileNotFoundError(f"Cookie文件不存在: {cookie_file}")

        if path.suffix == '.json':
            if encrypted:
                self._load_encrypted_json(path)
            else:
                self._load_json(path)
        else:
            self._load_text(path)

        logger.info(f"已加载 {len(self._cookies)} 个Cookie")

    def _load_json(self, path: Path) -> None:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        for item in data:
            name = item.get('name', '')
            value = item.get('value', '')
            if name and value:
                self._cookies[name] = value

        if 'z_c0' in self._cookies:
            self._z_c0_token = self._cookies['z_c0']

    def _load_encrypted_json(self, path: Path) -> None:
        with open(path, 'r', encoding='utf-8') as f:
            encrypted_data = json.load(f)

        decrypted = self._decrypt(encrypted_data['data'])
        data = json.loads(decrypted)

        for item in data:
            name = item.get('name', '')
            value = item.get('value', '')
            if name and value:
                self._cookies[name] = value

        if 'z_c0' in self._cookies:
            self._z_c0_token = self._cookies['z_c0']

    def _load_text(self, path: Path) -> None:
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue

                if '=' in line:
                    name, value = line.split('=', 1)
                    self._cookies[name.strip()] = value.strip()

    def set_token(self, token: str) -> None:
        self._z_c0_token = token
        self._cookies['z_c0'] = token
        logger.info("已设置z_c0 token")

    def set_cookie(self, name: str, value: str) -> None:
        self._cookies[name] = value

    def get_cookies(self) -> Dict[str, str]:
        return self._cookies.copy()

    def get_cookie_header(self) -> str:
        return '; '.join(f"{k}={v}" for k, v in self._cookies.items())

    @property
    def has_z_c0(self) -> bool:
        return bool(self._z_c0_token)

    def save_to_file(self, output_path: str, encrypt: bool = True) -> None:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        cookies_list = [
            {'name': k, 'value': v}
            for k, v in self._cookies.items()
        ]

        if encrypt and self._fernet:
            encrypted_data = {
                'encrypted': True,
                'version': 1,
                'data': self._encrypt(json.dumps(cookies_list, ensure_ascii=False))
            }
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(encrypted_data, f, ensure_ascii=False, indent=2)
        else:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(cookies_list, f, ensure_ascii=False, indent=2)

        logger.info(f"Cookie已保存到: {output_path}")

    def save_encryption_key(self, key_path: str) -> str:
        if not self._fernet:
            raise RuntimeError("加密功能不可用")

        key = secrets.token_hex(32)
        path = Path(key_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, 'w') as f:
            f.write(key)

        logger.info(f"加密密钥已保存到: {key_path}")
        return key


class CookieManager:
    """Cookie管理器 - 向后兼容版本"""

    def __init__(self):
        self._cookies: Dict[str, str] = {}
        self._z_c0_token: Optional[str] = None

    def load_from_file(self, cookie_file: str) -> None:
        path = Path(cookie_file)

        if not path.exists():
            raise FileNotFoundError(f"Cookie文件不存在: {cookie_file}")

        if path.suffix == '.json':
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            for item in data:
                name = item.get('name', '')
                value = item.get('value', '')
                if name and value:
                    self._cookies[name] = value

            if 'z_c0' in self._cookies:
                self._z_c0_token = self._cookies['z_c0']
        else:
            with open(path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue

                    if '=' in line:
                        name, value = line.split('=', 1)
                        self._cookies[name.strip()] = value.strip()

        logger.info(f"已加载 {len(self._cookies)} 个Cookie")

    def set_token(self, token: str) -> None:
        self._z_c0_token = token
        self._cookies['z_c0'] = token
        logger.info("已设置z_c0 token")

    def set_cookie(self, name: str, value: str) -> None:
        self._cookies[name] = value

    def get_cookies(self) -> Dict[str, str]:
        return self._cookies.copy()

    def get_cookie_header(self) -> str:
        return '; '.join(f"{k}={v}" for k, v in self._cookies.items())

    @property
    def has_z_c0(self) -> bool:
        return bool(self._z_c0_token)

    def save_to_file(self, output_path: str) -> None:
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump([
                {'name': k, 'value': v}
                for k, v in self._cookies.items()
            ], f, ensure_ascii=False, indent=2)

        logger.info(f"Cookie已保存到: {output_path}")
