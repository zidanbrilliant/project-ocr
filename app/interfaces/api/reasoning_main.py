from fastapi import FastAPI

from app.interfaces.api.routes.reasoning import router as reasoning_router

app = FastAPI(title="Qwen Field Reasoning Service", version="1.0.0", docs_url=None)
app.include_router(reasoning_router)
