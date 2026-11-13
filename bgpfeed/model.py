"""The event model every feed produces, and the gap report that says what a feed did not see.

An :class:`Event` is one routing fact about one prefix from one peer at one time: announced,
withdrawn, or a change of the peering session's state. Sources (an MRT updates archive today, a
live stream later) are mapped onto it, so a consumer is written once. Whether bmpkit imports this
module or keeps its own is an open owner decision (ROADMAP.md section 5): it is kept free of
anything specific to MRT or to a collector so that it can be shared.

Design decisions, stated because no RFC makes them:

* times are timezone-aware UTC, with the microseconds of MRT's Extended Timestamp when the
  source has them;
* an UPDATE that announces several prefixes is several events that share their attributes, and
  an attribute set that RFC 7606 treats as a withdrawal produces WITHDRAW events carrying a
  ``reason``, not ANNOUNCE events;
* the AS_PATH stays as the raw attribute value octets with the width of the AS numbers recorded,
  because decoding it is pathattr's and asnkit's job (``asnkit.rib.origin_of`` takes these two
  fields directly);
* a :class:`GapReport` lists the intervals of a span for which a source delivered nothing and
  the reason; a feed that cannot say what it missed cannot be trusted for what it reports.
"""

from __future__ import annotations

import datetime
import enum
import ipaddress
from dataclasses import dataclass

__all__ = [
    "Event",
    "EventKind",
    "Gap",
    "GapReport",
    "Network",
    "Peer",
    "RibView",
    "SessionState",
]

Address = ipaddress.IPv4Address | ipaddress.IPv6Address
Network = ipaddress.IPv4Network | ipaddress.IPv6Network


class EventKind(enum.StrEnum):
    """What an :class:`Event` reports."""

    ANNOUNCE = "announce"
    WITHDRAW = "withdraw"
    PEER_STATE = "peer-state"


class RibView(enum.StrEnum):
    """Which RIB a BMP route came from (RFC 7854 section 2, RFC 8671 section 4, RFC 9069 section 4).

    The pre- and post-policy forms of Adj-RIB-In are the L flag, Adj-RIB-Out is the O flag (and
    has both forms too), and Loc-RIB is peer type 3. MRT events carry no view (``None``).
    """

    ADJ_RIB_IN_PRE = "adj-rib-in-pre"
    ADJ_RIB_IN_POST = "adj-rib-in-post"
    ADJ_RIB_OUT_PRE = "adj-rib-out-pre"
    ADJ_RIB_OUT_POST = "adj-rib-out-post"
    LOC_RIB = "loc-rib"


class SessionState(enum.StrEnum):
    """A peering session going up or down, for a source that has no BGP FSM state numbers."""

    UP = "up"
    DOWN = "down"


@dataclass(frozen=True)
class Peer:
    """The BGP speaker a route or a state change was seen from.

    ``address`` is ``None`` for a peer that has none, the Loc-RIB Instance Peer of RFC 9069
    section 5.1. ``distinguisher`` (RFC 7854 section 4.2) and ``bgp_id`` are set by BMP and
    left ``None`` by MRT.
    """

    address: Address | None
    asn: int
    distinguisher: bytes | None = None
    bgp_id: ipaddress.IPv4Address | None = None


@dataclass(frozen=True)
class Event:
    """One routing fact (see the module docstring).

    ``source`` names where it was read (a collector or a file). For ANNOUNCE and WITHDRAW,
    ``prefix`` is set; ``path_id`` is the RFC 7911 Path Identifier when the source used ADD-PATH;
    ``as_path`` is the raw AS_PATH attribute value of an announcement, ``None`` when the UPDATE had
    none, with ``four_octet_as`` giving the width of its AS numbers. For PEER_STATE, ``old_state``
    and ``new_state`` are the BGP FSM state numbers of RFC 6396 section 4.4.1; a source without
    them (BMP Peer Up and Peer Down) sets ``session`` instead, and ``reason`` then says why a
    session went down. ``reason`` is otherwise empty except for a withdrawal that was not an
    explicit one, such as ``"treat-as-withdraw"``.

    ``time`` is ``None`` when the source gave none (a BMP per-peer timestamp of zero, RFC 7854
    section 4.2); otherwise it is aware UTC. ``view`` is the RIB a BMP route came from, ``None``
    for MRT.
    """

    time: datetime.datetime | None
    source: str
    peer: Peer
    kind: EventKind
    prefix: Network | None = None
    path_id: int | None = None
    as_path: bytes | None = None
    four_octet_as: bool = True
    old_state: int | None = None
    new_state: int | None = None
    reason: str = ""
    view: RibView | None = None
    session: SessionState | None = None

    def __post_init__(self) -> None:
        if self.time is not None and (
            self.time.tzinfo is None or self.time.utcoffset() != datetime.timedelta(0)
        ):
            raise ValueError("an Event time must be timezone-aware UTC, or None")
        if self.kind is EventKind.PEER_STATE:
            numbered = self.old_state is not None and self.new_state is not None
            if not numbered and self.session is None:
                raise ValueError("a PEER_STATE event needs old_state and new_state, or session")
            if (self.old_state is None) != (self.new_state is None):
                raise ValueError("old_state and new_state are given together")
            if self.prefix is not None:
                raise ValueError("a PEER_STATE event has no prefix")
        elif self.prefix is None:
            raise ValueError(f"a {self.kind.value} event needs a prefix")


@dataclass(frozen=True)
class Gap:
    """An interval ``[start, end)`` for which ``source`` delivered nothing, and why."""

    source: str
    start: datetime.datetime
    end: datetime.datetime
    reason: str

    def __post_init__(self) -> None:
        for moment in (self.start, self.end):
            if moment.tzinfo is None or moment.utcoffset() != datetime.timedelta(0):
                raise ValueError("a Gap needs timezone-aware UTC times")
        if self.end <= self.start:
            raise ValueError("a Gap must end after it starts")

    @property
    def duration(self) -> datetime.timedelta:
        return self.end - self.start


@dataclass(frozen=True)
class GapReport:
    """What a source missed within ``[start, end)``.

    Build it with :meth:`build`, which clips the gaps to the span, sorts them and merges the
    ones that touch or overlap, so ``missing`` never counts a moment twice. ``gaps`` empty means
    the source claims no gap, not that nothing was missed: the caller chose the evidence.
    """

    source: str
    start: datetime.datetime
    end: datetime.datetime
    gaps: tuple[Gap, ...]

    @classmethod
    def build(
        cls,
        source: str,
        start: datetime.datetime,
        end: datetime.datetime,
        gaps: list[Gap] | tuple[Gap, ...],
    ) -> GapReport:
        """Validate the span and normalise ``gaps`` (clip, sort, merge touching ones)."""
        probe = Gap(source, start, end, "span")  # validates both ends and their order
        del probe
        clipped = []
        for gap in gaps:
            low, high = max(gap.start, start), min(gap.end, end)
            if low < high:
                clipped.append(Gap(gap.source, low, high, gap.reason))
        clipped.sort(key=lambda g: (g.start, g.end))
        merged: list[Gap] = []
        for gap in clipped:
            if merged and gap.start <= merged[-1].end:
                last = merged[-1]
                reason = (
                    last.reason
                    if gap.reason in last.reason.split("; ")
                    else (f"{last.reason}; {gap.reason}")
                )
                merged[-1] = Gap(last.source, last.start, max(last.end, gap.end), reason)
            else:
                merged.append(gap)
        return cls(source, start, end, tuple(merged))

    @property
    def span(self) -> datetime.timedelta:
        return self.end - self.start

    @property
    def missing(self) -> datetime.timedelta:
        """Total time inside the span covered by a gap."""
        return sum((g.duration for g in self.gaps), datetime.timedelta(0))

    @property
    def coverage(self) -> float:
        """The fraction of the span not covered by a gap, between 0.0 and 1.0."""
        return 1.0 - self.missing / self.span

    @property
    def complete(self) -> bool:
        return not self.gaps
