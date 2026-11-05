"""UPDATE_FILE and TABLE_DUMP reading via asnkit.

Every object in this module is a placeholder until the milestone named in ROADMAP.md lands. A
stub raises instead of returning a plausible empty value: a protocol library that silently
answers nothing is worse than one that refuses to answer.
"""

from __future__ import annotations

import pathlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = [
    "iter_updates",
]


def iter_updates(path: pathlib.Path) -> Iterator:
    """Pending behaviour defined by RFC 6396.

    Not implemented yet. See the ``mrt.iter_updates()`` row in ROADMAP.md; this stub
    raises on purpose so nothing downstream mistakes it for working code.
    """
    raise NotImplementedError("iter_updates() is not implemented: RFC 6396")
