"""Menu-source adapters.

Each adapter knows how to pull a dispensary's live menu from one platform
(Dutchie, Leafly, Weedmaps, a proprietary site, …) and emit a list of
platform-agnostic ``MenuItem`` dicts (see :mod:`app.adapters.base`). The
scrape orchestrator (:mod:`app.scrape`) feeds those into
``app.pipeline.normalize.normalize_item`` to produce canonical deals.
"""

from .base import Adapter, MenuItem
from .dutchie import DutchieAdapter

__all__ = ["Adapter", "MenuItem", "DutchieAdapter"]
