"""Page routes: root redirect, login form, about, health.

Auth-protected pages live in `encounters.py` and `chat.py` to keep page
logic close to data. Templates are looked up off `app.state.templates`
to avoid circular imports.
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from backend.config import get_settings

router = APIRouter(tags=["pages"])
_settings = get_settings()


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.get("/")
async def root(request: Request):
    """If logged in -> /encounters/new, else -> /login."""
    if request.cookies.get("dermassist_session"):
        return RedirectResponse(url="/encounters/new", status_code=303)
    return RedirectResponse(url="/login", status_code=303)


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    templates = request.app.state.templates
    return templates.TemplateResponse(
        request,
        "login.html",
        {"google_oauth_enabled": _settings.google_oauth_enabled, "flash": None},
    )


@router.get("/about", response_class=HTMLResponse)
async def about_page():
    """Tiny 'what is this' page."""
    return HTMLResponse(
        "<!doctype html><html lang='vi'><body style='font-family: sans-serif; "
        "max-width: 640px; margin: 4rem auto; padding: 0 1rem;'>"
        "<h1>DermAssist VN</h1>"
        "<p>Hệ thống hỗ trợ quyết định lâm sàng cho 8 bệnh da liễu. "
        "Closed beta cho mục đích nghiên cứu kỹ thuật.</p>"
        "<p><a href='/'>← Trang chủ</a></p>"
        "</body></html>"
    )
