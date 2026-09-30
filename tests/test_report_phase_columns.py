import pytest

from remediation.csv_layout import follow_up_columns


def test_initial_report_omits_follow_up_columns():
    assert follow_up_columns() == ()


def test_reviewed_response_enables_follow_up_columns():
    assert follow_up_columns("Private approval response reference") == (
        "Blocker", "Next Action",
    )


@pytest.mark.parametrize("reference", ["", "  ", "\t", False, 1, "invalid\x00reference"])
def test_invalid_reference_does_not_enable_follow_up_columns(reference):
    with pytest.raises(ValueError):
        follow_up_columns(reference)
