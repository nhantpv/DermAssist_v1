"""FastAPI app entrypoint with Vietnamese error handlers and lifespan."""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.db import engine
from backend.routes.auth import router as auth_router
from backend.routes.chat import router as chat_router
from backend.routes.encounters import router as encounters_router
from backend.routes.pages import router as pages_router

logger = logging.getLogger("dermassist")
logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: verify DB reachable
    async with engine.begin() as conn:
        await conn.execute(text("SELECT 1"))
    logger.info("Database connection verified")
    yield
    await engine.dispose()


app = FastAPI(
    title="DermAssist VN",
    description="VLM clinical decision support — V1 closed beta",
    version="1.0.0-beta",
    lifespan=lifespan,
)

# Templates and static — exposed via app.state so route modules can grab
# them without importing this module (avoids circular imports).
_BACKEND_ROOT = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(_BACKEND_ROOT / "templates"))
app.state.templates = templates
app.mount(
    "/static",
    StaticFiles(directory=str(_BACKEND_ROOT / "static")),
    name="static",
)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Hide stack traces; return Vietnamese error JSON."""
    detail = exc.detail if isinstance(exc.detail, str) else "Lỗi máy chủ."
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": detail, "status_code": exc.status_code},
        headers=getattr(exc, "headers", None),
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "error": "Dữ liệu đầu vào không hợp lệ.",
            "status_code": 422,
            "fields": [
                {"field": ".".join(str(x) for x in e["loc"]), "issue": e["msg"]}
                for e in exc.errors()
            ],
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Catch-all so users never see stack traces."""
    logger.exception("Unhandled exception")
    return JSONResponse(
        status_code=500,
        content={
            "error": "Lỗi máy chủ. Vui lòng thử lại sau.",
            "status_code": 500,
        },
    )


app.include_router(auth_router)
app.include_router(pages_router)
app.include_router(encounters_router)
app.include_router(chat_router)
