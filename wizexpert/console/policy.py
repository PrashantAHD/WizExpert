"""Read-only policy for every Wiz MCP call the console makes.

Only the MCP tools ``discover`` and ``execute`` are allowed. ``execute`` may run only
read-style operations: the inner tool name must be a known read verb (or an allow-listed
read tool) and must not contain a write verb, and no argument may carry a GraphQL
``mutation``. Anything else is refused before any network traffic.
"""

from __future__ import annotations

import re
from typing import Any

ALLOWED_MCP_TOOLS = frozenset({"discover", "execute"})
READ_PREFIXES = (
    "get_",
    "list_",
    "search_",
    "describe_",
    "count_",
    "find_",
    "lookup_",
    "query_",
    "read_",
    "fetch_",
    "explain_",
    "show_",
)
EXTRA_READ_TOOLS = frozenset({"execute_graph_query", "graph_search"})
_WRITE_VERBS = (
    "create|update|delete|remove|add|set|assign|unassign|resolve|reject|ignore|close|reopen|"
    "snooze|dismiss|approve|send|post|patch|put|write|modify|edit|apply|remediate|trigger|"
    "mutate|mutation|comment|tag|untag|link|unlink|enable|disable|import|upload|invite|revoke|"
    "grant|rotate|reset|restore|archive|cancel|start|stop|run|deploy|attach|detach|merge|"
    "escalate|acknowledge|notify|email|sync|submit|publish|save|clone|copy|move|rename"
)
_WRITE_NAME = re.compile(rf"(?:^|_)(?:{_WRITE_VERBS})(?:_|$)")
_TOOL_NAME = re.compile(r"[a-z][a-z0-9_]{1,80}")
_MUTATION = re.compile(r"\bmutation\b", re.IGNORECASE)
_DOMAIN = re.compile(r"[A-Za-z0-9_ .\-]{0,80}")
MAX_DEPTH = 12
MAX_NODES = 5_000


class ReadOnlyViolation(Exception):
    """A call was refused because it is not a plain read-only Wiz query."""


def check_mcp_tool(name: Any) -> None:
    if name not in ALLOWED_MCP_TOOLS:
        raise ReadOnlyViolation(f"MCP tool {name!r} is not allowed (only discover and execute).")


def check_execute(tool_name: Any, parameters: Any) -> None:
    """Raise ReadOnlyViolation unless this is a read-only ``execute`` request."""
    if not isinstance(tool_name, str) or not _TOOL_NAME.fullmatch(tool_name):
        raise ReadOnlyViolation("Invalid Wiz tool name.")
    if tool_name not in EXTRA_READ_TOOLS:
        if not tool_name.startswith(READ_PREFIXES):
            raise ReadOnlyViolation(f"Wiz tool {tool_name!r} is not a read-only operation.")
        if _WRITE_NAME.search(tool_name):
            raise ReadOnlyViolation(f"Wiz tool {tool_name!r} looks like a write operation.")
    if parameters is None:
        parameters = {}
    if not isinstance(parameters, dict):
        raise ReadOnlyViolation("Wiz parameters must be an object.")
    _scan(parameters, 0, [0])


def check_discover(domain: Any) -> None:
    if domain is not None and (not isinstance(domain, str) or not _DOMAIN.fullmatch(domain)):
        raise ReadOnlyViolation("Invalid discover domain.")


def _scan(value: Any, depth: int, counter: list[int]) -> None:
    counter[0] += 1
    if depth > MAX_DEPTH or counter[0] > MAX_NODES:
        raise ReadOnlyViolation("Wiz parameters are too deeply nested or too large.")
    if isinstance(value, str):
        if _MUTATION.search(value):
            raise ReadOnlyViolation("GraphQL mutations are refused (read-only console).")
    elif isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ReadOnlyViolation("Wiz parameter keys must be text.")
            _scan(key, depth + 1, counter)
            _scan(item, depth + 1, counter)
    elif isinstance(value, list | tuple):
        for item in value:
            _scan(item, depth + 1, counter)
    elif value is not None and not isinstance(value, int | float | bool):
        raise ReadOnlyViolation("Unsupported value type in Wiz parameters.")
