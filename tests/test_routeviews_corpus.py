"""Real directory listings: row ``routeviews.index-capture``.

Three listings captured on 2026-11-13 (October 2026, a completed month) are pinned in
``tools/corpus.json`` and fetched by ``tools/fetch_corpus.py`` into a cache outside the repository;
nothing is vendored. Without the cache every test here skips with the command that fills it.

What they showed: RouteViews serves the Apache shape (``2026-10-01 00:15  2.8M``) with four sort
links and a parent link; RIS serves the nginx shape (``01-Oct-2026 00:06    394M``) with a ``../``
link. Both print sizes with a unit. The first parser read the nginx size as a bare integer, so a
394 MB bview came back as 394 octets; the capture found it and the nginx pattern now takes a unit.
"""

from __future__ import annotations

import datetime
import importlib.util
import pathlib
from typing import Any

import pytest

from bgpfeed.routeviews import Listing, find_gaps, parse_index

TOOL = pathlib.Path(__file__).resolve().parents[1] / "tools" / "fetch_corpus.py"
UTC = datetime.UTC
MIB = 1024**2


def _tool() -> Any:
    spec = importlib.util.spec_from_file_location("bgpfeed_fetch_corpus", TOOL)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


FETCH = _tool()


def listing(name: str) -> Listing:
    """The cached page, checked against its pin and parsed; a loud skip when it is absent."""
    (entry,) = [e for e in FETCH.load_manifest() if e["name"] == name]
    path = FETCH.cached(entry)
    if path is None:
        pytest.skip(
            f"real-data corpus absent: {name} is not in {FETCH.cache_dir()} with its pinned "
            f"SHA-256; run `python tools/fetch_corpus.py` (or set {FETCH.ENV})"
        )
    return parse_index(path.read_text(encoding="utf-8"))


def test_manifest_pins_every_listing_with_a_read_label():
    for entry in FETCH.load_manifest():
        assert entry["url"].startswith("https://"), entry["name"]
        assert len(entry["sha256"]) == 64, entry["name"]
        assert entry["size"] > 0, entry["name"]
        assert entry["read"] == "2026-11-13", entry["name"]
        assert "vendored" in entry["terms"], entry["name"]


def test_captured_listings():
    """RouteViews updates: every 15-minute file of October, Apache shape, nothing unexplained."""
    page = listing("routeviews-route-views2-2026.10-UPDATES.html")
    assert len(page.entries) == 31 * 96
    assert page.ignored == ("?C=N;O=D", "?C=M;O=A", "?C=S;O=A", "?C=D;O=A", "/bgpdata/2026.10/")
    first, last = page.entries[0], page.entries[-1]
    assert first.name.name == "updates.20261001.0000.bz2"
    assert first.modified == datetime.datetime(2026, 10, 1, 0, 15, tzinfo=UTC)
    assert (first.size, first.size_approximate) == (round(2.8 * MIB), True)
    assert last.name.name == "updates.20261031.2345.bz2"
    assert all(e.modified is not None and e.size is not None for e in page.entries)
    report = find_gaps(page.entries, interval=datetime.timedelta(minutes=15), source="rv2")
    assert report.gaps == ()


def test_captured_routeviews_rib_listing():
    page = listing("routeviews-route-views2-2026.10-RIBS.html")
    assert len(page.entries) == 31 * 12
    assert {e.name.kind for e in page.entries} == {"rib"}
    assert all(e.size_approximate for e in page.entries)
    report = find_gaps(page.entries, interval=datetime.timedelta(hours=2), source="rv2")
    assert report.gaps == ()


def test_captured_ris_listing_nginx_shape_with_unit_sizes():
    page = listing("ris-rrc00-2026.10.html")
    assert page.ignored == ("../",)
    kinds = [e.name.kind for e in page.entries]
    assert (kinds.count("bview"), kinds.count("updates")) == (31 * 3, 31 * 288)
    first = page.entries[0]
    assert first.name.name == "bview.20261001.0000.gz"
    assert first.modified == datetime.datetime(2026, 10, 1, 0, 6, tzinfo=UTC)
    # 394M, not 394 octets: the regression this capture found
    assert (first.size, first.size_approximate) == (394 * MIB, True)
    assert all(e.size is not None and e.size_approximate for e in page.entries)
    updates = [e for e in page.entries if e.name.kind == "updates"]
    report = find_gaps(updates, interval=datetime.timedelta(minutes=5), source="rrc00")
    assert report.gaps == ()
