"""bgpfeed -- RIPE RIS and RouteViews, without the C dependency.

A looking glass that only shows your own routers is a status page.
"""

from __future__ import annotations

from . import apps, budget, cli, model, mrt, ris, routeviews, state
from .budget import policy
from .mrt import iter_updates
from .ris import subscribe
from .routeviews import follow
from .state import checkpoint, resume

__version__ = "0.1.0"

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
