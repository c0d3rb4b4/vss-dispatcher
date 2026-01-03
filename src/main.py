"""Main entry point for vss-dispatcher."""

import json
import logging
import signal
import sys
from pathlib import Path

from .broker import MessageBroker
from .config import load_config
from .constants import ALLOWED_IMAGE_EXTENSIONS, APP_NAME, APP_VERSION
from .models import VssMessage
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
    logging.root.setLevel(level)


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
        logger.warning("Empty image path received")
        return False

    # Check extension
    path = Path(image_path)
    if path.suffix.lower() not in ALLOWED_IMAGE_EXTENSIONS:
        logger.warning(
            "Invalid image extension: %s (allowed: %s)",
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
                "Image path %s is outside mount path %s",
                image_path,
                mount_path,
            )
            return False
    except (OSError, ValueError) as e:
        logger.warning("Path validation error: %s", str(e))
        return False

    return True


class VssDispatcher:
    """Main dispatcher class that coordinates message handling and VSS communication."""

    def __init__(self):
        """Initialize the dispatcher."""
        self.config = load_config()

        # Set up logging first
        setup_logging(self.config.log_level)

        self.vss_client = VssClient(self.config.vss)
        self.broker: MessageBroker = None
        self._shutdown_requested = False

    def handle_message(self, message: VssMessage) -> None:
        """Handle a VSS message.

        Args:
            message: The message to process
        """
        # Validate image path
        if not validate_image_path(message.image_path, self.config.mount.samba_mount):
            logger.error("Invalid image path, skipping message: %s", message.image_path)
            return

        logger.info(
            "Processing %s message: %s (duration: %.2fs)",
            message.priority.value,
            message.image_path,
            message.duration,
        )

        # Send image to VSS
        response = self.vss_client.send_image(message)

        if response.success:
            # Wait for duration, checking for priority interrupts
            completed = self.vss_client.wait_duration(
                message.duration,
                check_interrupt=self.broker.has_priority_interrupt,
                check_interval=self.config.check_interval,
            )

            if completed:
                logger.info("Completed displaying: %s", message.image_path)
            else:
                logger.info(
                    "Display interrupted by priority message: %s",
                    message.image_path,
                )
        else:
            logger.error(
                "Failed to send image to VSS: %s - %s",
                message.image_path,
                response.error,
            )

    def _signal_handler(self, signum: int, frame) -> None:
        """Handle shutdown signals."""
        logger.info("Received signal %d, initiating shutdown", signum)
        self._shutdown_requested = True
        if self.broker:
            self.broker.stop()

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
        logger.info("RabbitMQ: %s:%d", self.config.rabbitmq.host, self.config.rabbitmq.port)
        logger.info("VSS Service: %s", self.config.vss.base_url)
        logger.info("Mount path: %s", self.config.mount.samba_mount)

        # Initialize broker
        self.broker = MessageBroker(
            self.config.rabbitmq,
            self.handle_message,
        )

        try:
            # Connect to RabbitMQ
            self.broker.connect()

            # Start consuming messages
            self.broker.start()

        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received")
        except Exception as e:
            logger.error("Fatal error: %s", str(e))
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
