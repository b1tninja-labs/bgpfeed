"""The package namespace is lazy (PEP 562): ``import bgpfeed.budget`` pulls in neither sibling.

PORTFOLIO section 9 item 15 ("RPKI and BGP data, round 2"): rpslkit imports only the budget, so
loading the budget must not import asnkit or pathattr. The check runs in a fresh interpreter with
both siblings importable, so their absence from ``sys.modules`` is the namespace's doing and not a
missing path.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys

import pytest

import bgpfeed

ROOT = pathlib.Path(__file__).resolve().parents[1]

PROBE = """
import sys
import bgpfeed.budget
heavy = sorted(m for m in sys.modules if m.split(".")[0] in ("asnkit", "pathattr"))
others = sorted(m for m in sys.modules if m.startswith("bgpfeed.") and m != "bgpfeed.budget")
import asnkit, pathattr  # importable: the absence above is not a missing path
print(heavy, others)
"""


def test_import_budget_loads_neither_asnkit_nor_pathattr():
    paths = [str(ROOT), str(ROOT.parent / "asnkit"), str(ROOT.parent / "pathattr")]
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(paths))
    result = subprocess.run(  # noqa: S603 - this interpreter, a fixed script
        [sys.executable, "-c", PROBE], capture_output=True, text=True, env=env, check=True
    )
    assert result.stdout.strip() == "[] []"


def test_public_names_resolve_on_first_access():
    assert bgpfeed.iter_updates is bgpfeed.mrt.iter_updates
    assert bgpfeed.policy is bgpfeed.budget.policy
    assert set(bgpfeed.__all__) <= set(dir(bgpfeed))


def test_an_unknown_name_is_an_attribute_error():
    with pytest.raises(AttributeError, match="no_such_name"):
        bgpfeed.no_such_name  # noqa: B018
