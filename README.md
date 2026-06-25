# Pi Agent 2 — FastAPI Server & Docker Infrastructure

A modern, containerized API server for the Pi agent ecosystem with OpenAI-compatible endpoints to Ollama. Built with Python/FastAPI and Docker Compose for easy deployment.

## Features

- **FastAPI Backend**: High-performance async framework serving requests
- **OpenAI-Compatible Schema**: Standardized interface bridging to local models via Ollama at `http://ollama:11434`
- **Docker-based Architecture**: Full isolation with configurable container names and ports
- **Persistent Workspaces**: Each agent has its own isolated workspace directory

## Getting Started

```bash
git clone <repo-url> && cd pi-agents
docker compose up -d ollama
./manage.sh start         # Starts api, webui, and test_cluster containers
./manage.sh stop          # Stops all running containers with proper cleanup
./manage.sh logs          # Tail combined output from all services
```

## Services (default ports)

| Service           | Port  | Description                    |
|-------------------|-------:|--------------------------------|
| **api**           | 8000   | FastAPI HTTP server            |
| **webui**         | 5173   | Pi agent web UI                |
| **frontend**      | 4173   | Static assets / nginx proxy    |
| test_cluster *   | —     | Health‑check harness per agent  |

\* `api` mounts only its own workspace (`workspaces/{agent}` → `/piagent_workspace`) so other containers cannot read or write there. Running all three containers together is required for full testing coverage; starting them individually works but some endpoints may behave differently in isolation. When updating any script (e.g., `chat.py`), re‑check its behaviour inside a running container via the API—it's often more reliable than editing locally because it reflects the actual runtime filesystem state, not the host copy.

## License

MIT License — see separate file for details.