# Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install pi-agent and API server dependencies
RUN pip install --no-cache-dir pi-agent fastapi uvicorn openai

# Create non-root user for security
RUN useradd -m -u 1000 pi && chown -R pi:pi /app
USER pi

# Expose API port
EXPOSE 8000

# Copy the API wrapper into the image
COPY server.py /app/server.py

# Set the entrypoint to run the FastAPI server
ENTRYPOINT ["python", "/app/server.py"]
CMD ["--port", "8000"]
