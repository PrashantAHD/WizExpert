"""Canonical comparison of complete Office packages without optional presentation imports."""

from pathlib import Path

# Canonicalization receives only trees already parsed with defusedxml.
from xml.etree import ElementTree  # nosec B405
from zipfile import ZipFile

from defusedxml.ElementTree import fromstring


def package_signature(path: Path) -> dict[str, bytes]:
    """Compare every part except ZIP metadata and core save timestamps."""
    result = {}
    with ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError(f"Duplicate Office package parts: {path}")
        for name in names:
            content = archive.read(name)
            if name.endswith((".xml", ".rels")):
                root = fromstring(content)
                if name == "docProps/core.xml":
                    for tag in ("created", "modified"):
                        for element in root.findall(f"{{http://purl.org/dc/terms/}}{tag}"):
                            root.remove(element)
                content = ElementTree.canonicalize(
                    ElementTree.tostring(root), rewrite_prefixes=True
                ).encode()
            result[name] = content
    return result
