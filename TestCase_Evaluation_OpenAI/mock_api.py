"""
mock_api.py - API executor: calls a real HTTP endpoint when configured, 
              falls back to built-in mock rules for demo/testing.
"""
import json
import urllib.request
import urllib.error
import ssl
from datetime import datetime, timedelta
from typing import Dict, Any, Optional


def determine_exemption(request: Dict[str, Any]) -> Dict[str, Any]:
    """
    Rule-based exemption determination matching the rules document.
    Used for generating realistic mock responses.
    """
    timestamp = datetime.now().isoformat()
    
    # Rule 1: TANF
    if request.get("tanf") is True:
        return {
            "timestamp": timestamp,
            "status": "SUCCESS",
            "exemptionStatus": "Exempt",
            "exemptionReason": "TANF Work Requirements Compliance",
            "ruleFired": "Rule 1: TANF"
        }
    
    # Rule 2: SNAP
    if request.get("snap") is True:
        return {
            "timestamp": timestamp,
            "status": "SUCCESS",
            "exemptionStatus": "Exempt",
            "exemptionReason": "SNAP Household",
            "ruleFired": "Rule 2: SNAP"
        }
    
    # Rule 3: Under 19
    age = request.get("age")
    if age is not None and age < 19:
        return {
            "timestamp": timestamp,
            "status": "SUCCESS",
            "exemptionStatus": "Exempt",
            "exemptionReason": "Under 19",
            "ruleFired": "Rule 3: Under 19 Individual"
        }
    
    # Rule 4: Former Inmate within 3-month grace period
    former_inmate = request.get("formerInmate") is True
    release_date_str = request.get("releaseDate")
    determination_date_str = request.get("determinationDate")
    
    if former_inmate and release_date_str and determination_date_str:
        try:
            release_date = datetime.fromisoformat(release_date_str)
            det_date = datetime.fromisoformat(determination_date_str)
            three_months_ago = det_date - timedelta(days=90)
            if three_months_ago <= release_date <= det_date:
                return {
                    "timestamp": timestamp,
                    "status": "SUCCESS",
                    "exemptionStatus": "Exempt",
                    "exemptionReason": "Former Inmate - 3-month grace period",
                    "ruleFired": "Rule 4: Former Inmate Grace Period"
                }
        except Exception:
            pass
    
    # Rule 5: Child Caregiver
    if request.get("caretakerOfChildUnder13") is True:
        return {
            "timestamp": timestamp,
            "status": "SUCCESS",
            "exemptionStatus": "Exempt",
            "exemptionReason": "Child Caregiver",
            "ruleFired": "Rule 5: Child Caregiver"
        }
    
    # Rule 6: Disabled Individual Caregiver
    if request.get("caretakerOfDisabledIndividualFlag") is True:
        return {
            "timestamp": timestamp,
            "status": "SUCCESS",
            "exemptionStatus": "Exempt",
            "exemptionReason": "Disabled Individual Caregiver",
            "ruleFired": "Rule 6: Disabled Individual Caregiver"
        }
    
    # No exemption
    return {
        "timestamp": timestamp,
        "status": "SUCCESS",
        "exemptionStatus": "Not Exempt",
        "exemptionReason": "No exemption criteria met",
        "ruleFired": "None"
    }


def execute_real_request(
    request_json: Dict[str, Any],
    api_url: str,
    bearer_token: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Execute a request against a real HTTP API endpoint.
    Returns the parsed JSON response, or an error dict on failure.
    """
    try:
        payload = json.dumps(request_json).encode("utf-8")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        # Only add Authorization header if token is a non-empty, non-whitespace string
        clean_token = (bearer_token or "").strip()
        if clean_token:
            headers["Authorization"] = f"Bearer {clean_token}"

        # Create an SSL context that tolerates self-signed/dev certs
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        req = urllib.request.Request(api_url, data=payload, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
            raw = resp.read().decode("utf-8")
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return {
                    "timestamp": datetime.now().isoformat(),
                    "status": "ERROR",
                    "exemptionStatus": None,
                    "exemptionReason": f"Non-JSON response from API: {raw[:200]}",
                    "ruleFired": None,
                }

    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8")
        except Exception:
            pass
        return {
            "timestamp": datetime.now().isoformat(),
            "status": "ERROR",
            "exemptionStatus": None,
            "exemptionReason": f"HTTP {e.code} {e.reason}: {body[:300]}",
            "ruleFired": None,
        }
    except urllib.error.URLError as e:
        return {
            "timestamp": datetime.now().isoformat(),
            "status": "ERROR",
            "exemptionStatus": None,
            "exemptionReason": f"Connection error: {e.reason}",
            "ruleFired": None,
        }
    except Exception as e:
        return {
            "timestamp": datetime.now().isoformat(),
            "status": "ERROR",
            "exemptionStatus": None,
            "exemptionReason": f"Unexpected error: {str(e)}",
            "ruleFired": None,
        }


def execute_request(request_json: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute a test request against the mock API.
    Returns a mock response based on the request data.
    """
    try:
        # Validate required fields
        required_fields = ["id"]
        for field in required_fields:
            if field not in request_json:
                return {
                    "timestamp": datetime.now().isoformat(),
                    "status": "ERROR",
                    "exemptionStatus": None,
                    "exemptionReason": f"Missing required field: {field}",
                    "ruleFired": None
                }

        # Validate age — must be a number if provided
        age = request_json.get("age")
        if age is not None and not isinstance(age, (int, float)):
            return {
                "timestamp": datetime.now().isoformat(),
                "status": "INVALID_DATA",
                "exemptionStatus": None,
                "exemptionReason": f"Invalid data type for age field: expected number, got {type(age).__name__}",
                "ruleFired": None
            }

        # Validate age is not negative
        if age is not None and isinstance(age, (int, float)) and age < 0:
            return {
                "timestamp": datetime.now().isoformat(),
                "status": "INVALID_DATA",
                "exemptionStatus": None,
                "exemptionReason": "Invalid value for age field: age cannot be negative",
                "ruleFired": None
            }

        # Validate boolean fields — must be actual booleans if provided
        boolean_fields = [
            "tanf", "snap", "caretakerOfChildUnder13",
            "incarcerationStatus", "formerInmate", "caretakerOfDisabledIndividualFlag"
        ]
        for field in boolean_fields:
            val = request_json.get(field)
            if val is not None and not isinstance(val, bool):
                return {
                    "timestamp": datetime.now().isoformat(),
                    "status": "INVALID_DATA",
                    "exemptionStatus": None,
                    "exemptionReason": f"Invalid data type for {field}: expected boolean, got {type(val).__name__} ({val!r})",
                    "ruleFired": None
                }

        return determine_exemption(request_json)

    except Exception as e:
        return {
            "timestamp": datetime.now().isoformat(),
            "status": "ERROR",
            "exemptionStatus": None,
            "exemptionReason": str(e),
            "ruleFired": None
        }
