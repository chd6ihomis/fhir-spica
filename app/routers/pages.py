"""HTML page routes (server-rendered shells; data loaded via the JSON API)."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from ..config import get_config

router = APIRouter(tags=["pages"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))

PAGES = [
    ("/", "dashboard.html", "Dashboard"),
    ("/submit", "submit.html", "Submit eReferral"),
    ("/modules", "modules.html", "Module Console"),
    ("/facility-onboarding", "facility_onboarding.html", "Facility Onboarding"),
    ("/patients", "patients.html", "Patient Masterlist"),
    ("/worklist", "worklist.html", "Referral Worklist"),
    ("/admin", "admin.html", "Admin"),
    ("/debug", "debug.html", "Developer Tools"),
]


def _render(request: Request, template: str, title: str) -> HTMLResponse:
    config = get_config()
    return templates.TemplateResponse(
        request,
        template,
        {
            "title": title,
            "nav": [(path, label) for path, _, label in PAGES],
            "config": config.public_dict(),
        },
    )


def register(app) -> None:
    for path, template, title in PAGES:
        def _make(template=template, title=title):
            async def handler(request: Request) -> HTMLResponse:
                return _render(request, template, title)
            return handler
        app.add_api_route(path, _make(), methods=["GET"], response_class=HTMLResponse, include_in_schema=False)
