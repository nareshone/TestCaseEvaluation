"""
app.py - CEV Exemption Rules Test Portal - Streamlit UI
"""
import json
import os
import io
import time
import threading
from datetime import datetime
from typing import Dict, Any

import streamlit as st
import pandas as pd

# ─── Page config must be first ───
st.set_page_config(
    page_title="CEV Rules Test Portal",
    page_icon="🧪",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Imports ───
from vector_store import RulesVectorStore
from mock_api import execute_request
from excel_reporter import generate_excel_report, compute_summary_stats

# ─── Defaults ───
DEFAULT_RULES = """Below rules are listed in priority wise. Exemption will be happened based on the priority.
1. TANF
if TANF_Flag==TRUE -> Exempt (Reason: TANF Work Requirements Compliance)
Else -> Not Exempt (Continue to next rule)

2. SNAP
If SNAP_FLAG==TRUE -> Exempt (Reason: SNAP Household)
Else -> Not Exempt (Continue to next rule)

3. Under 19 Individual
If age<19: return Exempt (Reason: Under 19)
else: return Not Exempt (Continue to next rule)

4. Exemption: Former Inmate within 3-Month lookback (Grace Period)
A former inmate is Exempt if their release date is within 3 months prior to the determination date.
If FormerInmateFlag=True and releaseDate between AsOfDate - 3 months and AsOfDate then Exempt (Reason: Former Inmate - 3-month grace)
else Not Exempt (Continue to next rule)

5. Exemption: Child Caregiver
A Medicaid expansion member is Exempt from CEV requirements if the source system indicates that the member is a caretaker (parent/guardian/relative) of a child aged 13 or younger.
If CaretakerOfChildUnder13_Flag==True -> Exempt (Reason: Child Caregiver)
Else Not Exempt (Continue to next rule)

6. Exemption: Disabled Individual Caregiver
A medical expansion member is Exempt from CEV requirements if the source system indicates that the member is a caretaker/guardian/relative responsible for a disabled individual.
If CaretakerOfDisabledIndividualFlag==True -> Exempt (Reason: Disabled Individual Caregiver)
Else Not Exempt"""

DEFAULT_REQUEST = {
    "id": "test-snap-001",
    "tanf": False,
    "age": 30,
    "meCode": None,
    "exemptionStatus": None,
    "snap": True,
    "caretakerOfChildUnder13": False,
    "incarcerationStatus": False,
    "formerInmate": False,
    "releaseDate": None,
    "determinationDate": None,
    "caretakerOfDisabledIndividualFlag": False
}

DEFAULT_RESPONSE = {
    "timestamp": "2026-03-23T12:45:48.8071557",
    "status": "SUCCESS",
    "exemptionStatus": "Exempt",
    "exemptionReason": "SNAP Household",
    "ruleFired": "Auto-Exemption: SNAP Household"
}

# ─── Custom CSS ───
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

:root {
    --navy: #1E3A5F;
    --blue: #2E75B6;
    --light-blue: #EBF3FB;
    --pass-green: #D6F5D6;
    --fail-red: #FDDEDE;
    --invalid-yellow: #FFF3CD;
    --text: #1a1a2e;
}

html, body, [class*="css"] {
    font-family: 'Inter', sans-serif;
}

.main-header {
    background: linear-gradient(135deg, #1E3A5F 0%, #2E75B6 50%, #4A90D9 100%);
    padding: 28px 36px;
    border-radius: 16px;
    margin-bottom: 28px;
    color: white;
    position: relative;
    overflow: hidden;
}
.main-header::before {
    content: '';
    position: absolute;
    top: -50%;
    right: -10%;
    width: 300px;
    height: 300px;
    background: rgba(255,255,255,0.05);
    border-radius: 50%;
}
.main-header h1 { font-size: 2rem; font-weight: 700; margin: 0; }
.main-header p { font-size: 0.95rem; opacity: 0.85; margin-top: 6px; }

.metric-card {
    background: white;
    border-radius: 12px;
    padding: 20px 24px;
    box-shadow: 0 2px 12px rgba(0,0,0,0.08);
    border-left: 4px solid var(--blue);
    margin-bottom: 12px;
}
.metric-card.pass { border-left-color: #2E7D32; }
.metric-card.fail { border-left-color: #C62828; }
.metric-card.invalid { border-left-color: #F57F17; }
.metric-card h3 { font-size: 0.75rem; text-transform: uppercase; color: #666; margin: 0 0 4px; letter-spacing: 1px; }
.metric-card .value { font-size: 2.2rem; font-weight: 700; color: var(--navy); }
.metric-card .sub { font-size: 0.8rem; color: #888; margin-top: 2px; }

.step-badge {
    display: inline-block;
    background: var(--blue);
    color: white;
    width: 28px;
    height: 28px;
    border-radius: 50%;
    text-align: center;
    line-height: 28px;
    font-weight: 700;
    font-size: 0.85rem;
    margin-right: 10px;
}

.section-title {
    font-size: 1.1rem;
    font-weight: 600;
    color: var(--navy);
    padding-bottom: 8px;
    border-bottom: 2px solid var(--light-blue);
    margin-bottom: 16px;
}

.status-pass {
    background: #D6F5D6;
    color: #1B5E20;
    padding: 3px 10px;
    border-radius: 12px;
    font-size: 0.78rem;
    font-weight: 600;
}
.status-fail {
    background: #FDDEDE;
    color: #B71C1C;
    padding: 3px 10px;
    border-radius: 12px;
    font-size: 0.78rem;
    font-weight: 600;
}
.status-invalid {
    background: #FFF3CD;
    color: #856404;
    padding: 3px 10px;
    border-radius: 12px;
    font-size: 0.78rem;
    font-weight: 600;
}

.info-box {
    background: var(--light-blue);
    border: 1px solid #BDD7EE;
    border-radius: 10px;
    padding: 14px 18px;
    font-size: 0.88rem;
    color: var(--navy);
    margin: 12px 0;
}

.tag {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 8px;
    font-size: 0.72rem;
    font-weight: 600;
    margin: 1px;
}
.tag-positive { background: #E8F5E9; color: #2E7D32; }
.tag-negative { background: #FFEBEE; color: #C62828; }
.tag-edge { background: #E3F2FD; color: #1565C0; }
.tag-invalid { background: #FFF8E1; color: #F57F17; }

stButton > button {
    border-radius: 10px !important;
    font-weight: 600 !important;
    letter-spacing: 0.3px !important;
}

.progress-log {
    background: #0d1117;
    color: #58a6ff;
    border-radius: 8px;
    padding: 14px 18px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.82rem;
    min-height: 120px;
    max-height: 200px;
    overflow-y: auto;
    white-space: pre-wrap;
}
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
# Session state init
# ─────────────────────────────────────────────
for key, default in [
    ("vector_store", None),
    ("rules_indexed", False),
    ("test_results", None),
    ("excel_bytes", None),
    ("run_in_progress", False),
    ("progress_messages", []),
    ("progress_pct", 0),
]:
    if key not in st.session_state:
        st.session_state[key] = default


# ─────────────────────────────────────────────
# Header
# ─────────────────────────────────────────────
st.markdown("""
<div class="main-header">
    <h1>🧪 CEV Exemption Rules — Test Automation Portal</h1>
    <p>AI-powered test case generation, execution, and verification using CrewAI + FAISS Vector DB + OpenAI</p>
</div>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
# Sidebar — Configuration
# ─────────────────────────────────────────────
with st.sidebar:
    st.markdown("### ⚙️ Configuration")

    openai_key = st.text_input(
        "OpenAI API Key",
        type="password",
        placeholder="sk-...",
        help="Required for AI-powered test case generation"
    )

    model_choice = st.selectbox(
        "LLM Model",
        ["gpt-4o-mini", "gpt-4o", "gpt-3.5-turbo"],
        index=0
    )

    st.divider()
    st.markdown("### 📋 Quick Actions")

    if st.session_state.rules_indexed:
        st.success("✅ Rules indexed in FAISS")
    else:
        st.warning("⚠️ Rules not yet indexed")

    if st.session_state.test_results:
        cnt = len(st.session_state.test_results)
        st.info(f"📊 {cnt} test results available")

    st.divider()
    st.markdown("""
    <div style='font-size:0.78rem; color:#888; line-height:1.6;'>
    <b>Architecture</b><br>
    🧠 CrewAI Agents<br>
    🗄️ FAISS Vector DB<br>
    🤖 OpenAI LLM<br>
    🔧 Mock API Executor<br>
    📊 Excel Reporter<br>
    🎨 Streamlit UI
    </div>
    """, unsafe_allow_html=True)


# ─────────────────────────────────────────────
# Tabs
# ─────────────────────────────────────────────
tab1, tab2, tab3, tab4 = st.tabs([
    "📥 Setup & Configuration",
    "🚀 Run Test Pipeline",
    "📊 Results & Report",
    "🔍 Manual API Tester"
])


# ══════════════════════════════════════════════
# TAB 1 — Setup
# ══════════════════════════════════════════════
with tab1:
    col1, col2 = st.columns([1, 1], gap="large")

    with col1:
        st.markdown('<div class="section-title"><span class="step-badge">1</span>Rules Document</div>', unsafe_allow_html=True)
        rules_input = st.text_area(
            "Paste your rules document",
            value=DEFAULT_RULES,
            height=340,
            help="Business rules in priority order. Will be stored in FAISS vector DB."
        )

        if st.button("🗄️ Index Rules in FAISS Vector DB", use_container_width=True, type="primary"):
            if not rules_input.strip():
                st.error("Please enter rules text.")
            else:
                with st.spinner("Chunking and indexing rules..."):
                    vs = RulesVectorStore(store_path="data/faiss_store")
                    count = vs.build_index(rules_input)
                    st.session_state.vector_store = vs
                    st.session_state.rules_indexed = True
                st.success(f"✅ Indexed {count} rule chunks in FAISS!")

                with st.expander("🔍 Test vector search"):
                    query = st.text_input("Search query", "SNAP exemption criteria")
                    if query and st.button("Search"):
                        results = vs.search(query, top_k=2)
                        for r in results:
                            st.code(r["text"][:300], language=None)

    with col2:
        st.markdown('<div class="section-title"><span class="step-badge">2</span>Sample Request & Response</div>', unsafe_allow_html=True)

        req_text = st.text_area(
            "Sample Request JSON",
            value=json.dumps(DEFAULT_REQUEST, indent=2),
            height=200,
            help="JSON schema that defines the request structure"
        )

        resp_text = st.text_area(
            "Sample Response JSON",
            value=json.dumps(DEFAULT_RESPONSE, indent=2),
            height=150,
            help="JSON schema that defines the response structure"
        )

        # Validate JSON
        try:
            parsed_req = json.loads(req_text)
            parsed_resp = json.loads(resp_text)
            st.success("✅ Both JSONs are valid")
            st.session_state["sample_request"] = parsed_req
            st.session_state["sample_response"] = parsed_resp
        except json.JSONDecodeError as e:
            st.error(f"❌ JSON parse error: {e}")

    # Load existing index if available
    if not st.session_state.rules_indexed:
        vs = RulesVectorStore(store_path="data/faiss_store")
        if vs.load_index():
            st.session_state.vector_store = vs
            st.session_state.rules_indexed = True
            st.info("ℹ️ Loaded existing FAISS index from disk")


# ══════════════════════════════════════════════
# TAB 2 — Run Pipeline
# ══════════════════════════════════════════════
with tab2:
    st.markdown('<div class="section-title">🤖 AI-Powered Test Pipeline</div>', unsafe_allow_html=True)

    st.markdown("""
    <div class="info-box">
    <b>Pipeline Overview:</b><br>
    <b>Agent 1</b> — Reads rules from FAISS → Generates all test cases<br>
    <b>Agent 2</b> — Builds request JSON payloads for each test case<br>
    <b>Agent 3</b> — Executes requests against mock API<br>
    <b>Agent 4</b> — Verifies actual vs expected results → PASS / FAIL / INVALID
    </div>
    """, unsafe_allow_html=True)

    run_col, info_col = st.columns([1, 1])

    with run_col:
        can_run = (
            st.session_state.rules_indexed
            and openai_key
            and not st.session_state.run_in_progress
        )

        if not openai_key:
            st.warning("⚠️ Enter OpenAI API Key in sidebar to run pipeline")
        if not st.session_state.rules_indexed:
            st.warning("⚠️ Index rules in FAISS first (Tab 1)")

        if st.button(
            "🚀 Run Full Test Pipeline",
            disabled=not can_run,
            use_container_width=True,
            type="primary"
        ):
            st.session_state.run_in_progress = True
            st.session_state.progress_messages = []
            st.session_state.progress_pct = 0
            st.session_state.test_results = None
            st.session_state.excel_bytes = None

            progress_bar = st.progress(0)
            log_placeholder = st.empty()
            status_placeholder = st.empty()

            log_lines = []

            def log(msg, pct):
                ts = datetime.now().strftime("%H:%M:%S")
                log_lines.append(f"[{ts}] {msg}")
                log_placeholder.markdown(
                    f'<div class="progress-log">' + '\n'.join(log_lines[-12:]) + '</div>',
                    unsafe_allow_html=True
                )
                progress_bar.progress(pct / 100)

            try:
                os.environ["OPENAI_API_KEY"] = openai_key

                from agents import run_test_pipeline

                sample_req = st.session_state.get("sample_request", DEFAULT_REQUEST)
                sample_resp = st.session_state.get("sample_response", DEFAULT_RESPONSE)

                results = run_test_pipeline(
                    vector_store=st.session_state.vector_store,
                    sample_request=sample_req,
                    sample_response=sample_resp,
                    openai_api_key=openai_key,
                    model=model_choice,
                    progress_callback=log
                )

                # Generate Excel
                log("📊 Generating Excel report...", 97)
                os.makedirs("outputs", exist_ok=True)
                excel_path = f"outputs/test_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
                generate_excel_report(results, excel_path)

                with open(excel_path, "rb") as f:
                    st.session_state.excel_bytes = f.read()

                st.session_state.test_results = results
                log("✅ Pipeline complete!", 100)
                progress_bar.progress(1.0)
                st.success(f"🎉 Pipeline complete! {len(results)} test cases processed.")

            except Exception as e:
                st.error(f"❌ Pipeline error: {str(e)}")
                log(f"ERROR: {str(e)}", 0)
            finally:
                st.session_state.run_in_progress = False

    with info_col:
        st.markdown("**What each agent does:**")
        agents_info = [
            ("🧠", "Test Case Generator", "Reads all rules from FAISS, generates positive, negative, edge case, and invalid data test cases"),
            ("🔧", "Request Builder", "Constructs exact JSON request payloads matching each test scenario"),
            ("🚀", "API Executor", "Runs each request against the mock API, collects responses"),
            ("🔍", "Test Verifier", "Compares actual vs expected, marks each as PASS/FAIL/INVALID"),
        ]
        for icon, name, desc in agents_info:
            st.markdown(f"""
            <div style='background:#F5F8FF; border-radius:10px; padding:12px 16px; margin-bottom:10px; border-left:3px solid #2E75B6;'>
            <b>{icon} {name}</b><br>
            <span style='font-size:0.82rem; color:#555;'>{desc}</span>
            </div>
            """, unsafe_allow_html=True)


# ══════════════════════════════════════════════
# TAB 3 — Results & Report
# ══════════════════════════════════════════════
with tab3:
    if not st.session_state.test_results:
        st.info("ℹ️ No results yet. Run the test pipeline in Tab 2.")
    else:
        results = st.session_state.test_results
        stats = compute_summary_stats(results)

        # ── Summary Metrics ──
        st.markdown('<div class="section-title">📊 Execution Summary</div>', unsafe_allow_html=True)
        m1, m2, m3, m4, m5 = st.columns(5)

        with m1:
            st.markdown(f"""<div class="metric-card">
            <h3>Total Cases</h3><div class="value">{stats['total']}</div>
            <div class="sub">Test cases executed</div></div>""", unsafe_allow_html=True)
        with m2:
            st.markdown(f"""<div class="metric-card pass">
            <h3>✅ Passed</h3><div class="value" style="color:#2E7D32">{stats['passed']}</div>
            <div class="sub">{stats['pass_rate']:.1f}% pass rate</div></div>""", unsafe_allow_html=True)
        with m3:
            st.markdown(f"""<div class="metric-card fail">
            <h3>❌ Failed</h3><div class="value" style="color:#C62828">{stats['failed']}</div>
            <div class="sub">Need investigation</div></div>""", unsafe_allow_html=True)
        with m4:
            st.markdown(f"""<div class="metric-card invalid">
            <h3>⚠️ Invalid</h3><div class="value" style="color:#F57F17">{stats['invalid']}</div>
            <div class="sub">Invalid data scenarios</div></div>""", unsafe_allow_html=True)
        with m5:
            st.markdown(f"""<div class="metric-card">
            <h3>Pass Rate</h3><div class="value">{stats['pass_rate']:.0f}%</div>
            <div class="sub">Overall success rate</div></div>""", unsafe_allow_html=True)

        st.markdown("---")

        # ── Charts ──
        chart_col1, chart_col2 = st.columns(2)

        with chart_col1:
            st.markdown("**By Test Type**")
            type_df = pd.DataFrame([
                {"Test Type": k, "Pass": v["pass"], "Fail": v["fail"], "Invalid": v["invalid"]}
                for k, v in stats["by_type"].items()
            ])
            if not type_df.empty:
                st.bar_chart(type_df.set_index("Test Type")[["Pass", "Fail", "Invalid"]])

        with chart_col2:
            st.markdown("**By Rule**")
            rule_df = pd.DataFrame([
                {"Rule": k[:30], "Pass": v["pass"], "Fail": v["fail"]}
                for k, v in stats["by_rule"].items()
            ])
            if not rule_df.empty:
                st.bar_chart(rule_df.set_index("Rule")[["Pass", "Fail"]])

        st.markdown("---")

        # ── Filter Controls ──
        st.markdown('<div class="section-title">🔍 Test Results Table</div>', unsafe_allow_html=True)

        f1, f2, f3 = st.columns(3)
        with f1:
            filter_status = st.multiselect(
                "Filter by Status",
                ["PASS", "FAIL", "INVALID"],
                default=["PASS", "FAIL", "INVALID"]
            )
        with f2:
            filter_type = st.multiselect(
                "Filter by Test Type",
                list(stats["by_type"].keys()),
                default=list(stats["by_type"].keys())
            )
        with f3:
            search_text = st.text_input("Search test name / description", "")

        # ── Results Table ──
        filtered = [
            r for r in results
            if r.get("verification_status", "") in filter_status
            and r.get("test_type", "") in filter_type
            and (not search_text or search_text.lower() in str(r).lower())
        ]

        def status_badge(status):
            cls = {"PASS": "status-pass", "FAIL": "status-fail", "INVALID": "status-invalid"}.get(status, "")
            return f'<span class="{cls}">{status}</span>'

        table_data = []
        for r in filtered:
            table_data.append({
                "ID": r.get("test_case_id", ""),
                "Test Case Name": r.get("test_case_name", ""),
                "Rule Tested": r.get("rule_being_tested", ""),
                "Type": r.get("test_type", ""),
                "Expected Exemption": r.get("expected_exemption_status", ""),
                "Actual Exemption": r.get("actual_exemption_status", ""),
                "Status": r.get("verification_status", ""),
                "Failure Reason": r.get("failure_reason", "") or "",
            })

        if table_data:
            df = pd.DataFrame(table_data)

            def color_status(val):
                if val == "PASS":
                    return "background-color: #D6F5D6; color: #1B5E20; font-weight: bold"
                elif val == "FAIL":
                    return "background-color: #FDDEDE; color: #B71C1C; font-weight: bold"
                elif val == "INVALID":
                    return "background-color: #FFF3CD; color: #856404; font-weight: bold"
                return ""

            styled_df = df.style.applymap(color_status, subset=["Status"])
            st.dataframe(styled_df, use_container_width=True, height=400)
            st.caption(f"Showing {len(filtered)} of {len(results)} test cases")
        else:
            st.info("No results match the current filters.")

        st.markdown("---")

        # ── Download Section ──
        st.markdown('<div class="section-title">⬇️ Download Reports</div>', unsafe_allow_html=True)

        dl1, dl2 = st.columns(2)
        with dl1:
            if st.session_state.excel_bytes:
                st.download_button(
                    label="📥 Download Excel Report (.xlsx)",
                    data=st.session_state.excel_bytes,
                    file_name=f"CEV_Test_Report_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                    type="primary"
                )
                st.caption("Includes: Test Results, Summary Dashboard, Request/Response Details sheets")

        with dl2:
            json_bytes = json.dumps(results, indent=2).encode()
            st.download_button(
                label="📥 Download JSON Results",
                data=json_bytes,
                file_name=f"CEV_Test_Results_{datetime.now().strftime('%Y%m%d_%H%M')}.json",
                mime="application/json",
                use_container_width=True
            )

        # ── Expandable detail view ──
        with st.expander("🔎 View Full Test Case Details"):
            for r in filtered[:20]:  # Show first 20 to avoid overload
                status = r.get("verification_status", "")
                badge_color = {"PASS": "🟢", "FAIL": "🔴", "INVALID": "🟡"}.get(status, "⚪")
                with st.expander(f"{badge_color} {r.get('test_case_id')} — {r.get('test_case_name', '')}"):
                    c1, c2 = st.columns(2)
                    with c1:
                        st.markdown("**Request JSON:**")
                        st.json(r.get("request_json", {}))
                    with c2:
                        st.markdown("**Response JSON:**")
                        st.json(r.get("response_json", {}))
                    if r.get("failure_reason"):
                        st.error(f"Failure reason: {r['failure_reason']}")


# ══════════════════════════════════════════════
# TAB 4 — Manual API Tester
# ══════════════════════════════════════════════
with tab4:
    st.markdown('<div class="section-title">🔍 Manual API Request Tester</div>', unsafe_allow_html=True)
    st.markdown("""
    <div class="info-box">
    Test individual requests against the mock API without running the full pipeline.
    Useful for debugging specific scenarios.
    </div>
    """, unsafe_allow_html=True)

    col_a, col_b = st.columns(2)

    with col_a:
        st.markdown("**Build Request:**")

        req_id = st.text_input("ID", value="manual-test-001")
        tanf = st.checkbox("TANF Flag")
        snap = st.checkbox("SNAP Flag", value=True)
        age = st.number_input("Age", min_value=0, max_value=120, value=30)
        caretaker_child = st.checkbox("Caretaker of Child Under 13")
        caretaker_disabled = st.checkbox("Caretaker of Disabled Individual")
        former_inmate = st.checkbox("Former Inmate")

        release_date = None
        det_date = None
        if former_inmate:
            release_date = st.date_input("Release Date")
            det_date = st.date_input("Determination Date")

        manual_request = {
            "id": req_id,
            "tanf": tanf,
            "snap": snap,
            "age": age,
            "meCode": None,
            "exemptionStatus": None,
            "caretakerOfChildUnder13": caretaker_child,
            "incarcerationStatus": False,
            "formerInmate": former_inmate,
            "releaseDate": str(release_date) if release_date else None,
            "determinationDate": str(det_date) if det_date else None,
            "caretakerOfDisabledIndividualFlag": caretaker_disabled
        }

        st.markdown("**Request Preview:**")
        st.json(manual_request)

        if st.button("▶️ Execute Request", type="primary", use_container_width=True):
            response = execute_request(manual_request)
            st.session_state["manual_response"] = response

    with col_b:
        st.markdown("**Response:**")
        if "manual_response" in st.session_state:
            resp = st.session_state["manual_response"]
            st.json(resp)

            status = resp.get("exemptionStatus", "")
            if status == "Exempt":
                st.success(f"✅ **{status}** — {resp.get('exemptionReason', '')}")
                st.info(f"🔥 Rule fired: `{resp.get('ruleFired', 'N/A')}`")
            elif status == "Not Exempt":
                st.warning(f"⚠️ **{status}** — No exemption criteria met")
            else:
                st.error(f"❌ Error: {resp.get('exemptionReason', 'Unknown error')}")
        else:
            st.markdown("""
            <div style='background:#F5F8FF; border-radius:10px; padding:40px; text-align:center; color:#888;'>
            <div style='font-size:2.5rem;'>📡</div>
            <div style='margin-top:8px;'>Execute a request to see the response</div>
            </div>
            """, unsafe_allow_html=True)

        st.markdown("---")
        st.markdown("**Rule Priority Reference:**")
        rules_ref = [
            ("1", "TANF", "tanf = True"),
            ("2", "SNAP", "snap = True"),
            ("3", "Under 19", "age < 19"),
            ("4", "Former Inmate", "formerInmate + release within 90 days"),
            ("5", "Child Caregiver", "caretakerOfChildUnder13 = True"),
            ("6", "Disabled Caregiver", "caretakerOfDisabledIndividualFlag = True"),
        ]
        for num, name, condition in rules_ref:
            st.markdown(f"""
            <div style='display:flex; align-items:center; gap:10px; padding:6px 0; border-bottom:1px solid #EBF3FB;'>
            <span style='background:#1E3A5F; color:white; width:22px; height:22px; border-radius:50%; display:inline-flex; align-items:center; justify-content:center; font-size:0.7rem; font-weight:700;'>{num}</span>
            <span style='font-weight:600; font-size:0.85rem;'>{name}</span>
            <span style='color:#888; font-size:0.8rem; font-family:monospace;'>({condition})</span>
            </div>
            """, unsafe_allow_html=True)
