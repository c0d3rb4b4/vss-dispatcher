"""Main entry point for vss-dispatcher."""

import json
import logging
import signal
import sys
from pathlib import Path

from .broker import MessageBroker
from .compositor import ImageCompositor
from .config import load_config
from .constants import ALLOWED_IMAGE_EXTENSIONS, APP_NAME, APP_VERSION
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
        
        logger.debug("VssDispatcher initialized successfully")

    def handle_message(self, message: VssMessage) -> None:
        """Handle a VSS message.

        Args:
            message: The message to process
        """
        logger.debug("Handling message: priority=%s, type=%s, image=%s, duration=%.2fs",
                    message.priority.value, message.message_type.value, message.image_path, message.duration)
        
        # Validate image path
        if not validate_image_path(message.image_path, self.config.mount.samba_mount):
            logger.error("Message rejected: invalid image path - priority=%s, type=%s, image=%s",
                        message.priority.value, message.message_type.value, message.image_path)
            return

        # Determine final image path based on message type
        final_image_path = message.image_path
        
        if message.message_type == MessageType.IMAGE:
            # Full image update - also update base image
            logger.info("Processing IMAGE message: updating base and displaying - image=%s, duration=%.2fs",
                       message.image_path, message.duration)
            if not self.compositor.update_base_image(message.image_path):
                logger.error("Failed to update base image: image=%s", message.image_path)
                return
            
            # If we have a stored overlay, reapply it to the new base image
            if self._last_overlay_path:
                logger.info("Reapplying stored overlay to new base image: overlay=%s", self._last_overlay_path)
                composited_path = self.compositor.composite_overlay(self._last_overlay_path)
                if composited_path:
                    final_image_path = composited_path
                    logger.debug("Overlay reapplied successfully: %s", composited_path)
                else:
                    logger.warning("Failed to reapply overlay, using base image only: overlay=%s", self._last_overlay_path)
                    final_image_path = message.image_path
            else:
                # No stored overlay, just display the new base image
                final_image_path = message.image_path
            
        elif message.message_type == MessageType.OVERLAY:
            # Overlay message - composite on current base
            logger.info("Processing OVERLAY message: compositing on base - overlay=%s, duration=%.2fs",
                       message.image_path, message.duration)
            
            # Check if this is a blank/transparent overlay (clear command)
            is_blank_overlay = self._is_blank_overlay(message.image_path)
            if is_blank_overlay:
                logger.info("Received blank overlay, clearing stored overlay")
                self._last_overlay_path = None
                final_image_path = self.compositor.get_current_base_image_path()
            else:
                # Store this overlay for reapplication on future base image changes
                self._last_overlay_path = message.image_path
                logger.debug("Stored overlay for future reapplication: %s", message.image_path)
                
                composited_path = self.compositor.composite_overlay(message.image_path)
                if not composited_path:
                    logger.error("Failed to composite overlay: overlay=%s", message.image_path)
                    return
                # Display the composited image
                final_image_path = composited_path
                # Clean up old composites
                self.compositor.clear_old_composites()

        # Send final image to VSS
        logger.debug("Sending image to VSS: image=%s, vss_url=%s",
                    final_image_path, self.config.vss.base_url)
        
        # Create a new message with the final image path
        display_message = VssMessage(
            image_path=final_image_path,
            duration=message.duration,
            priority=message.priority,
            message_type=message.message_type,
            message_id=message.message_id,
        )
        
        response = self.vss_client.send_image(display_message)

        if response.success:
            logger.debug("Image sent successfully to VSS, starting display wait: duration=%.2fs", message.duration)
            # Wait for duration, checking for priority interrupts
            completed = self.vss_client.wait_duration(
                message.duration,
                check_interrupt=self.broker.has_priority_interrupt,
                check_interval=self.config.check_interval,
            )

            if completed:
                logger.info("Display completed successfully: priority=%s, type=%s, image=%s, duration=%.2fs",
                           message.priority.value, message.message_type.value, final_image_path, message.duration)
            else:
                logger.info(
                    "Display interrupted by priority message: type=%s, image=%s, elapsed_time<%.2fs",
                    message.message_type.value, final_image_path, message.duration,
                )
        else:
            logger.error(
                "Failed to send image to VSS: priority=%s, type=%s, image=%s, vss_url=%s, error=%s",
                message.priority.value,
                message.message_type.value,
                final_image_path,
                self.config.vss.base_url,
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
        logger.info("RabbitMQ: host=%s, port=%d, vhost=%s, priority_queue=%s, normal_queue=%s", 
                   self.config.rabbitmq.host, self.config.rabbitmq.port, self.config.rabbitmq.virtual_host,
                   self.config.rabbitmq.priority_queue, self.config.rabbitmq.normal_queue)
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
