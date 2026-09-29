"""Private, operator-recorded workflow progress; never cloud authorization."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO
from pathlib import Path

STAGES = (
    "Collect and reconcile evidence",
    "Explain and analyze",
    "Prepare report and stakeholder email",
    "Obtain decisions and approval",
    "Prepare remediation",
    "Execute approved changes",
    "Verify results",
    "Report outcomes and close",
)
GATES = (
    ("issues", "graph", "field-coverage", "pagination", "reconciliation"),
    ("analysis", "options"),
    ("report", "email-draft", "ticket"),
    ("decisions", "authorization"),
    ("prechecks", "dependencies", "recovery", "plan"),
    ("execution",),
    ("technical-validation", "owner-validation", "wiz-reassessment"),
    ("closure",),
)
STATUSES = ("in_progress", "blocked", "complete")
ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 2_000_000


def _text(value: object, label: str, *, optional: bool = False) -> str:
    if not isinstance(value, str) or len(value) > 2000 or (
        not optional and not value.strip()
    ) or any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in value):
        raise ValueError(f"{label} must be single-line text (maximum 2000 characters).")
    return value


def _path(value: str | Path) -> Path:
    path = Path(value)
    if not path.is_absolute() or path.is_symlink():
        raise ValueError("Tracker must be an absolute, non-symlink path.")
    path = path.resolve()
    if path.is_relative_to(ROOT) or path.suffix.lower() != ".json":
        raise ValueError("Tracker must be a .json file outside the repository.")
    return path


@dataclass(frozen=True)
class Event:
    at: str
    stage: int
    status: str
    summary: str
    next_action: str
    blocker: str
    evidence: dict[str, str]


@dataclass(frozen=True)
class Tracker:
    finding_id: str
    control_id: str
    scope: str
    events: tuple[Event, ...]

    @property
    def current_stage(self) -> int:
        last = self.events[-1]
        return min(8, last.stage + 1) if last.status == "complete" else last.stage

    @property
    def status(self) -> str:
        last = self.events[-1]
        return "in_progress" if last.status == "complete" and last.stage < 8 else last.status

    def stage_status(self, stage: int) -> str:
        if stage < self.current_stage:
            return "complete"
        return self.status if stage == self.current_stage else "not_started"

    def cover_text(self) -> str:
        return (
            f"Workflow: Stage {self.current_stage}/8 - {STAGES[self.current_stage - 1]}\n"
            f"Status: {self.status.replace('_', ' ')} | Updated: {self.events[-1].at}\n"
            + ("Draft - evidence review incomplete. " if self.current_stage < 3 else "")
            + "Operator-recorded snapshot; not proof of remediation or Wiz closure."
        )

    def display(self) -> str:
        last = self.events[-1]
        rows = [
            f"Finding: {self.finding_id} | Control: {self.control_id}",
            f"Scope: {self.scope}",
            self.cover_text(),
            "",
            *(f"{n}. {title}: {self.stage_status(n).replace('_', ' ')}"
              for n, title in enumerate(STAGES, 1)),
            "",
            f"Latest recorded update (stage {last.stage}): {last.summary}",
            f"Blocker: {last.blocker or 'None recorded'}",
            f"Next action: {last.next_action}",
            "Completion references required: " + ", ".join(GATES[self.current_stage - 1]),
            "ServiceNow remains authoritative for approvals and closure.",
        ]
        return "\n".join(rows)


def _validate(tracker: Tracker) -> None:
    for name in ("finding_id", "control_id", "scope"):
        _text(getattr(tracker, name), name)
    if not tracker.events:
        raise ValueError("Tracker requires an initial event.")
    expected_stage = 1
    previous_time = None
    finished = False
    for index, event in enumerate(tracker.events):
        if type(event.stage) is not int or event.stage != expected_stage or finished:
            raise ValueError("Tracker history skips stages or follows completed closure.")
        if event.status not in STATUSES:
            raise ValueError("Unsupported tracker status.")
        if index == 0 and event.status != "in_progress":
            raise ValueError("Tracker must start with stage 1 in progress.")
        try:
            timestamp = datetime.fromisoformat(event.at)
        except (TypeError, ValueError):
            raise ValueError("Tracker timestamp must be valid UTC ISO text.") from None
        if timestamp.utcoffset() is None or timestamp.utcoffset().total_seconds() != 0:
            raise ValueError("Tracker timestamps must use UTC.")
        if previous_time is not None and timestamp < previous_time:
            raise ValueError("Tracker timestamps are out of order.")
        previous_time = timestamp
        _text(event.summary, "Summary")
        _text(event.next_action, "Next action")
        _text(event.blocker, "Blocker", optional=True)
        if (event.status == "blocked") != bool(event.blocker.strip()):
            raise ValueError("Blocked status requires a blocker; other statuses cannot retain one.")
        if not isinstance(event.evidence, dict) or any(
            key not in GATES[event.stage - 1] for key in event.evidence
        ):
            raise ValueError("Evidence keys must belong to the recorded stage's gates.")
        for reference in event.evidence.values():
            _text(reference, "Evidence reference")
        if event.status == "complete":
            if set(event.evidence) != set(GATES[event.stage - 1]):
                raise ValueError(
                    "Completion requires reviewed references for: "
                    + ", ".join(GATES[event.stage - 1])
                )
            finished = event.stage == 8
            expected_stage = min(8, event.stage + 1)


def _object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Tracker contains duplicate JSON keys.")
        result[key] = value
    return result


def _decode(content: bytes) -> Tracker:
    if len(content) > MAX_BYTES:
        raise ValueError("Tracker exceeds the size limit.")
    try:
        data = json.loads(content.decode("utf-8"), object_pairs_hook=_object)
    except (UnicodeError, json.JSONDecodeError):
        raise ValueError("Tracker is not valid UTF-8 JSON.") from None
    if not isinstance(data, dict) or set(data) != {
        "version", "finding_id", "control_id", "scope", "events",
    } or type(data["version"]) is not int or data["version"] != 1:
        raise ValueError("Unsupported tracker schema.")
    if not isinstance(data["events"], list):
        raise ValueError("Tracker events must be a list.")
    events = []
    for row in data["events"]:
        if not isinstance(row, dict) or set(row) != set(Event.__dataclass_fields__):
            raise ValueError("Unsupported tracker event schema.")
        events.append(Event(**row))
    tracker = Tracker(data["finding_id"], data["control_id"], data["scope"], tuple(events))
    _validate(tracker)
    return tracker


def load_tracker(path: str | Path) -> Tracker:
    with _path(path).open("rb") as handle:
        return _decode(handle.read(MAX_BYTES + 1))


def _save(path: Path, tracker: Tracker, digest: bytes | None = None) -> None:
    from remediation.csv_report import _publish

    _validate(tracker)
    data = json.dumps({"version": 1, **asdict(tracker)}, ensure_ascii=True, indent=2)
    content = (data + "\n").encode("utf-8")
    _decode(content)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_suffix(".json.lock")
    handle = lock.open("xb")
    try:
        with handle:
            _publish(BytesIO(content), path, expected_digest=digest)
    finally:
        lock.unlink()


def create_tracker(
    path: str | Path, *, finding_id: str, control_id: str, scope: str,
    summary: str, next_action: str,
) -> Tracker:
    tracker = Tracker(finding_id, control_id, scope, (
        Event(datetime.now(UTC).isoformat(timespec="seconds"), 1, "in_progress",
              summary, next_action, "", {}),
    ))
    _save(_path(path), tracker)
    return tracker


def record_progress(
    path: str | Path, *, stage: int, status: str, summary: str, next_action: str,
    evidence: dict[str, str] | None = None, blocker: str = "",
) -> Tracker:
    destination = _path(path)
    with destination.open("rb") as handle:
        content = handle.read(MAX_BYTES + 1)
    previous = _decode(content)
    if stage != previous.current_stage or previous.status == "complete":
        raise ValueError("Record only the current stage; stages cannot be skipped or reopened.")
    tracker = Tracker(previous.finding_id, previous.control_id, previous.scope, (
        *previous.events,
        Event(datetime.now(UTC).isoformat(timespec="seconds"), stage, status,
              summary, next_action, blocker, evidence if evidence is not None else {}),
    ))
    _save(destination, tracker, sha256(content).digest())
    return tracker


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="Create a private tracker at stage 1")
    show = commands.add_parser("show", help="Show progress and required completion references")
    record = commands.add_parser("record", help="Record reviewed progress for the current stage")
    for command in (init, show, record):
        command.add_argument("--tracker", required=True, type=Path)
    for command in (init, record):
        command.add_argument("--summary", required=True)
        command.add_argument("--next-action", required=True)
    init.add_argument("--finding-id", required=True, help="Stable case ID, unique for this scope")
    init.add_argument("--control-id", required=True)
    init.add_argument("--scope", required=True, help="Explicit project/account/status/time scope")
    record.add_argument("--stage", required=True, type=int, choices=range(1, 9))
    record.add_argument("--status", required=True, choices=STATUSES)
    record.add_argument("--blocker", default="")
    record.add_argument(
        "--evidence", action="append", default=[], metavar="GATE=REFERENCE",
        help="Repeat for every completion gate; references are not auto-verified",
    )
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            tracker = create_tracker(
                args.tracker, finding_id=args.finding_id, control_id=args.control_id,
                scope=args.scope, summary=args.summary, next_action=args.next_action,
            )
        elif args.command == "record":
            evidence = {}
            for item in args.evidence:
                key, separator, reference = item.partition("=")
                if not separator or key in evidence:
                    raise ValueError("Use one unique GATE=REFERENCE per evidence argument.")
                evidence[key] = reference
            tracker = record_progress(
                args.tracker, stage=args.stage, status=args.status, summary=args.summary,
                next_action=args.next_action, blocker=args.blocker, evidence=evidence,
            )
        else:
            tracker = load_tracker(args.tracker)
    except ValueError as error:
        print(f"Tracker operation failed: {error}", file=sys.stderr)
        return 1
    except OSError:
        print("Tracker operation failed: cannot read or publish private file; check access/locks.",
              file=sys.stderr)
        return 1
    print(tracker.display())
    return 0
