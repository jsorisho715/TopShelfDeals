"""Tests for geocoding + distance helpers.

These run fully offline: ``data/geocode_cache.json`` is pre-populated with the
test address and the five anchor zips, and we hard-fail if anything tries to hit
the network.
"""
import pytest

from app.pipeline import geocode as g

# Test address (cached in data/geocode_cache.json).
_TEMPE_ADDR = "723 N Scottsdale Rd, Tempe, AZ 85281"


class _FetchSpy:
    """Stand-in for the network fetch: counts calls and returns None (a miss).

    Lets us both keep tests offline (no real HTTP) and assert that cached lookups
    never reach the fetch path.
    """

    def __init__(self):
        self.calls = 0

    def __call__(self, *_a, **_k):
        self.calls += 1
        return None


@pytest.fixture(autouse=True)
def fetch_spy(monkeypatch):
    spy = _FetchSpy()
    monkeypatch.setattr(g, "_fetch", spy)
    # Drop any in-process cache so we re-read the on-disk seed each test, and
    # never let a test mutate the committed cache file on disk.
    monkeypatch.setattr(g, "_cache", None)
    monkeypatch.setattr(g, "_save_cache", lambda: None)
    return spy


def test_haversine_zero_distance():
    pt = (33.4929125, -111.9170683)
    assert g.haversine_miles(pt, pt) == pytest.approx(0.0, abs=1e-6)


def test_haversine_one_degree():
    # One degree of latitude is ~69.09 statute miles anywhere on Earth.
    assert g.haversine_miles((0.0, 0.0), (1.0, 0.0)) == pytest.approx(69.09, abs=0.2)
    # One degree of longitude at the equator is also ~69.09 miles.
    assert g.haversine_miles((0.0, 0.0), (0.0, 1.0)) == pytest.approx(69.09, abs=0.2)


def test_haversine_known_city_pair():
    # Phoenix (Sky Harbor) -> Tucson is ~110 miles straight-line.
    phx = (33.4342, -112.0080)
    tus = (32.1161, -110.9410)
    assert g.haversine_miles(phx, tus) == pytest.approx(110, abs=8)


def test_geocode_uses_cache_offline(fetch_spy):
    coords = g.geocode(_TEMPE_ADDR)
    assert coords is not None
    lat, lng = coords
    # Roughly central Tempe, AZ.
    assert 33.3 < lat < 33.6
    assert -112.1 < lng < -111.8
    # Came straight from cache — never touched the (stubbed) network.
    assert fetch_spy.calls == 0


def test_geocode_none_for_blank():
    assert g.geocode("") is None
    assert g.geocode(None) is None


def test_anchor_distances_on_cached_address():
    dists = g.anchor_distances(_TEMPE_ADDR)
    assert set(dists) == set(g.ANCHORS)
    assert all(isinstance(v, float) and v >= 0 for v in dists.values())
    # The address sits in Tempe (85281), so the Tempe anchor is the closest.
    nearest = min(dists, key=dists.get)
    assert nearest == "tempe"


def test_nearest_anchor_miles_matches_min():
    dists = g.anchor_distances(_TEMPE_ADDR)
    assert g.nearest_anchor_miles(_TEMPE_ADDR) == pytest.approx(min(dists.values()))


def test_anchor_distances_empty_for_ungeocodable():
    assert g.anchor_distances("definitely not a real place zzz") == {}
    assert g.nearest_anchor_miles("definitely not a real place zzz") is None


def test_shop_distance_matrix_shape():
    matrix = g.shop_distance_matrix({"Tempe Shop": _TEMPE_ADDR})
    assert set(matrix) == set(g.ANCHORS)
    for anchor_id in g.ANCHORS:
        assert "Tempe Shop" in matrix[anchor_id]
        assert isinstance(matrix[anchor_id]["Tempe Shop"], float)
