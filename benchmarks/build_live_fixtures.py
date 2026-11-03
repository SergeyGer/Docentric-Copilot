#!/usr/bin/env python3
"""Build the two extra DDSP fixtures the live benchmark needs.

The three ``examples/`` packages cover flat fields, repeating tables and
conditionals, but they deliberately have no nested collection and no wide line
table. The benchmark adds exactly two small synthetic packages:

* ``field-service.ddsp`` - a service order whose lines carry a nested ``Tasks``
  collection (tests nested repeats and alias scopes);
* ``sales-order-wide.ddsp`` - a sales order with a 12-column line table (tests a
  long table against a fixed output budget).

Both are deterministic ZIPs with fixed timestamps, so the committed bytes are
reproducible. They contain synthetic data only.

Usage::

    python benchmarks/build_live_fixtures.py [--check]
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "benchmarks" / "fixtures"
FIXED_TIME = (2024, 1, 1, 0, 0, 0)
MANIFEST = {
    "format": "docentric-ax-ddsp",
    "format_version": "1.0",
    "generator": "docentric-copilot/benchmarks/build_live_fixtures.py",
    "license": "Apache-2.0",
    "synthetic": True,
}

FIELD_SERVICE_XSD = """<?xml version="1.0" encoding="utf-8"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" elementFormDefault="qualified">
  <xs:element name="MainData">
    <xs:complexType>
      <xs:sequence>
        <xs:element name="ServiceOrder" type="ServiceOrderType" minOccurs="1"/>
        <xs:element name="ServiceOrderLines" type="ServiceOrderLinesType" minOccurs="1"/>
      </xs:sequence>
    </xs:complexType>
  </xs:element>

  <xs:complexType name="ServiceOrderType">
    <xs:sequence>
      <xs:element name="OrderId" type="xs:string" minOccurs="1"/>
      <xs:element name="OrderDate" type="xs:date" minOccurs="1"/>
      <xs:element name="CurrencyCode" type="xs:string" minOccurs="1"/>
      <xs:element name="Customer" type="CustomerType" minOccurs="1"/>
      <xs:element name="TotalAmount" type="xs:decimal" minOccurs="1"/>
      <xs:element name="ServiceNote" type="xs:string" minOccurs="0"/>
    </xs:sequence>
  </xs:complexType>

  <xs:complexType name="CustomerType">
    <xs:sequence>
      <xs:element name="AccountNum" type="xs:string" minOccurs="1"/>
      <xs:element name="Name" type="xs:string" minOccurs="1"/>
      <xs:element name="Address" type="xs:string" minOccurs="0"/>
      <xs:element name="IsEU" type="xs:boolean" minOccurs="0"/>
    </xs:sequence>
  </xs:complexType>

  <xs:complexType name="ServiceOrderLinesType">
    <xs:sequence>
      <xs:element name="Line" type="ServiceOrderLineType" maxOccurs="unbounded"/>
    </xs:sequence>
  </xs:complexType>

  <xs:complexType name="ServiceOrderLineType">
    <xs:sequence>
      <xs:element name="ItemId" type="xs:string" minOccurs="1"/>
      <xs:element name="Description" type="xs:string" minOccurs="1"/>
      <xs:element name="Quantity" type="xs:decimal" minOccurs="1"/>
      <xs:element name="UnitPrice" type="xs:decimal" minOccurs="1"/>
      <xs:element name="LineAmount" type="xs:decimal" minOccurs="1"/>
      <xs:element name="Tasks" type="TaskLinesType" minOccurs="0"/>
    </xs:sequence>
  </xs:complexType>

  <xs:complexType name="TaskLinesType">
    <xs:sequence>
      <xs:element name="Task" type="TaskType" maxOccurs="unbounded"/>
    </xs:sequence>
  </xs:complexType>

  <xs:complexType name="TaskType">
    <xs:sequence>
      <xs:element name="TaskId" type="xs:string" minOccurs="1"/>
      <xs:element name="Description" type="xs:string" minOccurs="1"/>
      <xs:element name="Hours" type="xs:decimal" minOccurs="1"/>
      <xs:element name="Rate" type="xs:decimal" minOccurs="1"/>
      <xs:element name="Amount" type="xs:decimal" minOccurs="1"/>
    </xs:sequence>
  </xs:complexType>

  <xs:element name="GeneralData">
    <xs:complexType>
      <xs:sequence>
        <xs:element name="Company" type="CompanyType" minOccurs="1"/>
      </xs:sequence>
    </xs:complexType>
  </xs:element>

  <xs:complexType name="CompanyType">
    <xs:sequence>
      <xs:element name="Name" type="xs:string" minOccurs="1"/>
      <xs:element name="CompanyLogo" type="xs:base64Binary" minOccurs="0"/>
      <xs:element name="Address" type="xs:string" minOccurs="0"/>
    </xs:sequence>
  </xs:complexType>
</xs:schema>
"""

FIELD_SERVICE_SAMPLE = """<?xml version="1.0" encoding="utf-8"?>
<FieldServiceOrder>
  <MainData>
    <ServiceOrder>
      <OrderId>SO-2041</OrderId>
      <OrderDate>2026-05-11</OrderDate>
      <CurrencyCode>EUR</CurrencyCode>
      <Customer>
        <AccountNum>FR-7781</AccountNum>
        <Name>Atelier Lumiere SARL</Name>
        <Address>14 rue de Rivoli, 75001 Paris, France</Address>
        <IsEU>true</IsEU>
      </Customer>
      <TotalAmount>1840.00</TotalAmount>
      <ServiceNote>On-site service, weekdays only.</ServiceNote>
    </ServiceOrder>
    <ServiceOrderLines>
      <Line>
        <ItemId>SVC-INSTALL</ItemId>
        <Description>Installation and commissioning</Description>
        <Quantity>1</Quantity>
        <UnitPrice>640.00</UnitPrice>
        <LineAmount>640.00</LineAmount>
        <Tasks>
          <Task>
            <TaskId>T-01</TaskId>
            <Description>Site survey</Description>
            <Hours>2.0</Hours>
            <Rate>95.00</Rate>
            <Amount>190.00</Amount>
          </Task>
          <Task>
            <TaskId>T-02</TaskId>
            <Description>Mounting and wiring</Description>
            <Hours>4.5</Hours>
            <Rate>100.00</Rate>
            <Amount>450.00</Amount>
          </Task>
        </Tasks>
      </Line>
      <Line>
        <ItemId>SVC-TRAINING</ItemId>
        <Description>Operator training</Description>
        <Quantity>1</Quantity>
        <UnitPrice>1200.00</UnitPrice>
        <LineAmount>1200.00</LineAmount>
        <Tasks>
          <Task>
            <TaskId>T-03</TaskId>
            <Description>Classroom session</Description>
            <Hours>6.0</Hours>
            <Rate>100.00</Rate>
            <Amount>600.00</Amount>
          </Task>
        </Tasks>
      </Line>
    </ServiceOrderLines>
  </MainData>
  <GeneralData>
    <Company>
      <Name>Northwind Services GmbH</Name>
      <Address>Industriestrasse 4, 80339 Munich, Germany</Address>
    </Company>
  </GeneralData>
</FieldServiceOrder>
"""

SALES_ORDER_XSD = """<?xml version="1.0" encoding="utf-8"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" elementFormDefault="qualified">
  <xs:element name="MainData">
    <xs:complexType>
      <xs:sequence>
        <xs:element name="SalesOrder" type="SalesOrderType" minOccurs="1"/>
        <xs:element name="SalesOrderLines" type="SalesOrderLinesType" minOccurs="1"/>
      </xs:sequence>
    </xs:complexType>
  </xs:element>

  <xs:complexType name="SalesOrderType">
    <xs:sequence>
      <xs:element name="OrderId" type="xs:string" minOccurs="1"/>
      <xs:element name="OrderDate" type="xs:date" minOccurs="1"/>
      <xs:element name="CurrencyCode" type="xs:string" minOccurs="1"/>
      <xs:element name="Customer" type="CustomerType" minOccurs="1"/>
      <xs:element name="TotalAmount" type="xs:decimal" minOccurs="1"/>
      <xs:element name="TaxAmount" type="xs:decimal" minOccurs="0"/>
      <xs:element name="DeliveryTerms" type="xs:string" minOccurs="0"/>
    </xs:sequence>
  </xs:complexType>

  <xs:complexType name="CustomerType">
    <xs:sequence>
      <xs:element name="AccountNum" type="xs:string" minOccurs="1"/>
      <xs:element name="Name" type="xs:string" minOccurs="1"/>
      <xs:element name="Address" type="xs:string" minOccurs="0"/>
      <xs:element name="IsEU" type="xs:boolean" minOccurs="0"/>
    </xs:sequence>
  </xs:complexType>

  <xs:complexType name="SalesOrderLinesType">
    <xs:sequence>
      <xs:element name="Line" type="SalesOrderLineType" maxOccurs="unbounded"/>
    </xs:sequence>
  </xs:complexType>

  <xs:complexType name="SalesOrderLineType">
    <xs:sequence>
      <xs:element name="ItemId" type="xs:string" minOccurs="1"/>
      <xs:element name="Description" type="xs:string" minOccurs="1"/>
      <xs:element name="Quantity" type="xs:decimal" minOccurs="1"/>
      <xs:element name="Unit" type="xs:string" minOccurs="0"/>
      <xs:element name="UnitPrice" type="xs:decimal" minOccurs="1"/>
      <xs:element name="DiscountPct" type="xs:decimal" minOccurs="0"/>
      <xs:element name="NetAmount" type="xs:decimal" minOccurs="1"/>
      <xs:element name="TaxAmount" type="xs:decimal" minOccurs="0"/>
      <xs:element name="LineAmount" type="xs:decimal" minOccurs="1"/>
      <xs:element name="Warehouse" type="xs:string" minOccurs="0"/>
      <xs:element name="DeliveryDate" type="xs:date" minOccurs="0"/>
      <xs:element name="LineNote" type="xs:string" minOccurs="0"/>
    </xs:sequence>
  </xs:complexType>

  <xs:element name="GeneralData">
    <xs:complexType>
      <xs:sequence>
        <xs:element name="Company" type="CompanyType" minOccurs="1"/>
      </xs:sequence>
    </xs:complexType>
  </xs:element>

  <xs:complexType name="CompanyType">
    <xs:sequence>
      <xs:element name="Name" type="xs:string" minOccurs="1"/>
      <xs:element name="CompanyLogo" type="xs:base64Binary" minOccurs="0"/>
    </xs:sequence>
  </xs:complexType>
</xs:schema>
"""

SALES_ORDER_SAMPLE = """<?xml version="1.0" encoding="utf-8"?>
<SalesOrder>
  <MainData>
    <SalesOrder>
      <OrderId>SO-88120</OrderId>
      <OrderDate>2026-06-02</OrderDate>
      <CurrencyCode>USD</CurrencyCode>
      <Customer>
        <AccountNum>US-4410</AccountNum>
        <Name>Contoso Distribution Inc.</Name>
        <Address>500 Market Street, Seattle, WA 98101, USA</Address>
        <IsEU>false</IsEU>
      </Customer>
      <TotalAmount>12480.00</TotalAmount>
      <TaxAmount>980.00</TaxAmount>
      <DeliveryTerms>FOB Seattle, net 30 days.</DeliveryTerms>
    </SalesOrder>
    <SalesOrderLines>
      <Line>
        <ItemId>HW-100</ItemId>
        <Description>Industrial sensor kit</Description>
        <Quantity>10</Quantity>
        <Unit>pcs</Unit>
        <UnitPrice>1248.00</UnitPrice>
        <DiscountPct>0.00</DiscountPct>
        <NetAmount>12480.00</NetAmount>
        <TaxAmount>980.00</TaxAmount>
        <LineAmount>13460.00</LineAmount>
        <Warehouse>SEA-01</Warehouse>
        <DeliveryDate>2026-06-20</DeliveryDate>
        <LineNote>Fragile, handle with care.</LineNote>
      </Line>
      <Line>
        <ItemId>HW-205</ItemId>
        <Description>Mounting bracket set</Description>
        <Quantity>24</Quantity>
        <Unit>pcs</Unit>
        <UnitPrice>48.50</UnitPrice>
        <DiscountPct>5.00</DiscountPct>
        <NetAmount>1105.80</NetAmount>
        <TaxAmount>88.46</TaxAmount>
        <LineAmount>1194.26</LineAmount>
        <Warehouse>SEA-02</Warehouse>
        <DeliveryDate>2026-06-24</DeliveryDate>
        <LineNote>Standard packaging.</LineNote>
      </Line>
    </SalesOrderLines>
  </MainData>
  <GeneralData>
    <Company>
      <Name>Northwind Components Inc.</Name>
    </Company>
  </GeneralData>
</SalesOrder>
"""

SPECS: dict[str, dict[str, str]] = {
    "field-service": {
        "name": "field_service",
        "xsd": FIELD_SERVICE_XSD,
        "sample": FIELD_SERVICE_SAMPLE,
    },
    "sales-order-wide": {
        "name": "sales_order_wide",
        "xsd": SALES_ORDER_XSD,
        "sample": SALES_ORDER_SAMPLE,
    },
}


def build_zip(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, date_time=FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, files[name])
    return buffer.getvalue()


def build(spec: dict[str, str]) -> bytes:
    manifest = dict(MANIFEST)
    manifest["name"] = spec["name"]
    files = {
        "manifest.json": (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode(),
        "schema/schema.xsd": spec["xsd"].encode(),
        "data/sample.xml": spec["sample"].encode(),
    }
    return build_zip(files)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify committed fixtures")
    args = parser.parse_args(argv)
    failures = 0
    for name, spec in SPECS.items():
        path = FIXTURES / f"{name}.ddsp"
        payload = build(spec)
        if args.check:
            if not path.exists() or path.read_bytes() != payload:
                print(f"out of date: {path.relative_to(ROOT)}")
                failures += 1
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
            print(f"wrote {path.relative_to(ROOT)} ({len(payload)} bytes)")
    if args.check and failures:
        print(f"{failures} fixture(s) out of date", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
