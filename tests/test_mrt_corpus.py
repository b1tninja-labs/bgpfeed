"""Real updates files through ``mrt.iter_updates``: row ``mrt.corpus-updates``.

The two files are pinned in ``tools/corpus.json`` with the same bytes as asnkit's pins, so one
shared cache directory (both ``*_CORPUS_DIR`` variables pointing at it) serves both projects;
``tools/fetch_corpus.py`` finds a file by its SHA-256. Reading both takes about 12 seconds, under
the 30-second line for an opt-in marker, so this runs with the default gates. The counts are
exact, measured on 2026-11-13.
"""

from __future__ import annotations

import collections
import importlib.util
import pathlib
from typing import Any

import pytest

from bgpfeed import mrt

TOOL = pathlib.Path(__file__).resolve().parents[1] / "tools" / "fetch_corpus.py"


def _tool() -> Any:
    spec = importlib.util.spec_from_file_location("bgpfeed_fetch_corpus_mrt", TOOL)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


FETCH = _tool()


def corpus(name: str) -> pathlib.Path:
    (entry,) = [e for e in FETCH.load_manifest() if e["name"] == name]
    path = FETCH.cached(entry)
    if path is None:
        pytest.skip(
            f"real-data corpus absent: {name} is not in {FETCH.cache_dir()} with its pinned "
            f"SHA-256; run `python tools/fetch_corpus.py` (or set {FETCH.ENV})"
        )
    return path


def census(name: str) -> tuple[dict[str, int], mrt.Stats]:
    stats = mrt.Stats()
    kinds: collections.Counter[str] = collections.Counter()
    for event in mrt.iter_updates(corpus(name), stats=stats):
        kinds[event.kind.name] += 1
    return dict(kinds), stats


def test_real_updates_files():
    kinds, stats = census("routeviews-route-views2-updates.20261112.0000.bz2")
    assert kinds == {"ANNOUNCE": 264293, "WITHDRAW": 14121}
    assert (stats.records, stats.messages, stats.events, stats.malformed) == (
        100953,
        100953,
        278414,
        0,
    )
    kinds, stats = census("ris-rrc00-updates.20261112.0000.gz")
    assert kinds == {"ANNOUNCE": 435162, "WITHDRAW": 35935, "PEER_STATE": 170}
    assert (stats.records, stats.messages, stats.events, stats.malformed) == (
        194896,
        194726,
        471267,
        0,
    )
