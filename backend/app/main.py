from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import RequestResponseEndpoint
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.v1 import api_router
from app.core.config import settings

LOOPBACK_HOSTS = {"127.0.0.1", "localhost"}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # GLO-07: se valida al arrancar el servidor (no en Settings) para que
    # alembic y los scripts no necesiten LOCAL_USER_ID.
    if settings.auth_mode == "local" and settings.local_user_id is None:
        raise RuntimeError("AUTH_MODE=local requiere LOCAL_USER_ID (UUID del perfil dueño)")
    scheduler = None
    if settings.scheduler_enabled:
        from app.jobs.scheduler import build_scheduler

        scheduler = build_scheduler()
        scheduler.start()
    yield
    if scheduler is not None:
        scheduler.shutdown(wait=False)


def create_app() -> FastAPI:
    app = FastAPI(title="Finanzas API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next: RequestResponseEndpoint) -> Response:
        """CWE-693: cabeceras de seguridad en todas las respuestas de la API.

        Se bloquea el sniffing de MIME, el embebido en iframes y el cacheo de
        respuestas con datos financieros. Solo los assets del frontend (nombres
        con hash, sin datos) se cachean. HSTS solo fuera de dev (HTTP local).
        """
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith("/assets/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            response.headers.setdefault("Cache-Control", "no-store")
        if settings.env != "dev":
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        return response

    if settings.auth_mode == "local":
        add_local_guards(app)

    app.include_router(api_router)

    @app.get("/health", tags=["meta"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    if settings.frontend_dist:
        mount_frontend(app, Path(settings.frontend_dist))

    return app


def add_local_guards(app: FastAPI) -> None:
    """GLO-07: without auth, only the local browser may talk to the API.

    - Host must be loopback: blocks DNS rebinding (evil.com -> 127.0.0.1).
    - A present Origin must be loopback: blocks cross-site form/fetch POSTs
      (CSRF) that the browser would send without a CORS preflight.
    """

    @app.middleware("http")
    async def reject_foreign_origin(
        request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        origin = request.headers.get("origin")
        if origin is not None:
            host = origin.split("://", 1)[-1].rsplit(":", 1)[0].strip("[]")
            if host not in LOOPBACK_HOSTS:
                return JSONResponse({"detail": "Forbidden origin"}, status_code=403)
        return await call_next(request)

    app.add_middleware(TrustedHostMiddleware, allowed_hosts=sorted(LOOPBACK_HOSTS))


def mount_frontend(app: FastAPI, dist: Path) -> None:
    """GLO-07: serve the built SPA from the same origin as the API.

    Hashed bundles live under /assets; any other non-API path returns the
    file if it exists in dist (icons) or index.html so React Router can
    resolve client-side routes on reload.
    """
    dist = dist.resolve()
    index = dist / "index.html"
    if not index.is_file():
        raise RuntimeError(f"FRONTEND_DIST no contiene index.html: {dist}")
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> FileResponse:
        if path.startswith("api/"):
            raise HTTPException(404, "Not Found")
        candidate = (dist / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(dist):
            return FileResponse(candidate)
        return FileResponse(index)


app = create_app()
