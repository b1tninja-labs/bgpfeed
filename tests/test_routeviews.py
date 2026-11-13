"""Archive names, directory listings, gaps and hash pinning (operational practice, not an RFC).

No listing was captured from a live server: the pages below are built in the two common shapes
(Apache-style and nginx-style autoindex), as the module docstring of ``bgpfeed.routeviews``
says, and ROADMAP.md keeps a row to pin a real capture. The names follow the published
``updates.YYYYMMDD.HHMM`` convention.
"""

from __future__ import annotations

import datetime
import hashlib
import json

import pytest

from bgpfeed.budget import DropCounter  # noqa: F401  (import check: package imports cleanly)
from bgpfeed.routeviews import (
    MAX_INDEX_CHARS,
    Ledger,
    find_gaps,
    parse_index,
    parse_name,
    sha256_file,
    verify,
)

UTC = datetime.UTC
FIFTEEN = datetime.timedelta(minutes=15)

APACHE = """\
<html><head><title>Index of /route-views2/bgpdata/2026.11/UPDATES</title></head><body>
<h1>Index of /route-views2/bgpdata/2026.11/UPDATES</h1>
<table>
<tr><th><a href="?C=N;O=D">Name</a></th><th><a href="?C=M;O=A">Last modified</a></th></tr>
<tr><td><a href="/route-views2/bgpdata/2026.11/">Parent Directory</a></td></tr>
<tr><td><a href="updates.20261112.0000.bz2">updates.20261112.0000.bz2</a></td><td>2026-11-12 00:05  </td><td>8.0M</td></tr>
<tr><td><a href="updates.20261112.0015.bz2">updates.20261112.0015.bz2</a></td><td>2026-11-12 00:20  </td><td>1536K</td></tr>
<tr><td><a href="updates.20261112.0045.bz2">updates.20261112.0045.bz2</a></td><td>2026-11-12 00:50  </td><td>-</td></tr>
<tr><td><a href="README.txt">README.txt</a></td></tr>
</table></body></html>
"""

NGINX = """\
<html><head><title>Index of /bgpdata/2026.11/UPDATES/</title></head>
<body><h1>Index of /bgpdata/2026.11/UPDATES/</h1><hr><pre><a href="../">../</a>
<a href="updates.20261112.0000.bz2">updates.20261112.0000.bz2</a>   12-Nov-2026 00:05     8388608
<a href="updates.20261112.0015.bz2">updates.20261112.0015.bz2</a>   12-Nov-2026 00:20     1572864
<a href="subdir/">subdir/</a>                  12-Nov-2026 00:20       -
</pre><hr></body></html>
"""


def test_parse_name_reads_kind_time_and_compression():
    name = parse_name("updates.20261112.0015.bz2")
    assert (name.kind, name.compression) == ("updates", "bz2")
    assert name.timestamp == datetime.datetime(2026, 11, 12, 0, 15, tzinfo=UTC)
    assert parse_name("rib.20261112.1200.bz2").kind == "rib"
    assert parse_name("bview.20261112.0800.gz").compression == "gz"


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "updates.20261112.0015",
        "updates.20261112.0015.zip",
        "updates.20261301.0015.bz2",  # month 13
        "updates.20261112.2460.bz2",  # minute 60
        "../updates.20261112.0015.bz2",
        "sub/updates.20261112.0015.bz2",
        "updates.20261112.0015.bz2.sha256",
        "updates.2026112.0015.bz2",
    ],
)
def test_parse_name_refuses(bad):
    with pytest.raises(ValueError, match=r"archive|impossible"):
        parse_name(bad)


def test_parse_index_apache_shape_reads_names_times_and_sizes_and_reports_what_it_skipped():
    listing = parse_index(APACHE)
    assert [e.name.name for e in listing.entries] == [
        "updates.20261112.0000.bz2",
        "updates.20261112.0015.bz2",
        "updates.20261112.0045.bz2",
    ]
    first, second, third = listing.entries
    assert first.modified == datetime.datetime(2026, 11, 12, 0, 5, tzinfo=UTC)
    assert (first.size, first.size_approximate) == (8 * 1024 * 1024, True)
    assert (second.size, second.size_approximate) == (1536 * 1024, True)
    assert third.size is None
    assert listing.ignored == (
        "?C=N;O=D",
        "?C=M;O=A",
        "/route-views2/bgpdata/2026.11/",
        "README.txt",
    )


def test_parse_index_nginx_shape_gives_exact_sizes():
    listing = parse_index(NGINX)
    assert [e.size for e in listing.entries] == [8388608, 1572864]
    assert not any(e.size_approximate for e in listing.entries)
    assert listing.entries[0].modified == datetime.datetime(2026, 11, 12, 0, 5, tzinfo=UTC)
    assert listing.ignored == ("../", "subdir/")


def test_parse_index_with_no_text_beside_the_link_still_yields_the_entry():
    listing = parse_index('<a href="updates.20261112.0000.bz2">x</a>')
    (entry,) = listing.entries
    assert (entry.modified, entry.size) == (None, None)


def test_parse_index_is_bounded_and_survives_garbage():
    with pytest.raises(ValueError, match="larger than"):
        parse_index("x" * (MAX_INDEX_CHARS + 1))
    assert parse_index("<<<>>> <a href=> <a>no href</a> \x00").entries == ()


def test_parse_index_does_not_follow_absolute_links():
    page = '<a href="http://evil.example/updates.20261112.0000.bz2">x</a>'
    listing = parse_index(page)
    assert listing.entries == ()
    assert listing.ignored == ("http://evil.example/updates.20261112.0000.bz2",)


def names(*stamps: str, kind: str = "updates"):
    return [parse_name(f"{kind}.{s}.bz2") for s in stamps]


def test_find_gaps_reports_missing_files_between_stamps():
    entries = names("20261112.0000", "20261112.0015", "20261112.0045", "20261112.0100")
    report = find_gaps(entries, interval=FIFTEEN, source="route-views2")
    start = datetime.datetime(2026, 11, 12, 0, 0, tzinfo=UTC)
    assert report.start == start
    assert report.end == start + datetime.timedelta(minutes=75)  # last stamp 01:00 + 15 min
    (gap,) = report.gaps
    assert (gap.start, gap.end) == (
        start + datetime.timedelta(minutes=30),
        start + datetime.timedelta(minutes=45),
    )
    assert gap.reason == "no archive file"
    assert report.missing == datetime.timedelta(minutes=15)
    assert report.coverage == pytest.approx(60 / 75)


def test_find_gaps_with_every_file_present_is_complete_and_order_does_not_matter():
    entries = names("20261112.0030", "20261112.0000", "20261112.0015", "20261112.0015")
    report = find_gaps(entries, interval=FIFTEEN, source="x")
    assert report.complete
    assert report.span == datetime.timedelta(minutes=45)


def test_find_gaps_accepts_index_entries():
    listing = parse_index(APACHE)
    report = find_gaps(listing.entries, interval=FIFTEEN, source="route-views2")
    assert len(report.gaps) == 1  # 00:30 to 00:45 is missing between the 00:15 and 00:45 files


def test_find_gaps_refuses_unusable_input():
    with pytest.raises(ValueError, match="no archive files"):
        find_gaps([], interval=FIFTEEN, source="x")
    with pytest.raises(ValueError, match="positive"):
        find_gaps(names("20261112.0000"), interval=datetime.timedelta(0), source="x")
    mixed = names("20261112.0000") + names("20261112.0000", kind="rib")
    with pytest.raises(ValueError, match="different kinds"):
        find_gaps(mixed, interval=FIFTEEN, source="x")


def test_sha256_file_matches_hashlib_and_counts_octets(tmp_path):
    data = b"abc" * 1_000_000  # more than one 1 MiB chunk
    target = tmp_path / "updates.20261112.0000.bz2"
    target.write_bytes(data)
    assert sha256_file(target) == (len(data), hashlib.sha256(data).hexdigest())


def test_verify_records_matches_and_mismatches(tmp_path):
    target = tmp_path / "updates.20261112.0000.bz2"
    target.write_bytes(b"payload")
    digest = hashlib.sha256(b"payload").hexdigest()
    assert verify(target).status == "recorded"
    assert verify(target, digest).status == "match"
    bad = verify(target, "0" * 64)
    assert (bad.status, bad.sha256, bad.expected) == ("mismatch", digest, "0" * 64)
    assert bad.name == target.name
    for wrong in ("ABC", digest.upper(), digest[:-1]):
        with pytest.raises(ValueError, match="64 lower-case"):
            verify(target, wrong)


def test_ledger_pins_the_first_digest_and_reports_a_change_without_overwriting(tmp_path):
    ledger_path = tmp_path / "state" / "ledger.json"
    archive = tmp_path / "updates.20261112.0000.bz2"
    archive.write_bytes(b"first")
    ledger = Ledger(ledger_path)
    assert ledger.check(archive).status == "recorded"
    assert ledger.check(archive).status == "match"
    first = hashlib.sha256(b"first").hexdigest()
    assert ledger.pinned(archive.name) == first

    archive.write_bytes(b"second")  # the operator replaced the file
    changed = ledger.check(archive)
    assert changed.status == "mismatch"
    assert changed.expected == first
    assert ledger.pinned(archive.name) == first  # the pin is not overwritten

    reopened = Ledger(ledger_path)  # the pin survives a restart
    assert reopened.pinned(archive.name) == first
    assert json.loads(ledger_path.read_text(encoding="utf-8")) == {archive.name: first}
    assert [p.name for p in ledger_path.parent.iterdir()] == ["ledger.json"]  # no temp left


@pytest.mark.parametrize(
    "content",
    ["not json", "[]", '{"a": 1}', '{"a": "XYZ"}', '{"a": "' + "A" * 64 + '"}'],
)
def test_ledger_refuses_a_file_that_is_not_a_digest_map(tmp_path, content):
    path = tmp_path / "ledger.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match="ledger"):
        Ledger(path)
