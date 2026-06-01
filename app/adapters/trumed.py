"""TruMed (trumedaz.com) menu adapter.

Investigated source of truth (live, 2026): ``trumedaz.com/shop`` is a WordPress
page that embeds a **Dutchie** storefront (the menu URL carries Dutchie's
``?dtche[...]`` plugin params, and the page loads
``dutchie.com/api/v2/embedded-menu/<retailerId>.js``). That is exactly the same
shape the :class:`app.adapters.trulieve.TrulieveAdapter` already handles, so this
adapter is a thin subclass that only swaps the ``Referer`` to trumedaz.com. All
embed-resolution, Dutchie GraphQL/Playwright fetching, parsing, and the Phase-1
promo extraction come for free from the Trulieve implementation.
"""

from __future__ import annotations

from typing import Any

from .trulieve import TrulieveAdapter


class TruMedAdapter(TrulieveAdapter):
    """TruMed = Dutchie embedded storefront (see module docstring)."""

    def _headers(self) -> dict[str, str]:
        h = super()._headers()
        h["Referer"] = "https://trumedaz.com/"
        return h
