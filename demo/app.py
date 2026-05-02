"""FastAPI app for the demo. Single file, all routes."""
from __future__ import annotations
import logging
import os
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from demo.llm import diagnose
from demo.storage import create_encounter, get_encounter, list_encounters

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("demo")

_ROOT = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(_ROOT / "templates"))

app = FastAPI(title="DermAssist VN — Demo", version="0.0.1-demo")
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("DEMO_SESSION_SECRET", "demo-only-not-for-production-use-32chars"),
    max_age=60 * 60 * 8,  # 8 hours
)
app.mount("/static", StaticFiles(directory=str(_ROOT / "static")), name="static")

# Demo creds — hardcoded
DEMO_USERNAME = "demo"
DEMO_PASSWORD = "demo"

# Image size cap: 8 MB. Anything bigger is rejected before hitting OpenAI.
MAX_IMAGE_BYTES = 8 * 1024 * 1024


def _require_login(request: Request) -> str:
    """Return username if logged in, else raise 302 to /login."""
    username = request.session.get("username")
    if not username:
        # Use HTTPException with 303 to redirect; FastAPI will respect Location header.
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return username


# === Routes ===

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    if request.session.get("username"):
        return RedirectResponse(url="/upload", status_code=303)
    return RedirectResponse(url="/login", status_code=303)


@app.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": None})


@app.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    if username == DEMO_USERNAME and password == DEMO_PASSWORD:
        request.session["username"] = username
        return RedirectResponse(url="/upload", status_code=303)
    return templates.TemplateResponse(
        request,
        "login.html",
        {"error": "Sai tên đăng nhập hoặc mật khẩu."},
        status_code=401,
    )


@app.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


@app.get("/upload", response_class=HTMLResponse)
async def upload_form(request: Request):
    username = _require_login(request)
    return templates.TemplateResponse(
        request, "upload.html", {"username": username, "error": None}
    )


@app.post("/upload")
async def upload_submit(
    request: Request,
    image: UploadFile = File(...),
    clinical_note: str = Form(""),
):
    username = _require_login(request)
    image_bytes = await image.read()

    if len(image_bytes) == 0:
        return templates.TemplateResponse(
            request,
            "upload.html",
            {"username": username, "error": "File ảnh trống."},
            status_code=400,
        )
    if len(image_bytes) > MAX_IMAGE_BYTES:
        return templates.TemplateResponse(
            request,
            "upload.html",
            {"username": username,
             "error": f"Ảnh quá lớn (tối đa {MAX_IMAGE_BYTES // (1024*1024)} MB)."},
            status_code=400,
        )

    try:
        diagnosis = diagnose(image_bytes, clinical_note)
    except Exception as e:
        logger.exception("Diagnosis failed")
        return templates.TemplateResponse(
            request,
            "upload.html",
            {"username": username,
             "error": f"Lỗi khi gọi mô hình: {type(e).__name__}: {e}"},
            status_code=500,
        )

    eid = create_encounter(
        username,
        {
            "clinical_note": clinical_note,
            "image_size_bytes": len(image_bytes),
            "image_filename": image.filename or "uploaded.jpg",
            "diagnosis": diagnosis,
        },
    )
    return RedirectResponse(url=f"/result/{eid}", status_code=303)


@app.get("/result/{eid}", response_class=HTMLResponse)
async def result_page(request: Request, eid: str):
    username = _require_login(request)
    record = get_encounter(username, eid)
    if record is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy encounter.")
    return templates.TemplateResponse(
        request, "result.html", {"username": username, "record": record}
    )


@app.get("/encounters", response_class=HTMLResponse)
async def encounters_list(request: Request):
    username = _require_login(request)
    records = list_encounters(username)
    return templates.TemplateResponse(
        request,
        "encounters.html",
        {"username": username, "records": records},
    )


@app.get("/health")
async def health():
    return {"status": "ok"}
