"""Translate FHIR OperationOutcome resources into actionable developer messages."""
from __future__ import annotations

from typing import Any, Dict, List

_SEVERITY_ORDER = {"fatal": 0, "error": 1, "warning": 2, "information": 3}


def _is_upstream_tx_timeout(text: str) -> bool:
    lower = (text or "").lower()
    return (
        "tx.fhir.org" in lower
        and (
            "sockettimeoutexception" in lower
            or "read timed out" in lower
            or "timed out" in lower
        )
    )


def _friendly_details(details: str, diagnostics: str) -> str:
    if _is_upstream_tx_timeout(diagnostics):
        hint = (
            "Upstream terminology validation timeout at tx.fhir.org. "
            "This is a validator-side outage; retry later or use a local/stable terminology endpoint on the FHIR server."
        )
        if details:
            return f"{hint} ({details})"
        return hint
    return details


def parse_operation_outcome(body: Any) -> List[Dict[str, str]]:
    """Return a flat list of {severity, code, location, details, diagnostics}."""
    issues: List[Dict[str, str]] = []
    if not isinstance(body, dict):
        if isinstance(body, str) and body.strip():
            issues.append({"severity": "error", "code": "exception", "location": "", "details": body[:500], "diagnostics": ""})
        return issues

    if body.get("resourceType") == "OperationOutcome":
        for issue in body.get("issue", []):
            details = issue.get("details", {})
            location = issue.get("location") or issue.get("expression") or []
            details_text = (details.get("text") if isinstance(details, dict) else str(details)) or ""
            diagnostics = issue.get("diagnostics", "") or ""
            issues.append({
                "severity": issue.get("severity", "error"),
                "code": issue.get("code", ""),
                "location": ", ".join(location) if isinstance(location, list) else str(location),
                "details": _friendly_details(details_text, diagnostics),
                "diagnostics": diagnostics,
            })
    elif body.get("resourceType") == "Bundle":
        # Inspect transaction-response entries for embedded OperationOutcomes.
        for idx, entry in enumerate(body.get("entry", [])):
            resp = entry.get("response", {})
            status = str(resp.get("status", ""))
            outcome = resp.get("outcome")
            if outcome:
                for issue in parse_operation_outcome(outcome):
                    issue["location"] = f"entry[{idx}] {issue['location']}".strip()
                    issues.append(issue)
            elif status and not status.startswith(("200", "201")):
                issues.append({"severity": "error", "code": "processing", "location": f"entry[{idx}]", "details": f"HTTP {status}", "diagnostics": ""})

    issues.sort(key=lambda i: _SEVERITY_ORDER.get(i["severity"], 9))
    return issues


def summarise(body: Any) -> Dict[str, Any]:
    """Return {has_errors, counts, issues} for a response body."""
    issues = parse_operation_outcome(body)
    counts: Dict[str, int] = {}
    for issue in issues:
        counts[issue["severity"]] = counts.get(issue["severity"], 0) + 1
    has_errors = any(s in counts for s in ("fatal", "error"))
    return {"has_errors": has_errors, "counts": counts, "issues": issues}
