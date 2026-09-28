# Publication safety

This repository is for public CLI source and synthetic tests only.
Never stage operational workbooks, reports, credentials, account identifiers, real
findings, screenshots, logs, databases, or deployment configuration. Keep runtime
inputs and outputs outside this repository. Ignore rules are not a security
boundary: an ignored file can still be force-added.

## Local verification and push gate

Create `.venv` and install the development extra (`python -m pip install -e
".[dev]"`). Install the hook **for this repository only**:

```powershell
git config --local core.hooksPath .githooks
git update-index --chmod=+x .githooks/pre-push
.\.venv\Scripts\python.exe scripts\verify.py
```

The chmod command applies after the hook has been staged. On Unix also run
`chmod +x .githooks/pre-push`. No global Git configuration is needed. Clones do
not inherit local hook configuration; each contributor must install it.

`verify.py` requires all of these to succeed, stopping on any error:

1. Offline public-content guard.
2. Pytest (synthetic fixtures only).
3. Ruff.
4. Bandit on application and verification source.

The pre-push hook also requires the metadata-only dependency audit below.
**Installing this hook opts normal pushes into that outbound audit.** A failed
check, missing tool, unavailable audit service, or detected vulnerability blocks
the push. Ordinary local verification does not perform an outbound audit:

```powershell
.\.venv\Scripts\python.exe scripts\verify.py --audit-dependencies
```

The hook invokes the repository's `.venv` Python directly on Windows and Unix.
It does not require PowerShell or change script execution policy. On Unix the
equivalent command is `.venv/bin/python scripts/verify.py`. `verify.ps1` is only
an optional thin wrapper for environments where existing policy permits it;
use the Python entry point when PowerShell scripts are disabled.

No verification command automatically commits or pushes. Git hooks are local
and bypassable (for example with `--no-verify`, a different hooks path, or a
client that ignores hooks). They cannot provide server-side enforcement.
Configure protected branches and require the `verify` CI check where available.
CI only runs **after** source has reached GitHub, so it cannot undo a disclosure.

CSV-report test cleanup retries Windows sharing/lock violations (codes 32/33)
for at most five attempts, with 3.1 seconds of total delay. Persistent locks and
all other cleanup errors still fail validation. This does not retry production
workbook writes, ignore test failures or bypass any push checks.

## What is inspected

`scripts/public_check.py` inspects the current contents of tracked files, every
index entry (including staged content different from the working copy), commit
messages, and file snapshots throughout **all reachable local history**. This
includes remote-tracking refs and files deleted in later commits. The hook also
passes the exact outgoing tips, covering detached commits and explicit SHA
refspecs. This conservative policy may reject unrelated local historical refs.
Shallow repositories fail closed; fetch complete history before checking.

Only the root project metadata files explicitly listed in the guard,
application source under `remediation`, Python tests under `tests`, Python and
PowerShell tools under `scripts`, Markdown under `docs`, workflow YAML directly
under `.github/workflows`, the exact instruction file
`.github/instructions/production-workflow.instructions.md`, and the pre-push
hook are allowed. Other instruction paths are not implicitly allowed. File names and
contents are checked independently. References to spreadsheet extensions in
source are allowed; actual spreadsheet, CSV, JSON data, database, environment,
archive, binary, and log files are not. Symlinks, submodules, non-UTF-8 text, and
files larger than 1 MB are rejected. The scanner reports categories, not matched
secret values.

Heuristics reject likely private keys, common service tokens, credential
assignments, AWS account identifiers and resource names, Azure subscription
resource paths, email addresses, and a restricted organization-name marker.
Do not weaken these checks to accommodate real data. Synthetic tests construct
representative patterns at runtime rather than storing complete examples.
Commit-message email checks permit only the exact standard Copilot public
co-author attribution as a final, separate trailer. This exception does not
apply to source files, other email addresses, modified trailers or other
sensitive patterns. Use a GitHub noreply identity for public author/committer
metadata when a work address should remain private.

Untracked files, reflog-only/unreachable objects, arbitrary prose identifying
other organizations or people, encoded/obfuscated secrets, and Git metadata
such as author identities are not comprehensively classified. A passing guard
**does not prove absence of private data**.

## Mandatory manual review before every public push

1. Review `git status --short`, `git diff`, and `git diff --cached`. Explicitly
   inspect new/untracked files before staging: the default guard does not scan
   them. Stage only intended public source; run verification again after staging.
2. Inspect outgoing commits and their full patches, not just the final files.
   Use `git log --all --stat` and `git log --all -p` for the initial publication;
   use the relevant remote branch range for later reviews. Include tag messages,
   commit messages, author identities, deleted files, and renamed files.
3. Check every fixture is synthetic, inspect any dependency URLs for private
   registries or credentials, and confirm no local input/output artifacts are
   staged.
4. If sensitive material was ever committed, stop. Removing it in a later commit
   is insufficient. Rotate exposed credentials and remove the material from
   every outgoing ref/history before publication. Verify again and manually
   review the rewritten history. Do not automatically force-push a cleanup.
5. Only after explicit human approval perform the intended `git push`.

## Precisely what the optional audit sends

The verifier first builds an offline inventory using Python's installed
distribution metadata, omitting editable installations and retaining only
validated names and exact versions (never local paths, source, or URLs).
It writes this inventory to a unique file beneath the repository's ignored
`.pytest_cache` directory, then deletes it even if the audit fails.
`python -m pip_audit --requirement <inventory> --disable-pip --no-deps
--strict --progress-spinner off` audits it against the default public PyPI
vulnerability service. It queries **distribution names and
versions**; it does not upload repository source, workbook contents, reports,
or private files. Normal network metadata (for example IP address and HTTP
headers) is also visible to the service. `--disable-pip --no-deps` prevents pip
dependency resolution/build execution; the inventory excludes this locally
installed editable application. `--strict` also fails on collection errors.
Use a dedicated virtual environment containing
only this project's public dependencies: private package names/versions would
otherwise also be disclosed. Do not change this command to audit private
requirements, private package lists, or remote project URLs.

Installing packages is a separate outbound package-download operation. Neither
offline verification nor its guard installs packages. CI installs public
dependencies and runs offline checks only, without audit, caches, artifacts,
deployment credentials, telemetry uploads, or access to local private data.
Its GitHub actions are pinned to full upstream commit IDs and its token has
read-only contents permission.
