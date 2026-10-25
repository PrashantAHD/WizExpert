import subprocess  # nosec B404
import sys

import pytest

CHECK = (
    "import wizexpert, openpyxl.xml.functions as f, openpyxl;"
    "print(openpyxl.LXML, openpyxl.DEFUSEDXML, f.fromstring.__module__)"
)


def test_workbooks_are_parsed_with_defusedxml_even_when_lxml_is_installed():
    pytest.importorskip("lxml")
    # A fresh interpreter proves the setting applies before openpyxl's first import.
    result = subprocess.run(  # nosec B603
        [sys.executable, "-c", CHECK], capture_output=True, text=True, check=True
    )
    lxml, defused, parser = result.stdout.split()
    assert (lxml, defused) == ("False", "True")
    assert parser.startswith("defusedxml.")
