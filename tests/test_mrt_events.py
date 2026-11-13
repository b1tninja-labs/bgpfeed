"""MRT updates archives mapped to events, through asnkit's MRT codec and pathattr's BGP codec.

Vector from the RFC: Figure 16 of RFC 6396 (a BGP4MP_MESSAGE_AS4 record) with erratum 5511 applied,
whose BGP message Figure 17 describes: an UPDATE announcing 203.0.113.0/24 with AS_PATH
64496 64511 64502 from peer 192.0.2.85, AS 64496. Every other record is built here from the layouts
of RFC 6396 section 4.4, RFC 8050 section 3, RFC 4271 section 4.3 and RFC 4760 sections 3 and 4.
"""

from __future__ import annotations

import bz2
import datetime
import gzip
import io
import ipaddress
import struct

import pytest
from asnkit.mrt import MrtError

from bgpfeed.budget import DropCounter
from bgpfeed.model import Event, EventKind, Peer
from bgpfeed.mrt import MalformedRecordError, Stats, events_from_stream, iter_updates

TS = 1300475700  # 2011-03-18 19:15:00 UTC
WHEN = datetime.datetime(2011, 3, 18, 19, 15, tzinfo=datetime.UTC)
MARK = b"\xff" * 16

FIG16_UPDATE = bytes.fromhex(
    "ff ff ff ff ff ff ff ff ff ff ff ff ff ff ff ff"
    "00 3e 02 00 00 00 23 40 01 01 02 40 02 0e 02 03"
    "00 00 fb f0 00 00 fb ff 00 00 fb f6 40 03 04 c6"
    "33 64 bc c0 08 04 fb f0 00 0e 18 cb 00 71"
)
FIG16_ASPATH = bytes.fromhex("02 03 0000fbf0 0000fbff 0000fbf6".replace(" ", ""))

ORIGIN = bytes([0x40, 1, 1, 0])
ASPATH4 = bytes([0x40, 2, 10, 2, 2]) + struct.pack(">II", 64496, 64502)
NEXTHOP = bytes([0x40, 3, 4, 192, 0, 2, 1])
V4_PEER = bytes([192, 0, 2, 85])
V4_LOCAL = bytes([198, 51, 100, 4])


def upd(withdrawn: bytes = b"", attrs: bytes = b"", nlri: bytes = b"") -> bytes:
    body = struct.pack(">H", len(withdrawn)) + withdrawn + struct.pack(">H", len(attrs)) + attrs
    body += nlri
    return MARK + struct.pack(">HB", 19 + len(body), 2) + body


def bgp4mp(
    subtype: int,
    message: bytes,
    *,
    as4: bool = True,
    when: int = TS,
    rtype: int = 16,
    microseconds: int | None = None,
    peer_as: int = 64496,
) -> bytes:
    fmt = ">II" if as4 else ">HH"
    body = struct.pack(fmt, peer_as, 64497) + struct.pack(">HH", 0, 1) + V4_PEER + V4_LOCAL
    body += message
    if microseconds is not None:
        body = struct.pack(">I", microseconds) + body
    return struct.pack(">IHHI", when, rtype, subtype, len(body)) + body


def run(data: bytes, **kw) -> list[Event]:
    return list(events_from_stream(io.BytesIO(data), source="test", **kw))


PEER = Peer(ipaddress.ip_address("192.0.2.85"), 64496)


def test_figure_16_update_is_one_announce_with_its_as_path():
    (event,) = run(bgp4mp(4, FIG16_UPDATE))
    assert event == Event(
        WHEN,
        "test",
        PEER,
        EventKind.ANNOUNCE,
        prefix=ipaddress.ip_network("203.0.113.0/24"),
        as_path=FIG16_ASPATH,
        four_octet_as=True,
    )


def test_every_prefix_of_an_update_is_its_own_event_sharing_the_attributes():
    nlri = bytes([24, 203, 0, 113, 16, 198, 51])
    events = run(bgp4mp(4, upd(attrs=ORIGIN + ASPATH4 + NEXTHOP, nlri=nlri)))
    assert [str(e.prefix) for e in events] == ["203.0.113.0/24", "198.51.0.0/16"]
    assert events[0].as_path == events[1].as_path


def test_withdrawn_routes_are_withdraw_events_without_an_as_path():
    (event,) = run(bgp4mp(4, upd(withdrawn=bytes([24, 203, 0, 113]))))
    assert event.kind is EventKind.WITHDRAW
    assert event.prefix == ipaddress.ip_network("203.0.113.0/24")
    assert event.as_path is None
    assert event.reason == ""


def test_ipv6_mp_reach_and_mp_unreach():
    reach = struct.pack(">HBB", 2, 1, 16) + bytes([0x20, 1, 0x0D, 0xB8]) + bytes(12) + b"\x00"
    reach += bytes([32, 0x20, 1, 0x0D, 0xB8])
    unreach = struct.pack(">HB", 2, 1) + bytes([48, 0x20, 1, 0x0D, 0xB8, 0, 7])
    attrs = (
        ORIGIN
        + ASPATH4
        + bytes([0x80, 14, len(reach)])
        + reach
        + bytes([0x80, 15, len(unreach)])
        + unreach
    )
    announce, withdraw = run(bgp4mp(4, upd(attrs=attrs)))
    assert (announce.kind, str(announce.prefix)) == (EventKind.ANNOUNCE, "2001:db8::/32")
    assert announce.as_path is not None
    assert (withdraw.kind, str(withdraw.prefix)) == (EventKind.WITHDRAW, "2001:db8:7::/48")


def test_addpath_subtype_reads_path_identifiers_and_the_plain_subtype_does_not():
    # RFC 8050 section 3: subtype 9 is BGP4MP_MESSAGE_AS4_ADDPATH; RFC 7911 section 3 puts a
    # 4-octet Path Identifier before each NLRI entry.
    nlri = struct.pack(">I", 77) + bytes([24, 203, 0, 113])
    message = upd(attrs=ORIGIN + ASPATH4 + NEXTHOP, nlri=nlri)
    (event,) = run(bgp4mp(9, message))
    assert event.path_id == 77
    assert event.prefix == ipaddress.ip_network("203.0.113.0/24")
    # the same bytes under the plain subtype are not valid NLRI: refused, not misread
    with pytest.raises(MalformedRecordError):
        run(bgp4mp(4, message))


def test_withdrawn_routes_under_addpath_carry_their_path_identifier():
    message = upd(withdrawn=struct.pack(">I", 5) + bytes([24, 203, 0, 113]))
    (event,) = run(bgp4mp(9, message))
    assert (event.kind, event.path_id) == (EventKind.WITHDRAW, 5)


def test_attributes_that_rfc_7606_treats_as_a_withdrawal_give_withdraw_events():
    # NEXT_HOP is a well-known mandatory attribute (RFC 7606 section 3 (d)): without it the
    # announced routes are treated as withdrawn.
    nlri = bytes([24, 203, 0, 113])
    (event,) = run(bgp4mp(4, upd(attrs=ORIGIN + ASPATH4, nlri=nlri)))
    assert event.kind is EventKind.WITHDRAW
    assert event.reason == "treat-as-withdraw"
    assert event.as_path is None
    assert event.prefix == ipaddress.ip_network("203.0.113.0/24")


def test_two_octet_as_numbers_are_recorded_as_such():
    aspath2 = bytes([0x40, 2, 6, 2, 2]) + struct.pack(">HH", 64496, 64502)
    nlri = bytes([24, 203, 0, 113])
    (event,) = run(bgp4mp(1, upd(attrs=ORIGIN + aspath2 + NEXTHOP, nlri=nlri), as4=False))
    assert event.four_octet_as is False
    assert event.as_path == bytes([2, 2]) + struct.pack(">HH", 64496, 64502)


def test_state_change_becomes_a_peer_state_event():
    body = struct.pack(">II", 64496, 64497) + struct.pack(">HH", 0, 1) + V4_PEER + V4_LOCAL
    body += struct.pack(">HH", 3, 6)
    record = struct.pack(">IHHI", TS, 16, 5, len(body)) + body
    (event,) = run(record)
    assert event.kind is EventKind.PEER_STATE
    assert (event.old_state, event.new_state) == (3, 6)
    assert event.peer == PEER
    assert event.prefix is None


def test_extended_timestamp_adds_microseconds():
    (event,) = run(bgp4mp(4, FIG16_UPDATE, rtype=17, microseconds=250_000))
    assert event.time == WHEN + datetime.timedelta(microseconds=250_000)


def test_records_that_make_no_event_are_counted_by_reason():
    keepalive = MARK + struct.pack(">HB", 19, 4)
    end_of_rib = upd()
    other = struct.pack(">IHHI", TS, 13, 1, 2) + b"xx"
    data = (
        bgp4mp(4, keepalive)
        + bgp4mp(4, end_of_rib)
        + other
        + bgp4mp(4, FIG16_UPDATE)
        + bgp4mp(2, b"")  # BGP4MP subtype 2 is not defined: passed through raw by asnkit
    )
    stats = Stats()
    events = run(data, stats=stats)
    assert len(events) == 1
    assert (stats.records, stats.messages, stats.events, stats.malformed) == (5, 3, 1, 0)
    assert stats.unmapped.snapshot() == {
        "message:keepalive": 1,
        "record:type13/subtype1": 1,
        "record:type16/subtype2": 1,
        "update:no-routes": 1,
    }
    assert isinstance(stats.unmapped, DropCounter)


def test_a_malformed_update_raises_without_stats_and_is_counted_with_them():
    bad = upd(attrs=ORIGIN + ASPATH4 + NEXTHOP, nlri=bytes([40, 1, 2, 3, 4, 5]))
    data = bgp4mp(4, bad) + bgp4mp(4, FIG16_UPDATE)
    with pytest.raises(MalformedRecordError, match="BGP message"):
        run(data)
    stats = Stats()
    events = run(data, stats=stats)
    assert len(events) == 1
    assert stats.malformed == 1
    assert "exceeds 32" in stats.examples[0]


def test_a_tolerant_reading_counts_defective_records_and_goes_on():
    """Row ``mrt.tolerant-bgp4mp``: trailing octets, a cut message and an unreadable header are
    malformed records with a reason, the good records around them still give their events."""
    longer = FIG16_UPDATE + b"\x00"
    cut = FIG16_UPDATE[:12]
    unreadable = struct.pack(">IHHI", TS, 16, 4, 12) + struct.pack(">IIHH", 1, 2, 1, 7)
    data = (
        bgp4mp(4, FIG16_UPDATE)
        + bgp4mp(4, longer)
        + bgp4mp(4, cut)
        + unreadable
        + bgp4mp(4, FIG16_UPDATE)
    )
    with pytest.raises(MrtError, match="disagrees"):
        run(data)
    with pytest.raises(ValueError, match="needs a Stats"):
        run(data, tolerant=True)
    stats = Stats()
    events = run(data, stats=stats, tolerant=True)
    assert [e.kind for e in events] == [EventKind.ANNOUNCE, EventKind.ANNOUNCE]
    assert (stats.records, stats.messages, stats.events, stats.malformed) == (5, 4, 2, 3)
    assert stats.examples[0].startswith("BGP4MP message: BGP message Length")
    assert any("shorter" in e for e in stats.examples)
    assert any("Address Family 7" in e for e in stats.examples)
    assert stats.unmapped.snapshot() == {}


def test_an_mp_attribute_that_cannot_be_read_is_counted_not_guessed():
    short = bytes([0x80, 14, 3]) + struct.pack(">HB", 2, 1)  # shorter than 5 octets
    stats = Stats()
    assert run(bgp4mp(4, upd(attrs=ORIGIN + ASPATH4 + short)), stats=stats) == []
    assert stats.malformed == 1


def test_an_undecoded_address_family_is_counted():
    reach = struct.pack(">HBB", 25, 65, 4) + bytes(4) + b"\x00" + b"\x01\x02"
    attrs = ORIGIN + ASPATH4 + bytes([0x80, 14, len(reach)]) + reach
    stats = Stats()
    assert run(bgp4mp(4, upd(attrs=attrs)), stats=stats) == []
    assert stats.unmapped.snapshot()["undecoded-family:25/65"] == 1


def test_a_truncated_mrt_stream_is_not_recoverable_and_propagates():
    from asnkit.mrt import MrtError

    with pytest.raises(MrtError):
        run(bgp4mp(4, FIG16_UPDATE)[:-3])


@pytest.mark.parametrize(("suffix", "opener"), [(".bz2", bz2.open), (".gz", gzip.open), ("", open)])
def test_iter_updates_reads_plain_gzip_and_bzip2_files_and_names_the_source(
    tmp_path, suffix, opener
):
    target = tmp_path / ("updates.20110318.1915" + suffix)
    with opener(target, "wb") as handle:
        handle.write(bgp4mp(4, FIG16_UPDATE) * 3)
    events = list(iter_updates(target))
    assert len(events) == 3
    assert {e.source for e in events} == {target.name}


def test_iter_updates_is_incremental():
    data = bgp4mp(4, FIG16_UPDATE) * 3 + b"\x00\x01"  # a truncated header after three records
    reader = events_from_stream(io.BytesIO(data), source="x")
    assert next(reader).kind is EventKind.ANNOUNCE  # no error yet: later records are unread


# -- TABLE_DUMP_V2 snapshots (row mrt.events-from-rib) ---------------------------------------------------


def _rec(rtype: int, subtype: int, body: bytes, when: int) -> bytes:
    return struct.pack(">IHHI", when, rtype, subtype, len(body)) + body


def _table(peers: list[tuple[str, int]], when: int) -> bytes:
    body = bytes([198, 51, 100, 4]) + struct.pack(">HH", 0, len(peers))
    for address, asn in peers:
        body += bytes([2]) + bytes([10, 0, 0, 1]) + ipaddress.ip_address(address).packed
        body += struct.pack(">I", asn)
    return _rec(13, 1, body, when)


def _rib(prefix: str, rows: list[tuple[int, list[int]]], when: int) -> bytes:
    net = ipaddress.ip_network(prefix)
    entries = b""
    for peer, path in rows:
        value = bytes([2, len(path)]) + b"".join(struct.pack(">I", a) for a in path)
        attrs = bytes([0x40, 1, 1, 0, 0x40, 2, len(value)]) + value
        entries += struct.pack(">HIH", peer, when - 5, len(attrs)) + attrs
    body = struct.pack(">I", 0) + bytes([net.prefixlen])
    body += net.network_address.packed[: (net.prefixlen + 7) // 8]
    body += struct.pack(">H", len(rows)) + entries
    return _rec(13, 2, body, when)


def _snapshot(when: int, routes: dict[str, list[tuple[int, list[int]]]]) -> bytes:
    peers = [("192.0.2.1", 64501), ("192.0.2.2", 64502)]
    return _table(peers, when) + b"".join(_rib(p, rows, when) for p, rows in routes.items())


def test_rib_snapshot_events():
    from bgpfeed.mrt import events_from_rib, snapshot_withdrawals

    first = _snapshot(
        TS,
        {
            "203.0.113.0/24": [(0, [64501, 64496]), (1, [64502, 64496])],
            "198.51.100.0/24": [(1, [64502, 64497])],
        },
    )
    stats = Stats()
    events = list(events_from_rib(io.BytesIO(first), source="bview", stats=stats))
    assert [(str(e.peer.address), e.peer.asn, str(e.prefix)) for e in events] == [
        ("192.0.2.1", 64501, "203.0.113.0/24"),
        ("192.0.2.2", 64502, "203.0.113.0/24"),
        ("192.0.2.2", 64502, "198.51.100.0/24"),
    ]
    assert {e.kind for e in events} == {EventKind.ANNOUNCE}
    assert {e.time for e in events} == {WHEN}, "the dump time, not the entries' originated time"
    assert events[0].as_path == bytes([2, 2]) + struct.pack(">II", 64501, 64496)
    assert (stats.records, stats.events, stats.malformed) == (3, 3, 0)

    # one hour later peer 2 has lost the second prefix and peer 1 has gone from the first
    later = _snapshot(TS + 3600, {"203.0.113.0/24": [(1, [64502, 64496])]})
    after = list(events_from_rib(io.BytesIO(later), source="bview"))
    gone = list(snapshot_withdrawals(events, after))
    assert [(str(e.peer.address), str(e.prefix)) for e in gone] == [
        ("192.0.2.1", "203.0.113.0/24"),
        ("192.0.2.2", "198.51.100.0/24"),
    ]
    assert {e.kind for e in gone} == {EventKind.WITHDRAW}
    assert {e.reason for e in gone} == {"absent-from-snapshot"}
    assert {e.time for e in gone} == {WHEN + datetime.timedelta(hours=1)}
    assert list(snapshot_withdrawals(after, after)) == []


def test_a_rib_snapshot_with_a_foreign_record_is_counted_or_raises():
    from asnkit.mrt import MrtError

    from bgpfeed.mrt import events_from_rib

    data = _snapshot(TS, {"203.0.113.0/24": [(0, [64501])]}) + _rec(13, 99, b"xx", TS)
    with pytest.raises(MrtError):
        list(events_from_rib(io.BytesIO(data), source="b"))
    stats = Stats()
    assert len(list(events_from_rib(io.BytesIO(data), source="b", stats=stats))) == 1
    assert stats.unmapped.snapshot() == {"rib:skipped": 1}
