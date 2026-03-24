"""
agents.py — 4-agent pipeline using direct OpenAI API calls.
No crewai. No langchain. No torch. No chromadb.
Packages needed: openai, python-dotenv only (beyond core project deps).
"""
import json
import re
import time
from typing import Any, Dict, List, Optional

from openai import OpenAI
from config import settings
from mock_api import execute_request


# ─────────────────────────────────────────────────────────────
# OpenAI client — singleton, initialised once from .env
# ─────────────────────────────────────────────────────────────

def _get_client() -> OpenAI:
    return OpenAI(api_key=settings.OPENAI_API_KEY)


# ─────────────────────────────────────────────────────────────
# Core LLM call helper
# ─────────────────────────────────────────────────────────────

def _call_llm(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.2,
    max_tokens: int = 4096,
    retries: int = 3,
) -> str:
    """
    Call OpenAI chat completion directly.
    Returns the assistant message content as a string.
    Retries up to `retries` times on transient errors.
    """
    client = _get_client()
    last_error = None

    for attempt in range(1, retries + 1):
        try:
            response = client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                temperature=temperature,
                max_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_prompt},
                ],
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            last_error = e
            if attempt < retries:
                time.sleep(2 ** attempt)   # exponential back-off: 2s, 4s
            continue

    raise RuntimeError(f"OpenAI call failed after {retries} attempts: {last_error}")


# ─────────────────────────────────────────────────────────────
# JSON parser — strips markdown fences robustly
# ─────────────────────────────────────────────────────────────

def _parse_json(text: str, fallback=None):
    if not text:
        return fallback
    # Strip ```json ... ``` or ``` ... ```
    text = re.sub(r"```(?:json)?\s*", "", text).strip().rstrip("`").strip()
    try:
        return json.loads(text)
    except Exception:
        # Try to extract the first JSON array from the response
        match = re.search(r"\[[\s\S]*\]", text)
        if match:
            try:
                return json.loads(match.group())
            except Exception:
                pass
    return fallback


# ─────────────────────────────────────────────────────────────
# AGENT 1 — Test Case Generator
# ─────────────────────────────────────────────────────────────

AGENT1_SYSTEM = """You are an expert QA engineer specialising in rules-based eligibility systems.
Your job is to read a business-rules document and generate EVERY possible test case that
exercises the rules thoroughly — positive paths, negative paths, edge cases, boundary
values, invalid data, and priority/ordering scenarios.
Always respond with ONLY a valid JSON array. No markdown, no preamble, no explanation."""


def agent_generate_test_cases(
    rules_text: str,
    sample_request: dict,
    sample_response: dict,
) -> List[Dict]:
    user_prompt = f"""Analyze the following business rules and generate EVERY possible test case.

RULES DOCUMENT:
{rules_text}

SAMPLE REQUEST SCHEMA:
{json.dumps(sample_request, indent=2)}

SAMPLE RESPONSE SCHEMA:
{json.dumps(sample_response, indent=2)}

Generate a comprehensive list of test cases. For EACH include:
- test_case_id: unique identifier (TC_001, TC_002, ...)
- test_case_name: descriptive name
- rule_being_tested: which rule number and name
- test_type: "positive", "negative", "edge_case", or "invalid_data"
- description: what this test verifies
- input_conditions: key field values to set
- expected_exemption_status: exact string the API will return
- expected_exemption_reason: exact string the API will return
- expected_rule_fired: which rule should fire, or "None" if no rule fires
- expected_status: "SUCCESS", "ERROR", or "INVALID_DATA"

CRITICAL RULES FOR EXPECTED VALUES — read carefully:

1. POSITIVE tests (rule fires and grants exemption):
   - expected_exemption_status = "Exempt"
   - expected_exemption_reason = the exact reason string for that rule (e.g. "SNAP Household")
   - expected_status = "SUCCESS"

2. NEGATIVE tests (rule condition is false, no exemption granted — ALL flags false):
   - expected_exemption_status = "Not Exempt"
   - expected_exemption_reason = "No exemption criteria met"   ← ALWAYS this exact string
   - expected_rule_fired = "None"
   - expected_status = "SUCCESS"

3. EDGE CASE tests (boundary values like age=18, age=19, date boundaries):
   - Set expected values based on whether the boundary condition grants exemption or not.
   - age=18 → Exempt (Under 19), expected_exemption_reason = "Under 19"
   - age=19 → Not Exempt from age rule, expected_exemption_reason = "No exemption criteria met"
   - release date exactly 90 days before → Exempt, reason = "Former Inmate - 3-month grace period"
   - release date exactly 91 days before → Not Exempt, reason = "No exemption criteria met"

4. INVALID DATA tests (wrong data types sent to the API):
   - Use CLEARLY invalid values — NOT strings that look like booleans.
   - For boolean fields: use integer 999, string "invalid_value", string "abc123", or string "yes"
   - For age: use string "thirty", string "abc", or negative integer -5
   - Do NOT use "true" or "false" as strings — these look too much like real booleans.
   - expected_status = "INVALID_DATA"
   - expected_exemption_status = null
   - expected_exemption_reason = null

5. PRIORITY tests (multiple flags true — only first matching rule fires):
   - Set expected values for the HIGHEST priority rule that is true.

Cover ALL these scenarios:
1. Each rule independently — positive test where only that rule fires
2. Each rule negative case — that rule's flag is false, all other flags also false → Not Exempt
3. Rule priority — higher priority rule fires before a lower priority rule
4. Edge cases: age=18, age=19, release date exactly 90 days before, exactly 91 days before
5. Null / missing optional fields
6. Invalid data types for boolean fields (use 999, "abc123", "invalid_value") and age field (use "thirty", -5)
7. All flags false → Not Exempt with reason "No exemption criteria met"
8. Multiple flags true → first matching rule fires (priority order)
9. Former inmate with release date inside the 3-month window vs outside

Return ONLY a valid JSON array of test-case objects. No markdown, no explanation."""

    raw = _call_llm(AGENT1_SYSTEM, user_prompt, max_tokens=6000)
    result = _parse_json(raw, [])
    if not result:
        raise ValueError(
            "Agent 1 (Test Case Generator) returned no parseable JSON. "
            "Check OPENAI_API_KEY and OPENAI_MODEL in .env"
        )
    return result


# ─────────────────────────────────────────────────────────────
# AGENT 2 — Request JSON Builder
# ─────────────────────────────────────────────────────────────

AGENT2_SYSTEM = """You are a precise JSON API request builder.
Given test case specifications and a sample request schema, you construct accurate
request JSON payloads that match each test scenario exactly.
Always respond with ONLY a valid JSON array. No markdown, no preamble, no explanation."""


def agent_build_requests(
    test_cases: List[Dict],
    sample_request: dict,
) -> List[Dict]:
    user_prompt = f"""For each test case below, build the exact request JSON payload.

SAMPLE REQUEST SCHEMA (all possible fields):
{json.dumps(sample_request, indent=2)}

TEST CASES:
{json.dumps(test_cases, indent=2)}

Rules for building payloads:
- Match input_conditions exactly for each test case.
- Use ISO date format (YYYY-MM-DD). Use "2026-03-23" for determinationDate.
- Former inmate INSIDE grace period: set releaseDate to "2026-02-06" (45 days before).
- Former inmate OUTSIDE grace period: set releaseDate to "2025-12-13" (100 days before).
- Set all unmentioned boolean fields to false and unmentioned date fields to null.

CRITICAL — invalid_data test cases ONLY:
- NEVER use the strings "true" or "false" as invalid values. They look like real booleans.
- For any boolean field needing an invalid value use exactly: 999 (integer)
- For the age field needing an invalid value use exactly: "thirty" (string)
- Example invalid boolean payload: {{"id":"TC_x","snap": 999,"tanf": false,"age": 30,...}}
- Example invalid age payload:     {{"id":"TC_x","snap": false,"tanf": false,"age": "thirty",...}}

Return a JSON array where each object has exactly two keys:
  "test_case_id": matching the test case ID
  "request_json": the complete request payload object

Return ONLY a valid JSON array. No markdown, no explanation."""

    raw = _call_llm(AGENT2_SYSTEM, user_prompt, max_tokens=6000)
    result = _parse_json(raw, [])
    if not result:
        raise ValueError("Agent 2 (Request Builder) returned no parseable JSON.")
    return result


# ─────────────────────────────────────────────────────────────
# AGENT 3 — API Executor  (no LLM needed — pure Python)
# ─────────────────────────────────────────────────────────────

def agent_execute_requests(requests_list: List[Dict]) -> List[Dict]:
    """
    Execute each request payload against the mock API.
    This agent is pure Python — no LLM call needed.
    """
    results = []
    for item in requests_list:
        tc_id = item.get("test_case_id", "")
        req   = item.get("request_json", {})
        resp  = execute_request(req)
        results.append({
            "test_case_id":  tc_id,
            "request_json":  req,
            "response_json": resp,
        })
    return results


# ─────────────────────────────────────────────────────────────
# AGENT 4 — Test Result Verifier
# ─────────────────────────────────────────────────────────────

AGENT4_SYSTEM = """You are a senior QA analyst specialising in rules-based eligibility systems.
Your job is to compare actual API responses against expected outcomes for each test case
and produce a clear PASS / FAIL / INVALID verdict with a precise reason where applicable.
Always respond with ONLY a valid JSON array. No markdown, no preamble, no explanation."""


def agent_verify_results(
    test_cases: List[Dict],
    execution_results: List[Dict],
    rules_text: str,
) -> List[Dict]:
    user_prompt = f"""Verify each test case result against its expected outcome.

RULES DOCUMENT (for reference):
{rules_text}

TEST CASES WITH EXPECTED OUTCOMES:
{json.dumps(test_cases, indent=2)}

ACTUAL EXECUTION RESULTS:
{json.dumps(execution_results, indent=2)}

Match each test_case_id from TEST CASES with the same test_case_id in EXECUTION RESULTS.

═══ VERDICT RULES — apply in this exact order ═══

RULE A — invalid_data test cases (test_type = "invalid_data"):
  PASS  → actual response status is "INVALID_DATA" or "ERROR"
  FAIL  → actual response status is "SUCCESS"  (the API wrongly accepted bad data)

RULE B — positive / edge_case tests where exemption IS granted:
  PASS  → actual exemptionStatus matches expected_exemption_status
           AND actual exemptionReason matches expected_exemption_reason
  FAIL  → either field does not match

RULE C — negative tests (test_type = "negative") and any case where expected_exemption_status = "Not Exempt":
  The mock API ALWAYS returns exemptionReason = "No exemption criteria met" for non-exempt cases.
  PASS  → actual exemptionStatus = "Not Exempt"
           AND actual exemptionReason = "No exemption criteria met"
  FAIL  → actual exemptionStatus is NOT "Not Exempt"

  *** IMPORTANT: Do NOT produce a FAIL verdict just because expected_exemption_reason
      in the test case was null, empty, or different from "No exemption criteria met".
      The API behaviour of returning "No exemption criteria met" is ALWAYS correct for
      negative tests. A null expected_exemption_reason does NOT mean the actual value
      should be null — it just means the test case didn't specify it precisely. ***

RULE D — unexpected API errors:
  INVALID → expected_status = "SUCCESS" but actual status = "ERROR" or "INVALID_DATA"

Return a JSON array where each object has:
- test_case_id
- test_case_name
- rule_being_tested
- test_type
- description
- expected_exemption_status
- expected_exemption_reason
- expected_rule_fired
- actual_exemption_status
- actual_exemption_reason
- actual_rule_fired
- actual_status
- verification_status   ("PASS", "FAIL", or "INVALID")
- failure_reason        (concise explanation when not PASS, otherwise null)

Return ONLY a valid JSON array. No markdown, no explanation."""

    raw = _call_llm(AGENT4_SYSTEM, user_prompt, max_tokens=6000)
    result = _parse_json(raw, [])
    if not result:
        raise ValueError("Agent 4 (Verifier) returned no parseable JSON.")
    return result


# ─────────────────────────────────────────────────────────────
# Pipeline Orchestrator
# ─────────────────────────────────────────────────────────────

def run_test_pipeline(
    vector_store,
    sample_request: dict,
    sample_response: dict,
    progress_callback=None,
) -> List[Dict]:
    """
    Run the full 4-agent test pipeline using direct OpenAI calls.
    progress_callback(message: str, pct: int)
    """

    def log(msg: str, pct: int):
        if progress_callback:
            progress_callback(msg, pct)

    # Validate config before starting
    errors = settings.validate()
    if errors:
        raise ValueError(f"Configuration error: {'; '.join(errors)}")

    rules_text = vector_store.get_all_rules()
    if not rules_text.strip():
        raise ValueError("Rules not indexed — index rules in the Setup tab first.")

    # ── Step 1: Generate test cases ──────────────────────────
    log("Agent 1 — Generating test cases from rules...", 10)
    test_cases = agent_generate_test_cases(rules_text, sample_request, sample_response)
    log(f"Agent 1 — Generated {len(test_cases)} test cases", 28)

    # ── Step 2: Build request JSON payloads ──────────────────
    log("Agent 2 — Building request JSON payloads...", 35)
    requests_list = agent_build_requests(test_cases, sample_request)
    log(f"Agent 2 — Built {len(requests_list)} request payloads", 52)

    # ── Step 3: Execute requests (no LLM) ────────────────────
    log("Agent 3 — Executing requests against mock API...", 58)
    execution_results = agent_execute_requests(requests_list)
    log(f"Agent 3 — Executed {len(execution_results)} requests", 72)

    # ── Step 4: Verify results ────────────────────────────────
    log("Agent 4 — Verifying results against expectations...", 78)
    verified_results = agent_verify_results(test_cases, execution_results, rules_text)
    log(f"Agent 4 — Verified {len(verified_results)} test cases", 93)

    # Attach request/response JSON to each verified result
    exec_map = {r["test_case_id"]: r for r in execution_results}
    for vr in verified_results:
        tc_id = vr.get("test_case_id", "")
        if tc_id in exec_map:
            vr["request_json"]  = exec_map[tc_id]["request_json"]
            vr["response_json"] = exec_map[tc_id]["response_json"]

    log(f"Pipeline complete — {len(verified_results)} test cases processed", 95)
    return verified_results
