"""Run orchestration: collect -> collection check -> narrative -> generate -> validate -> review.

A run is marked complete only after (1) the post-collection check passed from the real
activity log, (2) every bound validator passed on the real files, and (3) a named human
reviewer clicked Approve. The console never self-certifies review: the reviewer name and
UTC time come from the Approve request and are written to the run's private record.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import threading
import traceback
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from wizexpert.governance.categories import CATEGORIES
from wizexpert.governance.category_pipeline import PipelineError, run_category_pipeline
from wizexpert.workflow_qa import collection_check

from .adapters import AdapterError, CategoryAdapter, Field, coerce_fields
from .context import (
    ActivityLog,
    CollectionAborted,
    ReconnectRequired,
    RunContext,
    WindowExceeded,
    iso,
    utc_now,
)
from .policy import ReadOnlyViolation

RUNS_DIR = "_console-runs"
TERMINAL = {"complete", "failed", "blocked", "cancelled", "rejected", "reconnect_required"}
ACTIVE = {"collecting", "generating", "finalizing"}
PLACEHOLDER_NAMES = {
    "console", "system", "auto", "automatic", "wizexpert", "copilot", "ai", "bot", "admin",
    "reviewer", "n/a", "na", "none", "unknown", "approved", "user",
}  # fmt: skip
NAME_PATTERN = re.compile(r"[^\W\d_][\w .,'\-]{1,78}")
MAX_LOG_LINES = 5000


class RunError(Exception):
    """A request the run manager refuses (bad state, bad input); message is safe to show."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def confine(path: Path, root: Path) -> Path:
    """Resolve ``path`` and require it to stay inside ``root`` (no traversal, no escapes)."""
    resolved = Path(path).resolve()
    root = Path(root).resolve()
    if resolved != root and root not in resolved.parents:
        raise RunError("A path escaped the private deliverables root.")
    return resolved


def validate_reviewer(name: Any) -> str:
    if not isinstance(name, str):
        raise RunError("Enter the reviewer's name.")
    cleaned = " ".join(name.split())
    if not NAME_PATTERN.fullmatch(cleaned) or cleaned.lower() in PLACEHOLDER_NAMES:
        raise RunError("Enter the name of the human reviewer (a real name, not a placeholder).")
    return cleaned


class Run:
    def __init__(
        self,
        run_id: str,
        adapter: CategoryAdapter,
        inputs: dict[str, Any],
        dry_run: bool,
        run_dir: Path,
        output_dir: Path,
        preparer: str,
    ) -> None:
        self.id = run_id
        self.adapter = adapter
        self.category_id = adapter.category_id
        self.inputs = inputs
        self.dry_run = dry_run
        self.run_dir = run_dir
        self.output_dir = output_dir
        self.preparer = preparer
        self.status = "created"
        self.message = ""
        self.created_at = iso(utc_now())
        self.lock = threading.RLock()
        self.cancel_event = threading.Event()
        self.log: list[str] = []
        self.timeline: list[dict[str, str]] = []
        self.ctx: RunContext | None = None
        self.form: dict[str, Any] | None = None
        self.field_specs: list[Field] = []
        self.field_values: dict[str, Any] = {}
        self.collection: dict[str, Any] = {}
        self.problems: list[str] = []
        self.outputs: dict[str, Path] = {}
        self.output_hashes: dict[str, str] = {}
        self.validation: dict[str, Any] = {}
        self.approval: dict[str, Any] | None = None
        self.archived: list[str] = []
        self.moved: list[tuple[Path, Path]] = []
        self.pipeline: dict[str, Any] = {}

    # -- recording ------------------------------------------------------------------------
    def say(self, text: str) -> None:
        with self.lock:
            self.log.append(f"{iso(utc_now())} {text}")
            if len(self.log) > MAX_LOG_LINES:
                del self.log[: len(self.log) - MAX_LOG_LINES]
        try:
            with (self.run_dir / "run.log").open("a", encoding="utf-8") as stream:
                stream.write(f"{iso(utc_now())} {text}\n")
        except OSError:
            pass

    def set_status(self, status: str, message: str = "") -> None:
        with self.lock:
            self.status = status
            self.message = message
            self.timeline.append({"at": iso(utc_now()), "status": status, "message": message})
        self.say(f"[{status}] {message}" if message else f"[{status}]")
        self.persist()

    def record(self) -> dict[str, Any]:
        with self.lock:
            return {
                "schema_version": 1,
                "run_id": self.id,
                "category_id": self.category_id,
                "category_version": CATEGORIES[self.category_id].version,
                "dry_run": self.dry_run,
                "inputs": self.inputs,
                "preparer": self.preparer,
                "status": self.status,
                "message": self.message,
                "created_at": self.created_at,
                "output_dir": str(self.output_dir),
                "timeline": list(self.timeline),
                "collection": self.collection,
                "evidence_sha256": dict(self.ctx.evidence_hashes) if self.ctx else {},
                "field_values": self.field_values,
                "problems": list(self.problems),
                "archived_previous": list(self.archived),
                "outputs": {
                    slot: {"path": str(path), "sha256": self.output_hashes.get(slot, "")}
                    for slot, path in self.outputs.items()
                },
                "validation": self.validation,
                "approval": self.approval,
                "pipeline": self.pipeline,
                "notes": [
                    "workflow_qa is derived only from the recorded collection-check result and "
                    "the validators run on the actual files.",
                    "The evidence-bound `workflow-qa check` handoff review is a separate gate "
                    "this console does not perform or fabricate.",
                    "No email was sent; no Wiz, ticketing or cloud change was made.",
                ],
            }

    def persist(self) -> None:
        target = self.run_dir / "run.json"
        temp = self.run_dir / "run.json.tmp"
        try:
            temp.write_text(json.dumps(self.record(), indent=2, default=str), encoding="utf-8")
            os.replace(temp, target)
        except OSError:
            pass

    def view(self, since: int = 0) -> dict[str, Any]:
        with self.lock:
            data: dict[str, Any] = {
                "id": self.id,
                "category_id": self.category_id,
                "title": self.adapter.title,
                "status": self.status,
                "message": self.message,
                "dry_run": self.dry_run,
                "created_at": self.created_at,
                "inputs": self.inputs,
                "output_dir": str(self.output_dir),
                "log": self.log[since:],
                "log_next": len(self.log),
                "problems": list(self.problems),
                "collection": self.collection,
                "outputs": {
                    slot: {"name": path.name, "sha256": self.output_hashes.get(slot, "")}
                    for slot, path in self.outputs.items()
                },
                "approval": self.approval,
                "validation": self.validation,
                "archived_previous": list(self.archived),
            }
            if self.status == "awaiting_input" and self.form is not None:
                data["form"] = self.form
                data["field_values"] = self.field_values
            return data


class RunManager:
    """Owns runs, enforces the state machine and the review gate."""

    def __init__(
        self,
        adapters: Mapping[str, CategoryAdapter],
        deliverables_root: Path,
        client: Any | None,
        *,
        window_override_seconds: int | None = None,
        retry_delay: float = 1.0,
        run_async: bool = True,
        connected: Callable[[], bool] | None = None,
    ) -> None:
        self.adapters = dict(adapters)
        self.root = Path(deliverables_root).resolve()
        self.client = client
        self.window_override = window_override_seconds
        self._retry_delay = retry_delay
        self._run_async = run_async
        self._connected = connected or (lambda: bool(getattr(client, "connected", False)))
        self._runs: dict[str, Run] = {}
        self._lock = threading.Lock()

    # -- creation ---------------------------------------------------------------------------
    def categories(self) -> list[dict[str, Any]]:
        out = []
        for adapter in self.adapters.values():
            category = CATEGORIES[adapter.category_id]
            out.append(
                {
                    "id": adapter.category_id,
                    "title": adapter.title,
                    "description": adapter.description,
                    "version": category.version,
                    "slots": [{"id": s.slot_id, "title": s.title} for s in category.slots],
                    "fields": [f.to_json() for f in adapter.start_fields()],
                    "dry_run": adapter.supports_dry_run(),
                }
            )
        return out

    def create(
        self,
        category_id: str,
        raw_inputs: Mapping[str, Any],
        *,
        dry_run: bool = False,
        preparer: str = "",
    ) -> Run:
        adapter = self.adapters.get(category_id)
        if adapter is None:
            raise RunError("Unknown category.")
        if dry_run and not adapter.supports_dry_run():
            raise RunError("This category has no offline dry run.")
        if not dry_run and not self._connected():
            raise RunError("Connect Wiz first (reconnect Wiz).")
        with self._lock:
            if any(
                run.status in ACTIVE or run.status in {"awaiting_input", "awaiting_review"}
                for run in self._runs.values()
            ):
                raise RunError("Finish or cancel the current run before starting another.")
        try:
            inputs = adapter.validate_inputs(coerce_fields(adapter.start_fields(), raw_inputs))
        except AdapterError as error:
            raise RunError(str(error)) from None
        run_id = utc_now().strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(3)
        run_dir = confine(self.root / RUNS_DIR / run_id, self.root)
        run_dir.mkdir(parents=True, exist_ok=False)
        try:
            output_dir = (
                run_dir / "out" if dry_run else confine(adapter.output_dir(inputs), self.root)
            )
        except AdapterError as error:
            raise RunError(str(error)) from None
        run = Run(run_id, adapter, inputs, dry_run, run_dir, output_dir, preparer.strip()[:80])
        with self._lock:
            self._runs[run_id] = run
        run.set_status("created", "Run created.")
        self._start(self._collect, run)
        return run

    def _start(self, target: Callable[[Run], None], run: Run) -> None:
        if self._run_async:
            threading.Thread(target=target, args=(run,), daemon=True).start()
        else:
            target(run)

    def get(self, run_id: str) -> Run:
        with self._lock:
            run = self._runs.get(run_id)
        if run is None:
            raise RunError("Unknown run.")
        return run

    def history(self, limit: int = 30) -> list[dict[str, Any]]:
        """Recent runs: live ones plus records left by earlier sessions (read-only)."""
        seen: dict[str, dict[str, Any]] = {}
        base = self.root / RUNS_DIR
        if base.is_dir():
            for record in sorted(base.glob("*/run.json"), reverse=True)[: limit * 3]:
                try:
                    data = json.loads(record.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                status = data.get("status", "")
                if status not in TERMINAL:
                    status = "interrupted"
                seen[data.get("run_id", record.parent.name)] = {
                    "id": data.get("run_id", record.parent.name),
                    "category_id": data.get("category_id", ""),
                    "status": status,
                    "dry_run": data.get("dry_run", False),
                    "created_at": data.get("created_at", ""),
                }
        with self._lock:
            for run in self._runs.values():
                seen[run.id] = {
                    "id": run.id,
                    "category_id": run.category_id,
                    "status": run.status,
                    "dry_run": run.dry_run,
                    "created_at": run.created_at,
                }
        return sorted(seen.values(), key=lambda r: r["created_at"], reverse=True)[:limit]

    # -- phase 1: collection ----------------------------------------------------------------
    def _context(self, run: Run) -> RunContext:
        adapter = run.adapter
        client = adapter.replay_client(run.inputs) if run.dry_run else self.client
        activity = ActivityLog(run.run_dir / "activity.jsonl")
        return RunContext(
            run_id=run.id,
            category_id=run.category_id,
            inputs=run.inputs,
            dry_run=run.dry_run,
            run_dir=run.run_dir,
            output_dir=run.output_dir,
            client=client,
            activity=activity,
            log=run.say,
            cancelled=run.cancel_event.is_set,
            retry_delay=self._retry_delay,
        )

    def _collect(self, run: Run) -> None:
        adapter = run.adapter
        try:
            run.ctx = ctx = self._context(run)
            activity = ctx._activity  # noqa: SLF001
            run.set_status(
                "collecting",
                "Collecting read-only evidence." + (" (dry run: replay)" if run.dry_run else ""),
            )
            started = utc_now()
            activity.note(f"collection started dry_run={run.dry_run}")
            window = (
                self.window_override
                if self.window_override is not None
                else adapter.observation_window_seconds
            )
            if not run.dry_run:
                ctx.set_window(window)
            fragment = adapter.collect(ctx)
            activity.note("collection ended")
            ended = utc_now()
            elapsed = (ended - started).total_seconds()
            if window and not run.dry_run and elapsed > window:
                run.set_status(
                    "blocked",
                    f"Observation window exceeded ({int(elapsed)}s > {window}s). Start a new run; "
                    "evidence from different runs is never stitched.",
                )
                return
            manifest = {"started_at": iso(started), "ended_at": iso(ended), **fragment}
            if run.dry_run:
                manifest["dry_run"] = True
            manifest_path = run.run_dir / "collection-manifest.json"
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            result = collection_check(run.run_dir / "activity.jsonl", manifest, adapter.qa_workflow)
            (run.run_dir / "collection-check.json").write_text(
                json.dumps(result, indent=2), encoding="utf-8"
            )
            run.collection = {
                "status": result["status"],
                "flags": result.get("flags", []),
                "wiz_calls": result.get("wiz_calls", 0),
                "counts": manifest.get("counts", []),
                "started_at": manifest["started_at"],
                "ended_at": manifest["ended_at"],
            }
            if result["status"] != "pass":
                run.set_status(
                    "blocked",
                    "Post-collection check flagged the collection; generation is blocked.",
                )
                return
            run.say("Post-collection check passed.")
            run.field_specs = list(adapter.narrative_fields(ctx))
            prefill = adapter.prefill(ctx) or {}
            run.form = {
                "fields": [f.to_json() for f in run.field_specs],
                "reference": [
                    {"title": str(b.get("title", "")), "text": str(b.get("text", ""))}
                    for b in adapter.reference(ctx)
                ],
            }
            run.field_values = (
                coerce_fields(run.field_specs, prefill, partial=True) if run.field_specs else {}
            )
            if not run.field_specs:  # nothing to type: go straight to generation
                run.set_status("generating", "No input fields; generating deliverables.")
                self._generate(run)
                return
            run.set_status(
                "awaiting_input",
                "Review the pre-filled values, type the narrative fields and generate.",
            )
        except ReconnectRequired:
            run.set_status(
                "reconnect_required",
                "Wiz asked to reconnect (401 / OAuth challenge). The run was stopped and no "
                "collection window continues. Reconnect Wiz and start a new run.",
            )
        except ReadOnlyViolation as error:
            run.set_status("failed", f"Refused (read-only console): {error}")
        except WindowExceeded as error:
            run.set_status("blocked", str(error))
        except CollectionAborted as error:
            run.set_status("cancelled" if run.cancel_event.is_set() else "failed", str(error))
        except AdapterError as error:
            run.set_status("failed", str(error))
        except Exception as error:  # noqa: BLE001 - never crash the worker; keep detail private
            run.say(traceback.format_exc())
            run.set_status("failed", f"Unexpected {type(error).__name__}; see the private run log.")

    # -- phase 2: generation ------------------------------------------------------------------
    def submit_fields(self, run_id: str, values: Mapping[str, Any]) -> Run:
        run = self.get(run_id)
        with run.lock:
            if run.status != "awaiting_input":
                raise RunError("This run is not waiting for input.")
            try:
                run.field_values = coerce_fields(run.field_specs, values)
            except AdapterError as error:
                raise RunError(str(error)) from None
            run.status = "generating"
        self._start(self._generate, run)
        return run

    def _generate(self, run: Run) -> None:
        adapter, ctx = run.adapter, run.ctx
        if ctx is None:
            raise RunError("This run has no collected context.")
        try:
            run.set_status("generating", "Generating deliverables.")
            run.problems = []
            run.output_dir.mkdir(parents=True, exist_ok=True)
            expected = [
                confine(p, run.output_dir) for p in adapter.expected_outputs(ctx, run.field_values)
            ]
            self._archive(run, expected)
            try:
                outputs = adapter.generate(ctx, run.field_values)
                outputs = {slot: confine(Path(p), run.output_dir) for slot, p in outputs.items()}
                category = CATEGORIES[run.category_id]
                if sorted(outputs) != sorted(s.slot_id for s in category.slots):
                    raise AdapterError("Generation did not produce exactly the category's slots.")
            except BaseException:
                self._rollback(run, expected, "failed")
                raise
            run.outputs = outputs
            run.set_status("generating", "Validating every slot with its bound validator.")
            bindings = adapter.bindings(ctx, outputs)
            validation: dict[str, Any] = {"slots": {}, "extra": []}
            problems: list[str] = []
            for slot in category.slots:
                found = list(bindings[slot.slot_id].validator(outputs[slot.slot_id]))
                validation["slots"][slot.slot_id] = found or "passed"
                problems += [f"{slot.slot_id}: {p}" for p in found]
            extra = list(adapter.extra_checks(ctx, outputs))
            validation["extra"] = extra or "passed"
            problems += extra
            run.validation = validation
            if problems:
                run.problems = problems
                self._rollback(run, expected, "invalid")
                run.outputs, run.output_hashes = {}, {}
                run.set_status(
                    "awaiting_input",
                    "Validation found problems; fix the inputs and generate again.",
                )
                return
            run.output_hashes = {slot: sha256_file(p) for slot, p in outputs.items()}
            run.set_status(
                "awaiting_review",
                "Outputs validated. A named human reviewer must approve before completion.",
            )
        except (AdapterError, RunError) as error:
            run.problems = [str(error)]
            run.set_status(
                "awaiting_input", "Generation was blocked; fix the inputs and try again."
            )
        except CollectionAborted as error:
            run.set_status("cancelled", str(error))
        except Exception as error:  # noqa: BLE001
            run.say(traceback.format_exc())
            run.problems = [f"Unexpected {type(error).__name__}; see the private run log."]
            run.set_status("awaiting_input", "Generation failed; see the problems.")

    def _archive(self, run: Run, expected: list[Path]) -> None:
        existing = [p for p in expected if p.exists()]
        run.moved = []
        if not existing:
            return
        stamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
        folder = run.output_dir / "archives" / stamp
        folder.mkdir(parents=True, exist_ok=True)
        for path in existing:
            target = folder / path.name
            shutil.move(str(path), str(target))
            run.moved.append((path, target))
            run.archived.append(str(target))
        run.say(f"Archived {len(existing)} existing deliverable(s) before regenerating.")

    def _rollback(self, run: Run, expected: list[Path], why: str) -> None:
        """A failed or invalid generation must not leave the folder without its prior drafts.

        Anything this attempt wrote at the expected paths is kept under ``archives`` (named for
        the reason), then the archived previous deliverables are moved back.
        """
        attempted = [p for p in expected if p.exists()]
        if attempted:
            folder = run.output_dir / "archives" / f"{utc_now():%Y%m%dT%H%M%SZ}-{why}"
            folder.mkdir(parents=True, exist_ok=True)
            for path in attempted:
                shutil.move(str(path), str(folder / path.name))
        for original, archived in run.moved:
            if archived.exists() and not original.exists():
                shutil.move(str(archived), str(original))
                if str(archived) in run.archived:
                    run.archived.remove(str(archived))
        if run.moved:
            run.say("Restored the previous deliverables after an unsuccessful generation.")
        run.moved = []

    # -- phase 3: review gate -------------------------------------------------------------------
    def approve(self, run_id: str, reviewer: Any, *, confirm: bool) -> Run:
        run = self.get(run_id)
        name = validate_reviewer(reviewer)
        if confirm is not True:
            raise RunError("Tick the confirmation that you reviewed the deliverables.")
        with run.lock:
            if run.status != "awaiting_review" or run.approval is not None:
                raise RunError("This run is not awaiting approval.")
            for slot, path in run.outputs.items():
                if not path.is_file() or sha256_file(path) != run.output_hashes.get(slot):
                    raise RunError("A deliverable changed since validation; generate again.")
            run.approval = {
                "reviewer": name,
                "approved_at_utc": iso(utc_now()),
                "independent_of_preparer": bool(run.preparer)
                and run.preparer.lower() != name.lower(),
                "output_sha256": dict(run.output_hashes),
            }
            run.status = "finalizing"
        self._start(self._finalize, run)
        return run

    def _finalize(self, run: Run) -> None:
        adapter, ctx = run.adapter, run.ctx
        if ctx is None:
            raise RunError("This run has no collected context.")
        try:
            run.set_status("finalizing", "Running the enforced category pipeline.")
            category = CATEGORIES[run.category_id]
            bindings = adapter.bindings(ctx, run.outputs)
            workflow_ok = (
                run.collection.get("status") == "pass"
                and not run.problems
                and all(v == "passed" for v in run.validation.get("slots", {}).values())
                and run.validation.get("extra") == "passed"
            )
            qa = {
                "workflow_qa": "passed" if workflow_ok else "failed",
                "review": "passed" if run.approval else "pending",
                "category_id": run.category_id,
                "version": category.version,
                "slots": [s.slot_id for s in category.slots],
                "template_sha256": {k: b.template_sha256 for k, b in bindings.items()},
                "outputs_sha256": {k: sha256_file(p) for k, p in run.outputs.items()},
                **adapter.qa_extras(ctx),
            }
            result = run_category_pipeline(
                run.category_id, category.version, bindings, run.output_dir, qa
            )
            run.pipeline = {
                "complete": result.complete,
                "workflow_qa": qa["workflow_qa"],
                "review": qa["review"],
            }
            if result.complete:
                run.set_status(
                    "complete", "Complete: reviewed and approved. Drafts only; nothing was sent."
                )
            else:
                run.set_status("failed", "The category pipeline did not report completion.")
        except PipelineError as error:
            run.pipeline = {"complete": False, "error": str(error)[:500]}
            run.set_status(
                "failed", f"The category pipeline refused completion: {str(error)[:300]}"
            )
        except Exception as error:  # noqa: BLE001
            run.say(traceback.format_exc())
            run.set_status("failed", f"Unexpected {type(error).__name__}; see the private run log.")

    def reject(self, run_id: str, reviewer: Any, reason: str = "") -> Run:
        run = self.get(run_id)
        name = validate_reviewer(reviewer)
        with run.lock:
            if run.status != "awaiting_review":
                raise RunError("This run is not awaiting review.")
            run.approval = {
                "reviewer": name,
                "rejected_at_utc": iso(utc_now()),
                "reason": str(reason)[:500],
            }
        run.set_status("rejected", "Rejected by reviewer; not complete.")
        return run

    def cancel(self, run_id: str) -> Run:
        run = self.get(run_id)
        run.cancel_event.set()
        with run.lock:
            current = run.status
        if current in {"awaiting_input", "awaiting_review"}:
            run.set_status("cancelled", "Cancelled.")
        return run

    def output_file(self, run_id: str, slot: str) -> Path:
        run = self.get(run_id)
        with run.lock:
            path = run.outputs.get(slot)
        if path is None:
            raise RunError("Unknown deliverable.")
        return confine(path, self.root)
