#!/usr/bin/env python3
"""Load, validate and describe the versioned gold semantic dataset.

The dataset is a JSON document with an explicit schema version. Validation is
deterministic and side-effect free: every expected path, alternative, forbidden
path and block path is checked against the DDSP schema of its case, the split
sizes and family coverage are enforced, and every case must satisfy the
family-specific annotation rules.

The labels were authored by the implementer. The rule pass below is a
consistency check, **not** an independent human review; see
``docs/GOLD_LABELS.md`` for the honest adjudication record.

Usage::

    .venv/bin/python benchmarks/gold_dataset.py --check
    .venv/bin/python benchmarks/gold_dataset.py --check --json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:  # pragma: no cover - import bootstrap when run as a script
    sys.path.insert(0, str(ROOT))

from docentric_copilot.ddsp_parser import parse_ddsp  # noqa: E402

from benchmarks.semantic_scoring import validate_cases  # noqa: E402

DEFAULT_CASES = ROOT / "benchmarks" / "gold_cases.json"
GOLD_SCHEMA = "gold-cases/v2"
GOLD_VERSION = "2.0.0"
EXPECTED_CASE_COUNT = 32
EXPECTED_SPLIT_SIZES = {"calibration": 20, "holdout": 12}
EXPECTED_FAMILY_COUNTS = {
    "flat_fields": 5,
    "images": 3,
    "collections": 4,
    "nested_lists": 3,
    "conditions": 3,
    "missing": 2,
    "ambiguous": 3,
    "multilingual": 3,
    "long_tables": 3,
    "forbidden_scope": 3,
}
EXPECTED_CATEGORY_COUNTS = {
    "purchase_order": 10,
    "sales_order": 10,
    "conditional_complex": 6,
    "adversarial": 6,
}
GOLD_FAMILIES: tuple[str, ...] = tuple(EXPECTED_FAMILY_COUNTS)
GOLD_CATEGORIES: tuple[str, ...] = tuple(EXPECTED_CATEGORY_COUNTS)
GOLD_SPLITS = ("calibration", "holdout")
GOLD_DIFFICULTIES = ("easy", "medium", "hard")
CASE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{2,80}$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True, slots=True)
class GoldDataset:
    """The parsed dataset plus the metadata needed by reports."""

    path: Path
    version: str
    created_at: str
    cases: tuple[dict[str, Any], ...]
    document: dict[str, Any]

    @property
    def canonical_sha256(self) -> str:
        return canonical_cases_sha256(self.cases)

    @property
    def file_sha256(self) -> str:
        return hashlib.sha256(self.path.read_bytes()).hexdigest()


def canonical_cases_json(cases: Sequence[Mapping[str, Any]]) -> str:
    return json.dumps(list(cases), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_cases_sha256(cases: Sequence[Mapping[str, Any]]) -> str:
    return hashlib.sha256(canonical_cases_json(cases).encode("utf-8")).hexdigest()


def _relative(path: Path) -> str:
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)


def _string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field} must be a non-empty list")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{field} contains a non-string or blank value")
        result.append(item.strip())
    return result


def load_gold_dataset(path: Path = DEFAULT_CASES) -> GoldDataset:
    """Read the dataset and enforce the top-level contract.

    Deeper path/type checks live in :func:`validate_gold_dataset` so callers can
    choose when to pay for parsing every DDSP.
    """
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read gold dataset {path}: {exc}") from exc
    if not isinstance(document, dict):
        raise ValueError("gold dataset must be a JSON object")
    if document.get("schema") != GOLD_SCHEMA:
        raise ValueError(f"unsupported gold dataset schema: {document.get('schema')!r}")
    version = document.get("version")
    if not isinstance(version, str) or not version.strip():
        raise ValueError("gold dataset version is missing")
    created_at = document.get("created_at")
    if not isinstance(created_at, str) or not DATE.match(created_at):
        raise ValueError("gold dataset created_at must be YYYY-MM-DD")
    try:
        date.fromisoformat(created_at)
    except ValueError as exc:
        raise ValueError(f"gold dataset created_at is not a date: {created_at!r}") from exc
    raw_cases = document.get("cases")
    if not isinstance(raw_cases, list):
        raise ValueError("gold dataset cases must be a list")
    cases: list[dict[str, Any]] = []
    for index, item in enumerate(raw_cases):
        if not isinstance(item, dict):
            raise ValueError(f"case {index} is not an object")
        cases.append(item)
    return GoldDataset(
        path=path,
        version=version,
        created_at=created_at,
        cases=tuple(cases),
        document=document,
    )


def schema_paths_for_case(case: Mapping[str, Any]) -> dict[str, str]:
    """Parse the case's DDSP and return ``{path: data_type}``."""
    package = ROOT / str(case.get("package") or "")
    parsed = parse_ddsp(package.read_bytes(), package.name)
    return {path: parsed.schema.node(path).data_type for path in parsed.schema.paths}


def _safe_schema_paths(case: Mapping[str, Any]) -> dict[str, str]:
    """Parse only a public, in-repo DDSP; never touch private corpus material."""
    raw = str(case.get("package") or "")
    package = Path(raw)
    if (
        not raw
        or package.is_absolute()
        or ".." in package.parts
        or "corpus" in package.parts
        or ".tools" in package.parts
        or package.suffix != ".ddsp"
    ):
        return {}
    if not (ROOT / package).is_file():
        return {}
    try:
        return schema_paths_for_case(case)
    except (OSError, ValueError):
        return {}


def _collection_paths(case: Mapping[str, Any]) -> set[str]:
    schema_paths = _safe_schema_paths(case)
    if not schema_paths:
        return set()
    package = ROOT / str(case.get("package") or "")
    try:
        parsed = parse_ddsp(package.read_bytes(), package.name)
    except (OSError, ValueError):
        return set()
    return {node.path for node in parsed.schema.collections()}


def _schema_by_package(
    cases: Iterable[Mapping[str, Any]],
    schemas: Mapping[str, Mapping[str, str]] | None,
) -> dict[str, dict[str, str]]:
    if schemas is not None:
        return {str(package): dict(paths) for package, paths in schemas.items()}
    result: dict[str, dict[str, str]] = {}
    for case in cases:
        package = str(case.get("package") or "")
        if package and package not in result:
            result[package] = _safe_schema_paths(case)
    return result


def _family_errors(
    case: Mapping[str, Any],
    schema_paths: Mapping[str, str],
    collections: set[str],
) -> list[str]:
    case_id = str(case.get("id"))
    family = str(case.get("family"))
    requirements = case.get("required_bindings") or []
    forbidden = case.get("forbidden_paths") or []
    blocks = case.get("expected_blocks") or []
    labels = case.get("labels") or []
    errors: list[str] = []
    if family not in labels:
        errors.append(f"{case_id}: family {family!r} is not in labels")

    paths = [
        path
        for requirement in requirements
        if isinstance(requirement, Mapping)
        for path in (
            *(requirement.get("expected_paths") or []),
            *(requirement.get("allowed_alternatives") or []),
        )
        if isinstance(path, str)
    ]
    repeat_paths = [
        path
        for requirement in requirements
        if isinstance(requirement, Mapping) and requirement.get("expected_context") == "repeat"
        for path in (
            *(requirement.get("expected_paths") or []),
            *(requirement.get("allowed_alternatives") or []),
        )
        if isinstance(path, str)
    ]
    if family == "flat_fields":
        if blocks:
            errors.append(f"{case_id}: flat_fields must not declare blocks")
        if repeat_paths:
            errors.append(f"{case_id}: flat_fields must not use repeat context")
    elif family == "images":
        if not any(
            isinstance(requirement, Mapping) and requirement.get("expected_type") == "image"
            for requirement in requirements
        ) and not any(
            isinstance(block, Mapping) and block.get("kind") == "image" for block in blocks
        ):
            errors.append(f"{case_id}: images family needs an image binding or image block")
    elif family == "collections":
        if not any(
            isinstance(block, Mapping) and block.get("kind") in {"table", "repeat"}
            for block in blocks
        ):
            errors.append(f"{case_id}: collections family needs a table or repeat block")
        if not repeat_paths:
            errors.append(f"{case_id}: collections family needs repeat-context bindings")
    elif family == "nested_lists":
        nested = any(".Tasks.Task." in path for path in paths)
        inner_repeat = any(
            ".Tasks.Task" in (block.get("path") or "")
            for block in blocks
            if isinstance(block, Mapping)
        )
        if not (nested and inner_repeat):
            errors.append(f"{case_id}: nested_lists family needs a nested Tasks.Task repeat")
    elif family == "conditions":
        if not any(
            isinstance(block, Mapping) and block.get("kind") == "conditional" for block in blocks
        ):
            errors.append(f"{case_id}: conditions family needs a conditional block")
        if not any(
            isinstance(requirement, Mapping)
            and requirement.get("expected_context") == "conditional"
            for requirement in requirements
        ):
            errors.append(f"{case_id}: conditions family needs a conditional-context binding")
    elif family == "missing":
        if not any(
            isinstance(requirement, Mapping) and requirement.get("satisfiable") is False
            for requirement in requirements
        ):
            errors.append(f"{case_id}: missing family needs an unsatisfiable requirement")
    elif family == "ambiguous":
        if not any(
            isinstance(requirement, Mapping) and (requirement.get("allowed_alternatives") or [])
            for requirement in requirements
        ):
            errors.append(f"{case_id}: ambiguous family needs allowed_alternatives")
    elif family == "multilingual":
        if case.get("language") == "en":
            errors.append(f"{case_id}: multilingual family needs a non-English language")
    elif family == "long_tables":
        if not any(isinstance(block, Mapping) and block.get("kind") == "table" for block in blocks):
            errors.append(f"{case_id}: long_tables family needs a table block")
        if len(paths) < 3:
            errors.append(f"{case_id}: long_tables family needs at least three columns")
    elif family == "forbidden_scope":
        if not forbidden:
            errors.append(f"{case_id}: forbidden_scope family needs forbidden_paths")
    else:
        errors.append(f"{case_id}: unknown family {family!r}")

    block_paths = [
        block.get("path")
        for block in blocks
        if isinstance(block, Mapping) and isinstance(block.get("path"), str)
    ]
    for path in block_paths:
        if path not in schema_paths:
            errors.append(f"{case_id}: block path {path!r} is not in the schema")
        kind = next(
            block.get("kind")
            for block in blocks
            if isinstance(block, Mapping) and block.get("path") == path
        )
        if kind in {"table", "repeat"} and path not in collections:
            errors.append(f"{case_id}: {kind} block path {path!r} is not a collection")
        if kind == "image" and schema_paths.get(path) != "image":
            errors.append(f"{case_id}: image block path {path!r} is not an image")
    return errors


def _provenance_errors(dataset: GoldDataset) -> list[str]:
    """Check the v2 annotation-provenance contract.

    A v2 dataset must say who authored each label, which deterministic pass
    adjudicated it, and whether that pass agreed. A gap case is allowed, but it
    must carry ``label_status: "gap"`` so the scorer can exclude it from the
    semantic denominators. The contract deliberately does not claim human
    double review: AT-07 stays partial.
    """
    errors: list[str] = []
    provenance = dataset.document.get("provenance")
    if not isinstance(provenance, dict):
        return ["dataset provenance block is missing"]
    for field in ("author", "adjudicator", "review_status", "at07_status"):
        if not isinstance(provenance.get(field), str) or not provenance.get(field):
            errors.append(f"dataset provenance is missing {field}")
    if provenance.get("human_review") is not False:
        errors.append("dataset provenance must keep human_review=false until a human review exists")
    if provenance.get("at07_status") != "partial":
        errors.append("dataset provenance must keep AT-07 status=partial")
    for case in dataset.cases:
        case_id = str(case.get("id"))
        if case.get("label_status") not in {"verified", "gap"}:
            errors.append(f"{case_id}: label_status must be 'verified' or 'gap'")
        case_provenance = case.get("provenance")
        if not isinstance(case_provenance, dict):
            errors.append(f"{case_id}: case provenance is missing")
        else:
            for field in ("author", "adjudicator", "agreement"):
                if field not in case_provenance:
                    errors.append(f"{case_id}: case provenance is missing {field}")
        requirements = [
            item for item in case.get("required_bindings") or [] if isinstance(item, dict)
        ]
        for requirement in requirements:
            binding_provenance = requirement.get("provenance")
            if not isinstance(binding_provenance, dict):
                errors.append(f"{case_id}: requirement {requirement.get('id')!r} has no provenance")
                continue
            for field in ("author", "adjudicator", "agreement"):
                if field not in binding_provenance:
                    errors.append(
                        f"{case_id}: requirement {requirement.get('id')!r} provenance "
                        f"is missing {field}"
                    )
        forbidden = case.get("forbidden_paths") or []
        forbidden_provenance = case.get("forbidden_provenance")
        if forbidden and not isinstance(forbidden_provenance, dict):
            errors.append(f"{case_id}: forbidden_provenance is missing")
        elif isinstance(forbidden_provenance, dict):
            missing = [path for path in forbidden if path not in forbidden_provenance]
            if missing:
                errors.append(f"{case_id}: forbidden_provenance is missing {missing}")
        blocks = case.get("expected_blocks") or []
        block_provenance = case.get("block_provenance")
        if blocks and not isinstance(block_provenance, list):
            errors.append(f"{case_id}: block_provenance is missing")
        elif isinstance(block_provenance, list) and len(block_provenance) != len(blocks):
            errors.append(f"{case_id}: block_provenance length does not match expected blocks")
    return errors


def validate_gold_dataset(
    dataset: GoldDataset,
    *,
    schemas: Mapping[str, Mapping[str, str]] | None = None,
    check_counts: bool = True,
) -> list[str]:
    """Return human-readable problems; an empty list means the dataset is usable."""
    errors: list[str] = []
    cases = list(dataset.cases)
    if not cases:
        return ["gold dataset has no cases"]
    if check_counts and dataset.version != GOLD_VERSION:
        errors.append(f"dataset version {dataset.version!r} != expected {GOLD_VERSION!r}")
    if check_counts and len(cases) != EXPECTED_CASE_COUNT:
        errors.append(f"expected {EXPECTED_CASE_COUNT} cases, found {len(cases)}")

    seen: set[str] = set()
    for index, case in enumerate(cases):
        case_id = case.get("id")
        if not isinstance(case_id, str) or not CASE_ID.match(case_id):
            errors.append(f"case {index}: invalid id {case_id!r}")
            continue
        if case_id in seen:
            errors.append(f"duplicate case id {case_id!r}")
        seen.add(case_id)
        for field in ("prompt", "package", "family", "category", "difficulty", "split"):
            if not isinstance(case.get(field), str) or not str(case[field]).strip():
                errors.append(f"{case_id}: missing {field}")
        if case.get("family") not in GOLD_FAMILIES:
            errors.append(f"{case_id}: invalid family {case.get('family')!r}")
        if case.get("category") not in GOLD_CATEGORIES:
            errors.append(f"{case_id}: invalid category {case.get('category')!r}")
        if case.get("difficulty") not in GOLD_DIFFICULTIES:
            errors.append(f"{case_id}: invalid difficulty {case.get('difficulty')!r}")
        if case.get("split") not in GOLD_SPLITS:
            errors.append(f"{case_id}: invalid split {case.get('split')!r}")
        try:
            labels = _string_list(case.get("labels"), f"{case_id}.labels")
        except ValueError as exc:
            errors.append(str(exc))
            labels = []
        if case.get("family") and case.get("family") not in labels:
            errors.append(f"{case_id}: family missing from labels")
        package = case.get("package")
        if isinstance(package, str):
            package_path = Path(package)
            if package_path.is_absolute() or ".." in package_path.parts:
                errors.append(f"{case_id}: package must be a relative path")
            if "corpus" in package_path.parts or ".tools" in package_path.parts:
                errors.append(f"{case_id}: package points at private corpus material")
            if package_path.suffix != ".ddsp":
                errors.append(f"{case_id}: package must be a .ddsp file")
            if not (ROOT / package_path).exists():
                errors.append(f"{case_id}: package does not exist: {package}")
        prompt = case.get("prompt")
        if isinstance(prompt, str) and len(prompt.strip()) < 10:
            errors.append(f"{case_id}: prompt is too short to be meaningful")

    packages_ok = all(
        isinstance(case.get("package"), str)
        and not Path(str(case["package"])).is_absolute()
        and ".." not in Path(str(case["package"])).parts
        and "corpus" not in Path(str(case["package"])).parts
        and ".tools" not in Path(str(case["package"])).parts
        and Path(str(case["package"])).suffix == ".ddsp"
        and (ROOT / str(case["package"])).is_file()
        for case in cases
    )
    if packages_ok:
        schema_map = _schema_by_package(cases, schemas)
        for case in cases:
            package = str(case.get("package") or "")
            schema_paths = schema_map.get(package, {})
            if not schema_paths:
                continue
            errors.extend(validate_cases([case], schema_paths=schema_paths))
            errors.extend(_family_errors(case, schema_paths, _collection_paths(case)))

    errors.extend(_provenance_errors(dataset))

    families = Counter(str(case.get("family")) for case in cases)
    categories = Counter(str(case.get("category")) for case in cases)
    splits = Counter(str(case.get("split")) for case in cases)
    if check_counts:
        if dict(families) != EXPECTED_FAMILY_COUNTS:
            errors.append(f"family counts {dict(families)} != {EXPECTED_FAMILY_COUNTS}")
        if dict(categories) != EXPECTED_CATEGORY_COUNTS:
            errors.append(f"category counts {dict(categories)} != {EXPECTED_CATEGORY_COUNTS}")
        if dict(splits) != EXPECTED_SPLIT_SIZES:
            errors.append(f"split sizes {dict(splits)} != {EXPECTED_SPLIT_SIZES}")
        if dataset.document.get("expected_case_count") != len(cases):
            errors.append("dataset metadata expected_case_count does not match the cases")
        if dataset.document.get("split_sizes") != EXPECTED_SPLIT_SIZES:
            errors.append("dataset metadata split_sizes does not match the enforced split")
        if set(dataset.document.get("families") or []) != set(GOLD_FAMILIES):
            errors.append("dataset metadata families do not match the enforced families")
        if set(dataset.document.get("categories") or []) != set(GOLD_CATEGORIES):
            errors.append("dataset metadata categories do not match the enforced categories")
        for split in GOLD_SPLITS:
            split_families = {
                str(case.get("family")) for case in cases if case.get("split") == split
            }
            missing = set(GOLD_FAMILIES) - split_families
            if missing:
                errors.append(f"{split} split is missing families: {sorted(missing)}")
    return errors


def dataset_metadata(dataset: GoldDataset) -> dict[str, Any]:
    """Describe the dataset for a report. Counts are derived, never hand-written."""
    cases = list(dataset.cases)

    families = Counter(str(case.get("family")) for case in cases)
    categories = Counter(str(case.get("category")) for case in cases)
    languages = Counter(str(case.get("language") or "en") for case in cases)
    difficulties = Counter(str(case.get("difficulty")) for case in cases)
    splits = Counter(str(case.get("split")) for case in cases)
    return {
        "file": _relative(dataset.path),
        "schema": GOLD_SCHEMA,
        "version": dataset.version,
        "created_at": dataset.created_at,
        "sha256": dataset.canonical_sha256,
        "file_sha256": dataset.file_sha256,
        "hash": dataset.canonical_sha256[:16],
        "case_count": len(cases),
        "splits": dict(sorted(splits.items())),
        "families": dict(sorted(families.items())),
        "categories": dict(sorted(categories.items())),
        "languages": dict(sorted(languages.items())),
        "difficulties": dict(sorted(difficulties.items())),
        "labels_provenance": dataset.document.get("provenance", {}),
        "split_policy": dataset.document.get("split_policy", ""),
        "label_status": dict(
            sorted(Counter(str(case.get("label_status") or "verified") for case in cases).items())
        ),
        "gap_cases": [
            str(case.get("id"))
            for case in cases
            if str(case.get("label_status") or "verified") == "gap"
        ],
        "at07_status": (dataset.document.get("provenance") or {}).get("at07_status", "partial"),
        "image_subtypes": dict(
            sorted(
                Counter(
                    str(case.get("image_subtype") or "unspecified")
                    for case in cases
                    if str(case.get("family")) == "images"
                ).items()
            )
        ),
    }


def cases_for_split(dataset: GoldDataset, split: str) -> tuple[dict[str, Any], ...]:
    if split not in (*GOLD_SPLITS, "all"):
        raise ValueError(f"split must be one of {', '.join((*GOLD_SPLITS, 'all'))}")
    if split == "all":
        return dataset.cases
    return tuple(case for case in dataset.cases if case.get("split") == split)


def print_summary(dataset: GoldDataset) -> None:
    metadata = dataset_metadata(dataset)
    print(f"{metadata['file']} · version {metadata['version']} · {metadata['case_count']} cases")
    print(f"sha256 {metadata['sha256']}")
    print(f"splits {metadata['splits']}")
    print(f"families {metadata['families']}")
    print(f"categories {metadata['categories']}")
    print(f"languages {metadata['languages']}")
    print(f"difficulties {metadata['difficulties']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--check", action="store_true", help="validate and exit")
    parser.add_argument("--json", action="store_true", help="print metadata as JSON")
    args = parser.parse_args(argv)
    try:
        dataset = load_gold_dataset(args.cases)
    except ValueError as exc:
        print(f"gold dataset error: {exc}", file=sys.stderr)
        return 2
    errors = validate_gold_dataset(dataset)
    if errors:
        print("gold dataset is invalid:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(dataset_metadata(dataset), indent=2, sort_keys=True))
    else:
        print_summary(dataset)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
