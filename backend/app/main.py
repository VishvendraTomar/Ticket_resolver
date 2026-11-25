"""FastAPI application factory."""

from __future__ import annotations

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import knowledge, tenancy
from app.core.config import Settings, get_settings
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging, request_id_middleware


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    if settings.sentry_dsn is not None:
        import sentry_sdk

        # Tickets and policies carry HR data: collect as little as possible.
        sentry_sdk.init(
            dsn=settings.sentry_dsn.get_secret_value(),
            environment=settings.environment,
            data_collection={
                "user_info": False,
                "http_bodies": [],
                "database_query_data": False,
                "stack_frame_variables": False,
            },
        )

    app = FastAPI(title="Ticket Resolver API", version="0.1.0")
    install_error_handlers(app)
    app.middleware("http")(request_id_middleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/healthz", tags=["ops"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    v1 = APIRouter(prefix="/v1")
    v1.include_router(tenancy.router)
    v1.include_router(knowledge.router)
    app.include_router(v1)
    return app


app = create_app()
