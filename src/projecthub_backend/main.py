from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from projecthub_backend.api.v1.auth import router as authRouter

app = FastAPI(title="ProjectHub API", version="0.1.0")

app.include_router(authRouter, prefix="/api/v1")

@app.get("/health", tags=["Health"])
def health_check() -> dict[str, str]:
    return {"status": "ok"}

@app.get("/")
def root():
    return {"status": "running"}
