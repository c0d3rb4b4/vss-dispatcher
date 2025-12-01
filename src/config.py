"""Configuration management for vss-dispatcher."""

import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RabbitMQConfig:
    """RabbitMQ connection configuration."""

    host: str = field(default_factory=lambda: os.getenv("RABBITMQ_HOST", "rabbitmq"))
    port: int = field(
        default_factory=lambda: int(os.getenv("RABBITMQ_PORT", "5672"))
    )
    username: str = field(
        default_factory=lambda: os.getenv("RABBITMQ_USERNAME", "guest")
    )
    password: str = field(
        default_factory=lambda: os.getenv("RABBITMQ_PASSWORD", "guest")
    )
    virtual_host: str = field(
        default_factory=lambda: os.getenv("RABBITMQ_VHOST", "/")
    )
    normal_queue: str = field(
        default_factory=lambda: os.getenv("RABBITMQ_NORMAL_QUEUE", "vss.normal")
    )
    priority_queue: str = field(
        default_factory=lambda: os.getenv("RABBITMQ_PRIORITY_QUEUE", "vss.priority")
    )
    prefetch_count: int = field(
        default_factory=lambda: int(os.getenv("RABBITMQ_PREFETCH_COUNT", "1"))
    )


@dataclass
class VSSConfig:
    """VSS service configuration."""

    base_url: str = field(
        default_factory=lambda: os.getenv("VSS_BASE_URL", "http://localhost:8080")
    )
    timeout: int = field(
        default_factory=lambda: int(os.getenv("VSS_TIMEOUT", "30"))
    )
    retry_count: int = field(
        default_factory=lambda: int(os.getenv("VSS_RETRY_COUNT", "3"))
    )
    retry_delay: float = field(
        default_factory=lambda: float(os.getenv("VSS_RETRY_DELAY", "1.0"))
    )


@dataclass
class MountConfig:
    """Mount paths configuration."""

    samba_mount: str = field(
        default_factory=lambda: os.getenv("SAMBA_MOUNT_PATH", "/mnt/samba")
    )
    config_mount: str = field(
        default_factory=lambda: os.getenv("CONFIG_MOUNT_PATH", "/mnt/config")
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
        default_factory=lambda: float(os.getenv("CHECK_INTERVAL", "0.1"))
    )


def load_config() -> AppConfig:
    """Load and return application configuration."""
    return AppConfig()
