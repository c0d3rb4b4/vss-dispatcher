"""Constants for vss-dispatcher service."""

# Application metadata
APP_NAME = "vss-dispatcher"
APP_VERSION = "1.0.0"

# RabbitMQ queue names
DEFAULT_NORMAL_QUEUE = "vss.normal"
DEFAULT_PRIORITY_QUEUE = "vss.priority"
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
DEFAULT_MESSAGE_DURATION = 5.0

# Mount paths
DEFAULT_SAMBA_MOUNT = "/mnt/mediawall"

# Allowed image extensions
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
