import json

import pytest

from wizexpert.governance.dashboard_data import DashboardError
from wizexpert.governance.pagination import paginate


def response(nodes, total, cursor, more):
    return {
        "issues": {
            "nodes": nodes,
            "pageInfo": {"endCursor": cursor, "hasNextPage": more},
            "totalCount": total,
        }
    }


def test_paginates_and_persists_all_pages(tmp_path):
    pages = {
        None: response([{"id": "a"}], 2, "c1", True),
        "c1": response([{"id": "b"}], 2, "c2", False),
    }
    calls = []

    result = paginate(
        lambda params: calls.append(params) or pages[params.get("after")],
        {"status": ["OPEN"]},
        tmp_path,
    )

    assert result["complete"] is True
    assert result["rows"] == 2
    assert [call.get("after") for call in calls] == [None, "c1"]
    assert (tmp_path / "page-0002.raw.json").is_file()
    assert len((tmp_path / "activity.jsonl").read_text(encoding="utf-8").splitlines()) == 2


def test_resumes_from_saved_cursor(tmp_path):
    first = response([{"id": "a"}], 2, "c1", True)
    calls = 0

    def interrupted(params):
        nonlocal calls
        calls += 1
        if calls == 1:
            return first
        raise RuntimeError("interrupted")

    with pytest.raises(RuntimeError, match="interrupted"):
        paginate(interrupted, {"status": ["OPEN"]}, tmp_path, page_size=500)

    def resumed(params):
        assert params["after"] == "c1"
        assert params["first"] == 500
        return response([{"id": "b"}], 2, "c2", False)

    result = paginate(resumed, {"status": ["OPEN"]}, tmp_path, page_size=500)
    assert result["complete"] is True


def test_rejects_page_size_20(tmp_path):
    with pytest.raises(DashboardError, match="MG-COL-02"):
        paginate(lambda params: {}, {"status": ["OPEN"]}, tmp_path, page_size=20)


def test_resume_with_first_20_identity_fails(tmp_path):
    query = {"status": ["OPEN"], "first": 20}
    (tmp_path / "collection-manifest.json").write_text(
        json.dumps({"query": query, "query_sha256": "x", "pages": [], "complete": False}),
        encoding="utf-8",
    )
    with pytest.raises(DashboardError, match="MG-COL-02"):
        paginate(lambda params: {}, {"status": ["OPEN"]}, tmp_path)


@pytest.mark.parametrize(
    "page",
    [
        response([{"id": "a"}], 2, None, True),
        response([{"id": "a"}], 1, "c1", True),
    ],
)
def test_invalid_pagination_fails_closed(tmp_path, page):
    with pytest.raises(DashboardError):
        paginate(lambda params: page, {"status": ["OPEN"]}, tmp_path)


def test_total_count_mismatch_fails_closed(tmp_path):
    pages = {
        None: response([{"id": "a"}], 2, "c1", True),
        "c1": response([{"id": "b"}], 3, None, False),
    }
    with pytest.raises(Exception, match="totalCount changed"):
        paginate(lambda params: pages[params.get("after")], {"status": ["OPEN"]}, tmp_path)
