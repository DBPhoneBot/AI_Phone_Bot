from fastapi import FastAPI

from app.api.routes.health import router as health_router
from app.api.routes.twilio import router as twilio_router
from app.config import apply_runtime_environment, get_settings


settings = apply_runtime_environment(get_settings())

app = FastAPI(
    title="phone-system",
    description="Dedicated inbound phone system service for Daly & Black.",
    version="0.1.0",
)

app.include_router(health_router)
app.include_router(twilio_router)


@app.get("/", tags=["meta"])
async def root() -> dict[str, str]:
    return {
        "service": "phone-system",
        "environment": settings.app_env,
        "status": "ok",
    }
