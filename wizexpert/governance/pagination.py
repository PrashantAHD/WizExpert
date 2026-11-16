"""Resumable, lossless pagination for read-only Wiz collection responses."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from wizexpert.governance.dashboard_data import require

LIST_ISSUES_PAGE_SIZE = 500  # Monthly rule MG-COL-02


def _query_hash(query: Mapping[str, Any]) -> str:
    encoded = json.dumps(dict(query), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _write(path: Path, data: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def paginate(
    fetch: Callable[[dict[str, Any]], Mapping[str, Any]],
    query: Mapping[str, Any],
    output_dir: Path,
    *,
    page_size: int = LIST_ISSUES_PAGE_SIZE,
) -> dict[str, Any]:
    """Fetch and persist every page, resuming from a prior manifest when present.

    ``fetch`` must perform one read-only request and return the decoded Wiz response.
    A failed or interrupted run leaves its completed pages and cursor in the manifest.
    """
    require(
        page_size == LIST_ISSUES_PAGE_SIZE,
        f"MG-COL-02: every list_issues page must use first={LIST_ISSUES_PAGE_SIZE}; "
        f"got {page_size!r}.",
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "collection-manifest.json"
    activity_path = output_dir / "activity.jsonl"
    query_data = dict(query)
    query_data["first"] = page_size
    identity = _query_hash(query_data)
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        saved_query = manifest.get("query")
        require(
            isinstance(saved_query, Mapping)
            and saved_query.get("first") == LIST_ISSUES_PAGE_SIZE,
            f"MG-COL-02: saved pagination query must use first={LIST_ISSUES_PAGE_SIZE}.",
        )
        require(manifest.get("query_sha256") == identity, "Saved pagination query does not match.")
        pages = manifest.get("pages", [])
        require(isinstance(pages, list), "Saved pagination pages are invalid.")
    else:
        pages = []
        manifest = {
            "schema_version": 1,
            "query": query_data,
            "query_sha256": identity,
            "pages": pages,
            "complete": False,
        }

    if manifest.get("complete") is True and pages and pages[-1].get("has_next_page") is False:
        require(
            manifest.get("rows") == manifest.get("total_count")
            == sum(page.get("rows", 0) for page in pages),
            "Saved complete pagination manifest does not reconcile.",
        )
        return manifest
    last_terminal = bool(pages) and pages[-1].get("has_next_page") is False
    require(
        not (last_terminal and manifest.get("complete") is not True),
        "Saved pagination manifest is terminal but incomplete.",
    )
    seen_cursors = {page.get("end_cursor") for page in pages}
    seen_ids: set[str] = set()
    for page in pages:
        saved = json.loads(Path(page["path"]).read_text(encoding="utf-8"))
        for node in saved["issues"]["nodes"]:
            if isinstance(node, Mapping) and node.get("id") is not None:
                require(node["id"] not in seen_ids, "Saved pagination pages repeat an issue ID.")
                seen_ids.add(node["id"])
    total_count = manifest.get("total_count")
    after = pages[-1].get("end_cursor") if pages else None
    while True:
        params = dict(query_data)
        if after:
            params["after"] = after
        response = dict(fetch(params))
        issues = response.get("issues")
        require(isinstance(issues, Mapping), "Wiz response has no issues object.")
        nodes = issues.get("nodes")
        page_info = issues.get("pageInfo")
        observed_total = issues.get("totalCount")
        require(isinstance(nodes, list), "Wiz response nodes are invalid.")
        require(isinstance(page_info, Mapping), "Wiz response pageInfo is invalid.")
        require(type(observed_total) is int and observed_total >= 0, "Wiz totalCount is invalid.")
        if total_count is None:
            total_count = observed_total
        require(observed_total == total_count, "Wiz totalCount changed during pagination.")
        for node in nodes:
            node_id = node.get("id") if isinstance(node, Mapping) else None
            require(node_id is not None, "Wiz response node has no issue ID.")
            require(node_id not in seen_ids, "Wiz pagination repeated an issue ID.")
            seen_ids.add(node_id)
        has_next = page_info.get("hasNextPage")
        require(type(has_next) is bool, "Wiz pageInfo.hasNextPage is not a boolean.")
        require(nodes or not has_next, "Wiz returned an empty page with hasNextPage true.")
        end_cursor = page_info.get("endCursor")
        if has_next:
            require(isinstance(end_cursor, str) and end_cursor, "Next page has no end cursor.")
            require(end_cursor not in seen_cursors, "Wiz pagination repeated a cursor.")
        page_number = len(pages) + 1
        page_path = output_dir / f"page-{page_number:04d}.raw.json"
        require(not page_path.exists(), f"Pagination page already exists: {page_path}")
        _write(page_path, response)
        pages.append(
            {
                "number": page_number,
                "path": str(page_path.resolve()),
                "rows": len(nodes),
                "end_cursor": end_cursor,
                "has_next_page": has_next,
            }
        )
        manifest.update(
            {
                "total_count": total_count,
                "rows": sum(page["rows"] for page in pages),
                "pages": pages,
                "complete": not has_next and sum(page["rows"] for page in pages) == total_count,
            }
        )
        _write(manifest_path, manifest)
        with activity_path.open("a", encoding="utf-8") as stream:
            stream.write(
                json.dumps(
                    {
                        "page": page_number,
                        "query_sha256": identity,
                        "rows": len(nodes),
                        "total_count": total_count,
                        "end_cursor": end_cursor,
                        "has_next_page": has_next,
                    }
                )
                + "\n"
            )
        if not has_next:
            require(manifest["complete"], "Terminal page count does not equal totalCount.")
            return manifest
        seen_cursors.add(end_cursor)
        after = end_cursor
