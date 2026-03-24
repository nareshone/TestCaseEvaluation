"""
agents.py - CrewAI agents — API key & model loaded from config/.env
"""
import json
import os
import re
from typing import Any, Dict, List
from crewai import Agent, Task, Crew, Process
from crewai.tools import BaseTool
from pydantic import Field
from mock_api import execute_request
from config import settings


# ─────────────────────────────────────────────
# Custom Tools
# ─────────────────────────────────────────────

class RulesSearchTool(BaseTool):
    name: str = "rules_search"
    description: str = "Search the FAISS vector store for relevant rules"
    vector_store: Any = Field(default=None, exclude=True)

    def _run(self, query: str) -> str:
        if self.vector_store is None or not self.vector_store.is_ready():
            return "Vector store not available"
        results = self.vector_store.search(query, top_k=3)
        return "\n\n".join(f"[Rule Chunk]\n{r['text']}" for r in results)


class MockAPITool(BaseTool):
    name: str = "execute_api_request"
    description: str = "Execute a test request against the mock API"

    def _run(self, request_json_str: str) -> str:
        try:
            request = json.loads(request_json_str)
            response = execute_request(request)
            return json.dumps(response, indent=2)
        except Exception as e:
            return json.dumps({"status": "ERROR", "error": str(e)})


# ─────────────────────────────────────────────
# Agent Factory — reads from .env via settings
# ─────────────────────────────────────────────

def create_agents(vector_store):
    """Create CrewAI agents using API key and model from .env / settings."""
    from langchain_openai import ChatOpenAI

    # Ensure env var is set for CrewAI internals
    os.environ["OPENAI_API_KEY"] = settings.OPENAI_API_KEY

    llm = ChatOpenAI(
        model=settings.OPENAI_MODEL,
        temperature=0.2,
        openai_api_key=settings.OPENAI_API_KEY,
    )

    rules_tool = RulesSearchTool(vector_store=vector_store)
    api_tool = MockAPITool()

    test_generator = Agent(
        role="Test Case Generator",
        goal="Generate comprehensive test cases covering all rules, edge cases, boundary conditions, and invalid data scenarios",
        backstory=(
            "You are an expert QA engineer specializing in rules-based systems. "
            "You analyze business rules documents and systematically create test cases "
            "that cover every rule, including positive, negative, edge cases, and invalid data."
        ),
        tools=[rules_tool],
        llm=llm,
        verbose=False,
        allow_delegation=False,
    )

    request_builder = Agent(
        role="Request JSON Builder",
        goal="Build valid and invalid JSON request payloads for each test case",
        backstory=(
            "You are a precise JSON API request builder. Given test case specifications "
            "and a sample request schema, you construct accurate request JSON payloads "
            "that match the test scenario exactly."
        ),
        tools=[rules_tool],
        llm=llm,
        verbose=False,
        allow_delegation=False,
    )

    verifier = Agent(
        role="Test Result Verifier",
        goal="Verify each test case execution result against expected outcomes and determine pass/fail status",
        backstory=(
            "You are a senior QA analyst who carefully compares actual API responses "
            "against expected outcomes and determines PASS/FAIL/INVALID status."
        ),
        tools=[rules_tool],
        llm=llm,
        verbose=False,
        allow_delegation=False,
    )

    return test_generator, request_builder, verifier


# ─────────────────────────────────────────────
# Tasks
# ─────────────────────────────────────────────

def create_test_generation_task(agent, rules_text, sample_request, sample_response):
    return Task(
        description=f"""
Analyze the following business rules and generate EVERY possible test case.

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
- expected_exemption_status: "Exempt" or "Not Exempt"
- expected_exemption_reason: exact expected reason string
- expected_rule_fired: which rule should fire
- expected_status: "SUCCESS", "ERROR", or "INVALID_DATA"

Cover ALL scenarios:
1. Each rule independently (positive - rule fires)
2. Each rule negative case (rule does NOT fire, next rule checked)
3. Rule priority — higher priority fires before lower
4. Edge cases: age=18, age=19, release date exactly 90 days, exactly 91 days
5. Null / missing optional fields
6. Invalid data types (string instead of boolean, negative age)
7. All flags false → no exemption
8. Multiple flags true → first matching rule fires
9. Former inmate with release date in range vs out of range

Return ONLY a valid JSON array. No markdown, no explanation.
""",
        agent=agent,
        expected_output="JSON array of test case objects",
    )


def create_request_building_task(agent, test_cases_json, sample_request):
    return Task(
        description=f"""
For each test case, build the exact request JSON payload.

SAMPLE REQUEST SCHEMA:
{json.dumps(sample_request, indent=2)}

TEST CASES:
{test_cases_json}

Rules:
- Match input_conditions exactly for each test case.
- Use ISO format for dates (YYYY-MM-DD). determinationDate = "2026-03-23".
- Former inmate in grace period: releaseDate 45 days before determinationDate.
- Former inmate outside grace period: releaseDate 100 days before.
- For invalid_data tests, intentionally use wrong types.

Return a JSON array where each object has:
- test_case_id: matching the test case
- request_json: the full request payload

Return ONLY valid JSON array. No markdown, no explanation.
""",
        agent=agent,
        expected_output="JSON array of {test_case_id, request_json} objects",
    )


def create_verification_task(agent, test_cases_json, results_json, rules_text):
    return Task(
        description=f"""
Verify each test case result against expected outcomes.

RULES:
{rules_text}

TEST CASES WITH EXPECTATIONS:
{test_cases_json}

EXECUTION RESULTS:
{results_json}

For each test case compare actual vs expected response.

Determine:
- PASS: actual matches expected (exemptionStatus + exemptionReason match)
- FAIL: actual does NOT match expected
- INVALID: API returned ERROR/INVALID_DATA when SUCCESS expected (or vice versa)

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
- verification_status: "PASS", "FAIL", or "INVALID"
- failure_reason: explanation if not PASS, else null

Return ONLY valid JSON array. No markdown, no explanation.
""",
        agent=agent,
        expected_output="JSON array of verification result objects",
    )


# ─────────────────────────────────────────────
# Pipeline Orchestrator
# ─────────────────────────────────────────────

def safe_parse_json(text: str, fallback=None):
    if not text:
        return fallback
    text = re.sub(r'```(?:json)?\s*', '', str(text)).strip().rstrip('`').strip()
    try:
        return json.loads(text)
    except Exception:
        match = re.search(r'\[[\s\S]*\]', text)
        if match:
            try:
                return json.loads(match.group())
            except Exception:
                pass
    return fallback


def run_test_pipeline(vector_store, sample_request, sample_response, progress_callback=None):
    """
    Full pipeline — API key and model come from .env via settings.
    progress_callback(message: str, pct: int)
    """
    rules_text = vector_store.get_all_rules()
    test_generator, request_builder, verifier = create_agents(vector_store)

    # Step 1: Generate test cases
    if progress_callback:
        progress_callback("Generating test cases from rules...", 10)
    gen_task = create_test_generation_task(test_generator, rules_text, sample_request, sample_response)
    crew1 = Crew(agents=[test_generator], tasks=[gen_task], process=Process.sequential, verbose=False)
    result1 = crew1.kickoff()
    test_cases = safe_parse_json(str(result1), [])
    if not test_cases:
        raise ValueError("Failed to generate test cases. Check OPENAI_API_KEY in .env")
    if progress_callback:
        progress_callback(f"Generated {len(test_cases)} test cases", 30)

    # Step 2: Build request payloads
    if progress_callback:
        progress_callback("Building request JSON payloads...", 40)
    req_task = create_request_building_task(request_builder, json.dumps(test_cases), sample_request)
    crew2 = Crew(agents=[request_builder], tasks=[req_task], process=Process.sequential, verbose=False)
    result2 = crew2.kickoff()
    requests_list = safe_parse_json(str(result2), [])
    if progress_callback:
        progress_callback(f"Built {len(requests_list)} request payloads", 55)

    # Step 3: Execute requests via mock API
    if progress_callback:
        progress_callback("Executing requests against mock API...", 60)
    execution_results = []
    for item in requests_list:
        tc_id = item.get("test_case_id", "")
        req = item.get("request_json", {})
        resp = execute_request(req)
        execution_results.append({"test_case_id": tc_id, "request_json": req, "response_json": resp})
    if progress_callback:
        progress_callback(f"Executed {len(execution_results)} requests", 75)

    # Step 4: Verify results
    if progress_callback:
        progress_callback("Verifying results against expectations...", 80)
    ver_task = create_verification_task(verifier, json.dumps(test_cases), json.dumps(execution_results), rules_text)
    crew4 = Crew(agents=[verifier], tasks=[ver_task], process=Process.sequential, verbose=False)
    result4 = crew4.kickoff()
    verified_results = safe_parse_json(str(result4), [])

    # Merge execution data
    exec_map = {r["test_case_id"]: r for r in execution_results}
    for vr in verified_results:
        tc_id = vr.get("test_case_id", "")
        if tc_id in exec_map:
            vr["request_json"] = exec_map[tc_id]["request_json"]
            vr["response_json"] = exec_map[tc_id]["response_json"]

    if progress_callback:
        progress_callback(f"Verification complete — {len(verified_results)} test cases", 95)

    return verified_results
