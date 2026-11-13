"""The event model and the gap report (design: no RFC defines either)."""

from __future__ import annotations

import datetime
import ipaddress
import threading

import pytest

from bgpfeed.budget import DropCounter
from bgpfeed.model import Event, EventKind, Gap, GapReport, Peer

UTC = datetime.UTC
T0 = datetime.datetime(2026, 11, 12, 0, 0, tzinfo=UTC)
PEER = Peer(ipaddress.ip_address("192.0.2.1"), 64500)
NET = ipaddress.ip_network("203.0.113.0/24")


def at(minutes: int) -> datetime.datetime:
    return T0 + datetime.timedelta(minutes=minutes)


def test_an_event_needs_utc_aware_time():
    with pytest.raises(ValueError, match="UTC"):
        Event(datetime.datetime(2026, 1, 1), "s", PEER, EventKind.ANNOUNCE, prefix=NET)
    plus_one = datetime.timezone(datetime.timedelta(hours=1))
    with pytest.raises(ValueError, match="UTC"):
        Event(
            datetime.datetime(2026, 1, 1, tzinfo=plus_one),
            "s",
            PEER,
            EventKind.ANNOUNCE,
            prefix=NET,
        )


def test_announce_and_withdraw_need_a_prefix_and_peer_state_needs_states():
    with pytest.raises(ValueError, match="prefix"):
        Event(T0, "s", PEER, EventKind.WITHDRAW)
    with pytest.raises(ValueError, match="old_state"):
        Event(T0, "s", PEER, EventKind.PEER_STATE)
    with pytest.raises(ValueError, match="no prefix"):
        Event(T0, "s", PEER, EventKind.PEER_STATE, prefix=NET, old_state=1, new_state=2)
    ok = Event(T0, "s", PEER, EventKind.PEER_STATE, old_state=1, new_state=6)
    assert ok.new_state == 6


def test_event_kinds_have_stable_text_values():
    assert [k.value for k in EventKind] == ["announce", "withdraw", "peer-state"]


def test_gap_validates_its_interval_and_zone():
    assert Gap("s", at(0), at(15), "x").duration == datetime.timedelta(minutes=15)
    with pytest.raises(ValueError, match="end after"):
        Gap("s", at(15), at(15), "x")
    with pytest.raises(ValueError, match="UTC"):
        Gap("s", datetime.datetime(2026, 1, 1), at(15), "x")


def test_report_clips_sorts_merges_and_counts_each_moment_once():
    gaps = [
        Gap("s", at(60), at(90), "no archive file"),
        Gap("s", at(-30), at(10), "outage"),  # starts before the span
        Gap("s", at(5), at(20), "no archive file"),  # overlaps the previous one
        Gap("s", at(20), at(30), "no archive file"),  # touches: merged
        Gap("s", at(200), at(300), "outside"),  # beyond the span: dropped
    ]
    report = GapReport.build("s", at(0), at(120), gaps)
    assert [(g.start, g.end) for g in report.gaps] == [(at(0), at(30)), (at(60), at(90))]
    assert report.gaps[0].reason == "outage; no archive file"
    assert report.missing == datetime.timedelta(minutes=60)
    assert report.span == datetime.timedelta(minutes=120)
    assert report.coverage == 0.5
    assert not report.complete


def test_report_without_gaps_is_complete_with_full_coverage():
    report = GapReport.build("s", at(0), at(60), [])
    assert report.complete
    assert report.coverage == 1.0
    assert report.missing == datetime.timedelta(0)


def test_report_refuses_a_bad_span():
    with pytest.raises(ValueError, match="end after"):
        GapReport.build("s", at(60), at(0), [])


def test_a_gap_covering_the_whole_span_gives_zero_coverage():
    report = GapReport.build("s", at(0), at(60), [Gap("s", at(-10), at(70), "down")])
    assert report.coverage == 0.0


def test_drop_counter_counts_by_reason_sorted_and_without_resetting():
    counter = DropCounter()
    counter.count("queue-full")
    counter.count("bad-update", 3)
    counter.count("queue-full", 2)
    assert counter.snapshot() == {"bad-update": 3, "queue-full": 3}
    assert list(counter.snapshot()) == ["bad-update", "queue-full"]
    assert counter.total == 6
    assert counter.snapshot() == counter.snapshot()  # reading changes nothing


@pytest.mark.parametrize(("reason", "n"), [("", 1), ("x", 0), ("x", -1), ("x", True), (3, 1)])
def test_drop_counter_refuses_bad_input(reason, n):
    with pytest.raises(ValueError, match="must"):
        DropCounter().count(reason, n)


def test_drop_counter_is_thread_safe():
    counter = DropCounter()

    def work() -> None:
        for _ in range(2000):
            counter.count("x")

    threads = [threading.Thread(target=work) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert counter.snapshot() == {"x": 16000}
