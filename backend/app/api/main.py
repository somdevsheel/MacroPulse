"""FastAPI entrypoint. Run: uv run uvicorn app.api.main:app --reload  (from backend/)

OpenAPI docs at /docs. Provider credentials are never returned -- only connection status.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.analysis import router as analysis_router
from app.api.live import router as live_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.universe import get_universe
from app.providers.registry import health_report

settings = get_settings()
configure_logging(settings.log_level, settings.log_json)

app = FastAPI(
    title="MacroPulse API",
    version="0.1.0",
    description="Macroeconomic news-driven market reaction research. Not trading advice.",
)
# Dev frontend (Vite). Tighten for production.
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173",
                                                  "http://127.0.0.1:5173"],
                   allow_methods=["GET", "POST"], allow_headers=["*"])
app.include_router(analysis_router)
app.include_router(live_router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/v1/providers/status")
def providers_status() -> list[dict]:
    return [
        {
            "provider": h.provider_key,
            "status": h.status.value,
            "checked_at": h.checked_at.isoformat(),
            "detail": h.detail,
        }
        for h in health_report()
    ]


@app.get("/api/v1/config/universe")
def universe() -> dict:
    u = get_universe()
    return {
        "releases": {k: r.model_dump(mode="json") for k, r in u.releases.items()},
        "indicators": {k: i.model_dump(mode="json") for k, i in u.indicators.items()},
        "instruments": {k: i.model_dump(mode="json") for k, i in u.instruments.items()},
    }
