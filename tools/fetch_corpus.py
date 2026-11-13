#!/usr/bin/env python3
"""Fetch the real-data corpus into a cache outside the repository, pinned by SHA-256 and size.

The corpus is real archive directory listings, parsed by ``tests/test_routeviews_corpus.py``. None is
vendored: the operators' terms (recorded per file in ``tools/corpus.json``) do not grant
redistribution in a source tree, and a listing is the operator's page, not ours. So this tool fetches
each file into a cache, checks it against the pin, and the tests skip loudly when it is absent.

* The cache is ``$BGPFEED_CORPUS_DIR`` when set, else the user cache directory
  (``%LOCALAPPDATA%\\bgpfeed\\corpus`` on Windows, ``~/Library/Caches/bgpfeed/corpus`` on macOS,
  ``$XDG_CACHE_HOME/bgpfeed/corpus`` or ``~/.cache/bgpfeed/corpus`` elsewhere).
* Every file in ``tools/corpus.json`` carries its URL, SHA-256, size and a read label: the date it
  was fetched and the operator's terms as read on their site. A fetched file whose digest or size
  differs from the pin is deleted and reported; the pin is never rewritten. ``--record`` fills a pin
  only where the manifest has none, which is how a new file is added.
* Requests are spaced at least one second apart, and only files not yet cached are fetched.

Run: ``python tools/fetch_corpus.py`` (``--list`` shows the cache and what is in it).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import sys
import time
import urllib.request
from typing import Any

PROJECT = "bgpfeed"
ENV = "BGPFEED_CORPUS_DIR"
MANIFEST = pathlib.Path(__file__).resolve().with_name("corpus.json")
USER_AGENT = f"{PROJECT}-corpus-fetch/0.1 (python-urllib)"
INTERVAL = 1.0  # seconds between requests, the owner's rule for these archives


def cache_dir() -> pathlib.Path:
    """The corpus cache: ``$BGPFEED_CORPUS_DIR``, else the platform user cache directory."""
    override = os.environ.get(ENV)
    if override:
        return pathlib.Path(override)
    home = pathlib.Path.home()
    if sys.platform == "win32":
        base = pathlib.Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = home / "Library" / "Caches"
    else:
        base = pathlib.Path(os.environ.get("XDG_CACHE_HOME") or home / ".cache")
    return base / PROJECT / "corpus"


def load_manifest() -> list[dict[str, Any]]:
    """The pinned files, in manifest order."""
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    files: list[dict[str, Any]] = data["files"]
    return files


def digest(path: pathlib.Path) -> tuple[int, str]:
    """The size and SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            h.update(chunk)
            size += len(chunk)
    return size, h.hexdigest()


def cached(entry: dict[str, Any]) -> pathlib.Path | None:
    """The cached file for a manifest entry when it is present and matches its pin, else None.

    The pinned name is tried first; failing that, any file in the cache with the pinned size and
    SHA-256 is the entry. So pointing two projects' cache variables at one directory shares the
    bytes whatever each project calls them: a file is identified by its digest, never by its name.
    """
    if not entry.get("sha256"):
        return None
    root = cache_dir()
    named = root / entry["name"]
    candidates = [named] if named.is_file() else []
    if root.is_dir():
        candidates += [
            p
            for p in sorted(root.iterdir())
            if p != named and p.is_file() and p.stat().st_size == entry["size"]
        ]
    for path in candidates:
        if digest(path) == (entry["size"], entry["sha256"]):
            return path
    return None


class _Spacer:
    def __init__(self) -> None:
        self.last = 0.0

    def wait(self) -> None:
        delay = INTERVAL - (time.monotonic() - self.last)
        if delay > 0:
            time.sleep(delay)
        self.last = time.monotonic()


def fetch(entry: dict[str, Any], spacer: _Spacer, *, record: bool) -> str:
    """Fetch one entry into the cache and check it; returns a one-line status."""
    target = cache_dir() / entry["name"]
    if cached(entry) is not None:
        return f"present  {entry['name']}"
    if not entry.get("sha256") and not record:
        return f"UNPINNED {entry['name']}: run with --record to pin it on first fetch"
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    spacer.wait()
    if not entry["url"].startswith("https://"):
        return f"REFUSED  {entry['name']}: only https URLs are fetched"
    request = urllib.request.Request(entry["url"], headers={"User-Agent": USER_AGENT})  # noqa: S310 - https checked above
    with urllib.request.urlopen(request, timeout=120) as response, partial.open("wb") as out:  # noqa: S310
        while chunk := response.read(1 << 20):
            out.write(chunk)
    size, sha = digest(partial)
    if entry.get("sha256"):
        if (size, sha) != (entry["size"], entry["sha256"]):
            partial.unlink()
            return f"MISMATCH {entry['name']}: got {size} {sha}, pinned {entry['size']} {entry['sha256']}"
    else:
        entry["size"], entry["sha256"] = size, sha
    partial.replace(target)
    return f"fetched  {entry['name']} {size} {sha}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--record", action="store_true", help="pin entries that have no pin yet")
    parser.add_argument("--list", action="store_true", help="show the cache and its state")
    args = parser.parse_args(argv)
    files = load_manifest()
    print(f"cache: {cache_dir()}")
    if args.list:
        for entry in files:
            state = "ok" if cached(entry) is not None else "absent"
            print(f"{state:7} {entry['name']} {entry.get('size')} {entry.get('sha256')}")
        return 0
    spacer = _Spacer()
    failed = False
    for entry in files:
        line = fetch(entry, spacer, record=args.record)
        failed |= line.startswith(("MISMATCH", "UNPINNED", "REFUSED"))
        print(line, flush=True)
    if args.record:
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
        data["files"] = files
        MANIFEST.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
