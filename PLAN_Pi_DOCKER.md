# Implementation Plan: Pi Agent Cluster with Ollama (gemma4:26b-mlx)
**Hardware:** Mac Mini M4 (64GB RAM) - *Target: 2 agents, 1 shared local LLM instance.*

## 1. Project Structure
Create a structured environment to separate configuration, persistent workspaces, and Docker artifacts.

```bash
mkdir -p ~/pi-cluster/workspaces/p1 ~/pi-cluster/workspaces/p2
mkdir -p ~/pi-cluster/config/agent
cd ~/pi-cluster
```

## 2. Host-Side Preparation (Ollama)
The agents rely on a host-running Ollama instance.

1. **Install Ollama**: `curl -fsSL https://ollama.com/install.sh | sh`
2. **Pull Model**: `ollama pull gemma4:26b-mlx` (~17GB)
3. **Verify Connectivity**: Ensure Ollama is running and listening on `0.0.0.0:11434` (default).
4. **Performance Note**: For 26B models, ensure your Mac has sufficient Unified Memory. Monitor via `top` or `Activity Monitor` to ensure the model isn't swapping.

## 3. Custom Dockerfile
Build an image that contains the `pi-agent` runtime and necessary system tools.

```dockerfile
# Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install pi-agent (Assumes package is available in the environment's pip registry)
RUN pip install --no-cache-dir pi-agent

# Create non-root user for security
RUN useradd -m -u 1000 pi && chown -R pi:pi /app
USER pi

# Expose API port
EXPOSE 8000

# Set the entrypoint
ENTRYPOINT ["pi-agent", "start"]
CMD ["--port", "8000"]
```

## 4. Docker Compose Orchestration
This setup spins up two isolated agents. We use `host.docker.internal` to route requests to the host's Ollama instance.

```yaml
# docker-compose.yml
services:
  agent1:
    build: .
    container_name: pi-agent-1
    hostname: pi-agent-1
    user: "1000:1000"
    volumes:
      - ./workspaces/p1:/home/pi/.pi_workspace
      - ./config/agent/models.json:/home/pi/.pi/agent/models.json:ro
    environment:
      - PI_WORKSPACE=/home/pi/.pi_workspace
      - OLLAMA_BASE_URL=http://host.docker.internal:11434
    ports:
      - "8001:8000"
    networks:
      - pi-network
    deploy:
      resources:
        limits:
          memory: 8G # Adjust based on agent-side memory overhead
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
    restart: unless-stopped

  agent2:
    build: .
    container_name: pi-agent-2
    hostname: pi-agent-2
    user: "1000:1000"
    volumes:
      - ./workspaces/p2:/home/pi/.pi_workspace
      - ./config/agent/models.json:/home/pi/.pi/agent/models.json:ro
    environment:
      - PI_WORKSPACE=/home/pi/.pi_workspace
      - OLLAMA_BASE_URL=http://host.docker.internal:11434
    ports:
      - "8002:8000"
    networks:
      - pi-network
    deploy:
      resources:
        limits:
          memory: 8G
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
    restart: unless-stopped

networks:
  pi-network:
    driver: bridge
```

## 5. Agent Model Configuration
The `models.json` file tells the agent how to interface with the Ollama OpenAI-compatible API.

```json
{
  "models": [
    {
      "id": "gemma4-local",
      "name": "Gemma 4 26B (Local)",
      "provider": "ollama",
      "base_url": "http://host.docker.internal:11434/v1",
      "model_name": "gemma4:26b-mlx",
      "api_key": "ollama",
      "options": {
        "num_ctx": 8192,
        "temperature": 0.7
      }
    }
  ],
  "default_model": "gemma4-local"
}
```

## 6. Deployment Workflow

```bash
# 1. Build the custom image
docker compose build

# 2. Start the agents in detached mode
docker compose up -d

# 3. Verify health status
docker compose ps

# 4. Check logs for startup errors
docker compose logs -f
```

## 7. Verification Suite

### A. Health Verification
```bash
curl -I http://localhost:8001/health
curl -I http://localhost:8002/health
```

### B. Model Inference Test
Send a test prompt to ensure the bridge to Ollama is functioning.
```bash
curl -X POST http://localhost:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemma4-local",
    "messages": [{"role": "user", "content": "Confirm you are running in a Docker container."}]
  }'
```

### C. Workspace Isolation Check
Verify that files created by agent1 do not appear in agent2's workspace.
```bash
# Agent 1 creates a file
docker exec pi-agent-1 touch /home/pi/.pi_workspace/test_p1.txt
# Verify isolation
ls ./workspaces/p1 # Should contain test_p1.txt
ls ./workspaces/p2 # Should NOT contain test_p1.txt
```

## 8. Management & Troubleshooting

| Action | Command |
|---|---|
| **Stop Cluster** | `docker compose down` |
| **Restart Agent** | `docker compose restart agent1` |
| **Shell Access** | `docker exec -it pi-agent-1 /bin/bash` |
| **Clean Slate** | `docker compose down -v` (Deletes networks/containers, preserves volumes) |

### Common Issues
- **Ollama Connection Refused**: Ensure Ollama is running on the host. Mac users: `host.docker.internal` is required.
- **Permission Denied on Workspaces**: Run `chmod -R 777 ~/pi-cluster/workspaces` if Docker's `1000:1000` user cannot write to the host mount.
- **Inference Slowness**: A 26B model on 64GB RAM is tight. If agents are unresponsive, check if Ollama is swapping to disk.
- **Model Not Found**: Ensure the model name in `models.json` exactly matches the name in `ollama list`.
