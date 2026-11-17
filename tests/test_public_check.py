from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from scripts import public_check

_REAL_RUN = subprocess.run
_LOCAL_ENV = None


def local_git_env_names():
    """Repository-local variables a Git hook may export (Git's documented list)."""
    global _LOCAL_ENV
    if _LOCAL_ENV is None:
        executable = shutil.which("git")
        assert executable is not None, "Git is required to run publication tests."
        out = _REAL_RUN(
            [executable, "rev-parse", "--local-env-vars"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.split()
        _LOCAL_ENV = frozenset(out)
    return _LOCAL_ENV


def _is_local(key):
    key = key.upper()
    return key in local_git_env_names() or key.startswith(
        ("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")
    )


def scrubbed_env():
    return {k: v for k, v in os.environ.items() if not _is_local(k)}


def run_git(root: Path, *args: str) -> str:
    executable = shutil.which("git")
    assert executable is not None, "Git is required to run publication tests."
    result = _REAL_RUN(
        [executable, "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
        env=scrubbed_env(),
    )
    return result.stdout.strip()


@pytest.fixture(autouse=True)
def isolate_git_env(monkeypatch):
    """Insulate fixtures and public_check from hook-inherited repository env."""
    for key in [k for k in os.environ if _is_local(k)]:
        monkeypatch.delenv(key)

    def scrubbed_run(*args, **kwargs):
        kwargs.setdefault("env", scrubbed_env())
        return _REAL_RUN(*args, **kwargs)

    monkeypatch.setattr(public_check.subprocess, "run", scrubbed_run)


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
        "wizexpert/private.db",
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
        ".github/instructions/any.instructions.md",
        "data/customer.txt",
        "docs/assets/logo.png",
        "docs/assets/diagram.svgz",
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
        "wizexpert/app.py",
        "wizexpert/templates/index.html",
        "wizexpert/static/app.js",
        "tests/test_public_check.py",
        "scripts/verify.ps1",
        ".githooks/pre-push",
        ".github/workflows/checks.yml",
        "docs/PUBLICATION.md",
        "docs/assets/logo.svg",
    ],
)
def test_allows_source_files(name):
    assert public_check.path_issues(name) == []


def test_retired_layout_is_allowed_only_for_history():
    retired = (
        "remediation/workflow.py",
        ".github/instructions/production-workflow.instructions.md",
    )
    for name in retired:
        assert public_check.path_issues(name)
        assert public_check.path_issues(name, historical=True) == []
    assert public_check.path_issues("remediation/data.csv", historical=True)


def test_checks_content_separately_from_extension_references():
    source = b'EXTENSIONS = {".xlsx", ".csv", ".db", ".env"}\n'
    assert public_check.content_issues(source) == []
    assert public_check.path_issues("wizexpert/formats.py") == []
    assert public_check.path_issues("wizexpert/formats.csv")


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


def test_exact_final_public_attribution_is_allowed_only_in_commit_messages(repository):
    message = "Add public source\n\n" + public_check.PUBLIC_ATTRIBUTION
    assert "email address" in public_check.content_issues(message.encode())
    assert public_check.content_issues(message.encode(), commit_message=True) == []
    run_git(repository, "commit", "--allow-empty", "-qm", message)
    assert public_check.inspect_repository(repository) == []


@pytest.mark.parametrize("message", [
    "Subject\n\nCo-authored-by: Synthetic <synthetic" + "@example.invalid>",
    "Subject\n\n" + public_check.PUBLIC_ATTRIBUTION.replace("Copilot <", "Someone <"),
    "Subject\n\n" + public_check.PUBLIC_ATTRIBUTION + "\nAdditional text",
    "Subject\n\n" + public_check.PUBLIC_ATTRIBUTION + "\n\n" + public_check.PUBLIC_ATTRIBUTION,
    "Subject\n\nContact synthetic" + "@example.invalid\n\n" + public_check.PUBLIC_ATTRIBUTION,
    "Subject\n\n" + public_check.PUBLIC_ATTRIBUTION + " ",
])
def test_public_attribution_does_not_exempt_other_email_content(message):
    assert "email address" in public_check.content_issues(message.encode(), commit_message=True)


def test_public_attribution_does_not_exempt_other_sensitive_patterns():
    message = "1" * 12 + "\n\n" + public_check.PUBLIC_ATTRIBUTION
    assert "AWS account ID" in public_check.content_issues(message.encode(), commit_message=True)


def test_synthetic_merge_subject_object_ids_are_not_account_ids():
    head = "b75aad7c43498ee304f" + "6" + "27814458483" + "a466246ed"
    base = "d" * 40
    message = f"Merge {head} into {base}\n".encode()
    parents = frozenset({head, base})
    assert public_check.content_issues(message, commit_message=True, parents=parents) == []
    assert "AWS account ID" in public_check.content_issues(message, commit_message=True)
    assert "AWS account ID" in public_check.content_issues(message)


def test_synthetic_merge_exemption_covers_64_hex_and_second_id():
    first, second = "a" * 64, "b" * 52 + "1" * 12
    message = f"Merge {first} into {second}".encode()
    parents = frozenset({first, second})
    assert public_check.content_issues(message, commit_message=True, parents=parents) == []


@pytest.mark.parametrize(("body", "label"), [
    ("Contact synthetic" + "@example.invalid", "email address"),
    ("gh" + "p_" + "A" * 24, "GitHub token"),
    ("1" * 12, "AWS account ID"),
])
def test_synthetic_merge_exemption_still_scans_body(body, label):
    first, second = "a" * 40, "b" * 28 + "1" * 12
    message = f"Merge {first} into {second}\n\n{body}".encode()
    parents = frozenset({first, second})
    assert label in public_check.content_issues(message, commit_message=True, parents=parents)


A40, B40 = "a" * 40, "b" * 40


@pytest.mark.parametrize(("message", "parents"), [
    ("Merge " + "1" * 12 + "a" * 28 + " into " + B40, {"1" * 12 + "a" * 28, "c" * 40}),
    ("Merge " + A40 + " into " + "b" * 28 + "1" * 12 + "b" * 5, {A40, "b" * 28 + "1" * 12}),
    ("Merge " + A40 + " into " + B40 + " " + "1" * 12, {A40, B40}),
    ("Merge " + A40 + " into " + B40 + "\n\n" + "1" * 12, {A40, B40}),
    ("Subject\nMerge " + "1" * 12 + "a" * 28 + " into " + B40, {"1" * 12 + "a" * 28, B40}),
    ("Merge " + "1" * 12 + "A" * 28 + " into " + B40, {"1" * 12 + "A" * 28, B40}),
    ("Merge " + "1" * 12 + "a" * 28 + " into " + B40 + "\r\n", {"1" * 12 + "a" * 28, B40}),
    ("Merge " + "1" * 12 + "a" * 28 + " into " + B40, {"1" * 12 + "a" * 28}),
])
def test_synthetic_merge_exemption_is_exact(message, parents):
    issues = public_check.content_issues(
        message.encode(), commit_message=True, parents=frozenset(parents)
    )
    assert "AWS account ID" in issues


def test_real_merge_commit_subject_naming_its_parents_passes(repository):
    run_git(repository, "commit", "--allow-empty", "-qm", "Base")
    base = run_git(repository, "rev-parse", "HEAD").strip()
    run_git(repository, "checkout", "-qb", "topic")
    run_git(repository, "commit", "--allow-empty", "-qm", "Topic")
    head = run_git(repository, "rev-parse", "HEAD").strip()
    run_git(repository, "checkout", "-q", "-")
    run_git(repository, "merge", "--no-ff", "-qm", f"Merge {head} into {base}", "topic")
    assert public_check.inspect_repository(repository) == []


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


MEDIA = "docs/assets/demo.gif"
MEDIA_BYTES = b"GIF89a\x00synthetic-approved-bytes" * 3


@pytest.fixture
def approved(monkeypatch):
    digest = hashlib.sha256(MEDIA_BYTES).hexdigest()
    monkeypatch.setitem(public_check.APPROVED_MEDIA, MEDIA, (len(MEDIA_BYTES), digest))


def commit_media(root: Path, name: str, data: bytes) -> None:
    target = root / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    run_git(root, "add", "-f", name)
    run_git(root, "commit", "-qm", "Add synthetic media")


def test_exact_approved_media_passes_index_working_and_history(repository, approved):
    commit_media(repository, MEDIA, MEDIA_BYTES)
    assert public_check.inspect_repository(repository) == []


@pytest.mark.parametrize(
    "data", [MEDIA_BYTES[:-1], MEDIA_BYTES[:-1] + b"X", b"benign text\n", b""]
)
def test_changed_or_truncated_media_fails_in_every_variant(repository, approved, data):
    commit_media(repository, MEDIA, data)
    issues = public_check.inspect_repository(repository)
    for source in ("index", "history", "working"):
        assert any(i.startswith(source) and "approved media" in i for i in issues)


def test_working_copy_of_approved_media_must_stay_exact(repository, approved):
    commit_media(repository, MEDIA, MEDIA_BYTES)
    (repository / MEDIA).write_text("benign\n", encoding="utf-8")
    issues = public_check.inspect_repository(repository)
    assert [i for i in issues if i.startswith("working")]
    assert not [i for i in issues if i.startswith("index")]


def test_approval_is_path_specific_even_for_identical_bytes(repository, approved):
    commit_media(repository, MEDIA, MEDIA_BYTES)
    for other in ("docs/assets/moved.gif", "docs/assets/demo.png", "docs/assets/copied.svg"):
        (repository / other).write_bytes(MEDIA_BYTES)
        run_git(repository, "add", "-f", other)
    run_git(repository, "commit", "-qm", "Copy media elsewhere")
    issues = public_check.inspect_repository(repository)
    for other in ("moved.gif", "demo.png", "copied.svg"):
        assert any(other in i for i in issues)
    assert not any("demo.gif" in i for i in issues)
    # An allowed text extension must still be rejected as binary content.
    assert any(
        "copied.svg" in i and "binary content is not allowed" in i
        for i in issues
    )


def test_hook_environment_cannot_mutate_a_separate_repository(repository, monkeypatch):
    parent = repository.parent / ("parent-" + uuid.uuid4().hex)
    parent.mkdir()
    try:
        run_git(parent, "init", "-q", "-b", "main")
        run_git(parent, "config", "user.name", "Parent Author")
        run_git(parent, "config", "user.email", "parent@" + "example.invalid")
        (parent / "a.md").write_text("parent\n", encoding="utf-8")
        run_git(parent, "add", ".")
        run_git(parent, "commit", "-qm", "Parent")
        git_dir = parent / ".git"
        before = (
            run_git(parent, "rev-parse", "HEAD"),
            run_git(parent, "for-each-ref"),
            (git_dir / "config").read_bytes(),
            (git_dir / "index").read_bytes(),
        )
        # Simulate a hook in a disposable parent: variables point at it, not the project.
        monkeypatch.setenv("GIT_DIR", str(git_dir))
        monkeypatch.setenv("GIT_WORK_TREE", str(parent))
        monkeypatch.setenv("GIT_INDEX_FILE", str(git_dir / "index"))
        monkeypatch.setenv("GIT_COMMON_DIR", str(git_dir))
        monkeypatch.setenv("GIT_PREFIX", "")
        monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
        monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.bare")
        monkeypatch.setenv("GIT_CONFIG_VALUE_0", "true")
        before_child = run_git(repository, "rev-parse", "HEAD")
        run_git(repository, "config", "commit.gpgsign", "false")
        run_git(repository, "commit", "--allow-empty", "-qm", "Child only")
        assert run_git(repository, "rev-parse", "HEAD") != before_child
        assert public_check.inspect_repository(repository) == []
        after = (
            run_git(parent, "rev-parse", "HEAD"),
            run_git(parent, "for-each-ref"),
            (git_dir / "config").read_bytes(),
            (git_dir / "index").read_bytes(),
        )
        assert after == before
    finally:
        shutil.rmtree(parent, onexc=remove_readonly)


def test_unrelated_binary_remains_rejected(approved):
    assert public_check.content_issues(MEDIA_BYTES) == ["binary content is not allowed"]
    assert public_check.path_issues("docs/assets/other.gif")


def test_workflow_sync_svg_is_historical_only():
    name = "wizexpert/console/static/assets/workflow-sync.svg"
    assert public_check.path_issues(name, historical=True) == []
    assert public_check.path_issues(name)
    assert public_check.content_issues(("1" * 12).encode(), allow_bom=True)
