"""Checkpoint store: a stored checkpoint resumes exactly, or refuses."""

from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import replace

import pytest

from bgpfeed import state
from bgpfeed.state import Checkpoint, StateError, StateStore

H = hashlib.sha256(b"consumed").hexdigest()


def cp(source="ris:rrc00", position="updates.20261112.0000.gz", offset=100, when=None):
    when = when or "2026-11-12T10:00:00+00:00"
    return Checkpoint(source, position, offset, H, when)


def only_file(store):
    (path,) = [p for p in store.directory.iterdir() if p.suffix == ".json"]
    return path


def test_roundtrip(tmp_path):
    store = StateStore(tmp_path / "s")
    store.checkpoint(cp())
    assert store.resume("ris:rrc00") == cp()


def test_module_functions_wrap_the_store(tmp_path):
    store = StateStore(tmp_path)
    state.checkpoint(store, cp())
    assert state.resume(store, "ris:rrc00") == cp()


def test_resume_missing_returns_none(tmp_path):
    assert StateStore(tmp_path).resume("nothing") is None
    assert StateStore(tmp_path / "absent").resume("nothing") is None


def test_checkpoint_is_atomic_under_crash(tmp_path, monkeypatch):
    store = StateStore(tmp_path)
    store.checkpoint(cp(offset=1))

    def boom(*_a, **_k):
        raise OSError("crash")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError, match="crash"):
        store.checkpoint(cp(offset=2, when="2026-11-12T11:00:00+00:00"))
    monkeypatch.undo()
    assert store.resume("ris:rrc00").offset == 1
    assert not [p for p in tmp_path.iterdir() if p.suffix == ".part"]


def test_resume_corrupt_json_raises(tmp_path):
    store = StateStore(tmp_path)
    store.checkpoint(cp())
    only_file(store).write_bytes(b"{not json")
    with pytest.raises(StateError, match="corrupt"):
        store.resume("ris:rrc00")


def test_resume_truncated_file_raises(tmp_path):
    store = StateStore(tmp_path)
    store.checkpoint(cp())
    path = only_file(store)
    path.write_bytes(path.read_bytes()[:-20])
    with pytest.raises(StateError):
        store.resume("ris:rrc00")


def test_resume_wrong_schema_raises(tmp_path):
    store = StateStore(tmp_path)
    store.checkpoint(cp())
    path = only_file(store)
    record = json.loads(path.read_text())
    record["checkpoint"]["schema"] = 2
    record["sha256"] = state._digest(record["checkpoint"])  # a valid hash over a wrong schema
    path.write_text(json.dumps(record))
    with pytest.raises(StateError, match="schema"):
        store.resume("ris:rrc00")


def test_resume_hash_of_record_mismatch_raises(tmp_path):
    store = StateStore(tmp_path)
    store.checkpoint(cp(offset=100))
    path = only_file(store)
    path.write_text(path.read_text().replace('"offset": 100', '"offset": 101'))
    with pytest.raises(StateError, match="hash"):
        store.resume("ris:rrc00")


def test_resume_refuses_a_file_swapped_between_sources(tmp_path):
    store = StateStore(tmp_path)
    store.checkpoint(cp(source="a"))
    store.checkpoint(cp(source="b"))
    a, b = store._path("a"), store._path("b")
    b.write_bytes(a.read_bytes())
    with pytest.raises(StateError, match="different source"):
        store.resume("b")


@pytest.mark.parametrize(
    "source",
    ["../../x", "/etc/passwd", "C:\\Windows\\x", "a\x00b", "x" * 100_000, "CON", "NUL", "a/b\\c"],
    ids=["dotdot", "absolute", "drive", "nul", "long", "con", "nul-device", "separators"],
)
def test_source_with_path_traversal_is_confined(tmp_path, source):
    store = StateStore(tmp_path / "s")
    store.checkpoint(cp(source=source))
    assert store.resume(source).source == source
    files = list((tmp_path / "s").iterdir())
    assert len(files) == 1
    assert files[0].parent == tmp_path / "s"
    assert len(files[0].name) == 64 + len(".json")
    assert list(tmp_path.iterdir()) == [tmp_path / "s"]


def test_two_sources_do_not_collide(tmp_path):
    store = StateStore(tmp_path)
    store.checkpoint(cp(source="a", offset=1))
    store.checkpoint(cp(source="b", offset=2))
    assert (store.resume("a").offset, store.resume("b").offset) == (1, 2)


def test_checkpoint_monotonic_guard(tmp_path):
    store = StateStore(tmp_path)
    store.checkpoint(cp(offset=500))
    with pytest.raises(StateError, match="rewind"):
        store.checkpoint(cp(offset=400))
    with pytest.raises(StateError, match="rewind"):
        store.checkpoint(cp(offset=900, when="2026-11-12T09:00:00+00:00"))
    assert store.resume("ris:rrc00").offset == 500
    store.checkpoint(cp(offset=400), allow_rewind=True)
    assert store.resume("ris:rrc00").offset == 400


def test_new_position_may_restart_offset(tmp_path):
    store = StateStore(tmp_path)
    store.checkpoint(cp(offset=500))
    store.checkpoint(
        replace(cp(offset=0), position="next-file", updated_utc="2026-11-12T11:00:00Z")
    )
    assert store.resume("ris:rrc00").position == "next-file"


def test_concurrent_writers_last_complete_write_wins(tmp_path):
    store = StateStore(tmp_path)
    errors = []

    def write(n):
        try:
            store.checkpoint(cp(offset=n), allow_rewind=True)
        except Exception as error:
            errors.append(error)

    threads = [threading.Thread(target=write, args=(n,)) for n in range(40)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert 0 <= store.resume("ris:rrc00").offset < 40  # intact, one of the writes
    assert not [p for p in tmp_path.iterdir() if p.suffix == ".part"]


@pytest.mark.parametrize(
    "bad",
    [
        cp(source=""),
        cp(offset=-1),
        cp(offset=True),
        replace(cp(), consumed_sha256="ABC"),
        replace(cp(), updated_utc="yesterday"),
        replace(cp(), updated_utc="2026-11-12T10:00:00"),
        replace(cp(), schema=9),
    ],
)
def test_invalid_checkpoint_refused_on_write(tmp_path, bad):
    with pytest.raises(StateError):
        StateStore(tmp_path).checkpoint(bad)
    assert not list(tmp_path.iterdir())


def test_state_errors_are_raised_not_asserted():
    # Under python -O an assert would vanish; the guards above are raises.
    with pytest.raises(StateError):
        cp(source="").validate()
