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

        logger.debug("Preparing to send image to VSS: url=%s, image=%s, duration=%.2fs, max_attempts=%d",
                    url, message.image_path, message.duration, self.config.retry_count)
        
        for attempt in range(self.config.retry_count):
            try:
                logger.info(
                    "Sending image to VSS: image=%s, attempt=%d/%d, timeout=%ds",
                    message.image_path,
                    attempt + 1,
                    self.config.retry_count,
                    self.config.timeout,
                )

                response = self.session.post(
                    url,
                    json=payload,
                    timeout=self.config.timeout,
                )
                response.raise_for_status()

                logger.info("Successfully sent image to VSS: image=%s, status=%d, attempt=%d/%d",
                           message.image_path, response.status_code, attempt + 1, self.config.retry_count)
                return VssResponse(success=True, message="Image sent successfully")

            except RequestException as e:
                logger.warning(
                    "Failed to send image to VSS: image=%s, url=%s, attempt=%d/%d, error=%s",
                    message.image_path,
                    url,
                    attempt + 1,
                    self.config.retry_count,
                    str(e),
                )
                if attempt < self.config.retry_count - 1:
                    logger.debug("Retrying in %.1fs...", self.config.retry_delay)
                    time.sleep(self.config.retry_delay)

        error_msg = f"Failed to send image after {self.config.retry_count} attempts"
        logger.error("All VSS send attempts failed: image=%s, url=%s, attempts=%d",
                    message.image_path, url, self.config.retry_count)
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
        logger.debug("Starting wait duration: duration=%.2fs, check_interval=%.2fs, has_interrupt_check=%s",
                    duration, check_interval, bool(check_interrupt))
        start_time = time.time()
        elapsed = 0.0

        while elapsed < duration:
            if check_interrupt and check_interrupt():
                logger.info("Wait interrupted by priority message: elapsed=%.2fs, total_duration=%.2fs",
                           elapsed, duration)
                return False

            remaining = duration - elapsed
            sleep_time = min(check_interval, remaining)
            time.sleep(sleep_time)
            elapsed = time.time() - start_time

        logger.debug("Wait duration completed: duration=%.2fs, actual_elapsed=%.2fs", duration, elapsed)
        return True

    def close(self) -> None:
        """Close the client session."""
        self.session.close()
