"""自定义异常类"""

from typing import Optional


class DownloaderError(Exception):
    """下载器基础异常"""

    def __init__(
        self,
        message: str,
        url: Optional[str] = None,
        status_code: Optional[int] = None,
        retry_count: int = 0
    ):
        self.message = message
        self.url = url
        self.status_code = status_code
        self.retry_count = retry_count

        detail = f"[URL: {url}] " if url else ""
        detail += f"[Status: {status_code}] " if status_code else ""
        detail += f"[Retry: {retry_count}] " if retry_count else ""

        super().__init__(f"{detail}{message}" if detail else message)


class NetworkError(DownloaderError):
    """网络相关错误"""

    pass


class HTTPError(DownloaderError):
    """HTTP协议错误"""

    def __init__(self, status_code: int, message: str, url: Optional[str] = None, retry_count: int = 0):
        self.status_code = status_code
        super().__init__(message, url, status_code, retry_count)


class RateLimitError(HTTPError):
    """请求频率超限"""

    def __init__(self, url: Optional[str] = None, retry_count: int = 0):
        super().__init__(
            status_code=429,
            message="请求频率超限，请降低下载速度",
            url=url,
            retry_count=retry_count
        )


class AuthenticationError(DownloaderError):
    """认证失败"""

    def __init__(self, message: str = "认证失败，请检查Cookie或Token", url: Optional[str] = None):
        super().__init__(message, url, status_code=403)


class NotFoundError(HTTPError):
    """资源不存在"""

    def __init__(self, url: Optional[str] = None):
        super().__init__(
            status_code=404,
            message="资源不存在",
            url=url
        )


class ParsingError(DownloaderError):
    """解析错误"""

    pass


class CacheError(Exception):
    """缓存相关错误"""

    pass


class ConfigError(Exception):
    """配置相关错误"""

    pass
