"""Command line entry point for bgpfeed.

The CLI is how most people meet a protocol library, so it is part of the public surface and
gets the same typing and testing discipline as the rest of the package.
"""

from __future__ import annotations

import argparse
import sys

USAGE = """\
Examples:
  bgpfeed ris --view rrc00 --collector rrc00-collector-1 --out events.ndjson"""


def build_parser():
    return argparse.ArgumentParser(
        prog="bgpfeed",
        description="Live and archive upstream feeds: RIPE RIS websocket streaming and RouteViews BGP2K MRT deltas, with checkpointing and a normalised event model shared with bmpkit",
        epilog=USAGE,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )


def main(argv=None):
    """Parse arguments, then refuse to pretend the protocol works.

    Exiting non-zero is the correct behaviour for a shell. A CLI that printed a friendly
    banner and exited 0 would be indistinguishable from one that actually did something.
    """
    parser = build_parser()
    parser.parse_args(argv)
    parser.print_usage(sys.stderr)
    print("bgpfeed: no protocol behaviour is implemented yet; see ROADMAP.md", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
