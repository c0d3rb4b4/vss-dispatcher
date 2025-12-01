"""Main entry point for vss-dispatcher."""

import logging
import signal
import sys

from .broker import MessageBroker
from .config import load_config
from .models import VssMessage
from .vss_client import VssClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger(__name__)


class VssDispatcher:
    """Main dispatcher class that coordinates message handling and VSS communication."""

    def __init__(self):
        """Initialize the dispatcher."""
        self.config = load_config()
        self.vss_client = VssClient(self.config.vss)
        self.broker: MessageBroker = None
        self._shutdown_requested = False

        # Set log level from config
        logging.getLogger().setLevel(self.config.log_level)

    def handle_message(self, message: VssMessage) -> None:
        """Handle a VSS message.

        Args:
            message: The message to process
        """
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

        logger.info("Starting VSS Dispatcher")
        logger.info("RabbitMQ: %s:%d", self.config.rabbitmq.host, self.config.rabbitmq.port)
        logger.info("VSS Service: %s", self.config.vss.base_url)

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
