"""Constants for vss-dispatcher service."""

# Application metadata
APP_NAME = "vss-dispatcher"
APP_VERSION = "1.0.0"

# RabbitMQ queue name
DEFAULT_NORMAL_QUEUE = "vss.normal"
DEFAULT_VHOST = "/mediawall"

# Connection defaults
DEFAULT_RABBITMQ_PORT = 5672
DEFAULT_PREFETCH_COUNT = 1
DEFAULT_HEARTBEAT = 600
DEFAULT_BLOCKED_CONNECTION_TIMEOUT = 300

# VSS client defaults
DEFAULT_VSS_TIMEOUT = 30
DEFAULT_VSS_RETRY_COUNT = 3
DEFAULT_VSS_RETRY_DELAY = 1.0

# Reconnection settings
MAX_RECONNECT_RETRIES = 5
RECONNECT_DELAY_SECONDS = 5

# Processing defaults
DEFAULT_CHECK_INTERVAL = 0.1
DEFAULT_MESSAGE_DURATION = -1.0

# Mount paths
DEFAULT_SAMBA_MOUNT = "/mnt/mediawall"
DEFAULT_BASE_IMAGE_DIR = "/mnt/mediawall/mediawall/vss-dispatcher/base-image"
DEFAULT_COMPOSITE_DIR = "/mnt/mediawall/mediawall/vss-dispatcher/composites"

# Default display resolution
DEFAULT_DISPLAY_WIDTH = 2560
DEFAULT_DISPLAY_HEIGHT = 1440

# Allowed image extensions
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
