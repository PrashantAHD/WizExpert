import pytest

from wizexpert.__main__ import main


@pytest.mark.parametrize("arguments", [[], ["--help"], ["-h"]])
def test_no_arguments_or_help_prints_usage_and_succeeds(arguments, capsys):
    assert main(arguments) == 0
    out = capsys.readouterr().out
    for command in ("workflow-qa", "email-qa", "campaign", "governance"):
        assert command in out


@pytest.mark.parametrize("arguments", [["workflow"], ["update-remediation"], ["report.csv"]])
def test_unknown_command_fails_with_usage(arguments, capsys):
    assert main(arguments) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "usage: wizexpert" in captured.err
