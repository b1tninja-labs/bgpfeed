#!/usr/bin/env python3
"""Write the resolved environment to a requirements file for auditing.

A script rather than shell redirection so the CI step behaves the same on a self-hosted
runner, and so an empty freeze fails loudly instead of auditing nothing.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys


def main():
    if len(sys.argv) != 2:
        print("usage: write_freeze.py PATH")
        return 2
    frozen = subprocess.run(
        [sys.executable, "-m", "pip", "freeze", "--all"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    # Drop the project's own entry. pip freeze records the local tree as an editable or VCS reference,
    # and pip-audit then installs that URL to audit it: on a private repository the anonymous clone
    # fails, and the audit reports a build error instead of advisories. A project is not one of its own
    # dependencies, and only third-party distributions carry advisories worth resolving.
    lines = []
    dropped = 0
    for line in frozen.splitlines():
        if not line.strip():
            continue
        if line.startswith("-e") or "git+" in line or "file://" in line:
            dropped += 1
            continue
        lines.append(line)
    pathlib.Path(sys.argv[1]).write_text(chr(10).join(lines) + chr(10), encoding="utf-8")
    print(
        f"{len(lines)} distributions written to {sys.argv[1]} ({dropped} self-reference(s) excluded)"
    )
    return 0 if lines else 1


if __name__ == "__main__":
    sys.exit(main())
