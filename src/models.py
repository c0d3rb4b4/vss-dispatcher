"""Data models for vss-dispatcher."""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from .constants import DEFAULT_MESSAGE_DURATION


class MessageType(Enum):
    """Message type for different operations."""

    IMAGE = "image"  # Full image update
    OVERLAY = "overlay"  # Overlay to composite on current image


@dataclass
class VssMessage:
    """Message structure for VSS dispatcher."""

    image_path: str
    duration: float = DEFAULT_MESSAGE_DURATION
    message_type: MessageType = MessageType.IMAGE
    message_id: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict) -> "VssMessage":
        """Create a VssMessage from a dictionary."""
        # Determine message type from data
        msg_type_str = data.get("message_type", data.get("type", "image"))
        try:
            message_type = MessageType(msg_type_str)
        except ValueError:
            message_type = MessageType.IMAGE
        # Duration only meaningful for image messages
        raw_duration = data.get("duration", DEFAULT_MESSAGE_DURATION)
        duration = float(raw_duration) if message_type == MessageType.IMAGE else DEFAULT_MESSAGE_DURATION
        
        return cls(
            image_path=data.get("image_path", ""),
            duration=duration,
            message_type=message_type,
            message_id=data.get("message_id"),
        )

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "image_path": self.image_path,
            "duration": self.duration,
            "message_type": self.message_type.value,
            "message_id": self.message_id,
        }


@dataclass
class VssResponse:
    """Response from VSS service."""

    success: bool
    message: str = ""
    error: Optional[str] = None
