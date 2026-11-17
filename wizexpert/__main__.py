"""Command-line entry point: QA checks, PHP2Shell campaign and governance reporting."""

import sys
from collections.abc import Sequence

USAGE = (
    "usage: wizexpert {workflow-qa,email-qa,follow-up-email,campaign,governance,rules,console} "
    "[options]\n\n"
    "  rules        list the end-to-end workflow rules of a category (wizexpert rules <category>)\n"
    "  workflow-qa  validate evidence-bound workflow QA reviews\n"
    "  email-qa     check an email draft against its reviewed contract\n"
    "  campaign     PHP2Shell campaign reporting\n"
    "  governance   monthly governance reporting (needs the governance extra)\n"
    "  console      local frontend that starts a VS Code agent-mode chat (see docs/CONSOLE.md)\n\n"
    "The Risk Issues (wiz-issue-rule-id) workflow is being rebuilt.\n"
)
GOVERNANCE_COMMANDS = {
    "setup": "wizexpert.governance.profile",
    "workbook": "wizexpert.governance.wiz_report",
    "dashboard": "wizexpert.governance.dashboard",
    "monthly": "wizexpert.governance.monthly",
    "deck": "wizexpert.governance.governance",
    "snapshot": "wizexpert.governance.snapshot_build",
    "verify": "wizexpert.governance.verify",
    "reconcile": "wizexpert.governance.reconcile",
    "collect": "wizexpert.governance.collection_gate",
    "rules": "wizexpert.governance.workflow_rules",
}
GOVERNANCE_USAGE = (
    "usage: wizexpert governance "
    "{setup,workbook,dashboard,monthly,deck,snapshot,verify,reconcile,collect,rules} [options]\n\n"
    "  setup      create or update the client profile (client name, snapshot day, baseline, logo)\n"
    "  workbook   build or modify the governance Excel workbook from Wiz CSV exports\n"
    "  dashboard  build the executive dashboard deck from a reviewed workbook\n"
    "  monthly    create or refresh the month's workbook + dashboard pair, with backups\n"
    "  deck       build the ten-slide operational governance deck from a reviewed snapshot\n"
    "  snapshot   build the operational snapshot JSON from reviewed CSV + grouped Wiz responses\n"
    "  verify     replay and check the report set without modifying it (not release approval)\n\n"
    "  reconcile  check collection plans and reconcile retained/fresh issue evidence\n\n"
    "  collect    derive the delta plan and gate fresh read-only collection\n\n"
    "  rules      list the canonical end-to-end Monthly workflow rules (--json for JSON)\n\n"
    'Requires the governance extra: pip install "wizexpert[governance]"\n'
)


def governance_main(arguments: list[str]) -> int:
    if not arguments or arguments[0] not in GOVERNANCE_COMMANDS:
        print(GOVERNANCE_USAGE, file=sys.stderr if arguments else sys.stdout, end="")
        return 0 if not arguments or arguments[0] in {"-h", "--help"} else 2
    from importlib import import_module

    command, rest = arguments[0], arguments[1:]
    try:
        module = import_module(GOVERNANCE_COMMANDS[command])
    except ModuleNotFoundError as error:
        print(
            f"Governance reporting needs an optional dependency ({error.name}). "
            'Install it with: pip install "wizexpert[governance]"',
            file=sys.stderr,
        )
        return 2
    original = sys.argv
    # Some governance commands read sys.argv directly; present them their own command line.
    sys.argv = [f"wizexpert governance {command}", *rest]
    try:
        result = (
            module.main(rest)
            if command in {"setup", "deck", "snapshot", "verify", "reconcile", "collect", "rules"}
            else module.main()
        )
    finally:
        sys.argv = original
    return result or 0


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    command = arguments[0] if arguments else None
    if command == "workflow-qa":
        from wizexpert.workflow_qa import main as qa_main

        return qa_main(arguments[1:])
    if command == "email-qa":
        from wizexpert.email_qa import main as email_qa_main

        return email_qa_main(arguments[1:])
    if command == "follow-up-email":
        from wizexpert.follow_up_email import main as follow_up_main

        return follow_up_main(arguments[1:])
    if command == "governance":
        return governance_main(arguments[1:])
    if command == "rules":
        from wizexpert.category_rules import main as rules_main

        return rules_main(arguments[1:])
    if command == "campaign":
        from wizexpert.campaign import main as campaign_main

        return campaign_main(arguments[1:])
    if command == "console":
        from wizexpert.console.server import main as console_main

        return console_main(arguments[1:])
    known_help = command is None or command in {"-h", "--help"}
    print(USAGE, file=sys.stdout if known_help else sys.stderr, end="")
    return 0 if known_help else 2


if __name__ == "__main__":
    raise SystemExit(main())
