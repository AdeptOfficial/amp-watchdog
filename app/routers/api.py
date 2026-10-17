"""API routes — JSON for /api/health, HTML partials for the htmx UI."""

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import delete as sa_delete
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.checkers import get_checker
from app.config import settings
from app.database import get_db
from app.models import Channel, NotificationLog, Transition, Watch, default_notify_rules, utcnow
from app.notifiers import get_all_notifiers, get_notifier
from app.services.scheduler import request_immediate_sweep
from app.web import templates

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["api"])
partials = APIRouter(prefix="/partials", tags=["partials"])

RULE_KEYS = list(default_notify_rules().keys())


# ---------- helpers ----------

async def _all_watches(db: AsyncSession) -> list[Watch]:
    result = await db.execute(select(Watch).order_by(Watch.display_name))
    return list(result.scalars())


async def _all_channels(db: AsyncSession) -> list[Channel]:
    result = await db.execute(select(Channel).order_by(Channel.name))
    return list(result.scalars())


def _dashboard_rows(request: Request, watches: list[Watch]) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "components/dashboard_rows.html", {"watches": watches}
    )


async def _watch_rows(request: Request, db: AsyncSession) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "components/watch_rows.html",
        {"watches": await _all_watches(db), "channels": await _all_channels(db)},
    )


async def _channel_rows(request: Request, db: AsyncSession, error: str = "") -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "components/channel_rows.html",
        {"channels": await _all_channels(db), "error": error},
    )


# ---------- health ----------

@router.get("/health")
async def health():
    return {"status": "ok"}


# ---------- discovery ----------

@router.get("/amp/instances", response_class=HTMLResponse)
async def discover_instances(request: Request, db: AsyncSession = Depends(get_db)):
    checker = get_checker("amp")
    error = ""
    targets = []
    try:
        targets = await checker.discover() if checker else []
    except Exception as e:
        logger.warning("Discovery failed: %r", e)
        error = f"Could not reach AMP: {e}"
    watched_keys = {w.target_key for w in await _all_watches(db) if w.type == "amp"}
    return templates.TemplateResponse(
        request,
        "components/discover_list.html",
        {"targets": targets, "watched_keys": watched_keys, "error": error},
    )


# ---------- watches ----------

@router.post("/watches")
async def create_watch(request: Request, db: AsyncSession = Depends(get_db)):
    form = await request.form()
    target_key = str(form.get("target_key", "")).strip()
    name = str(form.get("name", "")).strip() or target_key
    instance_name = str(form.get("instance_name", "")).strip()

    if target_key:
        existing = await db.execute(
            select(Watch).where(Watch.type == "amp", Watch.target_key == target_key)
        )
        if existing.scalar_one_or_none() is None:
            db.add(Watch(
                type="amp",
                target_key=target_key,
                display_name=name,
                config={"instance_name": instance_name},
                check_interval_seconds=settings.DEFAULT_CHECK_INTERVAL,
                notify_rules=default_notify_rules(),
                channel_ids=[],
            ))
            await db.commit()
            request_immediate_sweep()
    # The Watch button uses hx-swap="none"; these events refresh both panels
    return Response(status_code=200, headers={"HX-Trigger": "refresh-watches, refresh-discover"})


@router.get("/watches/{watch_id}/edit", response_class=HTMLResponse)
async def edit_watch_form(watch_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    watch = await db.get(Watch, watch_id)
    if watch is None:
        return HTMLResponse("")
    return templates.TemplateResponse(
        request,
        "components/watch_form.html",
        {"watch": watch, "channels": await _all_channels(db), "rule_keys": RULE_KEYS},
    )


@router.post("/watches/{watch_id}", response_class=HTMLResponse)
async def update_watch(watch_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    watch = await db.get(Watch, watch_id)
    if watch is not None:
        form = await request.form()
        watch.display_name = str(form.get("display_name", watch.display_name)).strip() or watch.display_name
        try:
            watch.check_interval_seconds = max(10, int(form.get("check_interval_seconds", 60)))
        except (TypeError, ValueError):
            pass
        try:
            watch.realert_minutes = max(0, int(form.get("realert_minutes", 0)))
        except (TypeError, ValueError):
            pass
        watch.mention_id = str(form.get("mention_id", "")).strip() or None
        watch.message_template = str(form.get("message_template", "")).strip() or None
        watch.quiet_start = str(form.get("quiet_start", "")).strip() or None
        watch.quiet_end = str(form.get("quiet_end", "")).strip() or None
        watch.notify_rules = {key: (f"rule__{key}" in form) for key in RULE_KEYS}
        watch.channel_ids = [int(v) for v in form.getlist("channels") if str(v).isdigit()]
        await db.commit()
    return await _watch_rows(request, db)


@router.post("/watches/{watch_id}/toggle", response_class=HTMLResponse)
async def toggle_watch(watch_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    watch = await db.get(Watch, watch_id)
    if watch is not None:
        watch.enabled = not watch.enabled
        if watch.enabled:
            watch.next_check_at = utcnow()
            request_immediate_sweep()
        await db.commit()
    return await _watch_rows(request, db)


@router.delete("/watches/{watch_id}", response_class=HTMLResponse)
async def delete_watch(watch_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    watch = await db.get(Watch, watch_id)
    if watch is not None:
        # SQLite FK cascades need PRAGMA foreign_keys; delete history explicitly instead
        await db.execute(sa_delete(Transition).where(Transition.watch_id == watch_id))
        await db.delete(watch)
        await db.commit()
    response = await _watch_rows(request, db)
    response.headers["HX-Trigger"] = "refresh-discover"  # flips 'watching ✓' back to a Watch button
    return response


@router.post("/watches/{watch_id}/check-now")
async def check_now(watch_id: int, db: AsyncSession = Depends(get_db)):
    watch = await db.get(Watch, watch_id)
    if watch is not None:
        watch.next_check_at = utcnow()
        await db.commit()
        request_immediate_sweep()
    # htmx calls this with hx-swap="none"; the sweep's SSE broadcast refreshes rows
    return {"queued": watch_id}


# ---------- history ----------

@router.get("/history", response_class=HTMLResponse)
async def history(request: Request, watch_id: int | None = None, limit: int = 50,
                  db: AsyncSession = Depends(get_db)):
    query = select(Transition).order_by(desc(Transition.created_at)).limit(min(limit, 200))
    if watch_id:
        query = query.where(Transition.watch_id == watch_id)
    result = await db.execute(query)
    transitions = list(result.scalars())
    names = {w.id: w.display_name for w in await _all_watches(db)}
    return templates.TemplateResponse(
        request,
        "components/history_rows.html",
        {"transitions": transitions, "names": names},
    )


# ---------- channels ----------

@router.post("/channels", response_class=HTMLResponse)
async def create_channel(request: Request, db: AsyncSession = Depends(get_db)):
    form = await request.form()
    name = str(form.get("name", "")).strip()
    type_ = str(form.get("type", "discord")).strip()
    plugin = get_notifier(type_)
    if plugin is None:
        return await _channel_rows(request, db, error=f"Unknown channel type: {type_}")
    config = {
        f.name: str(form.get(f"config_{f.name}", "")).strip() for f in plugin.config_fields
    }
    problems = plugin.validate_config(config)
    if not name:
        problems.insert(0, "Name is required")
    existing = await db.execute(select(Channel).where(Channel.name == name))
    if name and existing.scalar_one_or_none() is not None:
        problems.append(f"A channel named '{name}' already exists")
    if problems:
        return await _channel_rows(request, db, error="; ".join(problems))
    db.add(Channel(name=name, type=type_, config=config))
    await db.commit()
    return await _channel_rows(request, db)


@router.get("/channels/{channel_id}/edit", response_class=HTMLResponse)
async def edit_channel_form(channel_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    channel = await db.get(Channel, channel_id)
    if channel is None:
        return HTMLResponse("")
    plugin = get_notifier(channel.type)
    return templates.TemplateResponse(
        request,
        "components/channel_form.html",
        {"channel": channel, "plugin": plugin},
    )


@router.post("/channels/{channel_id}", response_class=HTMLResponse)
async def update_channel(channel_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    channel = await db.get(Channel, channel_id)
    if channel is None:
        return await _channel_rows(request, db)
    plugin = get_notifier(channel.type)
    form = await request.form()
    name = str(form.get("name", "")).strip()
    config = dict(channel.config or {})
    if plugin is not None:
        config = {f.name: str(form.get(f"config_{f.name}", "")).strip() for f in plugin.config_fields}
        problems = plugin.validate_config(config)
    else:
        problems = []
    if not name:
        problems.insert(0, "Name is required")
    existing = await db.execute(select(Channel).where(Channel.name == name, Channel.id != channel_id))
    if name and existing.scalar_one_or_none() is not None:
        problems.append(f"A channel named '{name}' already exists")
    if problems:
        return await _channel_rows(request, db, error="; ".join(problems))
    channel.name = name
    channel.config = config
    channel.test_message = str(form.get("test_message", "")).strip() or None
    await db.commit()
    return await _channel_rows(request, db)


@router.post("/channels/{channel_id}/test", response_class=HTMLResponse)
async def test_channel(channel_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    channel = await db.get(Channel, channel_id)
    if channel is not None:
        plugin = get_notifier(channel.type)
        if plugin is None:
            channel.last_test_ok = False
        else:
            result = await plugin.send_test(channel.config or {}, channel.test_message)
            channel.last_test_ok = result.success
            db.add(NotificationLog(
                watch_id=None, channel_id=channel.id, kind="test",
                success=result.success, error=result.error, message="test notification",
            ))
        channel.last_test_at = utcnow()
        await db.commit()
    return await _channel_rows(request, db)


@router.post("/channels/{channel_id}/toggle", response_class=HTMLResponse)
async def toggle_channel(channel_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    channel = await db.get(Channel, channel_id)
    if channel is not None:
        channel.enabled = not channel.enabled
        await db.commit()
    return await _channel_rows(request, db)


@router.delete("/channels/{channel_id}", response_class=HTMLResponse)
async def delete_channel(channel_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    channel = await db.get(Channel, channel_id)
    if channel is not None:
        # scrub the id from watches so nothing dangles
        for watch in await _all_watches(db):
            if channel_id in (watch.channel_ids or []):
                watch.channel_ids = [i for i in watch.channel_ids if i != channel_id]
        await db.delete(channel)
        await db.commit()
    return await _channel_rows(request, db)


# ---------- partials ----------

@partials.get("/dashboard-rows", response_class=HTMLResponse)
async def dashboard_rows(request: Request, db: AsyncSession = Depends(get_db)):
    return _dashboard_rows(request, await _all_watches(db))


@partials.get("/watch-rows", response_class=HTMLResponse)
async def watch_rows(request: Request, db: AsyncSession = Depends(get_db)):
    return await _watch_rows(request, db)
