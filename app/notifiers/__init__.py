"""Notifier plugin loader — scans this package for NotifierPlugin subclasses."""

import importlib
import logging
import pkgutil

from app.core.notifier_base import NotifierPlugin

logger = logging.getLogger(__name__)

_notifiers: dict[str, NotifierPlugin] = {}


def load_notifiers() -> None:
    _notifiers.clear()
    package = importlib.import_module("app.notifiers")
    for _, module_name, _ in pkgutil.iter_modules(package.__path__):
        if module_name.startswith("_"):
            continue
        try:
            module = importlib.import_module(f"app.notifiers.{module_name}")
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if isinstance(attr, type) and issubclass(attr, NotifierPlugin) and attr is not NotifierPlugin:
                    plugin = attr()
                    _notifiers[plugin.type] = plugin
                    logger.info("Loaded notifier: %s (%s)", plugin.type, plugin.display_name)
        except Exception:
            logger.exception("Failed to load notifier module %s", module_name)


def get_notifier(type_: str) -> NotifierPlugin | None:
    return _notifiers.get(type_)


def get_all_notifiers() -> list[NotifierPlugin]:
    return list(_notifiers.values())
