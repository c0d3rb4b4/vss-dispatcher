"""RabbitMQ broker for consuming messages from vss.normal and vss.priority queues."""

import json
import logging
import threading
import time
from collections import deque
from typing import Callable, Optional

import pika
from pika.adapters.blocking_connection import BlockingChannel
from pika.exceptions import AMQPConnectionError, AMQPChannelError

from .config import RabbitMQConfig
from .constants import (
    DEFAULT_BLOCKED_CONNECTION_TIMEOUT,
    DEFAULT_HEARTBEAT,
    MAX_RECONNECT_RETRIES,
    RECONNECT_DELAY_SECONDS,
)
from .models import MessagePriority, VssMessage

logger = logging.getLogger(__name__)


class MessageBroker:
    """RabbitMQ message broker with priority interrupt support."""

    def __init__(
        self,
        config: RabbitMQConfig,
        message_handler: Callable[[VssMessage], None],
    ):
        """Initialize the message broker.

        Args:
            config: RabbitMQ configuration
            message_handler: Callback function to handle messages
        """
        self.config = config
        self.message_handler = message_handler
        self.connection: Optional[pika.BlockingConnection] = None
        self.channel: Optional[BlockingChannel] = None
        self.priority_queue: deque = deque()
        self.normal_queue: deque = deque()
        self._running = False
        self._lock = threading.Lock()
        self._priority_event = threading.Event()
        self._current_message: Optional[VssMessage] = None

    def connect(self) -> None:
        """Establish connection to RabbitMQ."""
        credentials = pika.PlainCredentials(
            self.config.username,
            self.config.password,
        )
        parameters = pika.ConnectionParameters(
            host=self.config.host,
            port=self.config.port,
            virtual_host=self.config.virtual_host,
            credentials=credentials,
            heartbeat=DEFAULT_HEARTBEAT,
            blocked_connection_timeout=DEFAULT_BLOCKED_CONNECTION_TIMEOUT,
        )

        logger.info("Connecting to RabbitMQ: host=%s, port=%d, vhost=%s, user=%s",
                   self.config.host, self.config.port, self.config.virtual_host, self.config.username)
        self.connection = pika.BlockingConnection(parameters)
        self.channel = self.connection.channel()

        # Declare queues
        logger.debug("Declaring priority queue: %s (durable=True)", self.config.priority_queue)
        self.channel.queue_declare(queue=self.config.priority_queue, durable=True)
        logger.debug("Declaring normal queue: %s (durable=True)", self.config.normal_queue)
        self.channel.queue_declare(queue=self.config.normal_queue, durable=True)

        # Set prefetch count
        logger.debug("Setting QoS prefetch count: %d", self.config.prefetch_count)
        self.channel.basic_qos(prefetch_count=self.config.prefetch_count)

        logger.info("Connected to RabbitMQ successfully: queues=%s, %s",
                   self.config.priority_queue, self.config.normal_queue)

    def _on_priority_message(
        self,
        channel: BlockingChannel,
        method: pika.spec.Basic.Deliver,
        properties: pika.BasicProperties,
        body: bytes,
    ) -> None:
        """Handle incoming priority messages."""
        try:
            logger.debug("Received priority message: delivery_tag=%d, body_size=%d bytes",
                        method.delivery_tag, len(body))
            data = json.loads(body.decode("utf-8"))
            message = VssMessage.from_dict(data, MessagePriority.PRIORITY)
            logger.info("Parsed priority message: type=%s, image=%s, duration=%.2fs, delivery_tag=%d",
                       message.message_type.value, message.image_path, message.duration, method.delivery_tag)

            with self._lock:
                queue_size = len(self.priority_queue)
                self.priority_queue.append((message, method.delivery_tag))
                self._priority_event.set()
                logger.debug("Priority message queued: queue_size=%d", queue_size + 1)

        except (json.JSONDecodeError, KeyError) as e:
            logger.error("Failed to parse priority message: delivery_tag=%d, body_size=%d, error=%s",
                        method.delivery_tag, len(body), str(e))
            channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

    def _on_normal_message(
        self,
        channel: BlockingChannel,
        method: pika.spec.Basic.Deliver,
        properties: pika.BasicProperties,
        body: bytes,
    ) -> None:
        """Handle incoming normal messages."""
        try:
            logger.debug("Received normal message: delivery_tag=%d, body_size=%d bytes",
                        method.delivery_tag, len(body))
            data = json.loads(body.decode("utf-8"))
            message = VssMessage.from_dict(data, MessagePriority.NORMAL)
            logger.info("Parsed normal message: type=%s, image=%s, duration=%.2fs, delivery_tag=%d",
                       message.message_type.value, message.image_path, message.duration, method.delivery_tag)

            with self._lock:
                queue_size = len(self.normal_queue)
                self.normal_queue.append((message, method.delivery_tag))
                logger.debug("Normal message queued: queue_size=%d", queue_size + 1)

        except (json.JSONDecodeError, KeyError) as e:
            logger.error("Failed to parse normal message: delivery_tag=%d, body_size=%d, error=%s",
                        method.delivery_tag, len(body), str(e))
            channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

    def has_priority_interrupt(self) -> bool:
        """Check if there's a priority message waiting to interrupt."""
        with self._lock:
            return len(self.priority_queue) > 0

    def _get_next_message(self) -> Optional[tuple[VssMessage, int]]:
        """Get the next message to process, prioritizing priority queue."""
        with self._lock:
            if self.priority_queue:
                return self.priority_queue.popleft()
            if self.normal_queue:
                return self.normal_queue.popleft()
        return None

    def _process_messages(self) -> None:
        """Process messages from both queues with priority interrupt support."""
        logger.debug("Starting message processing loop")
        while self._running:
            # Check for new messages
            if self.connection and self.connection.is_open:
                try:
                    self.connection.process_data_events(time_limit=0.1)
                except (AMQPConnectionError, AMQPChannelError) as e:
                    logger.error("Connection error during data events processing: error=%s", str(e))
                    self._reconnect()
                    continue

            # Get next message to process
            message_data = self._get_next_message()
            if message_data:
                message, delivery_tag = message_data
                self._current_message = message
                
                logger.debug("Processing message: priority=%s, image=%s, delivery_tag=%d",
                            message.priority.value, message.image_path, delivery_tag)

                try:
                    self.message_handler(message)
                    if self.channel and self.channel.is_open:
                        self.channel.basic_ack(delivery_tag=delivery_tag)
                        logger.debug("Message ACKed: delivery_tag=%d, image=%s", delivery_tag, message.image_path)
                except Exception as e:
                    logger.error("Error processing message: image=%s, delivery_tag=%d, error=%s",
                                message.image_path, delivery_tag, str(e), exc_info=True)
                    if self.channel and self.channel.is_open:
                        self.channel.basic_nack(
                            delivery_tag=delivery_tag, requeue=True
                        )
                        logger.warning("Message NACKed and requeued: delivery_tag=%d, image=%s", 
                                     delivery_tag, message.image_path)
                finally:
                    self._current_message = None
                    self._priority_event.clear()
            else:
                time.sleep(0.1)

    def _reconnect(self) -> None:
        """Attempt to reconnect to RabbitMQ."""
        for attempt in range(MAX_RECONNECT_RETRIES):
            try:
                logger.info(
                    "Attempting to reconnect (attempt %d/%d)",
                    attempt + 1,
                    MAX_RECONNECT_RETRIES,
                )
                self.connect()
                self._setup_consumers()
                logger.info("Reconnected successfully")
                return
            except AMQPConnectionError as e:
                logger.warning("Reconnection failed: %s", str(e))
                if attempt < MAX_RECONNECT_RETRIES - 1:
                    time.sleep(RECONNECT_DELAY_SECONDS)

        logger.error("Failed to reconnect after %d attempts", MAX_RECONNECT_RETRIES)
        self._running = False

    def _setup_consumers(self) -> None:
        """Set up message consumers for both queues."""
        if self.channel:
            self.channel.basic_consume(
                queue=self.config.priority_queue,
                on_message_callback=self._on_priority_message,
                auto_ack=False,
            )
            self.channel.basic_consume(
                queue=self.config.normal_queue,
                on_message_callback=self._on_normal_message,
                auto_ack=False,
            )

    def start(self) -> None:
        """Start consuming messages."""
        self._running = True
        self._setup_consumers()

        logger.info("Starting message consumption")
        self._process_messages()

    def stop(self) -> None:
        """Stop consuming messages and close connection."""
        logger.info("Stopping message broker")
        self._running = False

        if self.channel and self.channel.is_open:
            self.channel.close()
        if self.connection and self.connection.is_open:
            self.connection.close()

        logger.info("Message broker stopped")
