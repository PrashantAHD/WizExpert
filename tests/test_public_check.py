from __future__ import annotations

import shutil
import stat
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from scripts import public_check


def run_git(root: Path, *args: str) -> str:
    executable = shutil.which("git")
    assert executable is not None, "Git is required to run publication tests."
    result = subprocess.run(
        [executable, "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def remove_readonly(function, path, error):
    if not isinstance(error, PermissionError):
        raise error
    Path(path).chmod(stat.S_IWRITE)
    function(path)


@pytest.fixture
def repository():
    # Keep generated repositories beneath the project, never in system temp.
    root = Path.cwd() / ".pytest_cache" / "publication-repos" / uuid.uuid4().hex
    root.mkdir(parents=True)
    try:
        run_git(root, "init", "-q", "-b", "main")
        run_git(root, "config", "user.name", "Synthetic Author")
        run_git(root, "config", "user.email", "synthetic@" + "example.invalid")
        run_git(root, "config", "commit.gpgsign", "false")
        (root / "README.md").write_text("# Public source\n", encoding="utf-8")
        run_git(root, "add", ".")
        run_git(root, "commit", "-qm", "Initial public source")
        yield root
    finally:
        shutil.rmtree(root, onexc=remove_readonly)


@pytest.mark.parametrize(
    ("value", "category"),
    [
        ("-----BEGIN " + "PRIVATE KEY-----", "private key"),
        ("AK" + "IA" + "A" * 16, "AWS access key"),
        ("gh" + "p_" + "a" * 36, "GitHub token"),
        ("github_" + "pat_" + "a" * 40, "GitHub token"),
        ("xo" + "xb-" + "a" * 24, "service token"),
        ("sk" + "-" + "a" * 24, "service token"),
        ("ey" + "J" + "a" * 12 + "." + "b" * 12 + "." + "c" * 12, "JWT credential"),
        ("1" * 12, "AWS account ID"),
        ("arn:" + "aws:s3:::synthetic-bucket", "AWS ARN"),
        ("/subscriptions/" + "a" * 8 + "-bbbb-cccc-dddd-" + "e" * 12, "Azure resource path"),
        ("synthetic@" + "example.invalid", "email address"),
        ("care" + "first", "restricted organization name"),
        ("password" + ' = "' + "x" * 20 + '"', "credential assignment"),
        ("Bearer" + " " + "a" * 32, "authorization credential"),
    ],
)
def test_detects_sensitive_shapes(value, category):
    assert category in public_check.content_issues(value.encode())


@pytest.mark.parametrize(
    "name",
    [
        "report.xlsx",
        "tests/fixture.csv",
        "tests/fixture.json",
        "remediation/private.db",
        "logs/run.log",
        ".env",
        ".env.example",
        "scripts/.env.py",
        "../README.md",
        "/README.md",
        "docs\\guide.md",
        "docs/line\nbreak.md",
        ".github/workflows/nested/check.yml",
        ".github/instructions/other.instructions.md",
        ".github/instructions/nested/production-workflow.instructions.md",
        ".github/instructions/production-workflow.instructions.md.csv",
        "data/customer.txt",
    ],
)
def test_disallows_non_source_files(name):
    assert public_check.path_issues(name)


@pytest.mark.parametrize(
    "name",
    [
        "README.md",
        "LICENSE",
        "pyproject.toml",
        ".gitignore",
        "remediation/app.py",
        "remediation/templates/index.html",
        "remediation/static/app.js",
        "tests/test_public_check.py",
        "scripts/verify.ps1",
        ".githooks/pre-push",
        ".github/workflows/checks.yml",
        ".github/instructions/production-workflow.instructions.md",
        "docs/PUBLICATION.md",
    ],
)
def test_allows_source_files(name):
    assert public_check.path_issues(name) == []


def test_checks_content_separately_from_extension_references():
    source = b'EXTENSIONS = {".xlsx", ".csv", ".db", ".env"}\n'
    assert public_check.content_issues(source) == []
    assert public_check.path_issues("remediation/formats.py") == []
    assert public_check.path_issues("remediation/formats.csv")


def test_rejects_binary_invalid_utf8_and_large_files():
    assert public_check.content_issues(b"a\x00b") == ["binary content is not allowed"]
    assert public_check.content_issues(b"\xff") == ["content is not UTF-8 text"]
    assert public_check.content_issues(b"a" * (public_check.MAX_FILE_BYTES + 1)) == [
        "file exceeds publication size limit"
    ]


def test_checks_filenames_for_sensitive_identifiers():
    assert "restricted organization name" in public_check.path_issues(
        "docs/" + "care" + "first" + ".md"
    )


def test_clean_repository_passes(repository):
    assert public_check.inspect_repository(repository) == []


def test_scans_working_copy(repository):
    (repository / "README.md").write_text("1" * 12, encoding="utf-8")
    issues = public_check.inspect_repository(repository)
    assert any("working" in issue and "AWS account ID" in issue for issue in issues)


def test_scans_staged_content_even_when_working_copy_is_clean(repository):
    (repository / "README.md").write_text("1" * 12, encoding="utf-8")
    run_git(repository, "add", "README.md")
    (repository / "README.md").write_text("# Clean working copy\n", encoding="utf-8")
    issues = public_check.inspect_repository(repository)
    assert any("index" in issue and "AWS account ID" in issue for issue in issues)
    assert not any("working" in issue for issue in issues)


def test_deleted_historical_secret_still_blocks(repository):
    (repository / "docs").mkdir()
    secret = repository / "docs" / "old.md"
    secret.write_text("gh" + "p_" + "a" * 36, encoding="utf-8")
    run_git(repository, "add", ".")
    run_git(repository, "commit", "-qm", "Add synthetic fixture")
    run_git(repository, "rm", "docs/old.md")
    run_git(repository, "commit", "-qm", "Remove fixture")
    issues = public_check.inspect_repository(repository)
    assert any("history" in issue and "GitHub token" in issue for issue in issues)


def test_historical_disallowed_file_still_blocks(repository):
    (repository / "report.csv").write_text("synthetic,value\n", encoding="utf-8")
    run_git(repository, "add", ".")
    run_git(repository, "commit", "-qm", "Add synthetic table")
    run_git(repository, "rm", "report.csv")
    run_git(repository, "commit", "-qm", "Remove table")
    assert any("allowlist" in issue for issue in public_check.inspect_repository(repository))


def test_outgoing_detached_tip_is_checked(repository):
    run_git(repository, "checkout", "--detach", "-q")
    (repository / "README.md").write_text("1" * 12, encoding="utf-8")
    run_git(repository, "add", ".")
    run_git(repository, "commit", "-qm", "Detached synthetic fixture")
    outgoing = run_git(repository, "rev-parse", "HEAD")
    run_git(repository, "checkout", "-q", "main")
    assert public_check.inspect_repository(repository) == []
    updates = f"{outgoing} {outgoing} refs/heads/publish {'0' * 40}\n"
    tips = public_check.outgoing_commits(updates)
    issues = public_check.inspect_repository(repository, tips)
    assert any("AWS account ID" in issue for issue in issues)


def test_commit_messages_are_checked(repository):
    run_git(repository, "commit", "--allow-empty", "-qm", "1" * 12)
    assert any("commit message" in issue for issue in public_check.inspect_repository(repository))


def test_index_symlink_is_rejected_without_following_it(repository):
    blob = run_git(repository, "hash-object", "-w", "README.md")
    run_git(repository, "update-index", "--add", "--cacheinfo", f"120000,{blob},docs/link.md")
    assert any("symlinks" in issue for issue in public_check.inspect_repository(repository))


def test_shallow_history_fails_closed(repository):
    head = run_git(repository, "rev-parse", "HEAD")
    (repository / ".git" / "shallow").write_text(head + "\n", encoding="ascii")
    with pytest.raises(public_check.GuardError, match="Shallow"):
        public_check.inspect_repository(repository)


def test_invalid_git_revision_fails_closed(repository):
    with pytest.raises(public_check.GuardError, match="rev-list failed"):
        public_check.inspect_repository(repository, ["f" * 40])


def test_missing_git_fails_closed(monkeypatch):
    monkeypatch.setattr(public_check.shutil, "which", lambda name: None)
    with pytest.raises(public_check.GuardError, match="Git was not found"):
        public_check.git(Path.cwd(), "status")


def test_pre_push_parses_creation_deletion_and_multiple_updates():
    first, second, zero = "a" * 40, "b" * 40, "0" * 40
    updates = (
        f"refs/heads/main {first} refs/heads/main {zero}\n"
        f"(delete) {zero} refs/heads/old {second}\n"
        f"refs/tags/v1 {second} refs/tags/v1 {first}\n\n"
    )
    assert public_check.outgoing_commits(updates) == [first, second]


@pytest.mark.parametrize("updates", ["bad", "a not-a-hash b " + "0" * 40])
def test_malformed_hook_updates_fail_closed(updates):
    with pytest.raises(public_check.GuardError, match="Malformed"):
        public_check.outgoing_commits(updates)


class FakeDistribution:
    def __init__(self, name, version, direct_url=None):
        self.metadata = {"Name": name}
        self.version = version
        self.direct_url = direct_url

    def read_text(self, filename):
        assert filename == "direct_url.json"
        return self.direct_url


def test_inventory_emits_only_names_and_versions(monkeypatch):
    monkeypatch.setattr(
        public_check,
        "distributions",
        lambda: [
            FakeDistribution("Sample", "1.2.3"),
            FakeDistribution("another-package", "2.0rc1"),
            FakeDistribution("Sample", "1.2.3"),
            FakeDistribution("local-app", "0.1", '{"dir_info": {"editable": true}}'),
        ],
    )
    assert public_check.dependency_inventory() == ["another-package==2.0rc1", "Sample==1.2.3"]


@pytest.mark.parametrize(
    ("name", "version"),
    [
        ("https://example.invalid/package", "1.0"),
        ("package\n--index-url", "1.0"),
        ("package", "1.0\n--index-url"),
        ("package", ""),
        ("", "1.0"),
    ],
)
def test_inventory_rejects_requirement_injection(monkeypatch, name, version):
    monkeypatch.setattr(
        public_check, "distributions", lambda: [FakeDistribution(name, version)]
    )
    with pytest.raises(public_check.GuardError, match="Invalid installed package"):
        public_check.dependency_inventory()


def test_empty_inventory_fails_closed(monkeypatch):
    monkeypatch.setattr(public_check, "distributions", lambda: [])
    with pytest.raises(public_check.GuardError, match="Empty dependency inventory"):
        public_check.dependency_inventory()


def test_audit_flags_and_inventory_are_accepted_without_network(repository):
    requirements = repository / "audit-input.txt"
    requirements.write_text("\n".join(public_check.dependency_inventory()), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip_audit",
            "--requirement",
            str(requirements),
            "--disable-pip",
            "--no-deps",
            "--strict",
            "--progress-spinner",
            "off",
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "would have audited" in result.stderr
