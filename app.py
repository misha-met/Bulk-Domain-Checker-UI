"""FastAPI server for the Bulk Domain Checker.

Streams check results as NDJSON and supports real client-disconnect cancellation.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import AsyncIterator, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from check_domains import run_stream

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("bulk-domain-checker")
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
INDEX_FILE = BASE_DIR / "templates" / "index.html"

app = FastAPI(title="Bulk Domain Checker", version="2.0")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


class CheckRequest(BaseModel):
    domains: list[str] = Field(default_factory=list)
    timeout: float = Field(default=5.0, ge=0.5, le=60.0)
    workers: int = Field(default=100, ge=1, le=1000)
    dns_mode: Literal["system", "direct"] = "system"


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(INDEX_FILE)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/check")
async def check_endpoint(req: CheckRequest, request: Request) -> StreamingResponse:
    if not req.domains:
        raise HTTPException(status_code=400, detail="No domains provided")
    # Trim & dedupe defensively (frontend already does this).
    seen: set[str] = set()
    domains: list[str] = []
    for d in req.domains:
        d = d.strip()
        if d and d.lower() not in seen:
            seen.add(d.lower())
            domains.append(d)
    if not domains:
        raise HTTPException(status_code=400, detail="No valid domains provided")

    async def stream() -> AsyncIterator[bytes]:
        try:
            async for result in run_stream(domains, req.timeout, req.workers, dns_mode=req.dns_mode):
                if await request.is_disconnected():
                    log.info("Client disconnected; stopping stream")
                    break
                yield (json.dumps(result.to_dict()) + "\n").encode("utf-8")
        except Exception as e:
            log.exception("Streaming error")
            yield (json.dumps({"error": "Streaming failed", "detail": str(e)}) + "\n").encode("utf-8")

    return StreamingResponse(stream(), media_type="application/x-ndjson")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
