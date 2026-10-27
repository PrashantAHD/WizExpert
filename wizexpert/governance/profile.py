"""Client profile: the per-client business rules that every governance command uses.

A profile is a small JSON file kept outside the repository (it may name the client).
It is looked up in this order:

1. ``--profile PATH`` on any command
2. the ``WIZEXPERT_PROFILE`` environment variable
3. ``wizexpert-profile.json`` in the current directory
4. the per-user profile (``%APPDATA%\\WizExpert\\governance-profile.json`` or
   ``~/.config/wizexpert/governance-profile.json``)

The former ``WIZGOV_PROFILE`` variable and ``wizgov-profile.json`` file are still accepted.
The standalone per-user ``wizgov/profile.json`` is the last fallback.

When none exists, interactive commands start ``wizexpert governance setup`` once;
non-interactive runs stop with instructions instead of guessing client details.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

SCHEMA_VERSION = 1
ENV_VAR = "WIZEXPERT_PROFILE"
LOCAL_NAME = "wizexpert-profile.json"
# Profiles created by the former standalone Wiz Governance Reporter still load.
LEGACY_ENV_VAR = "WIZGOV_PROFILE"
LEGACY_LOCAL_NAME = "wizgov-profile.json"
SEVERITIES = ("CRITICAL", "HIGH")
LOGO_SUFFIXES = {".png", ".jpg", ".jpeg"}


class ProfileError(ValueError):
    """The client profile is missing or invalid."""


@dataclass(frozen=True)
class ClientProfile:
    client_name: str
    file_prefix: str
    baseline: date
    provider_name: str
    watermark: str
    baseline_open: dict[str, int] | None = None
    logo: Path | None = None

    @property
    def snapshot_day(self) -> int:
        return self.baseline.day

    @property
    def baseline_total(self) -> int | None:
        return sum(self.baseline_open.values()) if self.baseline_open else None

    def snapshot(self, year: int, month: int) -> datetime:
        """End-of-day cutoff for a reporting month."""
        return datetime(year, month, self.snapshot_day, 23, 59, 59)

    def to_json(self) -> dict:
        data = {
            "schema_version": SCHEMA_VERSION,
            "client_name": self.client_name,
            "file_prefix": self.file_prefix,
            "baseline_month": f"{self.baseline:%Y-%m}",
            "snapshot_day": self.snapshot_day,
            "provider_name": self.provider_name,
            "watermark": self.watermark,
        }
        if self.baseline_open:
            data["baseline_open"] = dict(self.baseline_open)
        if self.logo:
            data["logo"] = str(self.logo)
        return data


def ordinal(day: int) -> str:
    suffix = "th" if 11 <= day <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix}"


def _text(raw: dict, key: str, context: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ProfileError(f"{context}: '{key}' must be a non-empty string.")
    return value.strip()


def from_json(
    raw: object, context: str = "Client profile", base_dir: Path | None = None
) -> ClientProfile:
    if not isinstance(raw, dict) or raw.get("schema_version") != SCHEMA_VERSION:
        raise ProfileError(f"{context}: expected a schema_version={SCHEMA_VERSION} object.")
    client = _text(raw, "client_name", context)
    prefix = _text(raw, "file_prefix", context)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", prefix):
        raise ProfileError(
            f"{context}: 'file_prefix' may only contain letters, digits, '_', '-' and '.'."
        )
    day = raw.get("snapshot_day")
    if not isinstance(day, int) or isinstance(day, bool) or not 1 <= day <= 28:
        raise ProfileError(f"{context}: 'snapshot_day' must be a whole number from 1 to 28.")
    month = _text(raw, "baseline_month", context)
    try:
        start = datetime.strptime(month, "%Y-%m")
    except ValueError as exc:
        raise ProfileError(f"{context}: 'baseline_month' must use YYYY-MM.") from exc
    counts = raw.get("baseline_open")
    if counts is not None:
        if (
            not isinstance(counts, dict)
            or set(counts) != set(SEVERITIES)
            or not all(
                isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in counts.values()
            )
        ):
            raise ProfileError(
                f"{context}: 'baseline_open' needs non-negative CRITICAL and HIGH counts."
            )
        counts = {severity: counts[severity] for severity in SEVERITIES}
    logo = raw.get("logo")
    if logo is not None:
        if not isinstance(logo, str) or not logo.strip():
            raise ProfileError(f"{context}: 'logo' must be a file path.")
        logo = Path(logo.strip()).expanduser()
        if not logo.is_absolute() and base_dir is not None:
            logo = base_dir / logo
        if logo.suffix.lower() not in LOGO_SUFFIXES:
            raise ProfileError(f"{context}: logo must be a .png or .jpg image.")
    return ClientProfile(
        client_name=client,
        file_prefix=prefix,
        baseline=date(start.year, start.month, day),
        provider_name=_text(raw, "provider_name", context),
        watermark=_text(raw, "watermark", context),
        baseline_open=counts,
        logo=logo,
    )


def load(path: Path) -> ClientProfile:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ProfileError(f"Client profile not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ProfileError(f"Client profile {path} is not valid JSON: {exc}") from exc
    return from_json(raw, f"Client profile {path}", Path(path).resolve().parent)


def save(profile: ClientProfile, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profile.to_json(), indent=2) + "\n", encoding="utf-8")
    return path


def user_profile_path() -> Path:
    if os.name == "nt" and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / "WizExpert" / "governance-profile.json"
    return (
        Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        / "wizexpert"
        / "governance-profile.json"
    )


def legacy_user_profile_path() -> Path:
    if os.name == "nt" and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / "wizgov" / "profile.json"
    return (
        Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "wizgov" / "profile.json"
    )


def find_profile(explicit: Path | str | None = None) -> Path | None:
    if explicit:
        return Path(explicit)
    for variable in (ENV_VAR, LEGACY_ENV_VAR):
        if os.environ.get(variable):
            return Path(os.environ[variable])
    for candidate in (
        Path.cwd() / LOCAL_NAME,
        Path.cwd() / LEGACY_LOCAL_NAME,
        user_profile_path(),
        legacy_user_profile_path(),
    ):
        if candidate.is_file():
            return candidate
    return None


_active: ClientProfile | None = None


def use(profile: ClientProfile | None) -> None:
    """Make ``profile`` the one used by report builders (``None`` clears it)."""
    global _active
    _active = profile


def active() -> ClientProfile:
    global _active
    if _active is None:
        path = find_profile()
        if path is None:
            raise ProfileError(
                "No client profile is configured. "
                "Run 'wizexpert governance setup' (or pass --profile)."
            )
        _active = load(path)
    return _active


def ensure(explicit: Path | str | None = None, *, interactive: bool | None = None) -> ClientProfile:
    """CLI entry: load the profile, or run first-time setup when a person is at the terminal."""
    if explicit is None and _active is not None:
        return _active
    path = find_profile(explicit)
    try:
        if path is not None:
            profile = load(path)
        else:
            if interactive is None:
                interactive = sys.stdin.isatty() and sys.stdout.isatty()
            if not interactive:
                raise ProfileError(
                    "No client profile is configured. Run 'wizexpert governance setup' first, "
                    f"set {ENV_VAR}, or pass --profile."
                )
            print("No client profile found - starting first-time setup.\n")
            profile, saved = run_wizard()
            print(f"\nSaved client profile: {saved}\n")
    except ProfileError as exc:
        raise SystemExit(f"Error: {exc}") from exc
    use(profile)
    return profile


def add_profile_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--profile",
        type=Path,
        default=None,
        help=f"Client profile JSON (default: ${ENV_VAR}, ./{LOCAL_NAME}, "
        "then the per-user profile; created by wizexpert governance setup).",
    )


# ── Setup wizard ───────────────────────────────────────────────────────────────


def _default_prefix(client: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", client.strip()).strip("_") or "Client"


def _validated(build) -> ClientProfile:
    try:
        return build()
    except ProfileError as exc:
        raise SystemExit(f"Error: {exc}") from exc


def run_wizard(
    existing: ClientProfile | None = None, target: Path | None = None
) -> tuple[ClientProfile, Path]:
    import questionary

    def ask(question):
        answer = question.ask()
        if answer is None:
            raise SystemExit("Setup cancelled.")
        return answer

    def whole(minimum: int, maximum: int | None = None, blank: bool = False):
        def check(value: str):
            if blank and not value.strip():
                return True
            if not value.strip().isdigit():
                return "Enter a whole number."
            number = int(value)
            if number < minimum or (maximum is not None and number > maximum):
                return (
                    f"Enter a number from {minimum} to {maximum}."
                    if maximum
                    else f"Enter {minimum} or more."
                )
            return True

        return check

    def month(value: str):
        try:
            datetime.strptime(value.strip(), "%Y-%m")
            return True
        except ValueError:
            return "Use YYYY-MM, e.g. 2026-03."

    def logo_path(value: str):
        value = value.strip().strip('"')
        if not value:
            return True
        path = Path(value).expanduser()
        if path.suffix.lower() not in LOGO_SUFFIXES:
            return "Use a .png or .jpg image."
        return True if path.is_file() else "File not found."

    old = existing
    print("Client profile setup - these rules drive every report for this client.\n")
    client = ask(
        questionary.text(
            "Client name (shown on reports and decks):",
            default=old.client_name if old else "",
            validate=lambda v: bool(v.strip()) or "Required.",
        )
    ).strip()
    prefix = ask(
        questionary.text(
            "File name prefix:",
            default=old.file_prefix if old else _default_prefix(client),
            validate=lambda v: (
                bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", v.strip()))
                or "Letters, digits, '_', '-' and '.' only."
            ),
        )
    ).strip()
    day = int(
        ask(
            questionary.text(
                "Monthly snapshot day (1-28) - each reporting month closes on this day at EOD:",
                default=str(old.snapshot_day) if old else "15",
                validate=whole(1, 28),
            )
        )
    )
    start = ask(
        questionary.text(
            "Baseline month (YYYY-MM) - the first snapshot that progress is measured from:",
            default=f"{old.baseline:%Y-%m}" if old else f"{date.today():%Y-%m}",
            validate=month,
        )
    ).strip()
    counts = None
    if ask(
        questionary.confirm(
            "Do you know the open CRITICAL and HIGH counts at the baseline? "
            "(needed for the executive dashboard)",
            default=bool(old and old.baseline_open),
        )
    ):
        counts = {}
        for severity in SEVERITIES:
            current = old.baseline_open[severity] if old and old.baseline_open else ""
            counts[severity] = int(
                ask(
                    questionary.text(
                        f"Open {severity} findings at baseline:",
                        default=str(current),
                        validate=whole(0),
                    )
                )
            )
    provider = ask(
        questionary.text(
            "Your organisation (shown as 'Proprietary to ...'):",
            default=old.provider_name if old else "",
            validate=lambda v: bool(v.strip()) or "Required.",
        )
    ).strip()
    watermark = ask(
        questionary.text(
            "Excel confidentiality watermark:",
            default=old.watermark if old else f"PROPRIETARY TO {provider.upper()}",
            validate=lambda v: bool(v.strip()) or "Required.",
        )
    ).strip()
    logo = (
        ask(
            questionary.text(
                "Client logo for the Excel Summary tab (.png/.jpg, optional):",
                default=str(old.logo) if old and old.logo else "",
                validate=logo_path,
            )
        )
        .strip()
        .strip('"')
    )
    raw = {
        "schema_version": SCHEMA_VERSION,
        "client_name": client,
        "file_prefix": prefix,
        "baseline_month": start,
        "snapshot_day": day,
        "provider_name": provider,
        "watermark": watermark,
    }
    if counts:
        raw["baseline_open"] = counts
    if logo:
        raw["logo"] = str(Path(logo).expanduser().resolve())
    profile = _validated(lambda: from_json(raw))
    if target is None:
        choice = ask(
            questionary.select(
                "Where should this profile be saved?",
                choices=[
                    questionary.Choice(f"For my user account  ({user_profile_path()})", "user"),
                    questionary.Choice(f"This folder only  ({Path.cwd() / LOCAL_NAME})", "local"),
                ],
            )
        )
        target = user_profile_path() if choice == "user" else Path.cwd() / LOCAL_NAME
    return profile, save(profile, target)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="wizexpert governance setup",
        description="Create or update the client profile "
        "(client name, snapshot day, baseline, logo...). "
        "Without options it asks interactively.",
    )
    parser.add_argument("--output", type=Path, help="Where to save the profile (asked if omitted).")
    parser.add_argument("--show", action="store_true", help="Print the active profile and exit.")
    parser.add_argument("--client-name")
    parser.add_argument("--file-prefix")
    parser.add_argument("--snapshot-day", type=int)
    parser.add_argument("--baseline-month", help="YYYY-MM")
    parser.add_argument("--baseline-critical", type=int)
    parser.add_argument("--baseline-high", type=int)
    parser.add_argument("--provider-name")
    parser.add_argument("--watermark")
    parser.add_argument("--logo")
    add_profile_argument(parser)
    args = parser.parse_args(argv)

    if args.show:
        path = find_profile(args.profile)
        if path is None:
            parser.exit(1, "No client profile is configured. Run 'wizexpert governance setup'.\n")
        profile = _validated(lambda: load(path))
        print(f"Profile: {path.resolve()}")
        print(json.dumps(profile.to_json(), indent=2))
        return 0

    scripted = [args.client_name, args.snapshot_day, args.baseline_month, args.provider_name]
    if any(value is not None for value in scripted):
        if not all(value is not None for value in scripted):
            parser.error(
                "Non-interactive setup needs --client-name, --snapshot-day, --baseline-month "
                "and --provider-name."
            )
        if (args.baseline_critical is None) != (args.baseline_high is None):
            parser.error("Supply both --baseline-critical and --baseline-high, or neither.")
        raw = {
            "schema_version": SCHEMA_VERSION,
            "client_name": args.client_name,
            "file_prefix": args.file_prefix or _default_prefix(args.client_name),
            "baseline_month": args.baseline_month,
            "snapshot_day": args.snapshot_day,
            "provider_name": args.provider_name,
            "watermark": args.watermark or f"PROPRIETARY TO {args.provider_name.upper()}",
        }
        if args.baseline_critical is not None:
            raw["baseline_open"] = {"CRITICAL": args.baseline_critical, "HIGH": args.baseline_high}
        if args.logo:
            raw["logo"] = str(Path(args.logo).expanduser().resolve())
        profile = _validated(lambda: from_json(raw))
        if profile.logo and not profile.logo.is_file():
            parser.exit(1, f"Error: logo not found: {profile.logo}\n")
        saved = save(profile, args.output or user_profile_path())
    else:
        existing_path = find_profile(args.profile)
        existing = (
            _validated(lambda: load(existing_path))
            if existing_path and existing_path.is_file()
            else None
        )
        if existing:
            print(f"Updating existing profile: {existing_path.resolve()}\n")
        _, saved = run_wizard(existing, args.output or (existing_path if existing else None))
    print(f"Saved client profile: {Path(saved).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
