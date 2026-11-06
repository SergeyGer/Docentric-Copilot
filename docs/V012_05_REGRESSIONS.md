# V012-05 regressions — nested tables and repeat aliases

Issue #39 reported two independent defects observed in the v0.11 benchmark:

1. Gemini compact-v2 could not express an outer table whose row contains a
   nested repeat/table, so it emitted an outer `rep` with an inner `tbl` and
   failed the expected Table/Repeat hierarchy.
2. Anthropic could emit duplicate repeat aliases in separate branches, which
   V3-002 reported as a valid-template failure even though the branches cannot
   be active at the same time.

Both are fixed in the planner/validator, and both are covered by deterministic
tests that make no external model call.

| Field | Value |
| --- | --- |
| Tests | [tests/unit/test_v012_regressions.py](../tests/unit/test_v012_regressions.py) |
| Compact format | `packages/planner/.../compact_ir_v2.py` |
| Structural assertions | `packages/planner/.../structure.py` |
| Alias resolution | `packages/planner/.../aliases.py` |
| Validator | `packages/template-validator/.../engine.py` (V3-002) |
| External LLM required for tests | **No** |

## 1. Nested table in compact v2

A table column may now be an object instead of a positional array:

```json
["tbl", "MainData.ServiceOrderLines.Line", [
  ["Item", "line.ItemId"],
  {"h": "Tasks", "cell": [
    ["rep", "line.Tasks.Task", "task", [
      ["p", {"f": "task.TaskId"}],
      ["p", {"f": "task.Hours"}]
    ]]
  ]}
]]
```

- `h` is the column header; `cell` is a non-empty block list; `w` (5–200 mm)
  and `align` (`l/r/c/j`) are optional.
- Cell blocks expand inside the outer table row scope, so a nested repeat can
  use the outer alias (`line.Tasks.Task`) and introduces a unique inner alias
  (`task`).
- Unknown column keys, an empty cell, an invalid width or an invalid alignment
  raise `PlanInvalidError` with the exact JSON path before compile/export.
- Tables still fit the page: explicit widths are honoured and auto columns are
  scaled by the existing width fitter.

The new wire form is documented in the compact-v2 system prompt, so the model
is asked for the correct hierarchy rather than repaired after the fact.

## 2. Structural post-generation validator

`structural_findings(document, requirement)` runs before the plan is returned to
the planner's repair loop and before compile/export. It emits typed findings:

| Code | Meaning |
| --- | --- |
| `plan_table_hierarchy` | The requirement asks for a table, but there is no outer repeating table (only a repeat, a static table, or a table nested inside a repeat). |
| `plan_nested_table_wrapper` | A repeat over collection X wraps a table over the same X; that is a nested list, not the requested table. |
| `plan_table_without_rows` | A repeating table has no row template/cell blocks. |

The findings carry `severity: error`, a location such as `section[0].body[2]`
and a human-readable message. The planner raises `PlanInvalidError` with
`details.errors`; its repair loop receives the same locations and messages. If
the provider still cannot produce the hierarchy, the run fails before
compile/export with the typed diagnostic — it is never silently accepted.

The table check is conservative: it looks for an explicit `table`/`Tabelle`/
`tableau`/`grid` request and excludes `table of contents`.

## 3. Repeat-alias scope and deterministic resolution

V3-002 now treats these as independent alias scopes:

- the then and else branches of one conditional (mutually exclusive);
- each cell of a static table row;
- each cell of a table row template;
- nested repeats (a pushed scope, as before).

Two repeats in the same scope may still not share an alias. When a provider emits
such a conflict, `resolve_alias_conflicts` renames the later alias
deterministically (`line` → `line_2`, `line_3`, …) and rewrites every path that
uses the shadowed alias inside that block, including nested repeat paths and
condition fields. The planner records a repair note with code
`alias_conflict_resolved`, the location, the old alias and the replacement.
Aliases in separate branches/cells are left untouched.

This keeps the compiled document unambiguous without silently changing meaning:
the rename is reported, the IR is still validated, and the compile/export step
sees only unique aliases.

## 4. Tests and expected assertions

`tests/unit/test_v012_regressions.py` covers:

- a Gemini-style compact-v2 object column expanding to an outer `Table` with a
  nested `Repeat`, V1–V3 passing and a DOCX compile smoke test;
- the same payload producing no structural findings;
- an unknown object-column key being rejected with a path;
- sibling duplicate aliases renamed and their binding paths rewritten;
- duplicate aliases in conditional branches allowed and unchanged;
- duplicate aliases in independent table cells allowed and unchanged;
- duplicate table-repeat aliases renamed;
- the structural validator rejecting a repeat-instead-of-table plan, a
  same-collection wrapper and a table without row cells;
- the planner wiring structural findings into `PlanInvalidError` with
  `details.errors`.

All tests run without an API key.

### Live affected subset

The three nested cases were re-run after the fix (3 providers × 3 repeats = 27
logical runs):

| Provider | Completed | Correct | Semantic pass | Technical |
| --- | ---: | ---: | ---: | ---: |
| OpenAI | 9/9 | 9/9 | 100% | 0 |
| Anthropic | 9/9 | 9/9 | 100% | 0 |
| Gemini | 5/9 | 5/5 | 100% of evaluable | 4 `structured_output` |

The V3-002 Anthropic valid-template miss is gone, and every completed Gemini
nested plan satisfies the outer-table/nested-repeat hierarchy and the semantic
labels. The remaining four Gemini runs fail provider structured output before a
plan can be evaluated; they are technical failures, not structural or semantic
passes. Cost $0.4761. Report:
[gold_report_v012_v01205.json](../benchmarks/gold_report_v012_v01205.json).
The result is not spliced into the full 288-run benchmark, which was produced
before these fixes.

## 5. Known limits

- A provider can still choose a poor but structurally valid layout; the
  validator checks the requested hierarchy, not visual quality.
- The table requirement detector is lexical, not semantic. A requirement that
  describes a table without using one of the supported words is not forced into
  a table; an explicit table request is.
- The renamed alias is meaningful only inside its block; external references to
  the old alias do not exist in the IR contract.
- Docentric AX runtime compatibility remains `not_tested`.
