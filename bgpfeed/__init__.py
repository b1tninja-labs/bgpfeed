"""bgpfeed -- RIPE RIS and RouteViews, without the C dependency.

A looking glass that only shows your own routers is a status page.

The package namespace is lazy (PEP 562 ``__getattr__``): importing ``bgpfeed`` or
``bgpfeed.budget`` loads no other submodule, so a consumer of the polling budget alone
(rpslkit) never imports asnkit or pathattr, which only :mod:`bgpfeed.mrt` needs.
``from bgpfeed import iter_updates`` still works: the name is resolved on first access.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from . import apps, budget, cli, model, mrt, ris, routeviews, state
    from .budget import policy
    from .mrt import iter_updates
    from .ris import subscribe
    from .routeviews import follow
    from .state import checkpoint, resume

__version__ = "0.1.0"

_SUBMODULES = frozenset({"apps", "budget", "cli", "model", "mrt", "ris", "routeviews", "state"})
# public name -> the submodule that defines it
_NAMES = {
    "policy": "budget",
    "iter_updates": "mrt",
    "subscribe": "ris",
    "follow": "routeviews",
    "checkpoint": "state",
    "resume": "state",
}

__all__ = [
    "__version__",
    "apps",
    "budget",
    "checkpoint",
    "cli",
    "follow",
    "iter_updates",
    "model",
    "mrt",
    "policy",
    "resume",
    "ris",
    "routeviews",
    "state",
    "subscribe",
]


def __getattr__(name: str) -> Any:
    """Import a submodule, or the submodule defining a public name, on first access (PEP 562)."""
    if name in _SUBMODULES:
        value = importlib.import_module(f".{name}", __name__)
    elif name in _NAMES:
        value = getattr(importlib.import_module(f".{_NAMES[name]}", __name__), name)
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
