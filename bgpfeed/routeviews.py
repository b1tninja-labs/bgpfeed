"""Archive discovery for RouteViews and RIPE RIS: file names, directory indexes, gaps, hashes.

Everything here is operational practice, not a specification. The archive layout and the file
naming below are what the two projects publish (``updates.YYYYMMDD.HHMM.bz2`` and
``rib.YYYYMMDD.HHMM.bz2`` for RouteViews, ``updates.YYYYMMDD.HHMM.gz`` and
``bview.YYYYMMDD.HHMM.gz`` for RIS). Three real listings, captured on 2026-11-13 and pinned by
SHA-256 in ``tools/corpus.json`` (fetched into a cache, not vendored), test the parsers: RouteViews
serves the Apache shape and RIS the nginx shape, and both print sizes with a unit (``394M``).
The operators can change either without notice.

* :func:`parse_name` reads a file name into its kind, UTC timestamp and compression;
* :func:`parse_index` reads the links of an HTML directory listing, best-effort for the modified
  time and size that follow each link, and reports every link it ignored;
* :func:`find_gaps` turns the timestamps of an archive's files into a
  :class:`bgpfeed.model.GapReport`; the cadence is a required argument, because this project
  records no operator rates (see :mod:`bgpfeed.budget`);
* :func:`sha256_file`, :func:`verify` and :class:`Ledger` record the SHA-256 of every archive file
  read. A GET over HTTPS proves who answered, not that the file is the one the operator
  published, and these archives carry no signature, so the first digest seen is pinned and a
  later difference is reported as a mismatch rather than overwritten.

:func:`follow` (polling for new files) is not built.
"""

from __future__ import annotations

import datetime
import hashlib
import html.parser
import itertools
import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .model import Gap, GapReport

if TYPE_CHECKING:
    from collections.abc import Iterable
    from typing import Any

    Sink = Any  # placeholder: give it a real type in the milestone that needs it
    Stream = Any  # placeholder: give it a real type in the milestone that needs it

__all__ = [
    "ArchiveName",
    "IndexEntry",
    "Ledger",
    "Listing",
    "Verification",
    "find_gaps",
    "follow",
    "parse_index",
    "parse_name",
    "sha256_file",
    "verify",
]

_NAME = re.compile(
    r"(?P<kind>updates|rib|bview)\.(?P<date>[0-9]{8})\.(?P<time>[0-9]{4})\.(?P<comp>bz2|gz|xz)"
)
_APACHE = re.compile(
    r"(?P<when>[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2})\s+(?P<size>[0-9.]+[KMGkmg]?|-)"
)
_NGINX = re.compile(
    r"(?P<when>[0-9]{2}-[A-Za-z]{3}-[0-9]{4} [0-9]{2}:[0-9]{2})\s+(?P<size>[0-9.]+[KMGkmg]?|-)"
)
_UNITS = {"": 1, "K": 1024, "M": 1024**2, "G": 1024**3}
_SHA256 = re.compile(r"[0-9a-f]{64}")
MAX_INDEX_CHARS = 32 * 1024 * 1024


@dataclass(frozen=True)
class ArchiveName:
    """A parsed archive file name: ``kind`` is ``updates``, ``rib`` or ``bview``."""

    name: str
    kind: str
    timestamp: datetime.datetime
    compression: str


def parse_name(name: str) -> ArchiveName:
    """Read ``kind.YYYYMMDD.HHMM.compression`` into an :class:`ArchiveName`.

    The timestamp is UTC (the archives name files by UTC). ``ValueError`` for a name of another
    shape, an impossible date or time, or one containing a path separator.
    """
    match = _NAME.fullmatch(name)
    if match is None:
        raise ValueError(f"not an archive file name: {name!r}")
    try:
        stamp = datetime.datetime.strptime(match["date"] + match["time"], "%Y%m%d%H%M").replace(
            tzinfo=datetime.UTC
        )
    except ValueError as error:
        raise ValueError(f"impossible date or time in {name!r}") from error
    return ArchiveName(name, match["kind"], stamp, match["comp"])


@dataclass(frozen=True)
class IndexEntry:
    """One file of a directory listing.

    ``modified`` and ``size`` are read from the listing text beside the link when it has one of
    the two common shapes, else ``None``; a size shown with a unit (``8.0M``) is rounded, which
    ``size_approximate`` says.
    """

    name: ArchiveName
    modified: datetime.datetime | None = None
    size: int | None = None
    size_approximate: bool = False


@dataclass(frozen=True)
class Listing:
    """The result of :func:`parse_index`: the archive files in order, and every ignored link."""

    entries: tuple[IndexEntry, ...]
    ignored: tuple[str, ...]


class _Links(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list[tuple[str, str]] = []  # (href, text that follows the link)
        self._href: str | None = None
        self._after = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self._href = dict(attrs).get("href") or ""
            self.items.append((self._href, ""))
            self._after = False

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href is not None:
            self._after = True
        elif tag == "tr":
            self._after = False  # a table row ends the text that belongs to its link

    def handle_data(self, data: str) -> None:
        if self._after and self.items:
            href, text = self.items[-1]
            self.items[-1] = (href, text + " " + data)


def _modified(text: str, shape: re.Pattern[str], fmt: str) -> tuple[datetime.datetime, str] | None:
    match = shape.search(text)
    if match is None:
        return None
    try:
        when = datetime.datetime.strptime(match["when"], fmt).replace(tzinfo=datetime.UTC)
    except ValueError:
        return None
    return when, match["size"]


def parse_index(page: str) -> Listing:
    """Read the file links of an HTML directory listing (see the module docstring).

    A link counts when its target is a bare archive file name (:func:`parse_name`); parent
    links, sort links, sub-directories and anything else go to ``ignored`` in page order. The
    modified time (taken as UTC) and size are read from the text after the link when it matches
    the Apache or the nginx listing shape. ``ValueError`` for a page over ``MAX_INDEX_CHARS``.
    """
    if len(page) > MAX_INDEX_CHARS:
        raise ValueError(f"directory listing larger than {MAX_INDEX_CHARS} characters")
    parser = _Links()
    parser.feed(page)
    parser.close()
    entries: list[IndexEntry] = []
    ignored: list[str] = []
    for href, text in parser.items:
        try:
            name = parse_name(href)
        except ValueError:
            ignored.append(href)
            continue
        found = _modified(text, _APACHE, "%Y-%m-%d %H:%M") or _modified(
            text, _NGINX, "%d-%b-%Y %H:%M"
        )
        modified = size = None
        approximate = False
        if found is not None:
            modified, raw_size = found
            if raw_size != "-":
                unit = raw_size[-1].upper() if raw_size[-1].isalpha() else ""
                number = raw_size[:-1] if unit else raw_size
                try:
                    size = round(float(number) * _UNITS[unit])
                    approximate = bool(unit)
                except ValueError:
                    size = None
        entries.append(IndexEntry(name, modified, size, approximate))
    return Listing(tuple(entries), tuple(ignored))


def find_gaps(
    entries: Iterable[ArchiveName | IndexEntry],
    *,
    interval: datetime.timedelta,
    source: str,
) -> GapReport:
    """List the periods an archive has no file for, from the timestamps of the files it has.

    A file stamped ``t`` covers ``[t, t + interval)``. The span of the report runs from the
    earliest stamp to the latest stamp plus ``interval``, and each hole between consecutive
    stamps longer than ``interval`` is a gap with the reason ``"no archive file"``. ``interval``
    is required: the operators' cadence is not recorded in this project. The entries must be of
    one kind (all updates, or all ribs); mixing kinds is ``ValueError``, as is an empty list or a
    non-positive interval. Duplicate stamps (the same file twice) are not a gap.
    """
    if interval <= datetime.timedelta(0):
        raise ValueError("interval must be positive")
    names = [e.name if isinstance(e, IndexEntry) else e for e in entries]
    if not names:
        raise ValueError("no archive files, so no span to report on")
    if len({n.kind for n in names}) != 1:
        raise ValueError("entries of different kinds cannot share one gap report")
    stamps = sorted({n.timestamp for n in names})
    gaps = [
        Gap(source, earlier + interval, later, "no archive file")
        for earlier, later in itertools.pairwise(stamps)
        if later - earlier > interval
    ]
    return GapReport.build(source, stamps[0], stamps[-1] + interval, gaps)


def sha256_file(path: Path) -> tuple[int, str]:
    """The size in octets and the lower-case SHA-256 hex digest of the file at ``path``."""
    digest = hashlib.sha256()
    size = 0
    with Path(path).open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
            size += len(chunk)
    return size, digest.hexdigest()


@dataclass(frozen=True)
class Verification:
    """What was seen for one archive file: ``status`` is ``recorded``, ``match`` or ``mismatch``.

    ``expected`` is the digest it was compared with, ``None`` when none was known yet.
    """

    name: str
    size: int
    sha256: str
    expected: str | None
    status: str


def verify(path: Path, expected: str | None = None) -> Verification:
    """Hash the file at ``path`` and compare with ``expected`` (lower-case hex), if given.

    Without ``expected`` the result is ``recorded``: the digest is only reported. A bad
    ``expected`` is ``ValueError``.
    """
    if expected is not None and _SHA256.fullmatch(expected) is None:
        raise ValueError("expected must be 64 lower-case hex digits")
    size, digest = sha256_file(path)
    status = "recorded" if expected is None else ("match" if digest == expected else "mismatch")
    return Verification(Path(path).name, size, digest, expected, status)


class Ledger:
    """A file of pinned SHA-256 digests by archive file name; the first digest seen wins.

    ``check`` hashes a file: a name not yet in the ledger is pinned and saved (``recorded``), an
    equal digest is a ``match``, and a different one is a ``mismatch`` that is reported and never
    overwrites the pin. Writes are atomic (a temporary file in the same directory, then a
    rename). A ledger file that is not the expected JSON object of name to 64-hex digest is
    refused with ``ValueError``, not repaired.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._pins: dict[str, str] = {}
        if self.path.exists():
            self._pins = self._load()

    def _load(self) -> dict[str, str]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise ValueError(f"cannot read ledger {self.path}: {error}") from error
        if not isinstance(data, dict) or not all(
            isinstance(k, str) and isinstance(v, str) and _SHA256.fullmatch(v)
            for k, v in data.items()
        ):
            raise ValueError(f"ledger {self.path} is not a map of file name to SHA-256")
        return dict(data)

    def pinned(self, name: str) -> str | None:
        """The digest pinned for ``name``, or ``None``."""
        return self._pins.get(name)

    def check(self, path: Path) -> Verification:
        """Verify the file at ``path`` against the ledger, pinning it on first sight."""
        name = Path(path).name
        known = self._pins.get(name)
        result = verify(path, known)
        if known is None:
            self._pins[name] = result.sha256
            self._save()
        return result

    def _save(self) -> None:
        payload: Any = dict(sorted(self._pins.items()))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle, temp = tempfile.mkstemp(dir=self.path.parent, prefix=".ledger-", suffix=".tmp")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as out:
                json.dump(payload, out, indent=1)
                out.write("\n")
                out.flush()
                os.fsync(out.fileno())
            os.replace(temp, self.path)
        except BaseException:
            Path(temp).unlink(missing_ok=True)
            raise


async def follow(collectors: list, since: datetime.datetime, sink: Sink) -> Stream:
    """Pending behaviour defined by design.

    Not implemented yet. See the ``routeviews.follow()`` row in ROADMAP.md; this stub raises
    on purpose so nothing downstream mistakes it for working code.
    """
    raise NotImplementedError("follow() is not implemented: design")
