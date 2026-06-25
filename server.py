"""Pi Agent API Server — FastAPI wrapper bridging OpenAI-compatible requests to Ollama."""
import json
import os
import time
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from openai import OpenAI

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MODELS_CONFIG_PATH = os.getenv(
    "MODELS_CONFIG_PATH", "/home/pi/.pi/agent/models.json"
)
WORKSPACE_PATH = os.getenv("PI_WORKSPACE", "/home/pi/.pi_workspace")


def load_models_config() -> dict:
    try:
        with open(MODELS_CONFIG_PATH, "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"[warn] Could not load models config from {MODELS_CONFIG_PATH}: {e}")
        return {"models": [], "default_model": None}


config = load_models_config()
models_by_id: dict[str, dict] = {m["id"]: m for m in config.get("models", [])}
default_model_id: str | None = config.get("default_model")


def get_client(model_id: str) -> tuple[OpenAI, dict]:
    """Return an OpenAI client + model metadata dict for the given model id."""
    model_cfg = models_by_id.get(model_id)
    if model_cfg is None:
        raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found")
    client = OpenAI(
        base_url=model_cfg["base_url"],
        api_key=model_cfg.get("api_key", "ollama"),
    )
    return client, model_cfg


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(title="Pi Agent Server")


@app.get("/health")
async def health():
    return {"status": "ok", "model": default_model_id, "workspace": WORKSPACE_PATH}


@app.get("/v1/models")
async def list_models():
    data = [
        {
            "id": m["id"],
            "object": "model",
            "owned_by": m.get("provider", "local"),
        }
        for m in config.get("models", [])
    ]
    return {"object": "list", "data": data}


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    model_id = body.get("model", default_model_id)
    messages = body.get("messages", [])
    stream = body.get("stream", False)
    temperature = body.get("temperature")
    max_tokens = body.get("max_tokens")

    # Merge per-model options (num_ctx etc.) into the request
    client, model_cfg = get_client(model_id)
    extra_opts = model_cfg.get("options", {})

    kwargs: dict = dict(
        model=model_cfg["model_name"],
        messages=messages,
        stream=stream,
    )
    if temperature is not None:
        kwargs["temperature"] = temperature
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    # Pass Ollama-specific options via extra_body
    if extra_opts:
        kwargs["extra_body"] = extra_opts

    try:
        response = client.chat.completions.create(**kwargs)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Upstream error: {e}")

    if stream:
        # Return a SSE stream identical to OpenAI's streaming format
        def sse_generator():
            for chunk in response:
                yield f"data: {chunk.model_dump_json()}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            sse_generator(),
            media_type="text/event-stream",
            headers={"X-Accel-Buffering": "no"},
        )

    # Non-streaming response
    return JSONResponse(content=response.model_dump())


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
