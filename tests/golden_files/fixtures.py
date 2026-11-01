"""Synthetic DDSP fixtures for golden-file regression tests.

Every fixture is authored here (never third-party) and zipped deterministically.
Regenerate expectations with ``python -m tests.golden_files.update_golden``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tests.conftest import EXAMPLES, build_zip

MANIFEST = b'{"format":"docentric-ax-ddsp","format_version":"1.0","synthetic":true}'


@dataclass(frozen=True)
class Fixture:
    name: str
    package: bytes
    prompt: str
    language: str = "en"


SIMPLE_XSD = """<?xml version="1.0" encoding="utf-8"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
  <xs:element name="MainData">
    <xs:complexType>
      <xs:sequence>
        <xs:element name="Document">
          <xs:complexType>
            <xs:sequence>
              <xs:element name="Number" type="xs:string"/>
              <xs:element name="IssuedOn" type="xs:date"/>
              <xs:element name="TotalAmount" type="xs:decimal"/>
              <xs:element name="CustomerName" type="xs:string"/>
            </xs:sequence>
          </xs:complexType>
        </xs:element>
      </xs:sequence>
    </xs:complexType>
  </xs:element>
</xs:schema>
"""

SIMPLE_SAMPLE = """<?xml version="1.0" encoding="utf-8"?>
<Document>
  <MainData>
    <Document>
      <Number>DOC-1</Number>
      <IssuedOn>2026-05-04</IssuedOn>
      <TotalAmount>125.50</TotalAmount>
      <CustomerName>Acme GmbH</CustomerName>
    </Document>
  </MainData>
</Document>
"""

NESTED_XSD = """<?xml version="1.0" encoding="utf-8"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
  <xs:element name="MainData">
    <xs:complexType>
      <xs:sequence>
        <xs:element name="Orders">
          <xs:complexType>
            <xs:sequence>
              <xs:element name="Order" maxOccurs="unbounded">
                <xs:complexType>
                  <xs:sequence>
                    <xs:element name="OrderId" type="xs:string"/>
                    <xs:element name="Lines">
                      <xs:complexType>
                        <xs:sequence>
                          <xs:element name="Line" maxOccurs="unbounded">
                            <xs:complexType>
                              <xs:sequence>
                                <xs:element name="Description" type="xs:string"/>
                                <xs:element name="Quantity" type="xs:decimal"/>
                              </xs:sequence>
                            </xs:complexType>
                          </xs:element>
                        </xs:sequence>
                      </xs:complexType>
                    </xs:element>
                  </xs:sequence>
                </xs:complexType>
              </xs:element>
            </xs:sequence>
          </xs:complexType>
        </xs:element>
      </xs:sequence>
    </xs:complexType>
  </xs:element>
</xs:schema>
"""

NESTED_SAMPLE = """<?xml version="1.0" encoding="utf-8"?>
<Envelope>
  <MainData>
    <Orders>
      <Order>
        <OrderId>O-1</OrderId>
        <Lines>
          <Line><Description>Widget</Description><Quantity>2</Quantity></Line>
          <Line><Description>Gadget</Description><Quantity>5</Quantity></Line>
        </Lines>
      </Order>
      <Order>
        <OrderId>O-2</OrderId>
        <Lines>
          <Line><Description>Bolt</Description><Quantity>10</Quantity></Line>
        </Lines>
      </Order>
    </Orders>
  </MainData>
</Envelope>
"""

VAT_XSD = """<?xml version="1.0" encoding="utf-8"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
  <xs:element name="MainData">
    <xs:complexType>
      <xs:sequence>
        <xs:element name="Invoice">
          <xs:complexType>
            <xs:sequence>
              <xs:element name="InvoiceId" type="xs:string"/>
              <xs:element name="CustomerName" type="xs:string"/>
              <xs:element name="VatNumber" type="xs:string"/>
              <xs:element name="IsEU" type="xs:boolean"/>
              <xs:element name="NetAmount" type="xs:decimal"/>
              <xs:element name="TaxAmount" type="xs:decimal"/>
              <xs:element name="TotalAmount" type="xs:decimal"/>
            </xs:sequence>
          </xs:complexType>
        </xs:element>
      </xs:sequence>
    </xs:complexType>
  </xs:element>
</xs:schema>
"""

VAT_SAMPLE = """<?xml version="1.0" encoding="utf-8"?>
<VatInvoice>
  <MainData>
    <Invoice>
      <InvoiceId>INV-77</InvoiceId>
      <CustomerName>Nordic Trading AB</CustomerName>
      <VatNumber>SE556677889901</VatNumber>
      <IsEU>true</IsEU>
      <NetAmount>1000.00</NetAmount>
      <TaxAmount>250.00</TaxAmount>
      <TotalAmount>1250.00</TotalAmount>
    </Invoice>
  </MainData>
</VatInvoice>
"""

IMAGE_XSD = """<?xml version="1.0" encoding="utf-8"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
  <xs:element name="MainData">
    <xs:complexType>
      <xs:sequence>
        <xs:element name="Company">
          <xs:complexType>
            <xs:sequence>
              <xs:element name="Name" type="xs:string"/>
              <xs:element name="CompanyLogo" type="xs:base64Binary"/>
            </xs:sequence>
          </xs:complexType>
        </xs:element>
        <xs:element name="Report">
          <xs:complexType>
            <xs:sequence>
              <xs:element name="Title" type="xs:string"/>
              <xs:element name="TotalAmount" type="xs:decimal"/>
            </xs:sequence>
          </xs:complexType>
        </xs:element>
      </xs:sequence>
    </xs:complexType>
  </xs:element>
</xs:schema>
"""

# 1x1 transparent PNG, base64 encoded.
TINY_PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="

IMAGE_SAMPLE = f"""<?xml version="1.0" encoding="utf-8"?>
<Letterhead>
  <MainData>
    <Company>
      <Name>Contoso AG</Name>
      <CompanyLogo>{TINY_PNG_B64}</CompanyLogo>
    </Company>
    <Report>
      <Title>Annual Summary</Title>
      <TotalAmount>42.00</TotalAmount>
    </Report>
  </MainData>
</Letterhead>
"""

MULTILINGUAL_XSD = """<?xml version="1.0" encoding="utf-8"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
  <xs:element name="MainData">
    <xs:complexType>
      <xs:sequence>
        <xs:element name="Invoice">
          <xs:complexType>
            <xs:sequence>
              <xs:element name="InvoiceId" type="xs:string"/>
              <xs:element name="CustomerName" type="xs:string"/>
              <xs:element name="CurrencyCode" type="xs:string"/>
              <xs:element name="TotalAmount" type="xs:decimal"/>
            </xs:sequence>
          </xs:complexType>
        </xs:element>
      </xs:sequence>
    </xs:complexType>
  </xs:element>
</xs:schema>
"""

MULTILINGUAL_SAMPLE = """<?xml version="1.0" encoding="utf-8"?>
<Dokument>
  <MainData>
    <Invoice>
      <InvoiceId>RE-2026-1</InvoiceId>
      <CustomerName>Müller &amp; Söhne GmbH</CustomerName>
      <CurrencyCode>EUR</CurrencyCode>
      <TotalAmount>99.90</TotalAmount>
    </Invoice>
  </MainData>
</Dokument>
"""


def _package(xsd: str, sample: str | None, name: str) -> bytes:
    files = {"manifest.json": MANIFEST, "schema/schema.xsd": xsd.encode()}
    if sample is not None:
        files["data/sample.xml"] = sample.encode()
    return build_zip(files)


def _example(name: str, package: str) -> Fixture:
    return Fixture(
        name=name,
        package=(EXAMPLES / name / package).read_bytes(),
        prompt=(EXAMPLES / name / "prompt.txt").read_text(encoding="utf-8"),
    )


FIXTURES: dict[str, Fixture] = {
    "simple-fields": Fixture(
        name="simple-fields",
        package=_package(SIMPLE_XSD, SIMPLE_SAMPLE, "simple"),
        prompt="Create a simple document with the document number, issue date, customer name and total amount.",
    ),
    "sales-quotation": _example("quotation", "sales-quotation.ddsp"),
    "purchase-order": _example("purchase-order", "purchase-order.ddsp"),
    "nested-list": Fixture(
        name="nested-list",
        package=_package(NESTED_XSD, NESTED_SAMPLE, "nested"),
        prompt="Create an order report with a list of orders and their line items.",
    ),
    "conditional-vat": Fixture(
        name="conditional-vat",
        package=_package(VAT_XSD, VAT_SAMPLE, "vat"),
        prompt="Create a tax invoice with net, tax and total amounts and a VAT notice when the customer is in the EU.",
    ),
    "image-binding": Fixture(
        name="image-binding",
        package=_package(IMAGE_XSD, IMAGE_SAMPLE, "image"),
        prompt="Create a report with the company logo, the report title and the total amount.",
    ),
    "missing-data": Fixture(
        name="missing-data",
        package=_package(VAT_XSD, None, "missing"),
        prompt="Create an invoice with the customer name and a product image gallery.",
    ),
    "multilingual": Fixture(
        name="multilingual",
        package=_package(MULTILINGUAL_XSD, MULTILINGUAL_SAMPLE, "multilingual"),
        prompt="Create an invoice document with the invoice number, customer and amount.",
        language="de",
    ),
}

GOLDEN_ROOT = Path(__file__).resolve().parent / "expected"


def fixture_path(name: str) -> Path:
    return GOLDEN_ROOT / name


__all__ = ["FIXTURES", "GOLDEN_ROOT", "Fixture", "fixture_path"]
