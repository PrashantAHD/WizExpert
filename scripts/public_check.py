"""Offline publication checks; deliberately conservative, not a data classifier."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess  # nosec B404
import sys
from importlib.metadata import distributions
from pathlib import Path, PurePosixPath

ROOT_FILES = {
    ".gitignore",
    ".gitattributes",
    ".editorconfig",
    "LICENSE",
    "README.md",
    "pyproject.toml",
}
SOURCE_SUFFIXES = {
    "remediation": {".py", ".html", ".css", ".js"},
    "tests": {".py"},
    "scripts": {".py", ".ps1"},
    "docs": {".md"},
}
MAX_FILE_BYTES = 1_000_000
OID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
PUBLIC_ATTRIBUTION = (
    "Co-authored-by: Copilot <223556219+Copilot" + "@users.noreply.github.com>"
)
PATTERNS = (
    ("private key", re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----")),
    ("AWS access key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("GitHub token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_\w{20,})\b")),
    ("service token", re.compile(r"\b(?:xox[baprs]-[A-Za-z0-9-]{15,}|sk-[A-Za-z0-9]{20,})")),
    ("JWT credential", re.compile(r"\beyJ[\w-]{10,}\.[\w-]{10,}\.[\w-]{10,}\b")),
    ("AWS account ID", re.compile(r"(?<!\d)\d{12}(?!\d)")),
    ("AWS ARN", re.compile(r"\barn:(?:aws|aws-us-gov|aws-cn):[^\s\"'<>]+", re.I)),
    (
        "Azure resource path",
        re.compile(r"/subscriptions/[0-9a-f-]{36}(?:/|\b)", re.I),
    ),
    ("email address", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)),
    ("restricted organization name", re.compile("care" + "first", re.I)),
    (
        "credential assignment",
        re.compile(
            r"""(?ix)\b(?:password|passwd|secret|secret[_-]?key|api[_-]?key|access[_-]?token|
            auth[_-]?token|client[_-]?secret|aws[_-]?secret[_-]?access[_-]?key)
            \b["']?\s*[:=]\s*["'][A-Za-z0-9/+_.=-]{8,}["']"""
        ),
    ),
    (
        "authorization credential",
        re.compile(r"\b(?:Bearer|Basic)\s+[A-Za-z0-9+/_.=-]{16,}", re.I),
    ),
)


class GuardError(RuntimeError):
    """A repository state could not be inspected safely."""


def git(root: Path, *args: str) -> bytes:
    # Only fixed local Git commands are executed, never through a shell.
    executable = shutil.which("git")
    if executable is None:
        raise GuardError("Git was not found on PATH; publication check blocked.")
    result = subprocess.run(  # nosec B603
        [executable, "-C", str(root), *args],
        capture_output=True,
        check=False,
    )
    if result.returncode:
        # Git errors can contain private paths or remote addresses.
        raise GuardError(f"Git {args[0]} failed (exit {result.returncode}).")
    return result.stdout


def content_issues(data: bytes, *, commit_message: bool = False) -> list[str]:
    if len(data) > MAX_FILE_BYTES:
        return ["file exceeds publication size limit"]
    if b"\x00" in data:
        return ["binary content is not allowed"]
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return ["content is not UTF-8 text"]
    email_text = text
    ending = "\n\n" + PUBLIC_ATTRIBUTION
    if commit_message and text.rstrip("\r\n").endswith(ending):
        # Only this exact final public attribution is exempt, never source-file content.
        email_text = text.rstrip("\r\n")[:-len(PUBLIC_ATTRIBUTION)]
    return [
        label for label, pattern in PATTERNS
        if pattern.search(email_text if label == "email address" else text)
    ]


def path_issues(name: str) -> list[str]:
    path = PurePosixPath(name)
    if (
        path.is_absolute()
        or ".." in path.parts
        or "\\" in name
        or any(ord(char) < 32 for char in name)
    ):
        return ["unsafe file path"]
    issues = [label for label, pattern in PATTERNS if pattern.search(name)]
    allowed = name in ROOT_FILES or name == ".githooks/pre-push"
    allowed |= name == ".github/instructions/production-workflow.instructions.md"
    if len(path.parts) >= 2:
        suffixes = SOURCE_SUFFIXES.get(path.parts[0], set())
        allowed |= path.suffix in suffixes and not any(
            part.startswith(".") for part in path.parts[1:]
        )
    if len(path.parts) == 3 and path.parts[:2] == (".github", "workflows"):
        allowed |= path.suffix in {".yml", ".yaml"}
    if not allowed:
        issues.append("file location or extension is not on the publication allowlist")
    return issues


def outgoing_commits(updates: str) -> list[str]:
    commits = []
    for line in updates.splitlines():
        if not line.strip():
            continue
        fields = line.split()
        if len(fields) != 4 or not OID.fullmatch(fields[1]) or not OID.fullmatch(fields[3]):
            raise GuardError("Malformed pre-push update; refusing an incomplete history check.")
        local_oid = fields[1]
        if set(local_oid) != {"0"}:
            commits.append(local_oid)
    return commits


def dependency_inventory() -> list[str]:
    """Return only public-environment package metadata, never paths or URLs."""
    inventory = set()
    for distribution in distributions():
        direct_url = distribution.read_text("direct_url.json")
        if direct_url and json.loads(direct_url).get("dir_info", {}).get("editable"):
            continue
        name, version = distribution.metadata["Name"], distribution.version
        if not name or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name):
            raise GuardError("Invalid installed package name; dependency audit blocked.")
        if not version or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.!+_-]*", version):
            raise GuardError("Invalid installed package version; dependency audit blocked.")
        inventory.add(f"{name}=={version}")
    if not inventory:
        raise GuardError("Empty dependency inventory; audit blocked.")
    return sorted(inventory, key=str.lower)


def inspect_repository(root: Path, outgoing: list[str] | None = None) -> list[str]:
    if git(root, "rev-parse", "--is-shallow-repository").strip() != b"false":
        raise GuardError("Shallow history cannot be checked. Fetch complete history first.")
    problems: set[str] = set()
    checked_blobs: dict[str, list[str]] = {}
    checked_entries: set[tuple[str, str, str]] = set()

    def report(source: str, issues: list[str]) -> None:
        for issue in issues:
            problems.add(f"{source}: {issue}")

    def inspect_blob(mode: str, oid: str, name: str, source: str) -> None:
        report(source, path_issues(name))
        if mode not in {"100644", "100755"}:
            report(source, ["symlinks, submodules and non-regular files are not allowed"])
            return
        if oid not in checked_blobs:
            size = int(git(root, "cat-file", "-s", oid))
            checked_blobs[oid] = (
                ["file exceeds publication size limit"]
                if size > MAX_FILE_BYTES
                else content_issues(git(root, "cat-file", "blob", oid))
            )
        report(source, checked_blobs[oid])

    for entry in git(root, "ls-files", "--stage", "-z").split(b"\0"):
        if not entry:
            continue
        metadata, raw_name = entry.split(b"\t", 1)
        mode, oid, stage = metadata.decode("ascii").split()
        name = raw_name.decode("utf-8")
        source = f"index {name!r}"
        if stage != "0":
            report(source, ["unmerged index entry"])
        inspect_blob(mode, oid, name, source)
        file = root.joinpath(*PurePosixPath(name).parts)
        if file.is_symlink():
            report(f"working {name!r}", ["symlink is not allowed"])
        elif file.exists():
            if not file.is_file():
                report(f"working {name!r}", ["non-regular file is not allowed"])
            elif file.stat().st_size > MAX_FILE_BYTES:
                report(f"working {name!r}", ["file exceeds publication size limit"])
            else:
                report(f"working {name!r}", content_issues(file.read_bytes()))

    # Scan every reachable local ref, not merely the latest diff. Extra pre-push
    # tips cover detached commits and explicit SHA refspecs absent from --all.
    revisions = git(root, "rev-list", "--all", *(outgoing or [])).decode("ascii").splitlines()
    for revision in revisions:
        report(
            f"commit message {revision[:12]}",
            content_issues(
                git(root, "show", "-s", "--format=%B", revision), commit_message=True
            ),
        )
        for entry in git(root, "ls-tree", "-r", "-z", revision).split(b"\0"):
            if not entry:
                continue
            metadata, raw_name = entry.split(b"\t", 1)
            mode, _kind, oid = metadata.decode("ascii").split()
            name = raw_name.decode("utf-8")
            key = (mode, oid, name)
            if key not in checked_entries:
                checked_entries.add(key)
                inspect_blob(mode, oid, name, f"history {revision[:12]} {name!r}")
    return sorted(problems)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pre-push", action="store_true", help="Read Git pre-push updates on stdin"
    )
    parser.add_argument(
        "--dependency-inventory", action="store_true",
        help="Print installed non-editable distribution names and exact versions (offline)",
    )
    args = parser.parse_args()
    try:
        if args.dependency_inventory:
            print("\n".join(dependency_inventory()))
            return 0
        root = Path(git(Path.cwd(), "rev-parse", "--show-toplevel").decode("utf-8").strip())
        outgoing = outgoing_commits(sys.stdin.read()) if args.pre_push else []
        problems = inspect_repository(root, outgoing)
    except (GuardError, OSError, UnicodeError, ValueError) as error:
        print(f"Publication check could not complete: {error}", file=sys.stderr)
        return 2
    if problems:
        print("Publication check FAILED (matched values are not printed):", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    print("Publication check passed: tracked working files, index, and reachable history.")
    print("Manual content and history review is still required; untracked files were not scanned.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
