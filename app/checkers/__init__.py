"""Checker plugin loader — scans this package for CheckerPlugin subclasses."""

import importlib
import logging
import pkgutil

from app.core.checker_base import CheckerPlugin

logger = logging.getLogger(__name__)

_checkers: dict[str, CheckerPlugin] = {}


def load_checkers() -> None:
    _checkers.clear()
    package = importlib.import_module("app.checkers")
    for _, module_name, _ in pkgutil.iter_modules(package.__path__):
        if module_name.startswith("_"):
            continue
        try:
            module = importlib.import_module(f"app.checkers.{module_name}")
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if isinstance(attr, type) and issubclass(attr, CheckerPlugin) and attr is not CheckerPlugin:
                    plugin = attr()
                    _checkers[plugin.type] = plugin
                    logger.info("Loaded checker: %s (%s)", plugin.type, plugin.display_name)
        except Exception:
            logger.exception("Failed to load checker module %s", module_name)


def get_checker(type_: str) -> CheckerPlugin | None:
    return _checkers.get(type_)


def get_all_checkers() -> list[CheckerPlugin]:
    return list(_checkers.values())
