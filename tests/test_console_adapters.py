"""Adapter loading, field coercion and static-asset hygiene."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from wizexpert.console import server
from wizexpert.console.adapters import AdapterError, Field, coerce_fields, load_adapters

STATIC = Path(server.__file__).parent / "static"


def make_private_root(tmp_path: Path, body: str) -> Path:
    folder = tmp_path / "templates" / "console_adapters"
    folder.mkdir(parents=True)
    (folder / "adapters.py").write_text(body, encoding="utf-8")
    return tmp_path


def test_load_adapters_from_private_root(tmp_path):
    root = make_private_root(
        tmp_path,
        "from pathlib import Path\n"
        "from console_fakes import FakeAdapter\n"
        "def get_adapters(root):\n    return [FakeAdapter(Path(root) / 'deliverables')]\n",
    )
    adapters = load_adapters(root)
    assert list(adapters) == ["daily-progress-reporting"]


@pytest.mark.parametrize(
    "body",
    [
        "x = 1\n",
        "def get_adapters(root):\n    return []\n",
        "def get_adapters(root):\n    return [object()]\n",
    ],
)
def test_bad_private_adapter_modules_are_rejected(tmp_path, body):
    with pytest.raises(AdapterError):
        load_adapters(make_private_root(tmp_path, body))


def test_missing_private_adapters_fail_clearly(tmp_path):
    with pytest.raises(AdapterError, match="No private adapters"):
        load_adapters(tmp_path)


def test_cli_refuses_to_start_without_adapters(tmp_path):
    with pytest.raises(SystemExit) as info:
        server.main(["--private-root", str(tmp_path), "--no-browser", "--port", "0"])
    assert info.value.code == 1


def test_cli_rejects_a_bad_port(tmp_path):
    with pytest.raises(SystemExit):
        server.main(["--private-root", str(tmp_path), "--port", "70000"])


def test_field_coercion_rules():
    specs = [
        Field("a", "A", required=True),
        Field("s", "S", kind="select", options=("x", "y")),
        Field("rows", "Rows", kind="list", item_keys=("k", "v"), min_items=1, max_items=2),
        Field("flag", "Flag", kind="bool"),
    ]
    ok = coerce_fields(
        specs, {"a": " hi ", "s": "x", "rows": [{"k": "1"}, {"k": "", "v": ""}], "flag": 1}
    )
    assert ok == {"a": "hi", "s": "x", "rows": [{"k": "1", "v": ""}], "flag": True}
    for bad in (
        {"zzz": 1, "a": "x", "rows": [{"k": "1"}]},
        {"a": "", "rows": [{"k": "1"}]},
        {"a": "x", "s": "nope", "rows": [{"k": "1"}]},
        {"a": "x", "rows": []},
        {"a": "x", "rows": [{"k": "1"}] * 3},
        {"a": "x", "rows": [{"bad": "1"}]},
        {"a": "x", "rows": [{"k": 5}]},
        {"a": 5, "rows": [{"k": "1"}]},
    ):
        with pytest.raises(AdapterError):
            coerce_fields(specs, bad)
    assert coerce_fields(specs, {}, partial=True)["rows"] == []


def test_static_assets_never_inject_markup_or_run_dynamic_code():
    script = (STATIC / "app.js").read_text(encoding="utf-8")
    for banned in (
        "innerHTML",
        "outerHTML",
        "insertAdjacentHTML",
        "document.write",
        "eval(",
        "new Function",
    ):
        assert banned not in script
    page = (STATIC / "index.html").read_text(encoding="utf-8")
    assert not re.search(r"<script(?![^>]*\bsrc=)", page)  # no inline script
    assert not re.search(r"\son\w+=", page) and "javascript:" not in page
    assert "http://" not in page and "https://" not in page  # no third-party resources
