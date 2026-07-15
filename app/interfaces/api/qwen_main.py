from fastapi import FastAPI

from app.interfaces.api.routes.health import router as health_router
from app.interfaces.api.routes.qwen import router as qwen_router

app = FastAPI(
    title="Qwen Reasoning Service",
    version="2.1.0",
    docs_url="/docs",
)

app.include_router(health_router)
app.include_router(qwen_router)
