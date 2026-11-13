"""resume points and gap accounting per source.

A checkpoint is written atomically and carries a hash of its own contents. ``resume`` returns
the stored checkpoint exactly, returns None only when nothing was ever stored for the source,
and raises ``StateError`` for everything else: a checkpoint that cannot be proved intact is
refused, never guessed at. There is no default location; the caller names the directory.
"""

from __future__ import annotations

import contextlib
import datetime
import hashlib
import json
import os
import re
import tempfile
import threading
from dataclasses import asdict, dataclass
from pathlib import Path

__all__ = [
    "SCHEMA",
    "Checkpoint",
    "StateError",
    "StateStore",
    "checkpoint",
    "resume",
]

SCHEMA = 1
_SHA256 = re.compile(r"[0-9a-f]{64}")
_WRITE_LOCK = threading.Lock()


class StateError(Exception):
    """A checkpoint is unreadable, inconsistent, or refused."""


@dataclass(frozen=True)
class Checkpoint:
    """Where a source was read up to.

    ``position`` names the unit being read (an archive file name or a sequence id), ``offset``
    the byte offset or record index inside it, ``consumed_sha256`` the SHA-256 of everything
    consumed from that unit so far, and ``updated_utc`` a timezone-aware ISO 8601 time.
    """

    source: str
    position: str
    offset: int
    consumed_sha256: str
    updated_utc: str
    schema: int = SCHEMA

    def validate(self) -> None:
        if not isinstance(self.source, str) or not self.source:
            raise StateError("source must be a non-empty string")
        if not isinstance(self.position, str):
            raise StateError("position must be a string")
        if type(self.offset) is not int or self.offset < 0:
            raise StateError("offset must be a non-negative integer")
        if not isinstance(self.consumed_sha256, str) or not _SHA256.fullmatch(self.consumed_sha256):
            raise StateError("consumed_sha256 must be 64 lowercase hex digits")
        if self.schema != SCHEMA:
            raise StateError(f"unsupported checkpoint schema {self.schema!r}")
        _parse_time(self.updated_utc)


def _parse_time(text: object) -> datetime.datetime:
    try:
        when = datetime.datetime.fromisoformat(str(text))
    except ValueError as error:
        raise StateError(f"updated_utc is not ISO 8601: {text!r}") from error
    if when.tzinfo is None:
        raise StateError("updated_utc must carry a timezone")
    return when


def _digest(payload: dict[str, object]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


class StateStore:
    """A directory holding one checkpoint file per source.

    File names are the SHA-256 of the source string, so no source can name a path. Writes are
    serialised within a process; two processes writing one source are not coordinated.
    """

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)

    def _path(self, source: str) -> Path:
        name = hashlib.sha256(source.encode("utf-8", "surrogatepass")).hexdigest()
        return self.directory / f"{name}.json"

    def checkpoint(self, cp: Checkpoint, *, allow_rewind: bool = False) -> None:
        """Store ``cp`` atomically, replacing the previous checkpoint of its source.

        Unless ``allow_rewind``, a checkpoint older than the stored one, or one that moves
        backwards within the same position, raises ``StateError``.
        """
        cp.validate()
        path = self._path(cp.source)
        with _WRITE_LOCK:
            if not allow_rewind:
                previous = self.resume(cp.source)
                if previous is not None:
                    older = _parse_time(cp.updated_utc) < _parse_time(previous.updated_utc)
                    behind = previous.position == cp.position and cp.offset < previous.offset
                    if older or behind:
                        raise StateError("checkpoint would rewind the stored one")
            payload = asdict(cp)
            record = json.dumps({"checkpoint": payload, "sha256": _digest(payload)}, indent=1)
            self.directory.mkdir(parents=True, exist_ok=True)
            handle, temp = tempfile.mkstemp(dir=self.directory, prefix="tmp-", suffix=".part")
            try:
                with os.fdopen(handle, "w", encoding="ascii") as out:
                    out.write(record)
                    out.flush()
                    os.fsync(out.fileno())
                os.replace(temp, path)
            except BaseException:
                with contextlib.suppress(OSError):
                    os.unlink(temp)
                raise
            self._sync_directory()

    def _sync_directory(self) -> None:
        # Best effort: POSIX can fsync a directory; Windows cannot open one, so the rename
        # is atomic there but its durability across power loss is the filesystem's.
        try:
            fd = os.open(self.directory, os.O_RDONLY)
        except OSError:
            return
        try:
            with contextlib.suppress(OSError):
                os.fsync(fd)
        finally:
            os.close(fd)

    def resume(self, source: str) -> Checkpoint | None:
        """The stored checkpoint of ``source``, or None if none was ever stored.

        Any other problem (unreadable, truncated, bad hash, wrong schema or source) raises
        ``StateError``.
        """
        path = self._path(source)
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            return None
        except OSError as error:
            raise StateError(f"cannot read checkpoint: {error}") from error
        try:
            record = json.loads(raw.decode("ascii"))
            payload = record["checkpoint"]
            stored = record["sha256"]
            if not isinstance(payload, dict) or set(record) != {"checkpoint", "sha256"}:
                raise TypeError("shape")
        except (ValueError, KeyError, TypeError) as error:
            raise StateError("checkpoint file is corrupt") from error
        if stored != _digest(payload):
            raise StateError("checkpoint hash mismatch")
        try:
            cp = Checkpoint(**payload)
        except TypeError as error:
            raise StateError("checkpoint fields are wrong") from error
        cp.validate()
        if cp.source != source:
            raise StateError("checkpoint belongs to a different source")
        return cp


def checkpoint(store: StateStore, cp: Checkpoint, *, allow_rewind: bool = False) -> None:
    """Store ``cp`` in ``store``; behaviour defined by design: a stored checkpoint resumes
    exactly, or refuses. See ``StateStore.checkpoint``.
    """
    store.checkpoint(cp, allow_rewind=allow_rewind)


def resume(store: StateStore, source: str) -> Checkpoint | None:
    """Load the checkpoint of ``source``; behaviour defined by design: a stored checkpoint
    resumes exactly, or refuses. See ``StateStore.resume``.
    """
    return store.resume(source)
