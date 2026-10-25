"""Stage, back up and publish a monthly report pair without silent partial updates."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from wizexpert.governance.dashboard_data import DashboardError, require


def digest(path: Path) -> str | None:
    if not path.exists():
        return None
    require(path.is_file() and not path.is_symlink(), f"Not a regular report/input file: {path}")
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(block)
    return checksum.hexdigest()


def check_unchanged(expected: dict[Path, str | None]) -> None:
    for path, before in expected.items():
        require(
            digest(path) == before,
            f"File changed during generation: {path}. Close editors and rerun.",
        )


def check_recovery(directory: Path, month: str) -> None:
    for journal in (directory / "report-backups").glob(f"{month}-*/pair.monthly-run.json"):
        try:
            record = json.loads(journal.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise DashboardError(
                f"Unreadable monthly recovery record: {journal}. Inspect backups before rerunning."
            ) from exc
        require(
            isinstance(record, dict)
            and record.get("status") in {"preparing", "complete", "rolled-back", "recovered"},
            f"Interrupted publication needs recovery: {journal}. Restore the pair from its backups "
            "or verify both new files, then mark the record status 'recovered' before rerunning.",
        )


@contextmanager
def monthly_lock(directory: Path, month: str):
    lock = directory / f".wiz-monthly-{month}.lock"
    try:
        stream = lock.open("x", encoding="utf-8")
    except FileExistsError as exc:
        raise DashboardError(
            f"Monthly run lock already exists: {lock}. Another run may be active. "
            "After an interrupted run, inspect report-backups "
            "before manually removing a stale lock."
        ) from exc
    try:
        with stream:
            json.dump({"pid": os.getpid(), "host": socket.gethostname(), "month": month}, stream)
        yield
    finally:
        lock.unlink()


def publish_pair(
    staged: tuple[Path, Path],
    targets: tuple[Path, Path],
    expected: dict[Path, str | None],
    month: str,
) -> Path:
    check_unchanged(expected)
    archive_root = targets[0].parent / "report-backups"
    require(
        not archive_root.is_symlink(), f"Backup directory must not be a symlink: {archive_root}"
    )
    archive_root.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    archive = archive_root / f"{month}-{stamp}-{uuid4().hex[:8]}"
    archive.mkdir()
    new_hashes = {target: digest(source) for source, target in zip(staged, targets, strict=False)}
    record = {
        "month": month,
        "status": "preparing",
        "files": [
            {
                "name": target.name,
                "before_sha256": expected[target],
                "after_sha256": new_hashes[target],
            }
            for target in targets
        ],
    }
    journal = archive / "pair.monthly-run.json"

    def record_status(status: str) -> None:
        record["status"] = status
        pending = archive / "pair.monthly-run.json.tmp"
        with pending.open("w", encoding="utf-8") as stream:
            json.dump(record, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(pending, journal)

    record_status("preparing")
    for target in targets:
        if expected[target] is not None:
            backup = archive / target.name
            shutil.copy2(target, backup)
            require(digest(backup) == expected[target], f"Backup verification failed: {target}")
    check_unchanged(expected)
    record_status("publishing")
    published: list[Path] = []
    try:
        for source, target in zip(staged, targets, strict=False):
            check_unchanged({target: expected[target]})
            if expected[target] is None:
                # Exclusive publication must not overwrite a file created by another process.
                os.link(source, target)
            else:
                os.replace(source, target)
            published.append(target)
        check_unchanged(new_hashes)
        record_status("complete")
    except (OSError, DashboardError) as exc:
        recovery_errors = []
        for target in reversed(published):
            try:
                check_unchanged({target: new_hashes[target]})
                if expected[target] is None:
                    target.unlink()
                else:
                    # Keep the verified backup intact even after successful rollback.
                    restore = archive / f"restore-{target.name}"
                    shutil.copy2(archive / target.name, restore)
                    os.replace(restore, target)
            except (OSError, DashboardError) as recovery:
                recovery_errors.append(f"{target}: {recovery}")
        if recovery_errors:
            raise DashboardError(
                f"Publication failed ({exc}); rollback needs manual recovery from {archive}. "
                + "; ".join(recovery_errors)
            ) from exc
        record_status("rolled-back")
        raise DashboardError(
            f"Publication failed; changes from this run were rolled back. "
            f"Close Excel/PowerPoint and retry. Recovery record: {archive}. Cause: {exc}"
        ) from exc
    return archive
