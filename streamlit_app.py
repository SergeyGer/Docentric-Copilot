"""Interactive demo of Docentric Copilot — no API key, no external calls.

Run locally:  streamlit run streamlit_app.py
Deploy:       Streamlit Community Cloud, main file ``streamlit_app.py``.

Everything runs in-process on the deterministic mock provider: the same planner,
mapper, validator and DOCX compiler the API and CLI use.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import streamlit as st
from docentric_copilot.app.service import TemplateService
from docentric_copilot.ddsp_parser import parse_ddsp
from docentric_copilot.docx_compiler import CompileOptions
from docentric_copilot.planner import summarize_changes
from docentric_copilot.planner.rebind import rebind_paths
from docentric_copilot.planner.service import build_mapping_report
from docentric_copilot.template_ir import ir_digest

st.set_page_config(page_title="Docentric Copilot — live demo", page_icon="📄", layout="wide")

DEMO_DIR = Path(__file__).parent / "services" / "api" / "src" / "docentric_copilot" / "api" / "demo"
CASES = json.loads((DEMO_DIR / "manifest.json").read_text())["cases"]

STATUS_STYLE = {
    "confirmed": ("🟢", "Confirmed"),
    "schema_valid": ("🔵", "Schema-valid"),
    "needs_review": ("🟠", "Needs review"),
    "conflict": ("🔴", "Conflict"),
    "missing": ("⚪", "Missing"),
    "invalid": ("🔴", "Invalid"),
}
BLOCKING = {"needs_review", "conflict", "missing", "invalid"}


@st.cache_resource
def get_service() -> TemplateService:
    return TemplateService()


@st.cache_data(show_spinner=False)
def load_case(case_id: str):
    case = next(item for item in CASES if item["id"] == case_id)
    payload = (DEMO_DIR / case["package"]).read_bytes()
    parsed = parse_ddsp(payload, case["package"])
    return case, payload, parsed


@st.cache_data(show_spinner=False)
def plan(case_id: str, prompt: str):
    _case, _payload, parsed = load_case(case_id)
    outcome, report = asyncio.run(get_service().plan(parsed.schema, prompt, provider="mock"))
    return outcome, report, parsed.schema, parsed.sample_data


def badged(status: str) -> str:
    icon, label = STATUS_STYLE.get(status, ("⚪", status))
    return f"{icon} {label}"


st.sidebar.title("Docentric Copilot")
st.sidebar.caption("Schema-aware brief → validated Word document")
case_ids = [item["id"] for item in CASES]
case_id = st.sidebar.selectbox(
    "Demo package",
    case_ids,
    format_func=lambda cid: next(c["title"] for c in CASES if c["id"] == cid),
)
case, _payload, parsed = load_case(case_id)

prompt = st.sidebar.text_area("Business brief", value=case["prompt"], height=190)
st.sidebar.caption("Runs on the deterministic mock provider — no model key, no network calls.")
generate = st.sidebar.button("Generate document", type="primary", use_container_width=True)

if generate:
    st.session_state.pop("reviewed", None)
    st.session_state["confirmations"] = {}
st.session_state.setdefault("confirmations", {})

outcome, report, schema, sample_data = plan(case_id, prompt)
document = st.session_state.get("document", outcome.document)
if st.session_state.get("case_id") != case_id:
    st.session_state["case_id"] = case_id
    st.session_state["document"] = outcome.document
    st.session_state["confirmations"] = {}
    document = outcome.document

st.title("From a business brief to a validated Word document")
st.caption(
    "Every field is chosen from the loaded schema, every binding is checked, and the DOCX is compiled "
    "from a validated template — not generated as raw text."
)

stats = schema.stats()
cols = st.columns(5)
cols[0].metric("Scalar fields", stats.scalar_count)
cols[1].metric("Collections", stats.collection_count)
cols[2].metric("Sections", len(schema.section_names))
cols[3].metric("Provider", "mock (offline)")
cols[4].metric("IR digest", ir_digest(document)[:10])

tab_plan, tab_review, tab_preview, tab_revision, tab_evidence = st.tabs(
    ["1 · Plan", "2 · Mapping review", "3 · Preview & DOCX", "4 · Revision", "5 · Evidence"]
)

# --------------------------------------------------------------------- plan
with tab_plan:
    st.subheader("Typed requirements")
    st.write(
        "The brief is split into clauses and each clause is interpreted as a document requirement."
    )
    rows = [
        {
            "Requirement": item.requirement,
            "Concept": item.concept or "—",
            "Placement": item.placement or "body",
        }
        for item in outcome.mapping.mappings
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)
    st.subheader("Schema excerpt")
    st.dataframe(
        [
            {
                "Path": node.path,
                "Type": node.data_type,
                "Sample": str(node.sample_value)[:40] if node.sample_value is not None else "—",
            }
            for node in schema.scalars()
        ][:18],
        use_container_width=True,
        hide_index=True,
    )

# ------------------------------------------------------------------- review
with tab_review:
    mapping = build_mapping_report(schema, document, prompt)
    counts = mapping.counts()
    cols = st.columns(5)
    for column, status in zip(
        cols, ["confirmed", "schema_valid", "needs_review", "conflict", "missing"], strict=False
    ):
        column.metric(STATUS_STYLE[status][1], counts[status])

    st.dataframe(
        [
            {
                "Requirement": item.requirement,
                "Status": badged(item.status.value),
                "Schema field": item.selected_field_path or "—",
                "Confidence": f"{round((item.confidence_score or 0) * 100)}%",
                "Concept": item.concept or "—",
            }
            for item in mapping.mappings
        ],
        use_container_width=True,
        hide_index=True,
    )

    pending = [item for item in mapping.mappings if item.status.value in BLOCKING]
    if pending:
        st.warning(
            f"{len(pending)} mapping(s) need a decision before the DOCX can be compiled. "
            "Pick the correct field — the choice is recorded in a new template version."
        )
        for item in pending:
            with st.expander(f"{badged(item.status.value)} · {item.requirement}", expanded=True):
                st.write(item.explanation or "")
                options = list(
                    dict.fromkeys(
                        ([item.selected_field_path] if item.selected_field_path else [])
                        + item.candidate_field_paths
                    )
                )
                chosen = st.radio(
                    "Schema field",
                    options,
                    index=0,
                    key=f"choice-{item.requirement_id}",
                    format_func=lambda path: (
                        f"{path}  ·  {schema.node(path).data_type if schema.node(path) else '?'}"
                    ),
                )
                note = st.text_input(
                    "Reviewer note",
                    key=f"note-{item.requirement_id}",
                    placeholder="Why this field is correct",
                )
                if st.button(
                    "Confirm this binding", key=f"confirm-{item.requirement_id}", type="primary"
                ):
                    updated = document
                    if item.selected_field_path and item.selected_field_path != chosen:
                        updated, _ = rebind_paths(
                            document, schema, item.selected_field_path, chosen
                        )
                    st.session_state["document"] = updated
                    st.session_state["confirmations"][item.requirement_id] = (
                        note or "Confirmed by a reviewer."
                    )
                    st.rerun()
    else:
        st.success("All requirements are resolved. The document can be compiled.")

# ---------------------------------------------------------------- preview
with tab_preview:
    statuses = report.statuses() if hasattr(report, "statuses") else {}
    compile_ready = not [item for item in mapping.mappings if item.status.value in BLOCKING]
    compiled = None
    if compile_ready:
        compiled = get_service().compile(
            document,
            schema,
            sample_data=sample_data,
            options=CompileOptions(document_name=f"{case_id}.docx"),
        )
        st.download_button(
            "⬇ Download DOCX",
            data=compiled.content,
            file_name=f"{case_id}.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            type="primary",
        )
    else:
        st.info("Compile is locked until the mappings above are confirmed.")
    preview = get_service().preview(document, schema, sample_data=sample_data)
    st.components.v1.html(preview.html, height=820, scrolling=True)

# --------------------------------------------------------------- revision
with tab_revision:
    st.subheader("Change the document in plain language")
    st.caption(
        "Structural requests are applied as targeted edits — no model call, a small diff, and a new immutable version."
    )
    instruction = st.text_input(
        "Revision instruction",
        value="Make the product table more compact",
        key="revision-instruction",
    )
    if st.button("Apply revision"):
        revised = asyncio.run(get_service().revise(document, schema, instruction, provider="mock"))
        st.session_state["revised"] = revised
        st.session_state["document"] = revised.outcome.document

    revised = st.session_state.get("revised")
    if revised:
        st.write(summarize_changes(revised.changes))
        st.dataframe(
            [
                {"Change": c.kind, "Path": c.path, "Detail": str(c.before) + " → " + str(c.after)}
                for c in revised.changes
            ],
            use_container_width=True,
            hide_index=True,
        )
        left, right = st.columns(2)
        with left:
            st.caption("Before")
            st.components.v1.html(
                get_service().preview(outcome.document, schema, sample_data=sample_data).html,
                height=520,
                scrolling=True,
            )
        with right:
            st.caption("After")
            st.components.v1.html(
                get_service()
                .preview(revised.outcome.document, schema, sample_data=sample_data)
                .html,
                height=520,
                scrolling=True,
            )
        if st.button("Restore the original version"):
            st.session_state["document"] = outcome.document
            st.session_state.pop("revised", None)
            st.rerun()

# --------------------------------------------------------------- evidence
with tab_evidence:
    st.subheader("Validation")
    for name, status in report.statuses().items():
        st.write(f"**{name.replace('_', ' ').title()}**: `{status}`")
    st.caption(
        "Docentric AX compatibility is deliberately reported as not tested: the output is generic DOCX."
    )
    st.subheader("Mappings with evidence")
    st.json(
        [
            {
                "requirement": item.requirement,
                "status": item.status.value,
                "selected_path": item.selected_field_path,
                "confidence": item.confidence_score,
                "alternatives": item.candidate_field_paths,
                "conflict": item.conflict,
                "explanation": item.explanation,
            }
            for item in mapping.mappings
        ]
    )
