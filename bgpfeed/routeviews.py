"""archive discovery, delta polling and checkpoints.

Every object in this module is a placeholder until the milestone named in ROADMAP.md lands. A
stub raises instead of returning a plausible empty value: a protocol library that silently
answers nothing is worse than one that refuses to answer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime
    from typing import Any

    Sink = Any  # placeholder: give it a real type in the milestone that needs it
    Stream = Any  # placeholder: give it a real type in the milestone that needs it

__all__ = [
    "follow",
]


async def follow(collectors: list, since: datetime, sink: Sink) -> Stream:
    """Pending behaviour defined by design.

    Not implemented yet. See the ``routeviews.follow()`` row in ROADMAP.md; this stub
    raises on purpose so nothing downstream mistakes it for working code.
    """
    raise NotImplementedError("follow() is not implemented: design")
