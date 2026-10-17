"""HTML pages."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Channel, Watch, default_notify_rules
from app.notifiers import get_all_notifiers
from app.web import templates

router = APIRouter(tags=["pages"])


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    watches = list((await db.execute(select(Watch).order_by(Watch.display_name))).scalars())
    return templates.TemplateResponse(
        request, "dashboard.html",
        {"watches": watches, "active_page": "dashboard"},
    )


@router.get("/watches", response_class=HTMLResponse)
async def watches_page(request: Request, db: AsyncSession = Depends(get_db)):
    watches = list((await db.execute(select(Watch).order_by(Watch.display_name))).scalars())
    channels = list((await db.execute(select(Channel).order_by(Channel.name))).scalars())
    return templates.TemplateResponse(
        request, "watches.html",
        {
            "watches": watches,
            "channels": channels,
            "rule_keys": list(default_notify_rules().keys()),
            "active_page": "watches",
        },
    )


@router.get("/channels", response_class=HTMLResponse)
async def channels_page(request: Request, db: AsyncSession = Depends(get_db)):
    channels = list((await db.execute(select(Channel).order_by(Channel.name))).scalars())
    return templates.TemplateResponse(
        request, "channels.html",
        {"channels": channels, "notifiers": get_all_notifiers(), "active_page": "channels"},
    )
