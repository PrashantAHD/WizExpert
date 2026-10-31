from __future__ import annotations

import hashlib
import re
import zipfile
from pathlib import Path

import pytest
from openpyxl import load_workbook
from pptx import Presentation
from pptx.util import Inches

from wizexpert.governance import categories as cat
from wizexpert.governance import monthly_templates as mt
from wizexpert.governance.category_pipeline import SlotBinding, run_category_pipeline

REPO = Path(__file__).resolve().parents[1]
CLIENT = "care" + "first"
SLOTS = [mt.WORKBOOK_SLOT, mt.OPERATIONAL_SLOT, mt.EXECUTIVE_SLOT]


@pytest.fixture
def built(tmp_path):
    return mt.build_all(tmp_path / "out")


def _deck_text(path):
    return [[s.text_frame.text for s in sl.shapes if s.has_text_frame]
            for sl in Presentation(str(path)).slides]


def _wb_text(path):
    wb = load_workbook(path)
    return [[(c.coordinate, c.value) for row in ws.iter_rows() for c in row if c.value]
            for ws in wb]


def test_slots_match_category():
    assert [s.slot_id for s in cat.MONTHLY_GOVERNANCE.slots] == SLOTS
    assert set(mt.BUILDERS) == set(mt.VALIDATORS) == set(SLOTS)


def test_build_and_validate(built):
    assert mt.validate_all(built) == {slot: [] for slot in SLOTS}
    assert len(load_workbook(built[mt.WORKBOOK_SLOT]).sheetnames) == 6
    assert len(Presentation(str(built[mt.OPERATIONAL_SLOT])).slides) == 10
    assert len(Presentation(str(built[mt.EXECUTIVE_SLOT])).slides) == 3
    prs = Presentation(str(built[mt.OPERATIONAL_SLOT]))
    assert prs.slide_width == Inches(13.333) and prs.slide_height == Inches(7.5)


def test_schema_matches_files_and_severities(built):
    sch = mt.schema()
    assert sch["template_version"] == 1
    for slot in SLOTS:
        assert built[slot].name == sch[slot]["file"]
    wb = load_workbook(built[mt.WORKBOOK_SLOT])
    assert wb.sheetnames == [t["sheet"] for t in sch[mt.WORKBOOK_SLOT]["tabs"]]
    assert all(t["columns"] == 8 for t in sch[mt.WORKBOOK_SLOT]["tabs"])
    first = _wb_text(built[mt.WORKBOOK_SLOT])[0]
    for name in sch[mt.WORKBOOK_SLOT]["scalars"]:
        assert (f"B{sch[mt.WORKBOOK_SLOT]['scalars'].index(name) + 1}", "{{" + name + "}}") in first
    for slot in (mt.OPERATIONAL_SLOT, mt.EXECUTIVE_SLOT):
        texts = _deck_text(built[slot])
        specs = sch[slot]["slides"]
        assert len(texts) == len(specs)
        for text, spec in zip(texts, specs, strict=True):
            assert text == [spec["title"], *spec["fields"], sch[slot]["footer"]]
    assert sch[mt.OPERATIONAL_SLOT]["severities"] == ["Critical", "High", "Medium", "Low"]
    assert sch[mt.EXECUTIVE_SLOT]["severities"] == ["Critical", "High"]


def test_reproducible(tmp_path):
    a = mt.build_all(tmp_path / "a")
    b = mt.build_all(tmp_path / "b")
    assert _wb_text(a[mt.WORKBOOK_SLOT]) == _wb_text(b[mt.WORKBOOK_SLOT])
    for slot in (mt.OPERATIONAL_SLOT, mt.EXECUTIVE_SLOT):
        assert _deck_text(a[slot]) == _deck_text(b[slot])
    assert mt.schema() == mt.schema()
    props = load_workbook(a[mt.WORKBOOK_SLOT]).properties
    assert props.creator == mt.CREATOR and props.created == mt.FIXED_TIME


def _edit_deck(path, fn):
    prs = Presentation(str(path))
    fn(prs)
    prs.save(str(path))


def _edit_wb(path, fn):
    wb = load_workbook(path)
    fn(wb)
    wb.save(path)


def test_rejects_extra_slide(built):
    path = built[mt.EXECUTIVE_SLOT]
    _edit_deck(path, lambda p: p.slides.add_slide(p.slide_layouts[6]))
    assert any("expected 3 slides" in x for x in mt.validate_executive_dashboard(path))


def test_rejects_missing_placeholder(built):
    def drop(p):
        p.slides[0].shapes[1].text_frame.text = "{{other_field}}"

    path = built[mt.OPERATIONAL_SLOT]
    _edit_deck(path, drop)
    assert any("missing placeholder" in x for x in mt.validate_operational_deck(path))

    wpath = built[mt.WORKBOOK_SLOT]
    _edit_wb(wpath, lambda wb: wb["Tab 2 Placeholder"].__setitem__("A3", None))
    assert any("tab_2_empty_message" in x for x in mt.validate_workbook(wpath))


@pytest.mark.parametrize("bad,needle", [
    ("ref 1234567", "account-like"),
    ("name" + "@example.org", "email"),
    ("C:\\work\\file", "private path"),
    ("/home/someone/x", "private path"),
    ("\\\\server\\share\\x", "private path"),
    (CLIENT.upper() + " Corp", "restricted name"),
    ("see " + "https://example.org", "URL"),
    ("CVE-2024-1", "CVE"),
    ("wc-id-12", "workload"),
])
def test_rejects_private_content(built, bad, needle):
    path = built[mt.OPERATIONAL_SLOT]
    _edit_deck(path, lambda p: setattr(p.slides[2].shapes[1].text_frame, "text", bad))
    problems = mt.validate_operational_deck(path)
    assert any(needle in x for x in problems), problems
    wpath = built[mt.WORKBOOK_SLOT]
    _edit_wb(wpath, lambda wb: wb["Tab 3 Placeholder"].__setitem__("A5", bad))
    assert any(needle in x for x in mt.validate_workbook(wpath))


def test_rejects_workbook_order_and_creator(built):
    wpath = built[mt.WORKBOOK_SLOT]
    _edit_wb(wpath, lambda wb: wb.move_sheet("Tab 6 Placeholder", offset=-5))
    assert any("sheet order" in x for x in mt.validate_workbook(wpath))

    def creator(wb):
        wb.properties.creator = "Someone"

    wpath2 = mt.build_workbook(wpath.parent / "again")
    _edit_wb(wpath2, creator)
    assert any("creator" in x for x in mt.validate_workbook(wpath2))
    dpath = built[mt.EXECUTIVE_SLOT]
    _edit_deck(dpath, lambda p: setattr(p.core_properties, "author", "Someone"))
    assert any("author" in x for x in mt.validate_executive_dashboard(dpath))


def test_rejects_picture(built, tmp_path):
    from PIL import Image

    img = tmp_path / "pic.png"
    Image.new("RGB", (4, 4)).save(img)
    path = built[mt.EXECUTIVE_SLOT]
    _edit_deck(path, lambda p: p.slides[0].shapes.add_picture(str(img), 0, 0))
    assert any("picture" in x for x in mt.validate_executive_dashboard(path))


def test_non_placeholder_text_flagged(built):
    path = built[mt.EXECUTIVE_SLOT]
    _edit_deck(path, lambda p: setattr(p.slides[1].shapes[0].text_frame, "text", "Hello"))
    assert any("non-placeholder" in x for x in mt.validate_executive_dashboard(path))


def test_pipeline_wiring(tmp_path):
    category = cat.CATEGORIES["monthly-governance-reporting"]
    out = tmp_path / "run"
    first = {s: mt.BUILDERS[s](tmp_path / "probe") for s in SLOTS}
    qa = {
        "workflow_qa": "passed",
        "review": "passed",
        "category_id": category.category_id,
        "version": category.version,
        "slots": SLOTS,
        "template_sha256": {s: "a" * 64 for s in SLOTS},
        "outputs_sha256": {
            s: hashlib.sha256(p.read_bytes()).hexdigest() for s, p in first.items()
        },
    }
    def replay(slot):  # zip timestamps vary per build, so replay the hashed probe bytes
        def build(out_dir):
            out_dir.mkdir(parents=True, exist_ok=True)
            target = out_dir / first[slot].name
            target.write_bytes(first[slot].read_bytes())
            return target

        return build

    bindings = {s: SlotBinding("a" * 64, replay(s), mt.VALIDATORS[s]) for s in SLOTS}
    result = run_category_pipeline(category.category_id, category.version, bindings, out, qa)
    assert result.complete and set(result.outputs) == set(SLOTS)


def test_source_has_no_private_markers():
    src = (REPO / "wizexpert" / "governance" / "monthly_templates.py").read_text("utf-8")
    assert CLIENT not in src.lower()
    assert [m.start() for m in re.finditer("wc-id-", src)] and src.count("wc-id-") == 1
    assert not re.search(r"[A-Za-z]:[\\/][A-Za-z]", src)
    assert "/Users/" not in src and "/home/" not in src


def test_nothing_written_in_repo(tmp_path):
    def snapshot():
        files = set()
        for sub in ("wizexpert", "tests", "docs"):
            files |= {p for p in (REPO / sub).rglob("*") if "__pycache__" not in p.parts}
        files |= set(REPO.glob("*"))
        return files

    before = snapshot()
    mt.build_all(tmp_path / "x")
    assert REPO not in (tmp_path / "x").parents
    assert snapshot() == before


# ------------------------------------------------- hardening regressions

EMAIL = "name" + "@example.org"
URL = "https://" + "example.org"
DECKS = [mt.OPERATIONAL_SLOT, mt.EXECUTIVE_SLOT]
EXT_RELS = (
    '<Relationships><Relationship Target="' + URL + '" TargetMode="External"/></Relationships>'
)
MACRO_TYPES = '<Types><Override ContentType="application/x.macroEnabled"/></Types>'
CUSTOM_XML = (
    '<?xml version="1.0" encoding="UTF-8"?><Properties>'
    '<property name="k"><lpwstr>{value}</lpwstr></property></Properties>'
)


def _validate(slot, path):
    return mt.VALIDATORS[slot](path)


def _rewrite_zip(path, extra=None):
    with zipfile.ZipFile(path) as zin:
        items = [(i.filename, zin.read(i.filename)) for i in zin.infolist()]
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zout:
        for name, data in items:
            zout.writestr(name, data)
        for name, data in (extra or {}).items():
            zout.writestr(name, data)


def _has(problems, needle):
    return any(needle in x for x in problems)


@pytest.mark.parametrize("slot", DECKS)
def test_deck_nested_group_text(built, slot):
    def add(p):
        outer = p.slides[0].shapes.add_group_shape()
        inner = outer.shapes.add_group_shape()
        inner.shapes.add_textbox(0, 0, 100, 100).text_frame.text = "Hello " + EMAIL

    _edit_deck(built[slot], add)
    problems = _validate(slot, built[slot])
    assert _has(problems, "group shape") and _has(problems, "email")
    assert _has(problems, "non-placeholder")


def test_deck_table_cell_text(built):
    def add(p):
        frame = p.slides[0].shapes.add_table(2, 2, 0, 0, Inches(2), Inches(1))
        frame.table.cell(1, 1).text = "ref 1234567"

    _edit_deck(built[mt.EXECUTIVE_SLOT], add)
    problems = mt.validate_executive_dashboard(built[mt.EXECUTIVE_SLOT])
    assert _has(problems, "table") and _has(problems, "account-like")


def test_deck_notes_text(built):
    def add(p):
        p.slides[1].notes_slide.notes_text_frame.text = "call " + EMAIL

    _edit_deck(built[mt.OPERATIONAL_SLOT], add)
    problems = mt.validate_operational_deck(built[mt.OPERATIONAL_SLOT])
    assert _has(problems, "email") and _has(problems, "non-placeholder")


def test_deck_layout_and_master_text(built):
    _edit_deck(built[mt.EXECUTIVE_SLOT],
               lambda p: setattr(p.slide_layouts[0].shapes[0].text_frame, "text", EMAIL))
    assert _has(mt.validate_executive_dashboard(built[mt.EXECUTIVE_SLOT]), "email")


def test_deck_hyperlinks(built, tmp_path):
    def run_link(p):
        run = p.slides[0].shapes[0].text_frame.paragraphs[0].runs[0]
        run.hyperlink.address = URL

    path = built[mt.EXECUTIVE_SLOT]
    _edit_deck(path, run_link)
    problems = mt.validate_executive_dashboard(path)
    assert _has(problems, "hyperlink") or _has(problems, "external")

    other = mt.build_executive_dashboard(tmp_path / "second")

    def shape_link(p):
        p.slides[0].shapes[0].click_action.hyperlink.address = URL

    _edit_deck(other, shape_link)
    problems = mt.validate_executive_dashboard(other)
    assert _has(problems, "hyperlink") or _has(problems, "external")


def test_deck_chart_rejected(built):
    from pptx.chart.data import CategoryChartData
    from pptx.enum.chart import XL_CHART_TYPE

    def add(p):
        data = CategoryChartData()
        data.categories = ["a"]
        data.add_series("s", (1,))
        p.slides[0].shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, 0, 0, 100000, 100000, data)

    _edit_deck(built[mt.EXECUTIVE_SLOT], add)
    assert mt.validate_executive_dashboard(built[mt.EXECUTIVE_SLOT])


def test_deck_property_core_and_custom(built):
    path = built[mt.EXECUTIVE_SLOT]
    _edit_deck(path, lambda p: setattr(p.core_properties, "category", EMAIL))
    assert _has(mt.validate_executive_dashboard(path), "email")
    other = built[mt.OPERATIONAL_SLOT]
    _rewrite_zip(other, {"docProps/custom.xml": CUSTOM_XML.format(value=CLIENT)})
    assert _has(mt.validate_operational_deck(other), "restricted name")


@pytest.mark.parametrize("hidden,needle", [
    ("{{" + CLIENT + "}}", "restricted name"),
    ("{{slide_1_title1234567}}", "account-like"),
    ("{{" + EMAIL + "}}", "email"),
    ("{{" + URL + "}}", "URL"),
])
def test_placeholder_hides_private_content(built, hidden, needle):
    path = built[mt.OPERATIONAL_SLOT]
    _edit_deck(path, lambda p: setattr(p.slides[2].shapes[1].text_frame, "text", hidden))
    assert _has(mt.validate_operational_deck(path), needle)
    wpath = built[mt.WORKBOOK_SLOT]
    _edit_wb(wpath, lambda wb: wb["Tab 3 Placeholder"].__setitem__("A5", hidden))
    assert _has(mt.validate_workbook(wpath), needle)


def test_unknown_placeholder_name(built):
    path = built[mt.OPERATIONAL_SLOT]
    unknown = "{{unknown_name}}"
    _edit_deck(path, lambda p: setattr(p.slides[2].shapes[1].text_frame, "text", unknown))
    assert _has(mt.validate_operational_deck(path), "unknown placeholder")
    # valid name from another slide of the same slot is still a schema name
    wpath = built[mt.WORKBOOK_SLOT]
    _edit_wb(wpath, lambda wb: wb["Tab 3 Placeholder"].__setitem__("A5", "{{col9_label}}"))
    assert _has(mt.validate_workbook(wpath), "unknown placeholder")
    _edit_wb(wpath, lambda wb: wb["Tab 3 Placeholder"].__setitem__("A5", "{{ .col1 }}"))
    assert _has(mt.validate_workbook(wpath), "unknown placeholder")


def test_schema_placeholders_pass_privacy():
    names = ("{{slide_10_title}}", "{{.col8}}", "{{tab_6_empty_message}}", "{{exec_3_metric_2}}")
    for text in names:
        assert mt._privacy_problems("x", text) == []


def test_wrong_deck_size(built):
    def resize(p):
        p.slide_width = Inches(13.34)

    _edit_deck(built[mt.EXECUTIVE_SLOT], resize)
    assert _has(mt.validate_executive_dashboard(built[mt.EXECUTIVE_SLOT]), "slide size")
    assert Inches(13.333) == mt.DECK_WIDTH_EMU
    assert Inches(7.5) == mt.DECK_HEIGHT_EMU


def test_workbook_comment_and_hyperlink(built):
    from openpyxl.comments import Comment

    path = built[mt.WORKBOOK_SLOT]
    _edit_wb(path, lambda wb: wb["Tab 2 Placeholder"].__setitem__("H9", None))
    _edit_wb(path, lambda wb: setattr(wb["Tab 2 Placeholder"]["H9"], "comment",
                                      Comment(EMAIL, "me")))
    problems = mt.validate_workbook(path)
    assert _has(problems, "comment") and _has(problems, "email")

    other = mt.build_workbook(path.parent / "second")

    def link(wb):
        wb["Tab 1 Placeholder"]["H9"].hyperlink = URL

    _edit_wb(other, link)
    assert _has(mt.validate_workbook(other), "external relationships")

    internal = mt.build_workbook(path.parent / "third")

    def local_link(wb):
        from openpyxl.worksheet.hyperlink import Hyperlink

        cell = wb["Tab 1 Placeholder"]["H9"]
        cell.hyperlink = Hyperlink(ref="H9", location="'Tab 2 Placeholder'!A1")

    _edit_wb(internal, local_link)
    assert _has(mt.validate_workbook(internal), "H9: contains a hyperlink")


def test_workbook_header_footer(built):
    path = built[mt.WORKBOOK_SLOT]

    def hf(wb):
        wb["Tab 4 Placeholder"].oddHeader.center.text = EMAIL
        wb["Tab 4 Placeholder"].evenFooter.left.text = "Hello"
        wb["Tab 4 Placeholder"].firstFooter.right.text = "{{unknown_name}}"

    _edit_wb(path, hf)
    problems = mt.validate_workbook(path)
    assert _has(problems, "header/footer: contains email")
    assert _has(problems, "header/footer non-placeholder")
    assert _has(problems, "unknown placeholder")


def test_workbook_defined_name_validation_and_props(built):
    from openpyxl.workbook.defined_name import DefinedName
    from openpyxl.worksheet.datavalidation import DataValidation

    path = built[mt.WORKBOOK_SLOT]

    def edit(wb):
        wb.defined_names["scope"] = DefinedName("scope", attr_text='"' + EMAIL + '"')
        wb.defined_names[CLIENT] = DefinedName(CLIENT, attr_text="'Tab 1 Placeholder'!$A$1")
        dv = DataValidation(type="list", formula1='"' + URL + '"')
        dv.add("A1")
        wb["Tab 5 Placeholder"].add_data_validation(dv)
        wb.properties.category = "ref 1234567"
        wb.properties.title = EMAIL

    _edit_wb(path, edit)
    problems = mt.validate_workbook(path)
    for needle in ("defined name: contains email", "defined name: contains restricted name",
                   "data validation: contains URL", "property category", "property title"):
        assert _has(problems, needle), needle
    _rewrite_zip(path, {"docProps/custom.xml": CUSTOM_XML.format(value=EMAIL)})
    assert _has(mt.validate_workbook(path), "document properties: contains email")


def test_workbook_sheet_title_image_chart(built, tmp_path):
    from openpyxl.chart import BarChart
    from openpyxl.drawing.image import Image as XlImage
    from PIL import Image

    path = built[mt.WORKBOOK_SLOT]
    img = tmp_path / "p.png"
    Image.new("RGB", (4, 4)).save(img)

    def edit(wb):
        wb["Tab 1 Placeholder"].title = CLIENT
        wb["Tab 3 Placeholder"].add_chart(BarChart(), "J1")

    _edit_wb(path, edit)
    problems = mt.validate_workbook(path)
    assert _has(problems, "restricted name") and _has(problems, "pictures or charts")

    other = mt.build_workbook(path.parent / "second")
    _edit_wb(other, lambda wb: wb["Tab 2 Placeholder"].add_image(XlImage(str(img)), "J1"))
    assert _has(mt.validate_workbook(other), "picture")


def _zip_file(path, members):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in members.items():
            z.writestr(name, data)
    return path


@pytest.mark.parametrize("slot", SLOTS)
def test_bounds_and_zip_safety(built, tmp_path, slot):
    big = tmp_path / "big.bin"
    big.write_bytes(b"x" * (mt.MAX_FILE_BYTES + 1))
    assert _has(_validate(slot, big), "file larger")

    bomb = _zip_file(tmp_path / "bomb.zip", {"a.xml": b"0" * 5_000_000})
    assert _has(_validate(slot, bomb), "compression ratio")

    huge = _zip_file(tmp_path / "huge.zip", {"a.xml": b"0" * (mt.MAX_UNCOMPRESSED_BYTES + 1)})
    assert _has(_validate(slot, huge), "uncompressed size")

    many = _zip_file(tmp_path / "many.zip", {f"f{i}.txt": b"a" for i in range(mt.MAX_MEMBERS + 1)})
    assert _has(_validate(slot, many), "more than")

    for label, name in (("trav", "../evil.xml"), ("abs", "/evil.xml"), ("drive", "Z:/evil.xml"),
                        ("back", "..\\evil.xml")):
        p = _zip_file(tmp_path / f"{label}.zip", {name: b"x"})
        assert _has(_validate(slot, p), "unsafe path"), label

    vba = _zip_file(tmp_path / "vba.zip", {"xl/vbaProject.bin": b"x"})
    assert _has(_validate(slot, vba), "macro")
    emb = _zip_file(tmp_path / "emb.zip", {"ppt/embeddings/o.bin": b"x"})
    assert _has(_validate(slot, emb), "embedded-object")

    rels = _zip_file(tmp_path / "rels.zip", {
        "_rels/.rels": EXT_RELS})
    assert _has(_validate(slot, rels), "external relationships")

    macro_types = _zip_file(tmp_path / "ct.zip", {
        "[Content_Types].xml": MACRO_TYPES})
    assert _has(_validate(slot, macro_types), "macro")


@pytest.mark.parametrize("slot", SLOTS)
def test_malformed_files_return_problems(built, tmp_path, slot):
    junk = tmp_path / "secret-private-dir-name.bin"
    junk.write_bytes(b"not a zip at all")
    problems = _validate(slot, junk)
    assert problems and "secret-private-dir-name" not in " ".join(problems)
    assert str(tmp_path) not in " ".join(problems)
    empty_zip = _zip_file(tmp_path / "empty.zip", {"readme.txt": b"hi"})
    assert _validate(slot, empty_zip)
    assert _validate(slot, tmp_path / "missing.xlsx")


def test_external_relationship_in_real_deck(built):
    path = built[mt.OPERATIONAL_SLOT]
    _rewrite_zip(path, {"ppt/slides/_rels/extra.xml.rels": EXT_RELS})
    assert _has(mt.validate_operational_deck(path), "external relationships")


@pytest.mark.parametrize("rel", [
    "wizexpert/governance/monthly_templates.py",
    "tests/test_monthly_templates.py",
])
def test_source_files_have_no_bom_and_consistent_endings(rel):
    data = (REPO / rel).read_bytes()
    assert not data.startswith(b"\xef\xbb\xbf")
    bare = data.replace(b"\r\n", b"")
    assert not (b"\r\n" in data and b"\n" in bare)
    assert b"\r" not in bare
