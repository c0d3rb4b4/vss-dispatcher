"""VSS client for sending images to the VSS service."""

import logging
import time
from typing import Callable, Optional

import requests
from requests.exceptions import RequestException

from .config import VSSConfig
from .models import VssMessage, VssResponse

logger = logging.getLogger(__name__)


class VssClient:
    """Client for communicating with the VSS service."""

    def __init__(self, config: VSSConfig):
        """Initialize the VSS client.

        Args:
            config: VSS configuration
        """
        self.config = config
        self.session = requests.Session()

    def send_image(self, message: VssMessage) -> VssResponse:
        """Send an image to the VSS service for rendering.

        Args:
            message: The VSS message containing image path and duration

        Returns:
            VssResponse indicating success or failure
        """
        url = f"{self.config.base_url}/display"
        payload = {
            "image_path": message.image_path,
            "duration": message.duration,
        }

        for attempt in range(self.config.retry_count):
            try:
                logger.info(
                    "Sending image to VSS: %s (attempt %d/%d)",
                    message.image_path,
                    attempt + 1,
                    self.config.retry_count,
                )

                response = self.session.post(
                    url,
                    json=payload,
                    timeout=self.config.timeout,
                )
                response.raise_for_status()

                logger.info("Successfully sent image to VSS: %s", message.image_path)
                return VssResponse(success=True, message="Image sent successfully")

            except RequestException as e:
                logger.warning(
                    "Failed to send image (attempt %d/%d): %s",
                    attempt + 1,
                    self.config.retry_count,
                    str(e),
                )
                if attempt < self.config.retry_count - 1:
                    time.sleep(self.config.retry_delay)

        error_msg = f"Failed to send image after {self.config.retry_count} attempts"
        logger.error(error_msg)
        return VssResponse(success=False, error=error_msg)

    def wait_duration(
        self,
        duration: float,
        check_interrupt: Optional[Callable[[], bool]] = None,
        check_interval: float = 0.1,
    ) -> bool:
        """Wait for the specified duration, checking for interrupts.

        Args:
            duration: Time to wait in seconds
            check_interrupt: Optional callback to check for priority interrupts
            check_interval: How often to check for interrupts (seconds)

        Returns:
            True if completed without interrupt, False if interrupted
        """
        start_time = time.time()
        elapsed = 0.0

        while elapsed < duration:
            if check_interrupt and check_interrupt():
                logger.info("Wait interrupted by priority message")
                return False

            remaining = duration - elapsed
            sleep_time = min(check_interval, remaining)
            time.sleep(sleep_time)
            elapsed = time.time() - start_time

        return True

    def close(self) -> None:
        """Close the client session."""
        self.session.close()
