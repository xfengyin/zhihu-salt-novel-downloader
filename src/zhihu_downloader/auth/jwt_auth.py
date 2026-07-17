"""JWT认证模块

提供JWT令牌的创建、验证、解码和刷新功能，以及统一的认证服务。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from pydantic import BaseModel, EmailStr, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class JWTConfig(BaseSettings):
    """JWT配置类

    从环境变量或.env文件加载配置。
    """

    model_config = SettingsConfigDict(env_file=".env", env_prefix="JWT_")

    secret_key: str = Field(
        default="zhihu-downloader-secret-key-change-in-production",
        description="JWT签名密钥，生产环境必须更换",
    )
    algorithm: str = Field(default="HS256", description="JWT算法")
    access_token_expire_minutes: int = Field(
        default=30, description="访问令牌过期时间（分钟）"
    )
    refresh_token_expire_days: int = Field(
        default=7, description="刷新令牌过期时间（天）"
    )


class TokenData(BaseModel):
    """令牌数据模型"""

    user_id: int | None = None
    username: str | None = None


class User(BaseModel):
    """用户模型"""

    id: int
    username: str
    email: EmailStr | None = None
    is_active: bool = True


class UserInDB(User):
    """数据库中的用户模型"""

    hashed_password: str


JWT_CONFIG = JWTConfig()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")


def create_access_token(
    data: dict[str, Any],
    expires_delta: timedelta | None = None,
) -> str:
    """创建访问令牌

    Args:
        data: 令牌载荷数据
        expires_delta: 过期时间增量，默认为配置中的30分钟

    Returns:
        JWT访问令牌字符串
    """
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=JWT_CONFIG.access_token_expire_minutes)
    to_encode.update({"exp": expire, "token_type": "access"})
    encoded_jwt = jwt.encode(
        to_encode,
        JWT_CONFIG.secret_key,
        algorithm=JWT_CONFIG.algorithm,
    )
    return str(encoded_jwt)


def create_refresh_token(
    data: dict[str, Any],
    expires_delta: timedelta | None = None,
) -> str:
    """创建刷新令牌

    Args:
        data: 令牌载荷数据
        expires_delta: 过期时间增量，默认为配置中的7天

    Returns:
        JWT刷新令牌字符串
    """
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(days=JWT_CONFIG.refresh_token_expire_days)
    to_encode.update({"exp": expire, "token_type": "refresh"})
    encoded_jwt = jwt.encode(
        to_encode,
        JWT_CONFIG.secret_key,
        algorithm=JWT_CONFIG.algorithm,
    )
    return str(encoded_jwt)


def verify_token(token: str, credentials_exception: HTTPException) -> TokenData:
    """验证令牌

    Args:
        token: JWT令牌字符串
        credentials_exception: 验证失败时抛出的异常

    Returns:
        TokenData对象

    Raises:
        credentials_exception: 令牌无效时抛出
    """
    try:
        payload = jwt.decode(
            token,
            JWT_CONFIG.secret_key,
            algorithms=[JWT_CONFIG.algorithm],
        )
        user_id: int | None = payload.get("user_id")
        username: str | None = payload.get("username")
        if user_id is None or username is None:
            raise credentials_exception
        return TokenData(user_id=user_id, username=username)
    except JWTError as err:
        raise credentials_exception from err


def decode_token(token: str) -> dict[str, Any]:
    """解码令牌（不验证签名和过期时间）

    注意：此函数仅解码令牌内容，不进行安全验证。
    如需安全验证，请使用verify_token()。

    Args:
        token: JWT令牌字符串

    Returns:
        令牌载荷字典

    Raises:
        JWTError: 令牌格式无效时抛出
    """
    payload = jwt.decode(
        token,
        JWT_CONFIG.secret_key,
        algorithms=[JWT_CONFIG.algorithm],
        options={"verify_signature": False, "verify_exp": False},
    )
    return dict(payload)


def refresh_token(refresh_token_str: str) -> str:
    """使用刷新令牌获取新的访问令牌

    Args:
        refresh_token_str: 刷新令牌字符串

    Returns:
        新的访问令牌字符串

    Raises:
        HTTPException: 刷新令牌无效或类型错误时抛出
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="无效的刷新令牌",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(
            refresh_token_str,
            JWT_CONFIG.secret_key,
            algorithms=[JWT_CONFIG.algorithm],
        )
        token_type = payload.get("token_type")
        if token_type != "refresh":
            raise credentials_exception

        user_id: int | None = payload.get("user_id")
        username: str | None = payload.get("username")
        if user_id is None or username is None:
            raise credentials_exception

        return create_access_token(data={"user_id": user_id, "username": username})
    except JWTError as err:
        raise credentials_exception from err


class AuthService:
    """统一认证服务"""

    def __init__(self, config: JWTConfig | None = None) -> None:
        """
        初始化认证服务

        Args:
            config: JWT配置，默认为全局配置
        """
        self.config = config or JWT_CONFIG

    def create_access_token(
        self,
        data: dict[str, Any],
        expires_delta: timedelta | None = None,
    ) -> str:
        """创建访问令牌"""
        return create_access_token(data, expires_delta)

    def create_refresh_token(
        self,
        data: dict[str, Any],
        expires_delta: timedelta | None = None,
    ) -> str:
        """创建刷新令牌"""
        return create_refresh_token(data, expires_delta)

    def verify_token(self, token: str) -> TokenData:
        """验证令牌"""
        credentials_exception = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无法验证凭证",
            headers={"WWW-Authenticate": "Bearer"},
        )
        return verify_token(token, credentials_exception)

    def decode_token(self, token: str) -> dict[str, Any]:
        """解码令牌"""
        return decode_token(token)

    def refresh_token(self, refresh_token_str: str) -> str:
        """刷新令牌"""
        return refresh_token(refresh_token_str)

    def authenticate_user(
        self,
        username: str,
        password: str,
    ) -> UserInDB | None:
        """
        认证用户

        注意：此方法需要根据实际用户存储实现，当前为占位实现。

        Args:
            username: 用户名
            password: 密码

        Returns:
            用户对象，如果认证失败返回None
        """
        raise NotImplementedError(
            "请根据实际用户存储实现 authenticate_user 方法"
        )


async def get_current_user(token: str = Depends(oauth2_scheme)) -> TokenData:
    """获取当前用户（FastAPI依赖）

    Args:
        token: OAuth2令牌

    Returns:
        当前用户的TokenData

    Raises:
        HTTPException: 凭证无效时抛出
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="无法验证凭证",
        headers={"WWW-Authenticate": "Bearer"},
    )
    return verify_token(token, credentials_exception)


__all__ = [
    "JWT_CONFIG",
    "AuthService",
    "JWTConfig",
    "TokenData",
    "User",
    "UserInDB",
    "create_access_token",
    "create_refresh_token",
    "decode_token",
    "get_current_user",
    "oauth2_scheme",
    "refresh_token",
    "verify_token",
]
