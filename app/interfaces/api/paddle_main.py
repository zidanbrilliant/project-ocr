from fastapi import FastAPI

from app.interfaces.api.routes.paddle import router as paddle_router

app = FastAPI(title="PaddleOCR-VL Service", version="1.0.0", docs_url="/docs")
app.include_router(paddle_router)
