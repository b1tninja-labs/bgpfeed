"""MRT updates archives mapped onto events, through asnkit's MRT codec and pathattr's BGP codec.

The MRT codec is asnkit's (``asnkit.mrt``, owner decision 2026-11-13: one codec to fix when an
erratum lands); the BGP message and attribute decoding is pathattr's. This module only maps:
each BGP4MP record of RFC 6396 section 4.4 becomes zero or more :class:`bgpfeed.model.Event`.

* BGP4MP_STATE_CHANGE(_AS4) becomes a PEER_STATE event;
* BGP4MP_MESSAGE(_AS4, _LOCAL, _ADDPATH) holds one BGP message. An UPDATE gives a WITHDRAW event
  per withdrawn prefix (IPv4 Withdrawn Routes and MP_UNREACH_NLRI) and an ANNOUNCE event per
  announced prefix (IPv4 NLRI and MP_REACH_NLRI for IPv4 and IPv6, unicast and multicast), each
  with the AS_PATH of the UPDATE. When RFC 7606 section 3 says the attributes are to be treated
  as a withdrawal, the announced prefixes become WITHDRAW events with the reason
  ``"treat-as-withdraw"``. An UPDATE that needs the AFI/SAFI disabled or the session reset
  cannot be trusted and is counted as malformed;
* every record that produces no event is counted in :attr:`Stats.unmapped` by reason, and a
  malformed record raises :class:`MalformedRecordError` unless the caller passes a :class:`Stats`, in
  which case it is counted and the reading continues. Nothing is dropped without a trace.

RFC 8050 says nothing of which address families the ``_ADDPATH`` subtypes cover, so every
unicast and multicast IPv4 and IPv6 NLRI list inside such a message is read with Path
Identifiers (RFC 7911 section 3). Messages are read with the 65535-octet ceiling of RFC 8654
because the archive does not say what the peer negotiated.
"""

from __future__ import annotations

import datetime
import pathlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from asnkit import mrt as asnkit_mrt
from asnkit.history import open_dump
from pathattr import message as bgp
from pathattr import nlri as bgp_nlri
from pathattr.attribute import Action, AttrType
from pathattr.errors import BgpError

from .budget import DropCounter
from .model import Event, EventKind, Network, Peer

if TYPE_CHECKING:
    from collections.abc import Iterator
    from typing import IO

__all__ = [
    "MalformedRecordError",
    "Stats",
    "events_from_stream",
    "iter_updates",
]

_ALL_FAMILIES = frozenset({(1, 1), (1, 2), (2, 1), (2, 2)})
_MAX_MESSAGE = 65535
_EXAMPLES = 10


class MalformedRecordError(ValueError):
    """An MRT record or the BGP message inside it could not be read."""


@dataclass
class Stats:
    """What a reading did, so that the events are never the whole story.

    ``records`` counts MRT records read, ``messages`` the BGP messages found in them and
    ``events`` the events produced. ``unmapped`` counts, by reason, the records and messages that
    produced no event (a KEEPALIVE, an End-of-RIB UPDATE, an unknown record type); ``malformed``
    counts the ones that could not be read and ``examples`` keeps the first ten reasons.
    """

    records: int = 0
    messages: int = 0
    events: int = 0
    malformed: int = 0
    unmapped: DropCounter = field(default_factory=DropCounter)
    examples: list[str] = field(default_factory=list)


def _moment(timestamp: int, microseconds: int | None) -> datetime.datetime:
    base = datetime.datetime.fromtimestamp(timestamp, datetime.UTC)
    return base + datetime.timedelta(microseconds=microseconds or 0)


def _bad(stats: Stats | None, reason: str) -> None:
    if stats is None:
        raise MalformedRecordError(reason)
    stats.malformed += 1
    if len(stats.examples) < _EXAMPLES:
        stats.examples.append(reason)


def _update_events(
    record: asnkit_mrt.Bgp4mpMessage,
    update: bgp.Update,
    source: str,
    stats: Stats | None,
) -> list[Event]:
    when = _moment(record.timestamp, record.microseconds)
    peer = Peer(record.peer_ip, record.peer_as)
    if update.action >= Action.AFI_SAFI_DISABLE:
        _bad(stats, f"UPDATE needs {update.action.name}; not trusted")
        return []
    treat = update.action == Action.TREAT_AS_WITHDRAW
    as_path = next((a.value for a in update.attributes if a.type_code == AttrType.AS_PATH), None)
    events: list[Event] = []

    def announce(prefix: Network, path_id: int | None) -> None:
        kind = EventKind.WITHDRAW if treat else EventKind.ANNOUNCE
        events.append(
            Event(
                when,
                source,
                peer,
                kind,
                prefix=prefix,
                path_id=path_id,
                as_path=None if treat else as_path,
                four_octet_as=record.as4,
                reason="treat-as-withdraw" if treat else "",
            )
        )

    def withdraw(prefix: Network, path_id: int | None) -> None:
        events.append(
            Event(
                when,
                source,
                peer,
                EventKind.WITHDRAW,
                prefix=prefix,
                path_id=path_id,
                four_octet_as=record.as4,
            )
        )

    for index, prefix in enumerate(update.withdrawn):
        withdraw(prefix, update.withdrawn_path_ids[index] if update.withdrawn_path_ids else None)
    for index, prefix in enumerate(update.nlri):
        announce(prefix, update.nlri_path_ids[index] if update.nlri_path_ids else None)
    for attribute in update.attributes:
        family_path = _ALL_FAMILIES if record.addpath else frozenset()
        try:
            if attribute.type_code == AttrType.MP_REACH_NLRI:
                reach = bgp_nlri.parse_mp_reach(attribute.value, family_path)
                if reach.nlri is None:
                    _count(stats, f"undecoded-family:{reach.afi}/{reach.safi}")
                for entry in reach.nlri or ():
                    announce(entry.prefix, entry.path_id)
            elif attribute.type_code == AttrType.MP_UNREACH_NLRI:
                unreach = bgp_nlri.parse_mp_unreach(attribute.value, family_path)
                if unreach.nlri is None:
                    _count(stats, f"undecoded-family:{unreach.afi}/{unreach.safi}")
                for entry in unreach.nlri or ():
                    withdraw(entry.prefix, entry.path_id)
        except bgp_nlri.MpError as error:
            _bad(stats, f"multiprotocol attribute: {error}")
            return []
    return events


def _count(stats: Stats | None, reason: str) -> None:
    if stats is not None:
        stats.unmapped.count(reason)


def events_from_stream(
    stream: IO[bytes], *, source: str, stats: Stats | None = None
) -> Iterator[Event]:
    """Yield the events of an MRT updates stream (see the module docstring).

    ``source`` is recorded on every event. Framing errors in the MRT stream itself
    (``asnkit.mrt.MrtError``) are not recoverable and propagate: after a bad length the next
    record cannot be found. A BGP4MP record that is malformed inside raises
    :class:`MalformedRecordError`, or is counted in ``stats`` and skipped when one is given.
    """
    for item in asnkit_mrt.iter_bgp4mp(stream):
        if stats is not None:
            stats.records += 1
        if isinstance(item, asnkit_mrt.MrtRecord):
            _count(stats, f"record:type{item.type}/subtype{item.subtype}")
            continue
        if isinstance(item, asnkit_mrt.Bgp4mpStateChange):
            event = Event(
                _moment(item.timestamp, item.microseconds),
                source,
                Peer(item.peer_ip, item.peer_as),
                EventKind.PEER_STATE,
                old_state=item.old_state,
                new_state=item.new_state,
            )
            if stats is not None:
                stats.events += 1
            yield event
            continue
        if stats is not None:
            stats.messages += 1
        try:
            decoded = bgp.decode(
                item.message,
                max_length=_MAX_MESSAGE,
                four_octet_as=item.as4,
                add_path=_ALL_FAMILIES if item.addpath else frozenset(),
            )
        except BgpError as error:
            _bad(stats, f"BGP message: {error}")
            continue
        if not isinstance(decoded, bgp.Update):
            _count(stats, f"message:{type(decoded).__name__.lower()}")
            continue
        produced = _update_events(item, decoded, source, stats)
        if not produced:
            if decoded.action < Action.AFI_SAFI_DISABLE:
                _count(stats, "update:no-routes")
            continue
        if stats is not None:
            stats.events += len(produced)
        yield from produced


def iter_updates(path: pathlib.Path, *, stats: Stats | None = None) -> Iterator[Event]:
    """Yield the events of the MRT updates file at ``path`` (RFC 6396 section 4.4, RFC 8050).

    The file may be plain, ``.gz`` or ``.bz2`` (asnkit's ``open_dump`` chooses by suffix). The
    events carry the file name as their ``source``; use :func:`events_from_stream` to name a
    collector. The file is read incrementally and closed when the iterator is exhausted or
    closed. See the module docstring for what is mapped and how failures are accounted for.
    """
    path = pathlib.Path(path)
    with open_dump(path) as stream:
        yield from events_from_stream(stream, source=path.name, stats=stats)
