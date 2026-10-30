"""WizExpert: local cloud security reporting, QA and governance support."""

import os

# python-pptx (governance extra) installs lxml, which openpyxl would otherwise prefer over
# defusedxml when reading workbooks. Pin openpyxl to its defusedxml parser before it loads.
os.environ["OPENPYXL_LXML"] = "False"
