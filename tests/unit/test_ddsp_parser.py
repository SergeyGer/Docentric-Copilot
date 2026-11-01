"""Parser tests: schema discovery, sample data, determinism and hostile input."""

from __future__ import annotations

import io
import zipfile

import pytest
from docentric_copilot.config import Limits
from docentric_copilot.ddsp_parser import DiagnosticCode, parse_ddsp, parse_xml_string
from docentric_copilot.errors import (
    InvalidInputError,
    SecurityViolationError,
    UnsupportedInputError,
)

from tests.conftest import build_zip

MINI_XSD = """<?xml version="1.0" encoding="utf-8"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
  <xs:element name="MainData">
    <xs:complexType>
      <xs:sequence>
        <xs:element name="Document" type="DocumentType"/>
        <xs:element name="Lines" type="LinesType"/>
      </xs:sequence>
    </xs:complexType>
  </xs:element>
  <xs:complexType name="DocumentType">
    <xs:sequence>
      <xs:element name="Number" type="xs:string"/>
      <xs:element name="IssuedOn" type="xs:date" minOccurs="0"/>
      <xs:element name="NetAmount" type="xs:decimal" minOccurs="0"/>
      <xs:element name="IsPaid" type="xs:boolean" minOccurs="0"/>
      <xs:element name="Stamp" type="xs:base64Binary" minOccurs="0"/>
      <xs:element name="Note" type="xs:string" minOccurs="0"/>
    </xs:sequence>
    <xs:attribute name="Currency" type="xs:string"/>
  </xs:complexType>
  <xs:complexType name="LinesType">
    <xs:sequence>
      <xs:element name="Line" type="LineType" maxOccurs="unbounded"/>
    </xs:sequence>
  </xs:complexType>
  <xs:complexType name="LineType">
    <xs:sequence>
      <xs:element name="Description" type="xs:string"/>
      <xs:element name="Quantity" type="xs:decimal"/>
    </xs:sequence>
  </xs:complexType>
</xs:schema>
"""

MINI_XML = """<?xml version="1.0" encoding="utf-8"?>
<Document>
  <MainData>
    <Document Currency="EUR">
      <Number>D-1</Number>
      <IssuedOn>2026-01-15</IssuedOn>
      <NetAmount>10.50</NetAmount>
      <IsPaid>false</IsPaid>
      <Note>First note</Note>
    </Document>
    <Lines>
      <Line><Description>A</Description><Quantity>1</Quantity></Line>
      <Line><Description>B</Description><Quantity>2</Quantity></Line>
    </Lines>
  </MainData>
</Document>
"""


def _package(**files: bytes) -> bytes:
    return build_zip({"manifest.json": b'{"format":"docentric-ax-ddsp","name":"mini"}', **files})


class TestHappyPath:
    def test_quotation_schema_is_complete(self, quotation_source) -> None:
        schema = quotation_source.schema
        assert schema.schema_id == "sales_quotation"
        assert schema.section_names == ["MainData", "GeneralData", "Parameters"]
        assert schema.has_path("MainData.Quotation.Customer.Name")
        assert schema.node("MainData.QuotationLines.Line").collection is True
        assert schema.node("MainData.Quotation.QuotationDate").data_type == "date"
        assert schema.node("MainData.Quotation.TotalAmount").data_type == "number"
        assert schema.node("MainData.Quotation.Customer.IsEU").data_type == "boolean"
        assert schema.node("GeneralData.Company.CompanyLogo").data_type == "image"
        assert schema.stats().collection_count == 1
        assert schema.stats().scalar_count > 20

    def test_quotation_sample_data_is_coerced(self, quotation_source) -> None:
        sample = quotation_source.sample_data
        assert sample is not None
        quotation = sample["MainData"]["Quotation"]
        assert quotation["TotalAmount"] == 1980.0
        assert quotation["Customer"]["IsEU"] is True
        lines = sample["MainData"]["QuotationLines"]["Line"]
        assert len(lines) == 2
        assert lines[0]["UnitPrice"] == 750.0

    def test_parsing_is_deterministic(self, quotation_path) -> None:
        payload = quotation_path.read_bytes()
        first = parse_ddsp(payload, "q.ddsp").schema
        second = parse_ddsp(payload, "q.ddsp").schema
        assert first.canonical_json() == second.canonical_json()
        assert first.digest() == second.digest()

    def test_manifest_supplies_schema_id(self) -> None:
        parsed = parse_ddsp(
            _package(**{"schema.xsd": MINI_XSD.encode(), "sample.xml": MINI_XML.encode()}), "x.ddsp"
        )
        assert parsed.schema.schema_id == "mini"
        assert parsed.schema.format_version is None
        assert parsed.schema.sample_data_available is True

    def test_xsd_and_sample_inside_container(self) -> None:
        parsed = parse_ddsp(
            _package(**{"schema.xsd": MINI_XSD.encode(), "sample.xml": MINI_XML.encode()}), "x.ddsp"
        )
        schema = parsed.schema
        assert schema.has_path("MainData.Document.Note")
        assert schema.node("MainData.Document").attributes[0].name == "Currency"
        assert schema.node("MainData.Lines.Line.Description").collection is False
        assert schema.node("MainData.Lines.Line").collection is True
        assert parsed.sample_data is not None
        assert parsed.sample_data["MainData"]["Document"]["NetAmount"] == 10.5

    def test_single_xml_input_is_supported(self) -> None:
        parsed = parse_xml_string(MINI_XML)
        assert parsed.schema.schema_id == "source"
        assert any(
            item.code is DiagnosticCode.SCHEMA_INFERRED for item in parsed.schema.diagnostics
        )
        assert parsed.schema.has_path("MainData.Lines.Line.Description")
        assert parsed.schema.node("MainData.Lines.Line").collection is True

    def test_single_xsd_input_is_supported(self) -> None:
        parsed = parse_xml_string(MINI_XSD, filename="mini.xsd")
        assert parsed.schema.has_path("MainData.Document.Number")
        assert parsed.sample_data is None

    def test_schema_inference_from_repeated_values(self) -> None:
        payload = b"<Root><MainData><Rows><Row><A>1</A><B>x</B></Row><Row><A>2</A><B>y</B></Row></Rows></MainData></Root>"
        parsed = parse_xml_string(payload.decode())
        assert parsed.schema.node("MainData.Rows.Row").collection is True
        assert parsed.schema.node("MainData.Rows.Row.A").data_type == "number"

    def test_mismatched_sample_values_are_reported(self) -> None:
        xsd = MINI_XSD.encode()
        sample = MINI_XML.replace(
            "<NetAmount>10.50</NetAmount>", "<NetAmount>not-a-number</NetAmount>"
        )
        parsed = parse_ddsp(
            _package(**{"schema.xsd": xsd, "sample.xml": sample.encode()}), "x.ddsp"
        )
        codes = {item.code for item in parsed.schema.diagnostics}
        assert DiagnosticCode.SAMPLE_SCHEMA_MISMATCH in codes


class TestHostileInput:
    def test_missing_file_is_too_small(self) -> None:
        with pytest.raises(InvalidInputError) as exc:
            parse_ddsp(b"PK", "x.ddsp")
        assert exc.value.code == "DDSP011"

    def test_unknown_container_is_rejected(self) -> None:
        with pytest.raises(UnsupportedInputError) as exc:
            parse_ddsp(b"not a zip or xml at all, definitely", "x.ddsp")
        assert exc.value.code == "DDSP002"

    def test_doctype_and_entities_are_rejected(self) -> None:
        bomb = b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">]><lolz>&lol;</lolz>'
        with pytest.raises(SecurityViolationError) as exc:
            parse_ddsp(bomb, "bomb.xml")
        assert exc.value.code == "XML001"

    def test_oversized_file_is_rejected(self) -> None:
        limits = Limits(max_ddsp_bytes=64)
        with pytest.raises(UnsupportedInputError) as exc:
            parse_ddsp(_package(**{"s.xml": MINI_XML.encode()}), "x.ddsp", limits=limits)
        assert exc.value.code == "DDSP001"

    def test_zip_entry_limit(self) -> None:
        files = {f"f{index}.xml": b"<a/>" for index in range(20)}
        limits = Limits(max_zip_entries=10)
        with pytest.raises(SecurityViolationError) as exc:
            parse_ddsp(build_zip(files), "x.ddsp", limits=limits)
        assert exc.value.code == "DDSP003"

    def test_compression_ratio_limit(self) -> None:
        padded = MINI_XML.replace("First note", "A" * 2_000_000)
        limits = Limits(max_compression_ratio=50)
        with pytest.raises(SecurityViolationError) as exc:
            parse_ddsp(
                _package(**{"schema.xsd": MINI_XSD.encode(), "sample.xml": padded.encode()}),
                "x.ddsp",
                limits=limits,
            )
        assert exc.value.code == "DDSP005"

    def test_unsafe_entry_name(self) -> None:
        with pytest.raises(SecurityViolationError) as exc:
            parse_ddsp(build_zip({"../evil.xml": b"<a/>"}), "x.ddsp")
        assert exc.value.code == "DDSP007"

    def test_nested_archive_is_rejected(self) -> None:
        with pytest.raises(SecurityViolationError) as exc:
            parse_ddsp(
                build_zip({"inner.zip": build_zip({"a.xml": b"<a/>"}), "x.xml": b"<a/>"}), "x.ddsp"
            )
        assert exc.value.code == "DDSP009"

    def test_encrypted_entry_is_rejected(self) -> None:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("secret.xml", b"<schema/>")
        raw = bytearray(buffer.getvalue())
        # Set the "encrypted" general-purpose bit in the local and central headers.
        for marker, offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
            position = raw.find(marker)
            assert position != -1
            raw[position + offset] |= 0x1
        with pytest.raises(SecurityViolationError) as exc:
            parse_ddsp(bytes(raw), "x.ddsp")
        assert exc.value.code == "DDSP006"

    def test_no_xml_content(self) -> None:
        with pytest.raises(UnsupportedInputError) as exc:
            parse_ddsp(build_zip({"readme.txt": b"nothing to parse here"}), "x.ddsp")
        assert exc.value.code == "DDSP008"

    def test_xml_node_limit(self) -> None:
        body = "".join(f"<n{i}/>" for i in range(50))
        payload = f"<Root>{body}</Root>".encode()
        with pytest.raises(SecurityViolationError) as exc:
            parse_ddsp(payload, "x.xml", limits=Limits(max_xml_nodes=10))
        assert exc.value.code == "XML003"

    def test_xml_depth_limit(self) -> None:
        payload = "".join("<a>" for _ in range(30)) + "x" + "".join("</a>" for _ in range(30))
        with pytest.raises(SecurityViolationError) as exc:
            parse_ddsp(payload.encode(), "x.xml", limits=Limits(max_xml_depth=10))
        assert exc.value.code == "XML004"

    def test_malformed_xml_is_reported_not_crashed(self) -> None:
        with pytest.raises(InvalidInputError) as exc:
            parse_ddsp(b"<Root><Unclosed></Root>", "x.xml")
        assert exc.value.code == "XML002"

    def test_unreadable_zip(self) -> None:
        with pytest.raises(InvalidInputError) as exc:
            parse_ddsp(b"PK\x03\x04" + b"\x00" * 40, "x.ddsp")
        assert exc.value.code == "DDSP002"

    def test_container_without_xml(self) -> None:
        with pytest.raises(UnsupportedInputError) as exc:
            parse_ddsp(build_zip({"empty.txt": b"   "}), "x.ddsp")
        assert exc.value.code == "DDSP008"

    def test_unknown_root_is_inferred_as_a_section(self) -> None:
        parsed = parse_ddsp(b"<Envelope><MainData><A>x</A></MainData></Envelope>", "x.xml")
        assert parsed.schema.section_names == ["MainData"]
        assert parsed.schema.has_path("MainData.A")
