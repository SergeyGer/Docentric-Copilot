"""Synthetic reference-evaluation fixtures (REF-05).

Every payload here is authored by this repository. The templates exercise
generic Docentric *patterns* (Field, List, If, Image, Label) with synthetic
schema names and values; no file, fragment, label text or screenshot from the
Docentric example archive is used.

The module is both the source of the committed ``benchmarks/fixtures/reference``
artifacts and a library used by ``benchmarks/reference_evaluation.py`` tests.
Regenerate with::

    .venv/bin/python benchmarks/build_reference_fixtures.py
"""

from __future__ import annotations

import io
import json
import zipfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from html import escape
from pathlib import Path
from typing import Any, Final

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = ROOT / "benchmarks" / "fixtures" / "reference"
CASES_FILE = ROOT / "benchmarks" / "reference_cases.json"
FIXED_TIME: Final = (2024, 1, 1, 0, 0, 0)

W_NS: Final = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
DS_NS: Final = "http://schemas.openxmlformats.org/officeDocument/2006/customXml"
PROJECT_DATA_NS: Final = "http://Docentric.org/ProjectData.xml"
STORE_ITEM_ID: Final = "{55555555-5555-5555-5555-555555555555}"

KIND_ALIAS: Final[dict[str, str]] = {
    "field": "Field",
    "list": "List",
    "if": "If",
    "image": "Image",
    "label": "Label",
}


def _w(tag: str) -> str:
    return f"{{{W_NS}}}{tag}"


def _zip(files: Mapping[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, date_time=FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, files[name])
    return buffer.getvalue()


def _read_zip(data: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


# --------------------------------------------------------------------------- #
# Minimal OOXML/ProjectData builders
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ControlSpec:
    """One synthetic ``w:sdt``."""

    sdt_id: int
    kind: str
    text: str = ""
    paragraph: int = 0


@dataclass(frozen=True)
class ElementSpec:
    """One synthetic ProjectData element."""

    element_id: int
    element_type: str
    source: str | None
    path: str | None
    child_ids: tuple[int, ...] = ()
    properties: Mapping[str, str] = field(default_factory=dict)


def _control_element(spec: ControlSpec) -> Any:
    from docx.oxml import OxmlElement

    alias = KIND_ALIAS.get(spec.kind, "Field")
    sdt = OxmlElement("w:sdt")
    properties = OxmlElement("w:sdtPr")
    for tag, value in (("alias", alias), ("tag", alias)):
        item = OxmlElement(f"w:{tag}")
        item.set(_w("val"), value)
        properties.append(item)
    identifier = OxmlElement("w:id")
    identifier.set(_w("val"), str(spec.sdt_id))
    properties.append(identifier)
    placeholder = OxmlElement("w:placeholder")
    part = OxmlElement("w:docPart")
    part.set(_w("val"), "SYNTHETIC-REFERENCE")
    placeholder.append(part)
    properties.append(placeholder)
    content = OxmlElement("w:sdtContent")
    run = OxmlElement("w:r")
    text = OxmlElement("w:t")
    text.text = spec.text
    text.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    run.append(text)
    content.append(run)
    sdt.append(properties)
    sdt.append(content)
    return sdt


def build_docx(
    *,
    body: Sequence[ControlSpec] = (),
    header: Sequence[ControlSpec] = (),
    footer: Sequence[ControlSpec] = (),
    custom_parts: Mapping[str, bytes] | None = None,
) -> bytes:
    """Build a small synthetic DOCX with body, header and footer controls."""
    from docx import Document

    document = Document()
    document.add_paragraph("Synthetic reference pattern")
    for spec in body:
        paragraph = document.add_paragraph()
        paragraph._p.append(_control_element(spec))
    if header:
        header_paragraph = document.sections[0].header.paragraphs[0]
        for spec in header:
            header_paragraph._p.append(_control_element(spec))
    if footer:
        footer_paragraph = document.sections[0].footer.paragraphs[0]
        for spec in footer:
            footer_paragraph._p.append(_control_element(spec))
    buffer = io.BytesIO()
    document.save(buffer)
    files = _read_zip(buffer.getvalue())
    if custom_parts:
        files.update(custom_parts)
    return _zip(files)


def build_project_data(elements: Iterable[ElementSpec]) -> bytes:
    """Build a namespace-correct synthetic ProjectData document."""
    source_xml = '<DataSource Name="MainData"/>'
    rendered: list[str] = []
    for element in elements:
        attrs = f'Type="{escape(element.element_type)}" Id="{element.element_id}"'
        children: list[str] = []
        if element.child_ids:
            refs = "".join(f'<ElementRef Id="{child}"/>' for child in element.child_ids)
            children.append(f"<ChildElements>{refs}</ChildElements>")
        if element.properties:
            values = " ".join(
                f'{key}="{escape(value)}"' for key, value in sorted(element.properties.items())
            )
            children.append(f"<Value {values}/>")
        if element.source is not None and element.path is not None:
            children.append(
                '<ValueBinding DataKind="2" '
                f'Source="{escape(element.source)}" Path="{escape(element.path)}" '
                'ResultDataType="System.String"/>'
            )
        rendered.append(f"<Element {attrs}>{''.join(children)}</Element>")
    text = (
        f'<ProjectData xmlns="{PROJECT_DATA_NS}" ProductId="3" ProductVersion="3.0.0.998">'
        '<UISettings xmlns=""/>'
        f'<DataSources xmlns="">{source_xml}</DataSources>'
        f'<Elements xmlns="">{"".join(rendered)}</Elements>'
        "</ProjectData>"
    )
    return text.encode("utf-8")


def project_data_parts(project_data: bytes) -> dict[str, bytes]:
    return {
        "customXml/item5.xml": project_data,
        "customXml/itemProps5.xml": (
            f'<ds:datastoreItem xmlns:ds="{DS_NS}" ds:itemID="{STORE_ITEM_ID}">'
            "<ds:schemaRefs/></ds:datastoreItem>"
        ).encode(),
    }


# --------------------------------------------------------------------------- #
# Schema and sample data helpers
# --------------------------------------------------------------------------- #
def _complex_element(
    name: str,
    children: Sequence[str],
    *,
    min_occurs: int = 0,
    max_occurs: int | None = None,
) -> str:
    occurrence = f' minOccurs="{min_occurs}"'
    if max_occurs is not None:
        occurrence += ' maxOccurs="unbounded"'
    return (
        f'<xs:element name="{name}"{occurrence}><xs:complexType><xs:sequence>'
        + "".join(children)
        + "</xs:sequence></xs:complexType></xs:element>"
    )


def _leaf(name: str, data_type: str = "xs:string", *, min_occurs: int = 0) -> str:
    return f'<xs:element name="{name}" type="{data_type}" minOccurs="{min_occurs}"/>'


def _company(*, logo: bool = False, address: bool = False) -> str:
    children = [_leaf("Name")]
    if logo:
        children.append(_leaf("Logo", "xs:base64Binary"))
    if address:
        children.append(_leaf("Address"))
    return _complex_element("Company", children)


def _customer(*, eu: bool = False) -> str:
    children = [_leaf("Name")]
    if eu:
        children.append(_leaf("IsEU", "xs:boolean"))
    return _complex_element("Customer", children)


def _lines() -> str:
    line = _complex_element(
        "Line",
        [
            _leaf("ItemId"),
            _leaf("Description"),
            _leaf("Quantity", "xs:decimal"),
            _leaf("UnitPrice", "xs:decimal"),
            _leaf("LineAmount", "xs:decimal"),
        ],
        min_occurs=1,
        max_occurs=0,
    )
    return _complex_element("OrderLines", [line])


def _order(
    *,
    order_id: bool = True,
    dates: bool = False,
    totals: bool = False,
    payment_terms: bool = False,
    customer: bool = False,
    eu: bool = False,
) -> str:
    children: list[str] = []
    if order_id:
        children.append(_leaf("OrderId"))
    if dates:
        children.append(_leaf("OrderDate", "xs:date"))
        children.append(_leaf("DueDate", "xs:date"))
    if payment_terms:
        children.append(_leaf("PaymentTerms"))
    if customer:
        children.append(_customer(eu=eu))
    if totals:
        children.extend(
            [
                _leaf("NetAmount", "xs:decimal"),
                _leaf("TaxAmount", "xs:decimal"),
                _leaf("TotalAmount", "xs:decimal"),
            ]
        )
    return _complex_element("Order", children, min_occurs=1)


def _schema_xml(children: Sequence[str]) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" '
        'elementFormDefault="qualified">'
        '<xs:element name="MainData"><xs:complexType><xs:sequence>'
        + "".join(children)
        + "</xs:sequence></xs:complexType></xs:element></xs:schema>\n"
    )


def _sample_xml(body: str) -> str:
    return '<?xml version="1.0" encoding="utf-8"?>\n<MainData>' + body + "</MainData>\n"


def _ddsp_payload(name: str, xsd: str, sample: str) -> bytes:
    manifest = {
        "format": "docentric-ax-ddsp",
        "format_version": "1.0",
        "generator": "docentric-copilot/benchmarks/build_reference_fixtures.py",
        "license": "Apache-2.0",
        "name": name,
        "synthetic": True,
    }
    return _zip(
        {
            "manifest.json": (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode(),
            "schema/schema.xsd": xsd.encode(),
            "data/sample.xml": sample.encode(),
        }
    )


# --------------------------------------------------------------------------- #
# Case definitions
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ConceptSpec:
    """One expected reference pattern and its binding."""

    concept: str  # scalar | collection | condition | image | text
    kind: str  # Reference template ElementKind
    path: str
    expected_type: str
    contexts: tuple[str, ...] = ("body",)
    required: bool = True

    @property
    def identifier(self) -> str:
        return f"{self.concept}:{self.path}"

    def as_case_entry(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.identifier,
            "concept": self.concept,
            "kind": self.kind,
            "path": self.path,
            "expected_paths": [self.path],
            "expected_type": self.expected_type,
            "contexts": list(self.contexts),
            "required": self.required,
        }
        return payload


@dataclass(frozen=True)
class FixtureCase:
    """One synthetic prompt/schema/reference triple."""

    case_id: str
    title: str
    family: str
    prompt: str
    schema_name: str
    xsd: str
    sample: str
    concepts: tuple[ConceptSpec, ...]
    forbidden_paths: tuple[str, ...] = ()
    labels: tuple[str, ...] = ()

    @property
    def schema_file(self) -> str:
        return f"benchmarks/fixtures/reference/{self.case_id}.ddsp"

    @property
    def reference_file(self) -> str:
        return f"benchmarks/fixtures/reference/{self.case_id}.docx"

    def as_case_entry(self) -> dict[str, Any]:
        return {
            "id": self.case_id,
            "title": self.title,
            "family": self.family,
            "prompt": self.prompt,
            "schema": self.schema_file,
            "reference": self.reference_file,
            "patterns": list(dict.fromkeys(concept.concept for concept in self.concepts)),
            "expected": [concept.as_case_entry() for concept in self.concepts],
            "forbidden_paths": list(self.forbidden_paths),
            "labels": list(self.labels),
        }


def _relative_path(path: str) -> str:
    prefix = "MainData."
    return path[len(prefix) :].replace(".", "/") if path.startswith(prefix) else path


def _ref_elements(
    case: FixtureCase,
) -> tuple[list[ElementSpec], list[ControlSpec], list[ControlSpec], list[ControlSpec]]:
    """Build ProjectData elements and body/header/footer controls from concepts."""
    ids: dict[str, int] = {}
    next_id = 1000
    for concept in case.concepts:
        ids[concept.identifier] = next_id
        next_id += 1

    collection_paths = {
        concept.path for concept in case.concepts if concept.concept == "collection"
    }
    children: dict[str, list[int]] = {path: [] for path in collection_paths}
    elements: list[ElementSpec] = []
    for concept in case.concepts:
        element_id = ids[concept.identifier]
        parent = next(
            (
                collection_path
                for collection_path in collection_paths
                if concept.path.startswith(f"{collection_path}.")
            ),
            None,
        )
        if parent is not None:
            children[parent].append(element_id)
            elements.append(
                ElementSpec(
                    element_id,
                    KIND_ALIAS[concept.kind],
                    ".",
                    concept.path.rsplit(".", 1)[-1],
                )
            )
        elif concept.concept == "collection":
            elements.append(
                ElementSpec(
                    element_id,
                    "List",
                    "MainData",
                    _relative_path(concept.path),
                )
            )
        else:
            elements.append(
                ElementSpec(
                    element_id,
                    KIND_ALIAS[concept.kind],
                    "MainData",
                    _relative_path(concept.path),
                )
            )

    elements = [
        ElementSpec(
            element.element_id,
            element.element_type,
            element.source,
            element.path,
            tuple(children.get(concept.path, ())),
            element.properties,
        )
        for element, concept in zip(elements, case.concepts, strict=True)
    ]

    body: list[ControlSpec] = []
    header: list[ControlSpec] = []
    footer: list[ControlSpec] = []
    for concept in case.concepts:
        control = ControlSpec(
            ids[concept.identifier],
            concept.kind,
            text=concept.path.rsplit(".", 1)[-1],
        )
        if "header" in concept.contexts:
            header.append(control)
        elif concept.contexts == ("footer",):
            footer.append(control)
        else:
            body.append(control)
    return elements, body, header, footer


def build_case(case: FixtureCase) -> dict[str, bytes]:
    """Return the deterministic DDSP and DOCX bytes for one case."""
    elements, body, header, footer = _ref_elements(case)
    custom = project_data_parts(build_project_data(elements))
    document = build_docx(body=body, header=header, footer=footer, custom_parts=custom)
    ddsp = _ddsp_payload(case.schema_name, case.xsd, case.sample)
    return {case.schema_file: ddsp, case.reference_file: document}


# Identity / field cases ---------------------------------------------------- #
_IDENTITY_XSD = _schema_xml([_company(), _order()])
_IDENTITY_SAMPLE = _sample_xml(
    "<Company><Name>Synthetic Company</Name></Company><Order><OrderId>SYN-1001</OrderId></Order>"
)
_IDENTITY_CONCEPTS = (
    ConceptSpec("scalar", "field", "MainData.Company.Name", "string", ("header",)),
    ConceptSpec("scalar", "field", "MainData.Order.OrderId", "string", ("body",)),
)

_DATES_XSD = _schema_xml([_company(), _order(dates=True)])
_DATES_SAMPLE = _sample_xml(
    "<Company><Name>Synthetic Company</Name></Company>"
    "<Order><OrderId>SYN-1002</OrderId><OrderDate>2026-04-01</OrderDate>"
    "<DueDate>2026-05-01</DueDate></Order>"
)
_DATES_CONCEPTS = (
    ConceptSpec("scalar", "field", "MainData.Order.OrderId", "string"),
    ConceptSpec("scalar", "field", "MainData.Order.OrderDate", "date"),
    ConceptSpec("scalar", "field", "MainData.Order.DueDate", "date"),
)

_LINES_XSD = _schema_xml([_company(), _order(), _lines()])
_LINES_SAMPLE = _sample_xml(
    "<Company><Name>Synthetic Company</Name></Company>"
    "<Order><OrderId>SYN-1003</OrderId></Order>"
    "<OrderLines><Line><ItemId>SKU-1</ItemId><Description>Example item</Description>"
    "<Quantity>2</Quantity><UnitPrice>10.00</UnitPrice><LineAmount>20.00</LineAmount>"
    "</Line></OrderLines>"
)
_LINES_CONCEPTS = (
    ConceptSpec("scalar", "field", "MainData.Company.Name", "string", ("header",)),
    ConceptSpec("scalar", "field", "MainData.Order.OrderId", "string"),
    ConceptSpec("collection", "list", "MainData.OrderLines.Line", "collection"),
    ConceptSpec("scalar", "field", "MainData.OrderLines.Line.ItemId", "string", ("repeat",)),
    ConceptSpec("scalar", "field", "MainData.OrderLines.Line.Description", "string", ("repeat",)),
    ConceptSpec("scalar", "field", "MainData.OrderLines.Line.Quantity", "number", ("repeat",)),
    ConceptSpec("scalar", "field", "MainData.OrderLines.Line.UnitPrice", "number", ("repeat",)),
    ConceptSpec("scalar", "field", "MainData.OrderLines.Line.LineAmount", "number", ("repeat",)),
)

_CONDITION_XSD = _schema_xml([_company(), _order(customer=True, eu=True)])
_CONDITION_SAMPLE = _sample_xml(
    "<Company><Name>Synthetic Company</Name></Company>"
    "<Order><OrderId>SYN-1004</OrderId><Customer><Name>Example Customer</Name>"
    "<IsEU>true</IsEU></Customer></Order>"
)
_CONDITION_CONCEPTS = (
    ConceptSpec("scalar", "field", "MainData.Company.Name", "string", ("header",)),
    ConceptSpec("scalar", "field", "MainData.Order.OrderId", "string"),
    ConceptSpec("condition", "if", "MainData.Order.Customer.IsEU", "boolean", ("conditional",)),
)

_IMAGE_XSD = _schema_xml([_company(logo=True), _order()])
_IMAGE_SAMPLE = _sample_xml(
    "<Company><Name>Synthetic Company</Name><Logo>U1lOVEhFVElD</Logo></Company>"
    "<Order><OrderId>SYN-1005</OrderId></Order>"
)
_IMAGE_CONCEPTS = (
    ConceptSpec("image", "image", "MainData.Company.Logo", "image", ("header",)),
    ConceptSpec("scalar", "field", "MainData.Company.Name", "string", ("header",)),
    ConceptSpec("scalar", "field", "MainData.Order.OrderId", "string"),
)

_LABEL_XSD = _schema_xml([_company(), _order(payment_terms=True)])
_LABEL_SAMPLE = _sample_xml(
    "<Company><Name>Synthetic Company</Name></Company>"
    "<Order><OrderId>SYN-1006</OrderId><PaymentTerms>Net 30 days</PaymentTerms></Order>"
)
_LABEL_CONCEPTS = (
    ConceptSpec("scalar", "field", "MainData.Company.Name", "string", ("header",)),
    ConceptSpec("text", "label", "MainData.Order.PaymentTerms", "string", ("body",)),
)

_HEADER_FOOTER_XSD = _schema_xml([_company(address=True), _order(dates=True)])
_HEADER_FOOTER_SAMPLE = _sample_xml(
    "<Company><Name>Synthetic Company</Name><Address>Example Street 1</Address></Company>"
    "<Order><OrderId>SYN-1007</OrderId><OrderDate>2026-04-02</OrderDate>"
    "<DueDate>2026-05-02</DueDate></Order>"
)
_HEADER_FOOTER_CONCEPTS = (
    ConceptSpec("scalar", "field", "MainData.Company.Name", "string", ("header",)),
    ConceptSpec("scalar", "field", "MainData.Company.Address", "string", ("header",)),
    ConceptSpec("scalar", "field", "MainData.Order.OrderId", "string", ("footer",)),
    ConceptSpec("scalar", "field", "MainData.Order.OrderDate", "date"),
)

_MIXED_XSD = _schema_xml(
    [
        _company(logo=True),
        _order(dates=True, totals=True, payment_terms=True, customer=True, eu=True),
        _lines(),
    ]
)
_MIXED_SAMPLE = _sample_xml(
    "<Company><Name>Synthetic Company</Name><Logo>U1lOVEhFVElD</Logo></Company>"
    "<Order><OrderId>SYN-1008</OrderId><OrderDate>2026-04-03</OrderDate>"
    "<DueDate>2026-05-03</DueDate><PaymentTerms>Net 30 days</PaymentTerms>"
    "<Customer><Name>Example Customer</Name><IsEU>true</IsEU></Customer>"
    "<NetAmount>100.00</NetAmount><TaxAmount>20.00</TaxAmount>"
    "<TotalAmount>120.00</TotalAmount></Order>"
    "<OrderLines><Line><ItemId>SKU-2</ItemId><Description>Example item</Description>"
    "<Quantity>1</Quantity><UnitPrice>120.00</UnitPrice><LineAmount>120.00</LineAmount>"
    "</Line></OrderLines>"
)
_MIXED_CONCEPTS = (
    ConceptSpec("image", "image", "MainData.Company.Logo", "image", ("header",)),
    ConceptSpec("scalar", "field", "MainData.Company.Name", "string", ("header",)),
    ConceptSpec("scalar", "field", "MainData.Order.OrderId", "string"),
    ConceptSpec("scalar", "field", "MainData.Order.OrderDate", "date"),
    ConceptSpec("scalar", "field", "MainData.Order.Customer.Name", "string"),
    ConceptSpec("scalar", "field", "MainData.Order.NetAmount", "number"),
    ConceptSpec("scalar", "field", "MainData.Order.TaxAmount", "number"),
    ConceptSpec("scalar", "field", "MainData.Order.TotalAmount", "number"),
    ConceptSpec("text", "label", "MainData.Order.PaymentTerms", "string"),
    ConceptSpec("condition", "if", "MainData.Order.Customer.IsEU", "boolean", ("conditional",)),
    ConceptSpec("collection", "list", "MainData.OrderLines.Line", "collection"),
    ConceptSpec("scalar", "field", "MainData.OrderLines.Line.ItemId", "string", ("repeat",)),
    ConceptSpec("scalar", "field", "MainData.OrderLines.Line.Description", "string", ("repeat",)),
    ConceptSpec("scalar", "field", "MainData.OrderLines.Line.Quantity", "number", ("repeat",)),
    ConceptSpec("scalar", "field", "MainData.OrderLines.Line.UnitPrice", "number", ("repeat",)),
    ConceptSpec("scalar", "field", "MainData.OrderLines.Line.LineAmount", "number", ("repeat",)),
)

CASES: Final[tuple[FixtureCase, ...]] = (
    FixtureCase(
        "ref-field-scalar",
        "Field: scalar company and order identity",
        "field",
        "Create an invoice showing the company name and the order number.",
        "reference_field_scalar",
        _IDENTITY_XSD,
        _IDENTITY_SAMPLE,
        _IDENTITY_CONCEPTS,
        labels=("field", "header"),
    ),
    FixtureCase(
        "ref-field-date",
        "Field: issue and due dates",
        "field",
        "Create an invoice with its issue date and due date.",
        "reference_field_date",
        _DATES_XSD,
        _DATES_SAMPLE,
        _DATES_CONCEPTS,
        labels=("field", "dates"),
    ),
    FixtureCase(
        "ref-list-collection",
        "List: repeated line-item collection",
        "list",
        "Create an invoice with a line-item table for the order lines.",
        "reference_list_collection",
        _LINES_XSD,
        _LINES_SAMPLE,
        _LINES_CONCEPTS,
        labels=("list", "collection"),
    ),
    FixtureCase(
        "ref-if-condition",
        "If: conditional VAT notice",
        "if",
        "Create an invoice with a VAT notice for EU customers.",
        "reference_if_condition",
        _CONDITION_XSD,
        _CONDITION_SAMPLE,
        _CONDITION_CONCEPTS,
        labels=("if", "conditional"),
    ),
    FixtureCase(
        "ref-image-logo",
        "Image: company logo in the header",
        "image",
        "Create an invoice with the company logo in the header.",
        "reference_image_logo",
        _IMAGE_XSD,
        _IMAGE_SAMPLE,
        _IMAGE_CONCEPTS,
        labels=("image", "header"),
    ),
    FixtureCase(
        "ref-label-text",
        "Label: localized payment terms text",
        "label",
        "Create an invoice with the payment terms label.",
        "reference_label_text",
        _LABEL_XSD,
        _LABEL_SAMPLE,
        _LABEL_CONCEPTS,
        labels=("label", "text"),
    ),
    FixtureCase(
        "ref-header-footer",
        "Context: header, body and footer placement",
        "context",
        "Create an invoice with the company name in the header and the order number in the footer.",
        "reference_header_footer",
        _HEADER_FOOTER_XSD,
        _HEADER_FOOTER_SAMPLE,
        _HEADER_FOOTER_CONCEPTS,
        labels=("field", "context"),
    ),
    FixtureCase(
        "ref-mixed-invoice",
        "Mixed: Field, List, If, Image and Label patterns",
        "mixed",
        "Create a tax invoice with a logo, customer, line items, an EU VAT notice, payment terms and totals.",
        "reference_mixed_invoice",
        _MIXED_XSD,
        _MIXED_SAMPLE,
        _MIXED_CONCEPTS,
        forbidden_paths=("MainData.Company.InternalNote",),
        labels=("field", "list", "if", "image", "label", "mixed"),
    ),
)


def cases_payload() -> dict[str, Any]:
    """Return the committed cases document (deterministic, no timestamps)."""
    return {
        "version": "1.0",
        "provenance": "synthetic",
        "description": (
            "Human-reviewed synthetic gold set for reference-based evaluation. "
            "Expected bindings are authored from generic Field, List, If, Image and Label "
            "patterns; no Docentric corpus content is used."
        ),
        "patterns": ["field", "list", "if", "image", "label"],
        "cases": [case.as_case_entry() for case in CASES],
    }


def build_all() -> dict[str, bytes]:
    """Return every committed fixture file keyed by its repository-relative path."""
    files: dict[str, bytes] = {}
    for case in CASES:
        files.update(build_case(case))
    files["benchmarks/reference_cases.json"] = (
        json.dumps(cases_payload(), indent=2, sort_keys=True) + "\n"
    ).encode()
    return files


__all__ = [
    "CASES",
    "CASES_FILE",
    "FIXTURE_DIR",
    "ConceptSpec",
    "ControlSpec",
    "ElementSpec",
    "FixtureCase",
    "build_all",
    "build_case",
    "build_docx",
    "build_project_data",
    "cases_payload",
]
