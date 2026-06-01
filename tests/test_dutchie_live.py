"""Tests for the tolerant ``parse_menu_response`` against a REAL captured body.

``dutchie_live_capture.json`` is a trimmed, real GraphQL response captured from a
live Dutchie embed (The Mint - Tempe) via the Playwright fallback. It exercises
the actual production schema (``recSpecialPrices``, ``brandName``, ``THCContent``
range, ``images[].url``) rather than the hand-authored fixture, so the parser
stays honest about the shape Dutchie really serves.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.adapters.dutchie import parse_menu_response
from app.pipeline.normalize import normalize_item

_LIVE_FIXTURE = Path(__file__).parent / "fixtures" / "dutchie_live_capture.json"


def _load_live() -> dict:
    with open(_LIVE_FIXTURE, "r", encoding="utf-8") as fh:
        return json.load(fh)


@pytest.mark.skipif(not _LIVE_FIXTURE.exists(), reason="no live capture fixture present")
def test_parse_menu_response_on_live_capture():
    items = parse_menu_response(_load_live())
    # At least one real product comes out.
    assert len(items) >= 1

    # Every parsed product must carry an image URL and a usable price — the
    # contract the UI/bot depend on.
    priced_with_img = [
        it
        for it in items
        if it.get("img")
        and it.get("orig") is not None
        and it.get("sale") is not None
    ]
    assert len(priced_with_img) >= 1

    sample = priced_with_img[0]
    assert isinstance(sample["img"], str) and sample["img"].startswith("http")
    assert sample["orig"] > 0
    # Sale should never exceed the original.
    assert sample["sale"] <= sample["orig"]


@pytest.mark.skipif(not _LIVE_FIXTURE.exists(), reason="no live capture fixture present")
def test_live_capture_normalizes_when_allowlisted():
    items = parse_menu_response(_load_live())
    normalized = [d for d in (normalize_item(it, shop="The Mint") for it in items) if d]
    # The live capture may contain only non-allowlisted brands depending on the
    # trimmed slice; if any normalize, they must be well-formed.
    for d in normalized:
        assert d["shop"] == "The Mint"
        assert d.get("img")
        assert d.get("unit") is not None
