"""Configuration management for vss-dispatcher."""

import os
from dataclasses import dataclass, field

from .constants import (
    DEFAULT_CHECK_INTERVAL,
    DEFAULT_NORMAL_QUEUE,
    DEFAULT_PREFETCH_COUNT,
    DEFAULT_RABBITMQ_PORT,
    DEFAULT_SAMBA_MOUNT,
    DEFAULT_BASE_IMAGE_DIR,
    DEFAULT_COMPOSITE_DIR,
    DEFAULT_DISPLAY_WIDTH,
    DEFAULT_DISPLAY_HEIGHT,
    DEFAULT_VHOST,
    DEFAULT_VSS_RETRY_COUNT,
    DEFAULT_VSS_RETRY_DELAY,
    DEFAULT_VSS_TIMEOUT,
)


@dataclass
class RabbitMQConfig:
    """RabbitMQ connection configuration."""

    host: str = field(default_factory=lambda: os.getenv("RABBITMQ_HOST", "localhost"))
    port: int = field(
        default_factory=lambda: int(os.getenv("RABBITMQ_PORT", str(DEFAULT_RABBITMQ_PORT)))
    )
    username: str = field(
        default_factory=lambda: os.getenv("RABBITMQ_USERNAME", "guest")
    )
    password: str = field(
        default_factory=lambda: os.getenv("RABBITMQ_PASSWORD", "guest")
    )
    virtual_host: str = field(
        default_factory=lambda: os.getenv("RABBITMQ_VHOST", DEFAULT_VHOST)
    )
    normal_queue: str = field(
        default_factory=lambda: os.getenv("RABBITMQ_NORMAL_QUEUE", DEFAULT_NORMAL_QUEUE)
    )
    prefetch_count: int = field(
        default_factory=lambda: int(os.getenv("RABBITMQ_PREFETCH_COUNT", str(DEFAULT_PREFETCH_COUNT)))
    )


@dataclass
class VSSConfig:
    """VSS service configuration."""

    base_url: str = field(
        default_factory=lambda: os.getenv("VSS_BASE_URL", "http://localhost:8081")
    )
    api_key: str = field(
        default_factory=lambda: os.getenv("VSS_API_KEY", "")
    )
    api_secret: str = field(
        default_factory=lambda: os.getenv("VSS_API_SECRET", "")
    )
    device_uuids: list = field(
        default_factory=lambda: os.getenv("VSS_DEVICE_UUIDS", "").split(",") if os.getenv("VSS_DEVICE_UUIDS") else []
    )
    timeout: int = field(
        default_factory=lambda: int(os.getenv("VSS_TIMEOUT", str(DEFAULT_VSS_TIMEOUT)))
    )
    retry_count: int = field(
        default_factory=lambda: int(os.getenv("VSS_RETRY_COUNT", str(DEFAULT_VSS_RETRY_COUNT)))
    )
    retry_delay: float = field(
        default_factory=lambda: float(os.getenv("VSS_RETRY_DELAY", str(DEFAULT_VSS_RETRY_DELAY)))
    )


@dataclass
class MountConfig:
    """Mount paths configuration."""

    samba_mount: str = field(
        default_factory=lambda: os.getenv("SAMBA_MOUNT_PATH", DEFAULT_SAMBA_MOUNT)
    )
    base_image_dir: str = field(
        default_factory=lambda: os.getenv("BASE_IMAGE_DIR", DEFAULT_BASE_IMAGE_DIR)
    )
    composite_dir: str = field(
        default_factory=lambda: os.getenv("COMPOSITE_DIR", DEFAULT_COMPOSITE_DIR)
    )
    display_width: int = field(
        default_factory=lambda: int(os.getenv("DISPLAY_WIDTH", str(DEFAULT_DISPLAY_WIDTH)))
    )
    display_height: int = field(
        default_factory=lambda: int(os.getenv("DISPLAY_HEIGHT", str(DEFAULT_DISPLAY_HEIGHT)))
    )


@dataclass
class AppConfig:
    """Application configuration."""

    rabbitmq: RabbitMQConfig = field(default_factory=RabbitMQConfig)
    vss: VSSConfig = field(default_factory=VSSConfig)
    mount: MountConfig = field(default_factory=MountConfig)
    log_level: str = field(
        default_factory=lambda: os.getenv("LOG_LEVEL", "INFO")
    )
    check_interval: float = field(
        default_factory=lambda: float(os.getenv("CHECK_INTERVAL", str(DEFAULT_CHECK_INTERVAL)))
    )


def load_config() -> AppConfig:
    """Load and return application configuration."""
    return AppConfig()
