from fastapi import FastAPI
from app.interfaces.api.routes.health import router as health_router
from app.interfaces.api.routes.jobs import router as jobs_router

app = FastAPI(
    title="AI Invoice Verification Agent",
    version="2.1.0",
    docs_url="/docs",
)

app.include_router(health_router)
app.include_router(jobs_router)
