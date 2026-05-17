from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from web.db import init_db
from web.routes.auth import router as auth_router
from web.routes.files import router as files_router
from web.routes.terminal import router as terminal_router


@asynccontextmanager
async def _lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="zeropanel web", lifespan=_lifespan, docs_url=None, redoc_url=None)

app.include_router(auth_router, prefix="/api")
app.include_router(files_router, prefix="/api")
app.include_router(terminal_router, prefix="/api")

_static = Path(__file__).parent / "static"
app.mount("/", StaticFiles(directory=str(_static), html=True), name="static")
