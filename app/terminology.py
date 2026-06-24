"""Terminology server access: ValueSet/$expand, $validate-code, and CodeSystem/$lookup.

The portal is terminology-server driven: selection lists are expanded live from
the configured Ontoserver. A small set of curated fallbacks is provided ONLY so
the UI remains usable when the terminology server is unreachable; each response
flags its `source` ("server" or "fallback") for transparency.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from . import logstore
from .config import EffectiveConfig, get_config
from .fhir_client import FHIR_JSON, FHIRError, _request

# Canonical ValueSet URLs referenced by the eReferral acceptance criteria.
VALUE_SETS = {
    "practitioner-role": "https://www.fhir.doh.gov.ph/pheref/ValueSet/practitioner-role",
    "referral-category": "https://www.fhir.doh.gov.ph/pheref/ValueSet/referral-category",
    "reason-for-referral": "https://www.fhir.doh.gov.ph/pheref/ValueSet/reason-for-referral-service-type",
    "pwd-disability-type": "https://fhir.doh.gov.ph/pheref/ValueSet/pwd-disability-type-vs",
    "administrative-gender": "http://hl7.org/fhir/ValueSet/administrative-gender",
    "task-status": "http://hl7.org/fhir/ValueSet/task-status",
    "contact-point-system": "http://hl7.org/fhir/ValueSet/contact-point-system",
    "contact-point-use": "http://hl7.org/fhir/ValueSet/contact-point-use",
    "relatedperson-relationshiptype": "http://hl7.org/fhir/ValueSet/relatedperson-relationshiptype",
    "condition-code": "http://hl7.org/fhir/ValueSet/condition-code",
}

# Curated fallbacks (used only if the terminology server cannot be reached).
FALLBACKS: Dict[str, List[Dict[str, str]]] = {
    "administrative-gender": [
        {"system": "http://hl7.org/fhir/administrative-gender", "code": "male", "display": "Male"},
        {"system": "http://hl7.org/fhir/administrative-gender", "code": "female", "display": "Female"},
        {"system": "http://hl7.org/fhir/administrative-gender", "code": "other", "display": "Other"},
        {"system": "http://hl7.org/fhir/administrative-gender", "code": "unknown", "display": "Unknown"},
    ],
    "task-status": [
        {"system": "http://hl7.org/fhir/task-status", "code": c, "display": c.title()}
        for c in ["requested", "received", "accepted", "rejected", "in-progress", "completed", "cancelled"]
    ],
    "referral-category": [
        {"system": "http://snomed.info/sct", "code": "73770003", "display": "Emergency"},
        {"system": "http://snomed.info/sct", "code": "440655000", "display": "Outpatient"},
    ],
    "reason-for-referral": [
        {"system": "http://snomed.info/sct", "code": "11429006", "display": "Consultation"},
        {"system": "http://snomed.info/sct", "code": "165197003", "display": "Diagnostics"},
        {"system": "http://snomed.info/sct", "code": "71388002", "display": "Procedure"},
        {"system": "http://snomed.info/sct", "code": "3457005", "display": "Others"},
    ],
    "practitioner-role": [
        {"system": "http://snomed.info/sct", "code": "158965000", "display": "Medical practitioner"},
        {"system": "http://snomed.info/sct", "code": "265937000", "display": "Nursing"},
        {"system": "https://psa.gov.ph/classification/psoc", "code": "3253", "display": "Barangay Health Worker"},
    ],
    "contact-point-system": [
        {"system": "http://hl7.org/fhir/contact-point-system", "code": c, "display": c.title()}
        for c in ["phone", "email", "sms", "fax", "url", "other"]
    ],
    "contact-point-use": [
        {"system": "http://hl7.org/fhir/contact-point-use", "code": c, "display": c.title()}
        for c in ["home", "work", "mobile", "temp", "old"]
    ],
}


def _headers(config: EffectiveConfig) -> Dict[str, str]:
    headers = {"Accept": FHIR_JSON}
    if config.fhir_auth_token:
        headers["Authorization"] = f"Bearer {config.fhir_auth_token}"
    return headers


def _flatten_expansion(value_set: Any) -> List[Dict[str, str]]:
    contains = (value_set or {}).get("expansion", {}).get("contains", [])
    out = []
    for item in contains:
        out.append(
            {
                "system": item.get("system", ""),
                "code": item.get("code", ""),
                "display": item.get("display", item.get("code", "")),
            }
        )
    return out


async def expand(
    key_or_url: str,
    filter_text: Optional[str] = None,
    count: Optional[int] = None,
    allow_fallback: bool = True,
    config: Optional[EffectiveConfig] = None,
) -> Dict[str, Any]:
    """Expand a ValueSet by friendly key or canonical URL.

    Returns {"source": "server"|"fallback", "concepts": [...], "url": ...}.
    """
    config = config or get_config()
    canonical = VALUE_SETS.get(key_or_url, key_or_url)
    query = [f"url={quote(canonical, safe='')}"]
    if filter_text:
        query.append(f"filter={quote(filter_text, safe='')}")
    if count and count > 0:
        query.append(f"count={int(count)}")
    url = f"{config.terminology_base_url}/ValueSet/$expand?{'&'.join(query)}"
    last_error: Optional[FHIRError] = None
    try:
        body = await _request(
            "terminology", "GET", url, headers=_headers(config),
            timeout=config.http_timeout,
        )
        concepts = _flatten_expansion(body)
        return {"source": "server", "url": canonical, "concepts": concepts}
    except FHIRError as exc:
        last_error = exc
        if not allow_fallback:
            raise

    if not allow_fallback:
        if last_error:
            raise last_error
        raise FHIRError(f"Terminology expansion failed for {canonical}")

    fallback = FALLBACKS.get(key_or_url, [])
    if filter_text:
        f = filter_text.lower()
        fallback = [c for c in fallback if f in c.get("display", "").lower() or f in c.get("code", "").lower()]
    if count and count > 0:
        fallback = fallback[: int(count)]
    return {"source": "fallback", "url": canonical, "concepts": fallback}


async def lookup(system: str, code: str, config: Optional[EffectiveConfig] = None) -> Any:
    """CodeSystem/$lookup for a single code."""
    config = config or get_config()
    url = (
        f"{config.terminology_base_url}/CodeSystem/$lookup"
        f"?system={quote(system, safe='')}&code={quote(code, safe='')}"
    )
    return await _request(
        "terminology", "GET", url, headers=_headers(config),
        timeout=config.http_timeout,
    )


async def validate_code(
    url: str,
    system: str,
    code: str,
    display: Optional[str] = None,
    config: Optional[EffectiveConfig] = None,
) -> Any:
    """Validate a code against a ValueSet using ValueSet/$validate-code."""
    config = config or get_config()
    query = [
        f"url={quote(url, safe='')}",
        f"system={quote(system, safe='')}",
        f"code={quote(code, safe='')}",
    ]
    if display:
        query.append(f"display={quote(display, safe='')}")
    req_url = f"{config.terminology_base_url}/ValueSet/$validate-code?{'&'.join(query)}"
    return await _request(
        "terminology", "GET", req_url, headers=_headers(config),
        timeout=config.http_timeout,
    )
