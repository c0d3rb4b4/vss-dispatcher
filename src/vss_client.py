"""VSS client for sending images to the VSS service."""

import base64
import hashlib
import hmac
import io
import logging
import math
import time
from email.utils import formatdate
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urljoin, urlparse

import requests
from PIL import Image
from requests.exceptions import RequestException

from .config import VSSConfig
from .models import VssMessage, VssResponse

logger = logging.getLogger(__name__)


class VssClient:
    """Client for communicating with the VSS service using HMAC authentication."""

    def __init__(self, config: VSSConfig):
        """Initialize the VSS client.

        Args:
            config: VSS configuration
        """
        self.config = config
        self.session = requests.Session()

    def _build_auth_header(
        self,
        method: str,
        content_type: str,
        date_header: str,
        request_path: str,
    ) -> str:
        """Build HMAC authentication header as per Visionect docs.
        
        Authorization = APIKey + ":" + base64(hmac-sha256(APISecret,
            HTTP-verb + "\n" +
            Content-Sha256 + "\n" +
            Content-Type + "\n" +
            Date + "\n" +
            RequestPath))
        
        Args:
            method: HTTP method (PUT, GET, etc.)
            content_type: Content-Type header value
            date_header: Date header value
            request_path: The API request path
            
        Returns:
            Authorization header value
        """
        # Content-Sha256 not used → empty line between METHOD and Content-Type
        string_to_sign = f"{method}\n\n{content_type}\n{date_header}\n{request_path}"
        digest = hmac.new(
            self.config.api_secret.encode("utf-8"),
            string_to_sign.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        signature = base64.b64encode(digest).decode("ascii").strip()
        return f"{self.config.api_key}:{signature}"

    def _resize_and_center_crop(
        self,
        image_path: str,
        target_width: int = 2560,
        target_height: int = 1440,
    ) -> tuple[str, io.BytesIO, str]:
        """Resize and center-crop image to target dimensions.
        
        Args:
            image_path: Path to the image file
            target_width: Target width in pixels
            target_height: Target height in pixels
            
        Returns:
            Tuple of (filename, image_buffer, mime_type)
        """
        with Image.open(image_path) as img:
            img = img.convert("RGB")
            orig_width, orig_height = img.size
            scale = max(target_width / orig_width, target_height / orig_height)
            resized_width = math.ceil(orig_width * scale)
            resized_height = math.ceil(orig_height * scale)
            resized = img.resize((resized_width, resized_height), Image.LANCZOS)

            left = (resized_width - target_width) // 2
            top = (resized_height - target_height) // 2
            right = left + target_width
            bottom = top + target_height
            cropped = resized.crop((left, top, right, bottom))

            buffer = io.BytesIO()
            cropped.save(buffer, format="PNG")
            buffer.seek(0)

            filename = f"{Path(image_path).stem}_2560x1440.png"
            return filename, buffer, "image/png"

    def send_image(self, message: VssMessage) -> VssResponse:
        """Send an image to the VSS service for rendering.

        Args:
            message: The VSS message containing image path and duration

        Returns:
            VssResponse indicating success or failure
        """
        image_path = message.image_path
        
        # Validate image exists
        if not Path(image_path).exists():
            error_msg = f"Image file not found: {image_path}"
            logger.error("Image file not found: path=%s", image_path)
            return VssResponse(success=False, error=error_msg)

        # Prepare VSS endpoint
        if not self.config.base_url.endswith("/"):
            base_url = self.config.base_url + "/"
        else:
            base_url = self.config.base_url

        # Combine device UUIDs into comma-separated list for HTTP backend
        uuid_segment = ",".join(self.config.device_uuids)
        request_path = f"/backend/{uuid_segment}/"

        # Build full URL using netloc only
        parsed = urlparse(base_url)
        api_base = f"{parsed.scheme}://{parsed.netloc}"
        url = urljoin(api_base, request_path.lstrip("/"))

        logger.debug("Preparing to send image to VSS: url=%s, image=%s, duration=%.2fs, devices=%s",
                    url, image_path, message.duration, self.config.device_uuids)
        
        for attempt in range(self.config.retry_count):
            try:
                logger.info(
                    "Sending image to VSS: image=%s, attempt=%d/%d, timeout=%ds",
                    image_path,
                    attempt + 1,
                    self.config.retry_count,
                    self.config.timeout,
                )

                # Resize and prepare image
                filename, processed_image, mime_type = self._resize_and_center_crop(image_path)
                
                # Prepare headers with HMAC authentication
                method = "PUT"
                content_type = "multipart/form-data"
                date_header = formatdate(timeval=None, localtime=False, usegmt=True)
                
                auth_header = self._build_auth_header(
                    method=method,
                    content_type=content_type,
                    date_header=date_header,
                    request_path=request_path,
                )
                
                headers = {
                    "Date": date_header,
                    "Authorization": auth_header,
                }
                
                # Field name must be "image" as per HTTP Backend docs
                files = {
                    "image": (filename, processed_image, mime_type),
                }

                response = self.session.put(
                    url,
                    headers=headers,
                    files=files,
                    timeout=self.config.timeout,
                )
                response.raise_for_status()

                logger.info("Successfully sent image to VSS: image=%s, status=%d, attempt=%d/%d",
                           image_path, response.status_code, attempt + 1, self.config.retry_count)
                return VssResponse(success=True, message="Image sent successfully")

            except FileNotFoundError as e:
                error_msg = f"Image file not found: {image_path}"
                logger.error("Image file not found: path=%s, error=%s", image_path, str(e))
                return VssResponse(success=False, error=error_msg)
            except RequestException as e:
                logger.warning(
                    "Failed to send image to VSS: image=%s, url=%s, attempt=%d/%d, error=%s",
                    image_path,
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
                    image_path, url, self.config.retry_count)
        return VssResponse(success=False, error=error_msg)

    def wait_duration(
        self,
        duration: float,
        check_interrupt: Optional[Callable[[], bool]] = None,
        poll_callback: Optional[Callable[[], None]] = None,
        check_interval: float = 0.1,
    ) -> bool:
        """Wait for the specified duration, checking for interrupts.

        Args:
            duration: Time to wait in seconds
            check_interrupt: Optional callback to check for priority interrupts
            poll_callback: Optional callback to poll for new messages during wait
            check_interval: How often to check for interrupts (seconds)

        Returns:
            True if completed without interrupt, False if interrupted
        """
        logger.debug("Starting wait duration: duration=%.2fs, check_interval=%.2fs, has_interrupt_check=%s",
                    duration, check_interval, bool(check_interrupt))
        start_time = time.time()
        elapsed = 0.0

        while elapsed < duration:
            # Poll for new messages from RabbitMQ
            if poll_callback:
                poll_callback()
            
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
        return True

    def close(self) -> None:
        """Close the client session."""
        self.session.close()
