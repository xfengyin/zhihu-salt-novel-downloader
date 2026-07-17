"""NATS JetStream 任务队列实现

基于 nats-py 实现可靠的分布式任务队列，支持：
- 幂等消息（UUIDv7）
- 消息确认机制
- JetStream 持久化
- 生产者/消费者模式
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from collections.abc import Callable, Coroutine
from typing import Any

import nats
from nats.aio.client import Client as NATSClient
from nats.aio.msg import Msg
from nats.js import JetStreamContext
from nats.js.api import (
    ConsumerConfig,
    DeliverPolicy,
    StorageType,
    StreamConfig,
    StreamInfo,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class NATSConfig(BaseSettings):
    """NATS 连接配置"""

    model_config = SettingsConfigDict(env_prefix="NATS_", env_file=".env", extra="ignore")

    servers: str = "nats://localhost:4222"
    """NATS 服务器地址，多个用逗号分隔"""

    max_reconnect_attempts: int = 10
    """最大重连次数"""

    reconnect_time_wait: float = 2.0
    """重连等待时间（秒）"""

    name: str | None = "zhihu-downloader"
    """客户端名称"""

    stream_name: str = "download_tasks"
    """JetStream 流名称"""

    subject: str = "download.tasks"
    """消息主题"""

    consumer_name: str = "download_consumer"
    """消费者名称"""

    durable_name: str = "download_durable"
    """持久化名称"""

    ack_wait: int = 60
    """消息确认超时时间（秒）"""

    max_deliver: int = 5
    """最大投递次数"""

    storage: StorageType = StorageType.FILE
    """存储类型"""


class TaskProducer:
    """任务生产者"""

    def __init__(self, config: NATSConfig) -> None:
        self._config = config
        self._nc: NATSClient | None = None
        self._js: JetStreamContext | None = None

    async def connect(self) -> None:
        """连接到 NATS"""
        if self._nc is not None and self._nc.is_connected:
            return

        self._nc = await nats.connect(
            servers=self._config.servers.split(","),
            max_reconnect_attempts=self._config.max_reconnect_attempts,
            reconnect_time_wait=self._config.reconnect_time_wait,
            name=self._config.name,
        )
        self._js = self._nc.jetstream()
        logger.info("NATS producer connected")

    async def disconnect(self) -> None:
        """断开连接"""
        if self._nc is not None:
            await self._nc.close()
            self._nc = None
            self._js = None
            logger.info("NATS producer disconnected")

    async def submit(
        self,
        payload: dict[str, Any],
        *,
        msg_id: str | None = None,
        timeout: float = 5.0,
    ) -> str:
        """
        发送任务到 NATS

        Args:
            payload: 任务载荷
            msg_id: 消息幂等键，未提供时自动生成 UUIDv7
            timeout: 发送超时时间（秒）

        Returns:
            消息 ID
        """
        if self._js is None:
            await self.connect()
            assert self._js is not None

        message_id = msg_id or _generate_uuid7()

        await self._js.publish(
            subject=self._config.subject,
            payload=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Nats-Msg-Id": message_id},
            timeout=timeout,
        )

        logger.debug("Task submitted: msg_id=%s, payload=%s", message_id, payload)
        return message_id


class TaskConsumer:
    """任务消费者"""

    def __init__(
        self,
        config: NATSConfig,
        callback: Callable[[dict[str, Any], str], Coroutine[Any, Any, None]],
    ) -> None:
        self._config = config
        self._callback = callback
        self._nc: NATSClient | None = None
        self._js: JetStreamContext | None = None
        self._running: bool = False

    async def connect(self) -> None:
        """连接到 NATS"""
        if self._nc is not None and self._nc.is_connected:
            return

        self._nc = await nats.connect(
            servers=self._config.servers.split(","),
            max_reconnect_attempts=self._config.max_reconnect_attempts,
            reconnect_time_wait=self._config.reconnect_time_wait,
            name=self._config.name,
        )
        self._js = self._nc.jetstream()
        logger.info("NATS consumer connected")

    async def disconnect(self) -> None:
        """断开连接"""
        self._running = False
        if self._nc is not None:
            await self._nc.close()
            self._nc = None
            self._js = None
            logger.info("NATS consumer disconnected")

    async def run(self) -> None:
        """
        阻塞消费任务

        启动后会持续监听消息，直到收到停止信号或连接断开。
        """
        if self._js is None:
            await self.connect()
            assert self._js is not None

        self._running = True

        consumer = await self._js.subscribe(
            subject=self._config.subject,
            stream=self._config.stream_name,
            durable=self._config.durable_name,
            config=ConsumerConfig(
                name=self._config.consumer_name,
                deliver_policy=DeliverPolicy.LAST,
                ack_wait=self._config.ack_wait,
                max_deliver=self._config.max_deliver,
            ),
            cb=self._handle_message,
        )

        logger.info("Consumer started: stream=%s, subject=%s",
                    self._config.stream_name, self._config.subject)

        try:
            while self._running:
                await asyncio.sleep(0.1)
        finally:
            await consumer.unsubscribe()
            logger.info("Consumer stopped")

    async def _handle_message(self, msg: Msg) -> None:
        """
        处理收到的消息

        Args:
            msg: NATS 消息对象
        """
        try:
            msg_id = msg.headers.get("Nats-Msg-Id", "") if msg.headers else ""
            payload = json.loads(msg.data.decode("utf-8"))

            logger.debug("Received message: msg_id=%s, payload=%s", msg_id, payload)

            await self._callback(payload, msg_id)

            await msg.ack()
            logger.debug("Message acked: msg_id=%s", msg_id)

        except json.JSONDecodeError as e:
            logger.error("Failed to decode message: %s", e)
            await msg.nak()
        except Exception as e:
            logger.error("Failed to process message: msg_id=%s, error=%s", msg_id, e)
            await msg.nak()


async def create_stream(config: NATSConfig) -> StreamInfo:
    """
    创建 JetStream 流

    Args:
        config: NATS 配置

    Returns:
        流信息
    """
    nc = await nats.connect(
        servers=config.servers.split(","),
        max_reconnect_attempts=config.max_reconnect_attempts,
        reconnect_time_wait=config.reconnect_time_wait,
        name=config.name,
    )

    try:
        js = nc.jetstream()

        stream_info = await js.add_stream(
            StreamConfig(
                name=config.stream_name,
                subjects=[config.subject],
                storage=config.storage,
                max_msgs=-1,
                max_bytes=-1,
                max_age=-1,
                duplicate_window=300,
            )
        )

        logger.info("Stream created: name=%s", config.stream_name)
        return stream_info
    finally:
        await nc.close()


async def delete_stream(config: NATSConfig) -> bool:
    """
    删除 JetStream 流

    Args:
        config: NATS 配置

    Returns:
        是否删除成功
    """
    nc = await nats.connect(
        servers=config.servers.split(","),
        max_reconnect_attempts=config.max_reconnect_attempts,
        reconnect_time_wait=config.reconnect_time_wait,
        name=config.name,
    )

    try:
        js = nc.jetstream()
        await js.delete_stream(name=config.stream_name)

        logger.info("Stream deleted: name=%s", config.stream_name)
        return True
    except Exception:
        logger.warning("Stream not found: name=%s", config.stream_name)
        return False
    finally:
        await nc.close()


def _generate_uuid7() -> str:
    """
    生成 UUIDv7

    UUIDv7 包含时间戳，适合作为消息幂等键，保证唯一性且有序。
    兼容 Python 3.10+，使用手动实现以避免版本兼容性问题。

    Returns:
        UUIDv7 字符串
    """
    timestamp_ms = int(time.time() * 1000)
    rand_bytes = os.urandom(10)

    ts_high = (timestamp_ms >> 12) & 0xFFFFF
    ts_mid = (timestamp_ms >> 2) & 0xFFF
    ts_low = timestamp_ms & 0x3

    uuid_int = (
        (ts_high << 60)
        | (0x7 << 56)
        | (ts_mid << 44)
        | (0x8 << 40)
        | int.from_bytes(rand_bytes, "big")
        | ts_low
    )

    return str(uuid.UUID(int=uuid_int))


__all__ = [
    "NATSConfig",
    "TaskConsumer",
    "TaskProducer",
    "create_stream",
    "delete_stream",
]
