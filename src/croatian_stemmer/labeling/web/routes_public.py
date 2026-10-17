"""Unauthenticated routes: the page shell, public config, legal documents, probes."""

from fastapi import Depends, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from .common import failure


def register(app, ctx):
    from .api import STATIC
    settings = ctx.settings

    @app.get("/healthz")
    async def health():
        return {"ok": True}

    @app.get("/readyz")
    async def ready(db=Depends(ctx.session)):
        try:
            await db.execute(text("SELECT 1"))
        except SQLAlchemyError as exc:
            raise failure(503, "database_unavailable") from exc
        return {"ok": True}

    @app.get("/api/config")
    async def public_config(db=Depends(ctx.session)):
        try:
            accepting = await ctx.accepting_judgments(db)
        except SQLAlchemyError:
            accepting = False
        return {**settings.browser, "acceptingJudgments": accepting}

    @app.get("/legal/{name}")
    async def legal(name: str, request: Request):
        # privacy|terms|storage . hr|en; the controller values come from configuration.
        page = ctx.legal.render(name, request.url.netloc)
        if page is None:
            raise failure(404, "not_found")
        return HTMLResponse(page)

    @app.get("/")
    async def index():
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
