"""Data models for vss-dispatcher."""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class MessagePriority(Enum):
    """Message priority levels."""

    NORMAL = "normal"
    PRIORITY = "priority"


@dataclass
class VssMessage:
    """Message structure for VSS dispatcher."""

    image_path: str
    duration: float
    priority: MessagePriority = MessagePriority.NORMAL
    message_id: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict, priority: MessagePriority) -> "VssMessage":
        """Create a VssMessage from a dictionary."""
        return cls(
            image_path=data.get("image_path", ""),
            duration=float(data.get("duration", 5.0)),
            priority=priority,
            message_id=data.get("message_id"),
        )

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "image_path": self.image_path,
            "duration": self.duration,
            "priority": self.priority.value,
            "message_id": self.message_id,
        }


@dataclass
class VssResponse:
    """Response from VSS service."""

    success: bool
    message: str = ""
    error: Optional[str] = None
