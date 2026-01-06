"""Main entry point for vss-dispatcher."""

import json
import logging
import signal
import sys
import threading
from pathlib import Path

from .broker import MessageBroker
from .compositor import ImageCompositor
from .config import load_config
from .constants import ALLOWED_IMAGE_EXTENSIONS, APP_NAME, APP_VERSION, DEFAULT_MESSAGE_DURATION
from .models import MessageType, VssMessage
from .vss_client import VssClient


class JsonFormatter(logging.Formatter):
    """JSON formatter for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": APP_NAME,
            "version": APP_VERSION,
        }
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_data)


def setup_logging(level: str) -> None:
    """Configure JSON structured logging."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logging.root.handlers = [handler]
    log_level = getattr(logging, level.upper(), logging.INFO)
    logging.root.setLevel(log_level)
    handler.setLevel(log_level)


logger = logging.getLogger(__name__)


def validate_image_path(image_path: str, mount_path: str) -> bool:
    """Validate that the image path is valid and accessible.

    Args:
        image_path: Path to the image file
        mount_path: Base mount path for validation

    Returns:
        True if valid, False otherwise
    """
    if not image_path:
        logger.warning("Validation failed: empty image path")
        return False

    # Check extension
    path = Path(image_path)
    if path.suffix.lower() not in ALLOWED_IMAGE_EXTENSIONS:
        logger.warning(
            "Validation failed: invalid image extension - path=%s, extension=%s, allowed=%s",
            image_path,
            path.suffix,
            ALLOWED_IMAGE_EXTENSIONS,
        )
        return False

    # Check if path is under mount path (security)
    try:
        full_path = Path(image_path).resolve()
        mount_resolved = Path(mount_path).resolve()
        if not str(full_path).startswith(str(mount_resolved)):
            logger.warning(
                "Validation failed: image path outside mount - image=%s, mount=%s",
                image_path,
                mount_path,
            )
            return False
    except (OSError, ValueError) as e:
        logger.warning("Validation failed: path resolution error - path=%s, mount=%s, error=%s", 
                      image_path, mount_path, str(e))
        return False

    logger.debug("Image path validated successfully: path=%s", image_path)
    return True


class VssDispatcher:
    """Main dispatcher class that coordinates message handling and VSS communication."""

    def __init__(self):
        """Initialize the dispatcher."""
        logger.debug("Initializing VssDispatcher")
        self.config = load_config()

        # Set up logging first
        setup_logging(self.config.log_level)
        logger.info("Logging configured: level=%s", self.config.log_level)

        logger.debug("Initializing VSS client: base_url=%s, timeout=%d, retries=%d",
                    self.config.vss.base_url, self.config.vss.timeout, self.config.vss.retry_count)
        self.vss_client = VssClient(self.config.vss)
        
        logger.debug("Initializing image compositor: base_dir=%s, composite_dir=%s, resolution=%dx%d",
                    self.config.mount.base_image_dir, self.config.mount.composite_dir,
                    self.config.mount.display_width, self.config.mount.display_height)
        self.compositor = ImageCompositor(
            base_image_dir=self.config.mount.base_image_dir,
            composite_dir=self.config.mount.composite_dir,
            display_width=self.config.mount.display_width,
            display_height=self.config.mount.display_height,
        )
        
        self.broker: MessageBroker = None
        self._shutdown_requested = False
        
        # Store last overlay for reapplication on base image changes
        self._last_overlay_path: str | None = None
        self._forever_image_path: str | None = None
        self._revert_timer: threading.Timer | None = None
        
        logger.debug("VssDispatcher initialized successfully")

    def handle_message(self, message: VssMessage, ack_callback=None) -> None:
        """Handle a VSS message.

        Args:
            message: The message to process
            ack_callback: Optional callback to acknowledge message early
        """
        logger.debug(
            "Handling message: type=%s, image=%s, duration=%.2fs",
            message.message_type.value,
            message.image_path,
            message.duration,
        )

        # Validate image path
        if not validate_image_path(message.image_path, self.config.mount.samba_mount):
            logger.error(
                "Message rejected: invalid image path - type=%s, image=%s",
                message.message_type.value,
                message.image_path,
            )
            return

        # Handle based on type (duration only meaningful for IMAGE)
        final_image_path = message.image_path

        if message.message_type == MessageType.IMAGE:
            final_image_path = self._handle_image_message(message)
        elif message.message_type == MessageType.OVERLAY:
            final_image_path = self._handle_overlay_message(message)

        if not final_image_path:
            logger.error("Failed to determine final image path for message: %s", message.image_path)
            return

        response = self.vss_client.send_image(
            VssMessage(
                image_path=final_image_path,
                duration=message.duration,
                message_type=message.message_type,
                message_id=message.message_id,
            )
        )

        if response.success:
            logger.info(
                "Image sent to VSS: type=%s, image=%s, duration=%.2fs",
                message.message_type.value,
                final_image_path,
                message.duration,
            )
            if ack_callback:
                ack_callback()
        else:
            logger.error(
                "Failed to send image to VSS: type=%s, image=%s, vss_url=%s, error=%s",
                message.message_type.value,
                final_image_path,
                self.config.vss.base_url,
                response.error,
            )

    def _handle_image_message(self, message: VssMessage) -> str | None:
        """Handle an IMAGE message with forever/timed semantics."""
        # Cancel any pending revert timer when a new image arrives
        if self._revert_timer and self._revert_timer.is_alive():
            self._revert_timer.cancel()
            self._revert_timer = None

        if not self.compositor.update_base_image(message.image_path):
            logger.error("Failed to update base image: image=%s", message.image_path)
            return None

        # If duration <= 0, treat as forever image and remember it
        if message.duration <= 0:
            self._forever_image_path = message.image_path
            logger.info("Set forever base image: %s", self._forever_image_path)
        else:
            # Timed image: display now and schedule revert to forever image (if available)
            logger.info(
                "Processing timed IMAGE message: image=%s, duration=%.2fs",
                message.image_path,
                message.duration,
            )

            if self._forever_image_path:
                self._revert_timer = threading.Timer(
                    message.duration,
                    self._revert_to_forever_image,
                )
                self._revert_timer.daemon = True
                self._revert_timer.start()
                logger.debug(
                    "Scheduled revert to forever image in %.2fs: forever=%s",
                    message.duration,
                    self._forever_image_path,
                )
            else:
                logger.debug("No forever image set; timed image will persist until next update")

        # Reapply stored overlay if any
        if self._last_overlay_path:
            logger.info("Reapplying stored overlay to new base image: overlay=%s", self._last_overlay_path)
            composited_path = self.compositor.composite_overlay(self._last_overlay_path)
            if composited_path:
                self.compositor.clear_old_composites()
                return composited_path
            else:
                logger.warning("Failed to reapply overlay, using base image only")

        return message.image_path

    def _handle_overlay_message(self, message: VssMessage) -> str | None:
        """Handle an OVERLAY message by compositing on current base."""
        logger.info(
            "Processing OVERLAY message: compositing on base - overlay=%s",
            message.image_path,
        )

        # Check if this is a blank/clear overlay
        if self._is_blank_overlay(message.image_path):
            logger.info("Received blank overlay, clearing stored overlay")
            self._last_overlay_path = None
            return self.compositor.get_current_base_image_path()

        # Store this overlay for reapplication on future base image changes
        self._last_overlay_path = message.image_path
        logger.debug("Stored overlay for future reapplication: %s", message.image_path)

        # Composite overlay on current base
        composited_path = self.compositor.composite_overlay(message.image_path)
        if not composited_path:
            logger.error("Failed to composite overlay: overlay=%s", message.image_path)
            return None

        self.compositor.clear_old_composites()
        return composited_path

    def _revert_to_forever_image(self) -> None:
        """Revert display to the stored forever image if available."""
        if not self._forever_image_path:
            logger.debug("Revert skipped: no forever image set")
            return

        logger.info("Reverting to forever base image: %s", self._forever_image_path)
        self.compositor.update_base_image(self._forever_image_path)

        # Determine final image path - reapply overlay if stored
        final_image_path = self._forever_image_path
        if self._last_overlay_path:
            logger.info("Reapplying stored overlay after revert: overlay=%s", self._last_overlay_path)
            composited_path = self.compositor.composite_overlay(self._last_overlay_path)
            if composited_path:
                final_image_path = composited_path
                self.compositor.clear_old_composites()
            else:
                logger.warning("Failed to reapply overlay after revert, using base image only")

        response = self.vss_client.send_image(
            VssMessage(
                image_path=final_image_path,
                duration=DEFAULT_MESSAGE_DURATION,
                message_type=MessageType.IMAGE,
            )
        )
        if response.success:
            logger.info("Forever image restored successfully: %s", final_image_path)
        else:
            logger.error(
                "Failed to restore forever image: image=%s, error=%s",
                final_image_path,
                response.error,
            )

    def _signal_handler(self, signum: int, frame) -> None:
        """Handle shutdown signals."""
        logger.info("Received signal %d, initiating shutdown", signum)
        self._shutdown_requested = True
        if self.broker:
            self.broker.stop()

    def _is_blank_overlay(self, image_path: str) -> bool:
        """Check if an image is a blank/transparent overlay.
        
        Args:
            image_path: Path to the image file
            
        Returns:
            True if the image is blank/transparent, False otherwise
        """
        from pathlib import Path
        try:
            # Check filename - blank overlays typically have "clear" in the name
            if "clear" in Path(image_path).name.lower():
                logger.debug("Detected blank overlay from filename: %s", image_path)
                return True
            
            # Could also check file size - blank overlays are typically very small
            # For now, just use the filename check
            return False
        except Exception as e:
            logger.warning("Error checking if overlay is blank: %s, error=%s", image_path, str(e))
            return False

    def run(self) -> None:
        """Run the dispatcher."""
        # Set up signal handlers
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)

        logger.info(
            "Starting %s v%s",
            APP_NAME,
            APP_VERSION,
        )
        logger.info(
            "RabbitMQ: host=%s, port=%d, vhost=%s, queue=%s",
            self.config.rabbitmq.host,
            self.config.rabbitmq.port,
            self.config.rabbitmq.virtual_host,
            self.config.rabbitmq.normal_queue,
        )
        logger.info("VSS Service: base_url=%s, timeout=%ds, retries=%d", 
                   self.config.vss.base_url, self.config.vss.timeout, self.config.vss.retry_count)
        logger.info("Mount path: %s", self.config.mount.samba_mount)
        logger.info("Check interval: %.2fs, prefetch count: %d", 
                   self.config.check_interval, self.config.rabbitmq.prefetch_count)

        # Initialize broker
        logger.debug("Initializing message broker")
        self.broker = MessageBroker(
            self.config.rabbitmq,
            self.handle_message,
        )

        try:
            # Connect to RabbitMQ
            logger.debug("Connecting to RabbitMQ broker")
            self.broker.connect()

            # Start consuming messages
            logger.info("Starting message consumption loop")
            self.broker.start()

        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received, initiating shutdown")
        except Exception as e:
            logger.error("Fatal error in dispatcher: %s", str(e), exc_info=True)
            raise
        finally:
            self.cleanup()

    def cleanup(self) -> None:
        """Clean up resources."""
        logger.info("Cleaning up resources")
        if self.broker:
            self.broker.stop()
        if self.vss_client:
            self.vss_client.close()
        logger.info("Cleanup complete")


def main() -> None:
    """Main entry point."""
    dispatcher = VssDispatcher()
    dispatcher.run()


if __name__ == "__main__":
    main()
