"""The two-phase commit state machine, and its on-disk staging store.

Why this exists at all: a single `deliver(path)` call answers "does this hold
up right now". Between that answer and the moment the file lands in the delivery
folder, an agent can edit it again — and nothing in the old design noticed. The
staging record is what makes the gap observable: the hash taken at stage time is
compared again at commit time.

State transitions, and nothing else is allowed:

    STAGED   --verify(ok)--------> VERIFIED --commit(hash ok)--> COMMITTED
       |                              |
       |--verify(fail)--> FAILED <----|--commit(hash differs)--> FAILED
       |--ttl----------> EXPIRED

`VERIFIED` cannot be skipped: commit refuses anything else. That is the whole
point — a caller cannot go straight from "I copied the file" to "it is
delivered".

Honest limit, stated here because it belongs with the code: this is a protocol
discipline, not a security boundary. An agent can stage the same file again
after editing it and get a clean VERIFIED. The store records every attempt
(`attempts`, `history`) so that re-entry is visible in the audit rather than
invisible.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from .models import StageState

DEFAULT_TTL_DAYS = 7
STATE_FILE = "state.json"
FILES_DIR = "files"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def digest(path: str | os.PathLike) -> str:
    sha = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 256), b""):
            sha.update(block)
    return sha.hexdigest()


@dataclass
class StagedFile:
    name: str            # basename, preserved
    rel: str             # path inside the staging files/ directory
    bytes: int
    sha256: str
    source: str


@dataclass
class StagingRecord:
    staging_id: str
    state: str
    profile: str
    created_at: str
    updated_at: str
    files: list[StagedFile] = field(default_factory=list)
    verdict: str | None = None
    checks: list[dict] = field(default_factory=list)
    rules: list[dict] = field(default_factory=list)
    counts: dict = field(default_factory=dict)
    attempts: int = 0
    committed_to: str | None = None
    reason: str | None = None
    code: str | None = None
    history: list[dict] = field(default_factory=list)

    # -------------------------------------------------------------- helpers

    @property
    def is_expired(self) -> bool:
        try:
            created = datetime.fromisoformat(self.created_at)
        except ValueError:
            return False
        return datetime.now(timezone.utc) - created > timedelta(days=DEFAULT_TTL_DAYS)

    @property
    def blocking(self) -> list[dict]:
        return [r for r in self.rules if not r.get("ok") and r.get("severity") == "error"]

    def touch(self, note: str) -> None:
        self.updated_at = _now()
        self.history.append({"at": self.updated_at, "note": note})

    def as_dict(self) -> dict:
        data = asdict(self)
        data["is_expired"] = self.is_expired
        return data


class StagingStore:
    """Records live under `root/<staging_id>/`, one folder each.

    The root is a temporary directory by default so a staging area never
    outlives a reboot unnoticed, and so nothing is written next to the user's
    drawings until commit says so.
    """

    def __init__(self, root: str | os.PathLike | None = None) -> None:
        if root is None:
            root = os.path.join(tempfile.gettempdir(), "cad-deliver-staging")
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------ paths

    def folder(self, staging_id: str) -> Path:
        return self.root / staging_id

    def files_dir(self, staging_id: str) -> Path:
        return self.folder(staging_id) / FILES_DIR

    # ------------------------------------------------------------ lifecycle

    def create(
        self,
        sources: Iterable[str | os.PathLike],
        profile: str,
        logical_names: Iterable[str] | None = None,
    ) -> StagingRecord:
        """Copy the sources into a new staging folder and hash them.

        Copying is deliberate: the caller may keep editing its own working copy,
        and commit must compare against what was *staged*, not against whatever
        is on disk later.
        """
        staging_id = uuid.uuid4().hex[:16]
        folder = self.folder(staging_id)
        files_dir = self.files_dir(staging_id)
        files_dir.mkdir(parents=True, exist_ok=False)

        names = list(logical_names) if logical_names is not None else None
        staged: list[StagedFile] = []
        for index, source in enumerate(sources):
            src = Path(source)
            if not src.is_file():
                raise FileNotFoundError(f"not a file: {src}")
            name = names[index] if names else src.name
            rel = name
            target = files_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
            staged.append(
                StagedFile(
                    name=name,
                    rel=rel,
                    bytes=target.stat().st_size,
                    sha256=digest(target),
                    source=str(src),
                )
            )

        now = _now()
        record = StagingRecord(
            staging_id=staging_id,
            state=StageState.STAGED.value,
            profile=profile,
            created_at=now,
            updated_at=now,
            files=staged,
        )
        record.touch(f"staged {len(staged)} file(s) with profile {profile}")
        self.save(record)
        return record

    def load(self, staging_id: str) -> StagingRecord:
        path = self.folder(staging_id) / STATE_FILE
        if not path.is_file():
            raise KeyError(f"unknown staging id: {staging_id}")
        data = json.loads(path.read_text(encoding="utf-8"))
        data.pop("is_expired", None)
        data["files"] = [StagedFile(**item) for item in data.get("files", [])]
        return StagingRecord(**data)

    def save(self, record: StagingRecord) -> None:
        folder = self.folder(record.staging_id)
        folder.mkdir(parents=True, exist_ok=True)
        payload = asdict(record)
        tmp = folder / (STATE_FILE + ".partial")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, folder / STATE_FILE)   # atomic within one folder

    # ------------------------------------------------------------ integrity

    def verify_hashes(self, record: StagingRecord) -> list[str]:
        """Return the names whose staged bytes no longer match the record."""
        changed = []
        for item in record.files:
            path = self.files_dir(record.staging_id) / item.rel
            if not path.is_file():
                changed.append(item.name)
                continue
            if digest(path) != item.sha256:
                changed.append(item.name)
        return changed

    # ------------------------------------------------------------ housekeeping

    def expire_old(self) -> list[str]:
        """Mark records past the TTL as EXPIRED. Their audit trail stays."""
        expired = []
        for folder in self.root.iterdir():
            if not folder.is_dir():
                continue
            state = folder / STATE_FILE
            if not state.is_file():
                continue
            try:
                record = self.load(folder.name)
            except (KeyError, json.JSONDecodeError, TypeError):
                continue
            if record.state in (StageState.COMMITTED.value, StageState.EXPIRED.value):
                continue
            if record.is_expired:
                record.state = StageState.EXPIRED.value
                record.touch("expired: past TTL")
                self.save(record)
                expired.append(record.staging_id)
        return expired

    def audit(self, staging_id: str) -> dict:
        record = self.load(staging_id)
        return record.as_dict()

    def purge(self, staging_id: str) -> None:
        shutil.rmtree(self.folder(staging_id), ignore_errors=True)