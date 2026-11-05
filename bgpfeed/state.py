"""resume points and gap accounting per source.

Every object in this module is a placeholder until the milestone named in ROADMAP.md lands. A
stub raises instead of returning a plausible empty value: a protocol library that silently
answers nothing is worse than one that refuses to answer.
"""

from __future__ import annotations

__all__ = [
    "checkpoint",
    "resume",
]


def checkpoint(source: str, position: object) -> None:
    """Pending behaviour defined by design.

    Not implemented yet. See the ``state.checkpoint()`` row in ROADMAP.md; this stub
    raises on purpose so nothing downstream mistakes it for working code.
    """
    raise NotImplementedError("checkpoint() is not implemented: design")


def resume(source: str) -> object:
    """Pending behaviour defined by design.

    Not implemented yet. See the ``state.resume()`` row in ROADMAP.md; this stub raises
    on purpose so nothing downstream mistakes it for working code.
    """
    raise NotImplementedError("resume() is not implemented: design")
