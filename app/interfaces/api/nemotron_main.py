from fastapi import FastAPI

from app.interfaces.api.routes.nemotron import router as nemotron_router

app = FastAPI(title="NVIDIA Nemotron Parse Service", version="1.0.0", docs_url="/docs")
app.include_router(nemotron_router)
