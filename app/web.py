"""Shared Jinja2 templates instance."""

from pathlib import Path

from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def iso(dt) -> str:
    """Naive-UTC datetime -> ISO string with Z suffix for the local-time JS."""
    return dt.isoformat() + "Z" if dt else ""


templates.env.globals["iso"] = iso

from app.core.states import bucket_of  # noqa: E402

templates.env.globals["bucket_of"] = bucket_of

