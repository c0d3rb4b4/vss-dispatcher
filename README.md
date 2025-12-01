# vss-dispatcher

Central dispatcher that reads messages from vss.normal and vss.priority queues, applies "priority interrupts normal" scheduling rules, and sends images to VSS for rendering.

## Features

- Consumes messages from RabbitMQ `vss.normal` and `vss.priority` queues
- Priority messages can interrupt normal message processing
- Sends images to VSS service for rendering
- Waits for configured duration after sending each image
- Automatic reconnection on connection failures
- Configurable via environment variables

## Project Structure

```
vss-dispatcher/
├── src/
│   ├── __init__.py
│   ├── main.py          # Main entry point
│   ├── broker.py        # RabbitMQ consumer with priority interrupt
│   ├── vss_client.py    # VSS service client
│   ├── models.py        # Data models
│   └── config.py        # Configuration management
├── config/
│   └── dispatcher.env.example
├── .github/
│   └── workflows/
│       └── deploy.yml   # Self-hosted deployment workflow
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── README.md
```

## Message Format

Messages should be JSON formatted with the following structure:

```json
{
  "image_path": "/mnt/samba/images/example.jpg",
  "duration": 5.0,
  "message_id": "optional-unique-id"
}
```

## Configuration

The application can be configured via environment variables:

### RabbitMQ Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `RABBITMQ_HOST` | `rabbitmq` | RabbitMQ server hostname |
| `RABBITMQ_PORT` | `5672` | RabbitMQ server port |
| `RABBITMQ_USERNAME` | `guest` | RabbitMQ username |
| `RABBITMQ_PASSWORD` | `guest` | RabbitMQ password |
| `RABBITMQ_VHOST` | `/` | RabbitMQ virtual host |
| `RABBITMQ_NORMAL_QUEUE` | `vss.normal` | Normal priority queue name |
| `RABBITMQ_PRIORITY_QUEUE` | `vss.priority` | Priority queue name |
| `RABBITMQ_PREFETCH_COUNT` | `1` | Number of messages to prefetch |

### VSS Service Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `VSS_BASE_URL` | `http://localhost:8080` | VSS service base URL |
| `VSS_TIMEOUT` | `30` | Request timeout in seconds |
| `VSS_RETRY_COUNT` | `3` | Number of retry attempts |
| `VSS_RETRY_DELAY` | `1.0` | Delay between retries in seconds |

### Application Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_LEVEL` | `INFO` | Logging level |
| `CHECK_INTERVAL` | `0.1` | Priority interrupt check interval in seconds |

## Quick Start

### Using Docker Compose

1. Clone the repository:
   ```bash
   git clone https://github.com/c0d3rb4b4/vss-dispatcher.git
   cd vss-dispatcher
   ```

2. Build and start services:
   ```bash
   docker compose build
   docker compose up -d
   ```

3. Check service status:
   ```bash
   docker compose ps
   ```

4. View logs:
   ```bash
   docker compose logs -f vss-dispatcher
   ```

### Services

The Docker Compose setup includes:

- **vss-dispatcher**: The main dispatcher service
- **rabbitmq**: RabbitMQ with management UI (accessible at http://localhost:15672)
- **samba**: Samba file server for shared image storage

## Development

### Local Setup

1. Create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Run the application:
   ```bash
   python -m src.main
   ```

## CI/CD

The project includes a GitHub Actions workflow for self-hosted deployment:

- Builds Docker images on push to main branch
- Deploys using Docker Compose
- Runs on self-hosted runners

## License

MIT License
