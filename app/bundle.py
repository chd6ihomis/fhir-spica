"""Build the eReferral transaction Bundle aligned with PH eReferral IG.

Conformance target: `Bundle-ExampleERefSubmissionBundle` (Ana Reyes sample) —
21-entry transaction with:
  * Patient, 2x Practitioner, 2x Organization, 2x PractitionerRole — master
    data submitted via conditional PUT (`?identifier=...`) for idempotency.
  * ServiceRequest, Encounter, 2x Condition, 6x Observation, Procedure,
    DiagnosticReport, Task, Provenance — clinical data submitted via POST.

Rules (strict):
  * Form data is the sole source of truth. ``DEFAULTS`` is opt-in (demo only).
  * No silent fallbacks: missing form fields become ``None`` and are pruned.
  * Every coded element carries the matching ``display`` from the form.
  * Profile meta-tags are stamped on every IG-profiled resource.

The transaction Bundle uses ``urn:uuid:`` ``fullUrl`` references between
entries. ``routers/api.py`` may rewrite ``request.url`` to explicit
``Resource/{id}`` PUTs when an upstream search matches an existing record.
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Canonical systems & profile URLs (PH Core / PH eReferral IG)
# ---------------------------------------------------------------------------
PHCORE_SD = "https://fhir.doh.gov.ph/phcore/StructureDefinition"
PHEREF_SD = "https://fhir.doh.gov.ph/pheref/StructureDefinition"

PSGC_SYSTEM = "https://psa.gov.ph/classification/psgc"
NHFR_SYSTEM = "https://fhir.doh.gov.ph/phcore/Identifier/doh-nhfr-code"
HCPN_SYSTEM = "https://fhir.doh.gov.ph/phcore/Identifier/hcpn-code"
PRC_SYSTEM = "https://prc.gov.ph/"
PHILSYS_SYSTEM = "http://philsys.gov.ph/fhir/Identifier/philsys-id"
PHILHEALTH_SYSTEM = "http://philhealth.gov.ph/fhir/Identifier/philhealth-id"

SCT = "http://snomed.info/sct"
LOINC = "http://loinc.org"
UCUM = "http://unitsofmeasure.org"

V3_ACT_CODE = "http://terminology.hl7.org/CodeSystem/v3-ActCode"
V3_ROLE_CODE = "http://terminology.hl7.org/CodeSystem/v3-RoleCode"
COND_CLINICAL = "http://terminology.hl7.org/CodeSystem/condition-clinical"
COND_VER_STATUS = "http://terminology.hl7.org/CodeSystem/condition-ver-status"
COND_CATEGORY = "http://terminology.hl7.org/CodeSystem/condition-category"
OBS_CATEGORY = "http://terminology.hl7.org/CodeSystem/observation-category"
V3_DATA_OPERATION = "http://terminology.hl7.org/CodeSystem/v3-DataOperation"
PROVENANCE_PARTICIPANT_TYPE = (
    "http://terminology.hl7.org/CodeSystem/provenance-participant-type"
)
SIGNATURE_SYSTEM = "urn:iso-astm:E1762-95:2013"

# LOINC / SNOMED codes for vital-signs observations (aligned with IG sample).
LOINC_BP = "85354-9"
LOINC_SYSTOLIC = "8480-6"
LOINC_DIASTOLIC = "8462-4"
LOINC_HR = "8867-4"
LOINC_RR = "9279-1"
LOINC_SPO2 = "2708-6"  # IG sample uses 2708-6, not 59408-5
LOINC_TEMP = "8310-5"
LOINC_WEIGHT = "29463-7"

SCT_BP = "75367002"
SCT_SYSTOLIC = "271649006"
SCT_DIASTOLIC = "271650006"
SCT_HR = "78564009"
SCT_RR = "86290005"
SCT_SPO2 = "103228002"
SCT_TEMP = "386725007"
SCT_WEIGHT = "27113001"

VITAL_SIGNS_CATEGORY = {
    "coding": [
        {"system": OBS_CATEGORY, "code": "vital-signs", "display": "Vital Signs"}
    ]
}

# Map referral category SNOMED code -> ServiceRequest.priority.
PRIORITY_BY_CATEGORY = {"73770003": "stat", "440655000": "routine"}

# Demo defaults — opt-in only (``use_defaults=True``). MUST NOT be used as a
# fallback in production submissions.
DEFAULTS: Dict[str, Any] = {
    "patient_family": "Reyes",
    "patient_given": "Ana Luisa",
    "patient_gender": "female",
    "patient_birthdate": "1988-03-12",
    "patient_phone": "+63-919-876-5432",
    "philsys_id": "7731-0812-4491-0326",
    "philhealth_id": "78-658064775-3",
    "patient_line": "Area 4, Barangay Mabuhay",
    "patient_postal": "5600",
    "region_code": "0600000000",
    "region_display": "Region VI (Western Visayas)",
    "province_code": "0600400000",
    "province_display": "Aklan",
    "city_code": "0600407000",
    "city_display": "Kalibo",
    "barangay_code": "0600407013",
    "barangay_display": "Poblacion",
    "contact_relationship": "HUSB",
    "contact_relationship_display": "Husband",
    "contact_relationship_system": V3_ROLE_CODE,
    "contact_family": "Reyes",
    "contact_given": "Roberto",
    "referring_prac_family": "Villanueva",
    "referring_prac_given": "Maria",
    "referring_prac_prc": "5466863",
    "receiving_prac_family": "Lim",
    "receiving_prac_given": "Carlos",
    "receiving_prac_prc": "7890123",
    "referring_org_name": "Kalibo Health Center",
    "referring_org_nhfr": "3056",
    "referring_org_phone": "(043) 756-2233",
    "referring_org_hcpn": "Aklan HCPN",
    "receiving_org_name": "Dr. Rafael S. Tumbokon Memorial Hospital",
    "receiving_org_nhfr": "513",
    "receiving_org_phone": "(043) 756-3124",
    "receiving_org_hcpn": "Aklan HCPN",
    "role_code": "158965000",
    "role_display": "Medical practitioner",
    "referring_role_code": "158965000",
    "referring_role_display": "Medical practitioner",
    "receiving_role_code": "158965000",
    "receiving_role_display": "Medical practitioner",
    "referral_category_code": "73770003",
    "referral_category_display": "Hospital-based outpatient emergency care center",
    "reason_code": "71388002",
    "reason_display": "Procedure",
    "authored_on": "2026-06-18T08:30:00+08:00",
    "time_called": "2026-06-18T08:30:00+08:00",
    "chief_complaint_text": "Severe headache, dizziness, blurring of vision, epigastric pain",
    "chief_complaint_code": "25064002",
    "chief_complaint_display": "Headache",
    "clinical_history": "G2P1, 32 weeks AOG. Symptoms persisting for two days.",
    "diagnosis_code": "398254007",
    "diagnosis_display": "Pre-eclampsia",
    "working_impression": "G2P1(1001), Pregnancy Uterine, 32 weeks AOG -- Severe Pre-eclampsia",
    "bp_systolic": 180,
    "bp_diastolic": 110,
    "heart_rate": 112,
    "resp_rate": 24,
    "spo2": 96,
    "temperature": 36.8,
    "weight": 72,
    "treatment_given": "Methyldopa 250mg BID, Folic Acid 5mg OD, FeSO4 300mg OD, CaCO3 500mg TID",
    "lab_text": "Proteinuria 3+. Findings consistent with severe pre-eclampsia.",
    "lab_title": "Urinalysis Results — Kalibo Health Center",
    "lab_attachment": "",
    "task_note": "Referral initiated by Kalibo Health Center for severe pre-eclampsia management.",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _val(form: Dict[str, Any], key: str, use_defaults: bool = False) -> Any:
    """Return form value; only fall back to ``DEFAULTS`` when explicitly enabled."""
    if form and key in form and form[key] not in (None, ""):
        return form[key]
    if use_defaults:
        return DEFAULTS.get(key)
    return None


def _num(form: Dict[str, Any], key: str, use_defaults: bool = False) -> Optional[float]:
    raw = _val(form, key, use_defaults=use_defaults)
    if raw in (None, ""):
        return None
    try:
        num_val = float(raw)
        return int(num_val) if num_val.is_integer() else num_val
    except (TypeError, ValueError):
        return None


def _psgc_ext(form: Dict[str, Any], use_defaults: bool = False) -> List[Dict[str, Any]]:
    """Render the four PSGC address extensions, each carrying ``display``."""
    mapping = [
        ("region", "region_code", "region_display"),
        ("province", "province_code", "province_display"),
        ("city-municipality", "city_code", "city_display"),
        ("barangay", "barangay_code", "barangay_display"),
    ]
    out: List[Dict[str, Any]] = []
    for slice_name, key, display_key in mapping:
        code = _val(form, key, use_defaults=use_defaults)
        display = _val(form, display_key, use_defaults=use_defaults)
        if code:
            coding: Dict[str, Any] = {"system": PSGC_SYSTEM, "code": code}
            if display:
                coding["display"] = display
            out.append(
                {
                    "url": f"{PHCORE_SD}/{slice_name}",
                    "valueCoding": coding,
                }
            )
    return out


def _given(value: Any) -> List[str]:
    if value in (None, ""):
        return []
    return [p for p in str(value).split() if p]


def _prune_none(value: Any) -> Any:
    """Recursively drop None and empty containers from payload objects."""
    if isinstance(value, dict):
        pruned: Dict[str, Any] = {}
        for key, item in value.items():
            child = _prune_none(item)
            if child is None:
                continue
            if isinstance(child, (dict, list)) and not child:
                continue
            pruned[key] = child
        return pruned
    if isinstance(value, list):
        pruned_list: List[Any] = []
        for item in value:
            child = _prune_none(item)
            if child is None:
                continue
            if isinstance(child, (dict, list)) and not child:
                continue
            pruned_list.append(child)
        return pruned_list
    return value


def _coding(system: str, code: Any, display: Any = None) -> Optional[Dict[str, Any]]:
    if code in (None, ""):
        return None
    out: Dict[str, Any] = {"system": system, "code": code}
    if display:
        out["display"] = display
    return out


def _codeable(codings: List[Optional[Dict[str, Any]]], text: Any = None) -> Optional[Dict[str, Any]]:
    valid = [c for c in codings if c]
    if not valid and not text:
        return None
    out: Dict[str, Any] = {}
    if valid:
        out["coding"] = valid
    if text:
        out["text"] = text
    return out


def _quantity(value: Optional[float], unit: str, code: str) -> Optional[Dict[str, Any]]:
    if value is None:
        return None
    return {"value": value, "unit": unit, "system": UCUM, "code": code}


def _vital_observation(
    full_url: str,
    primary: Dict[str, Any],
    secondary: Optional[Dict[str, Any]],
    quantity: Optional[Dict[str, Any]],
    patient_ref: Dict[str, str],
    encounter_ref: Dict[str, str],
    effective: Any,
) -> Optional[Dict[str, Any]]:
    if quantity is None:
        return None
    codings = [primary]
    if secondary:
        codings.append(secondary)
    return {
        "fullUrl": full_url,
        "resource": {
            "resourceType": "Observation",
            "meta": {"profile": [f"{PHEREF_SD}/ereferral-observation"]},
            "status": "final",
            "category": [VITAL_SIGNS_CATEGORY],
            "code": {"coding": codings},
            "subject": patient_ref,
            "encounter": encounter_ref,
            "effectiveDateTime": effective,
            "valueQuantity": quantity,
        },
        "request": {"method": "POST", "url": "Observation"},
    }


# ---------------------------------------------------------------------------
# Bundle builder
# ---------------------------------------------------------------------------
def build_referral_bundle(
    form: Optional[Dict[str, Any]] = None,
    *,
    use_defaults: bool = False,
    _with_index: bool = False,
) -> Dict[str, Any]:
    """Build the eReferral transaction Bundle from form data.

    Args:
        form: form payload (preferred source of truth).
        use_defaults: opt-in demo mode. NEVER set this in production submits.
        _with_index: internal — also return the ``urn:uuid -> logical key``
            index (used by :func:`build_modules`).
    """
    form = form or {}

    def val(key: str) -> Any:
        return _val(form, key, use_defaults=use_defaults)

    def num(key: str) -> Optional[float]:
        return _num(form, key, use_defaults=use_defaults)

    def psgc_ext() -> List[Dict[str, Any]]:
        return _psgc_ext(form, use_defaults=use_defaults)

    def org_address(prefix: str) -> Optional[Dict[str, Any]]:
        """Build an Organization address using PSGC extensions (same structure as Patient).

        Prefers PSGC extension fields (org_region_code etc.) when available,
        then falls back to bare city/province strings for backwards compatibility
        with older form submissions.
        """
        address_text = val(f"{prefix}_org_address_text")
        postal = val(f"{prefix}_org_postal")

        # Build PSGC extensions from org-specific prefixed keys
        org_psgc_form = {
            "region_code":    val(f"{prefix}_org_region_code"),
            "region_display": val(f"{prefix}_org_region_display"),
            "province_code":    val(f"{prefix}_org_province_code"),
            "province_display": val(f"{prefix}_org_province_display"),
            "city_code":    val(f"{prefix}_org_city_code"),
            "city_display": val(f"{prefix}_org_city_display"),
            "barangay_code":    val(f"{prefix}_org_barangay_code"),
            "barangay_display": val(f"{prefix}_org_barangay_display"),
        }
        psgc_exts = _psgc_ext(org_psgc_form, use_defaults=False)

        # Nothing to include
        if not any([address_text, postal, psgc_exts]):
            return None

        address: Dict[str, Any] = {"use": "work", "country": "PH"}
        if psgc_exts:
            address["extension"] = psgc_exts
        if address_text:
            address["line"] = [address_text]
        if postal:
            address["postalCode"] = postal
        return address

    ids = {
        name: f"urn:uuid:{uuid.uuid4()}"
        for name in [
            "patient", "prac_ref", "prac_rec", "org_ref", "org_rec",
            "role_ref", "role_rec", "service_request", "encounter",
            "cond_chief", "cond_dx", "obs_bp", "obs_hr", "obs_rr",
            "obs_spo2", "obs_temp", "obs_weight", "procedure",
            "diagnostic_report", "task", "provenance",
        ]
    }

    patient_ref = {"reference": ids["patient"]}
    encounter_ref = {"reference": ids["encounter"]}

    role_code_default = val("role_code")
    role_display_default = val("role_display")
    referring_role_code = val("referring_role_code") or role_code_default
    referring_role_display = val("referring_role_display") or role_display_default
    receiving_role_code = val("receiving_role_code") or role_code_default
    receiving_role_display = val("receiving_role_display") or role_display_default

    # Practitioner display names (used on PractitionerRole-typed references such
    # as ServiceRequest.requester / Task.owner). The reference is a
    # PractitionerRole, so the display must describe the *practitioner*, not
    # the organization — the organization is reachable through the role's
    # `organization` element.
    def _prac_display(family_key: str, given_key: str) -> Optional[str]:
        family = val(family_key)
        given = val(given_key)
        parts = [p for p in (_given(given) + ([family] if family else [])) if p]
        if not parts:
            return None
        return "Dr. " + " ".join(parts)

    referring_prac_display = _prac_display("referring_prac_family", "referring_prac_given")
    receiving_prac_display = _prac_display("receiving_prac_family", "receiving_prac_given")

    authored = val("authored_on")
    time_called = val("time_called") or authored

    entries: List[Dict[str, Any]] = []

    # ---- 1. Patient (PUT by PhilSys identifier, mirroring IG sample) ----
    philsys = val("philsys_id")
    philhealth = val("philhealth_id")
    patient_phone = val("patient_phone")
    patient_identifiers: List[Dict[str, Any]] = []
    if philhealth:
        patient_identifiers.append({"system": PHILHEALTH_SYSTEM, "value": philhealth})
    if philsys:
        patient_identifiers.append({"system": PHILSYS_SYSTEM, "value": philsys})

    patient_address: Dict[str, Any] = {
        "use": "home",
        "country": "PH",
        "extension": psgc_ext(),
    }
    if val("patient_line"):
        patient_address["line"] = [val("patient_line")]
    if val("patient_postal"):
        patient_address["postalCode"] = val("patient_postal")

    patient_resource: Dict[str, Any] = {
        "resourceType": "Patient",
        "meta": {"profile": [f"{PHEREF_SD}/ereferral-patient"]},
        "identifier": patient_identifiers,
        "active": True,
        "name": [{
            "use": "official",
            "family": val("patient_family"),
            "given": _given(val("patient_given")),
        }],
        "gender": val("patient_gender"),
        "birthDate": val("patient_birthdate"),
        "address": [patient_address],
    }
    if patient_phone:
        patient_resource["telecom"] = [
            {"system": "phone", "value": patient_phone, "use": "mobile"}
        ]
    if val("contact_family") or val("contact_given") or val("contact_relationship"):
        patient_resource["contact"] = [{
            "relationship": [{"coding": [{
                "system": val("contact_relationship_system") or V3_ROLE_CODE,
                "code": val("contact_relationship"),
                "display": val("contact_relationship_display"),
            }]}],
            "name": {
                "use": "official",
                "family": val("contact_family"),
                "given": _given(val("contact_given")),
            },
        }]

    if philsys:
        patient_request_url = f"Patient?identifier={PHILSYS_SYSTEM}|{philsys}"
    elif philhealth:
        patient_request_url = f"Patient?identifier={PHILHEALTH_SYSTEM}|{philhealth}"
    else:
        patient_request_url = "Patient"

    entries.append({
        "fullUrl": ids["patient"],
        "resource": patient_resource,
        "request": {"method": "PUT" if patient_identifiers else "POST", "url": patient_request_url},
    })

    # ---- 2 & 3. Practitioners (PUT by PRC identifier) ----
    for key, prc_key, fam_key, giv_key in [
        ("prac_ref", "referring_prac_prc", "referring_prac_family", "referring_prac_given"),
        ("prac_rec", "receiving_prac_prc", "receiving_prac_family", "receiving_prac_given"),
    ]:
        prc_val = val(prc_key)
        prac_resource = {
            "resourceType": "Practitioner",
            "meta": {"profile": [f"{PHCORE_SD}/ph-core-practitioner"]},
            "identifier": [{"system": PRC_SYSTEM, "value": prc_val}] if prc_val else None,
            "name": [{
                "use": "official",
                "family": val(fam_key),
                "given": _given(val(giv_key)),
                "prefix": ["Dr."],
            }],
        }
        if prc_val:
            req = {"method": "PUT", "url": f"Practitioner?identifier={PRC_SYSTEM}|{prc_val}"}
        else:
            req = {"method": "POST", "url": "Practitioner"}
        entries.append({"fullUrl": ids[key], "resource": prac_resource, "request": req})

    # ---- 4. Referring Organization (PUT by NHFR) ----
    ref_nhfr = val("referring_org_nhfr")
    ref_hcpn = val("referring_org_hcpn")
    ref_org_identifiers: List[Dict[str, Any]] = []
    if ref_nhfr:
        ref_org_identifiers.append({"system": NHFR_SYSTEM, "value": ref_nhfr})
    if ref_hcpn:
        ref_org_identifiers.append({"system": HCPN_SYSTEM, "value": ref_hcpn})

    ref_org_address = org_address("referring")
    entries.append({
        "fullUrl": ids["org_ref"],
        "resource": {
            "resourceType": "Organization",
            "meta": {"profile": [f"{PHCORE_SD}/ph-core-organization"]},
            "identifier": ref_org_identifiers or None,
            "name": val("referring_org_name"),
            "telecom": [{"system": "phone", "value": val("referring_org_phone"), "use": "work"}] if val("referring_org_phone") else None,
            "address": [ref_org_address] if ref_org_address else None,
        },
        "request": {
            "method": "PUT" if ref_nhfr else "POST",
            "url": f"Organization?identifier={NHFR_SYSTEM}|{ref_nhfr}" if ref_nhfr else "Organization",
        },
    })

    # ---- 5. Receiving Organization (PUT by NHFR) ----
    rec_nhfr = val("receiving_org_nhfr")
    rec_hcpn = val("receiving_org_hcpn")
    rec_org_identifiers: List[Dict[str, Any]] = []
    if rec_nhfr:
        rec_org_identifiers.append({"system": NHFR_SYSTEM, "value": rec_nhfr})
    if rec_hcpn:
        rec_org_identifiers.append({"system": HCPN_SYSTEM, "value": rec_hcpn})

    rec_org_address = org_address("receiving")
    entries.append({
        "fullUrl": ids["org_rec"],
        "resource": {
            "resourceType": "Organization",
            "meta": {"profile": [f"{PHCORE_SD}/ph-core-organization"]},
            "identifier": rec_org_identifiers or None,
            "name": val("receiving_org_name"),
            "telecom": [{"system": "phone", "value": val("receiving_org_phone"), "use": "work"}] if val("receiving_org_phone") else None,
            "address": [rec_org_address] if rec_org_address else None,
        },
        "request": {
            "method": "PUT" if rec_nhfr else "POST",
            "url": f"Organization?identifier={NHFR_SYSTEM}|{rec_nhfr}" if rec_nhfr else "Organization",
        },
    })

    # ---- 6. Referring PractitionerRole (PUT by PRC identifier) ----
    referring_prc = val("referring_prac_prc")
    entries.append({
        "fullUrl": ids["role_ref"],
        "resource": {
            "resourceType": "PractitionerRole",
            "meta": {"profile": [f"{PHEREF_SD}/ereferral-practitioner-role"]},
            "identifier": [{"system": PRC_SYSTEM, "value": referring_prc}] if referring_prc else None,
            "practitioner": {"reference": ids["prac_ref"]},
            "organization": {"reference": ids["org_ref"]},
            "code": [{"coding": [{"system": SCT, "code": referring_role_code, "display": referring_role_display}]}] if referring_role_code else None,
        },
        "request": {
            "method": "PUT" if referring_prc else "POST",
            "url": f"PractitionerRole?identifier={PRC_SYSTEM}|{referring_prc}" if referring_prc else "PractitionerRole",
        },
    })

    # ---- 7. Receiving PractitionerRole (PUT by PRC identifier) ----
    receiving_prc = val("receiving_prac_prc")
    entries.append({
        "fullUrl": ids["role_rec"],
        "resource": {
            "resourceType": "PractitionerRole",
            "meta": {"profile": [f"{PHEREF_SD}/ereferral-practitioner-role"]},
            "identifier": [{"system": PRC_SYSTEM, "value": receiving_prc}] if receiving_prc else None,
            "practitioner": {"reference": ids["prac_rec"]},
            "organization": {"reference": ids["org_rec"]},
            "code": [{"coding": [{"system": SCT, "code": receiving_role_code, "display": receiving_role_display}]}] if receiving_role_code else None,
        },
        "request": {
            "method": "PUT" if receiving_prc else "POST",
            "url": f"PractitionerRole?identifier={PRC_SYSTEM}|{receiving_prc}" if receiving_prc else "PractitionerRole",
        },
    })

    category_code = val("referral_category_code")
    priority = PRIORITY_BY_CATEGORY.get(str(category_code or ""), "routine")

    # ---- 8. ServiceRequest (POST) ----
    sr_resource: Dict[str, Any] = {
        "resourceType": "ServiceRequest",
        "meta": {"profile": [f"{PHEREF_SD}/ereferral-service-request"]},
        "status": "active",
        "intent": "order",
        "priority": priority,
        "category": [_codeable([_coding(SCT, category_code, val("referral_category_display"))])] if category_code else None,
        "code": {"coding": [{"system": SCT, "code": "3457005", "display": "Patient referral"}]},
        "subject": patient_ref,
        "encounter": encounter_ref,
        "occurrenceDateTime": authored,
        "authoredOn": authored,
        "requester": {"reference": ids["role_ref"], "display": referring_prac_display},
        "performer": [{"reference": ids["role_rec"], "display": receiving_prac_display}],
        "reasonCode": [_codeable([_coding(SCT, val("reason_code"), val("reason_display"))])] if val("reason_code") else None,
        "reasonReference": [{"reference": ids["cond_dx"]}],
    }
    if val("task_note"):
        sr_resource["note"] = [{"text": val("task_note")}]
    entries.append({
        "fullUrl": ids["service_request"],
        "resource": sr_resource,
        "request": {"method": "POST", "url": "ServiceRequest"},
    })

    # ---- 9. Encounter (POST) ----
    entries.append({
        "fullUrl": ids["encounter"],
        "resource": {
            "resourceType": "Encounter",
            "meta": {"profile": [f"{PHEREF_SD}/ereferral-encounter"]},
            "status": "finished",
            "class": {"system": V3_ACT_CODE, "code": "AMB", "display": "ambulatory"},
            "subject": patient_ref,
        },
        "request": {"method": "POST", "url": "Encounter"},
    })

    # ---- 10. Condition: Chief complaint (POST) ----
    chief_code = val("chief_complaint_code")
    chief_display = val("chief_complaint_display")
    chief_text = val("chief_complaint_text")
    if chief_code or chief_text:
        cond_chief: Dict[str, Any] = {
            "resourceType": "Condition",
            "meta": {"profile": [f"{PHEREF_SD}/ereferral-condition"]},
            "clinicalStatus": {"coding": [{"system": COND_CLINICAL, "code": "active"}]},
            "category": [{"coding": [{"system": COND_CATEGORY, "code": "problem-list-item", "display": "Problem List Item"}]}],
            "code": _codeable([_coding(SCT, chief_code, chief_display)], text=chief_text),
            "subject": patient_ref,
            "encounter": encounter_ref,
        }
        if val("clinical_history"):
            cond_chief["note"] = [{"text": val("clinical_history")}]
        entries.append({
            "fullUrl": ids["cond_chief"],
            "resource": cond_chief,
            "request": {"method": "POST", "url": "Condition"},
        })

    # ---- 11. Condition: Working impression / diagnosis (POST) ----
    dx_code = val("diagnosis_code")
    dx_display = val("diagnosis_display")
    dx_text = val("working_impression")
    if dx_code or dx_text:
        entries.append({
            "fullUrl": ids["cond_dx"],
            "resource": _prune_none({
                "resourceType": "Condition",
                "meta": {"profile": [f"{PHEREF_SD}/ereferral-condition"]},
                "clinicalStatus": {"coding": [{"system": COND_CLINICAL, "code": "active"}]},
                "verificationStatus": {"coding": [{"system": COND_VER_STATUS, "code": "provisional", "display": "Provisional"}]},
                "category": [{"coding": [{"system": COND_CATEGORY, "code": "encounter-diagnosis", "display": "Encounter Diagnosis"}]}],
                "code": _codeable([_coding(SCT, dx_code, dx_display)], text=dx_text),
                "subject": patient_ref,
                "encounter": encounter_ref,
            }),
            "request": {"method": "POST", "url": "Condition"},
        })

    # ---- 12. Observation: Blood Pressure (panel + 2 components) ----
    sys_value = num("bp_systolic")
    dia_value = num("bp_diastolic")
    if sys_value is not None or dia_value is not None:
        components: List[Dict[str, Any]] = []
        if sys_value is not None:
            components.append({
                "code": {"coding": [
                    {"system": LOINC, "code": LOINC_SYSTOLIC, "display": "Systolic blood pressure"},
                    {"system": SCT, "code": SCT_SYSTOLIC, "display": "Systolic blood pressure"},
                ]},
                "valueQuantity": _quantity(sys_value, "mmHg", "mm[Hg]"),
            })
        if dia_value is not None:
            components.append({
                "code": {"coding": [
                    {"system": LOINC, "code": LOINC_DIASTOLIC, "display": "Diastolic blood pressure"},
                    {"system": SCT, "code": SCT_DIASTOLIC, "display": "Diastolic blood pressure"},
                ]},
                "valueQuantity": _quantity(dia_value, "mmHg", "mm[Hg]"),
            })
        entries.append({
            "fullUrl": ids["obs_bp"],
            "resource": {
                "resourceType": "Observation",
                "meta": {"profile": [f"{PHEREF_SD}/ereferral-observation"]},
                "status": "final",
                "category": [VITAL_SIGNS_CATEGORY],
                "code": {"coding": [
                    {"system": LOINC, "code": LOINC_BP, "display": "Blood pressure panel with all children optional"},
                    {"system": SCT, "code": SCT_BP, "display": "Blood pressure"},
                ]},
                "subject": patient_ref,
                "encounter": encounter_ref,
                "effectiveDateTime": authored,
                "component": components,
            },
            "request": {"method": "POST", "url": "Observation"},
        })

    # ---- 13-17. Vital sign observations (HR, RR, SpO2, Temp, Weight) ----
    vital_specs = [
        ("obs_hr", LOINC_HR, "Heart rate", SCT_HR, "Pulse rate", num("heart_rate"), "beats/minute", "/min"),
        ("obs_rr", LOINC_RR, "Respiratory rate", SCT_RR, "Respiratory rate", num("resp_rate"), "breaths/minute", "/min"),
        ("obs_spo2", LOINC_SPO2, "Oxygen saturation in Arterial blood", SCT_SPO2, "Hemoglobin saturation with oxygen", num("spo2"), "%", "%"),
        ("obs_temp", LOINC_TEMP, "Body temperature", SCT_TEMP, "Body temperature", num("temperature"), "Celsius", "Cel"),
        ("obs_weight", LOINC_WEIGHT, "Body weight", SCT_WEIGHT, "Body weight", num("weight"), "kg", "kg"),
    ]
    for key, loinc, loinc_display, sct_code, sct_display, value, unit, ucum in vital_specs:
        obs_entry = _vital_observation(
            ids[key],
            {"system": LOINC, "code": loinc, "display": loinc_display},
            {"system": SCT, "code": sct_code, "display": sct_display},
            _quantity(value, unit, ucum),
            patient_ref,
            encounter_ref,
            authored,
        )
        if obs_entry:
            entries.append(obs_entry)

    # ---- 18. Procedure: initial treatment / drug therapy ----
    if val("treatment_given"):
        entries.append({
            "fullUrl": ids["procedure"],
            "resource": {
                "resourceType": "Procedure",
                "meta": {"profile": [f"{PHEREF_SD}/ereferral-procedure"]},
                "status": "completed",
                "code": {"coding": [{"system": SCT, "code": "416608005", "display": "Drug therapy"}]},
                "subject": patient_ref,
                "encounter": encounter_ref,
                "performedDateTime": authored,
                "note": [{"text": val("treatment_given")}],
            },
            "request": {"method": "POST", "url": "Procedure"},
        })

    # ---- 19. DiagnosticReport: urinalysis ----
    if val("lab_text") or val("lab_attachment"):
        diag_report: Dict[str, Any] = {
            "resourceType": "DiagnosticReport",
            "status": "final",
            "code": {"coding": [{"system": LOINC, "code": "24356-8", "display": "Urinalysis complete panel - Urine"}]},
            "subject": patient_ref,
            "encounter": encounter_ref,
            "effectiveDateTime": authored,
        }
        if val("lab_text"):
            diag_report["conclusion"] = val("lab_text")
        attachment = val("lab_attachment")
        if attachment:
            diag_report["presentedForm"] = [{
                "contentType": "application/pdf",
                "data": attachment,
                "title": val("lab_title") or "Laboratory result",
            }]
        elif val("lab_title"):
            diag_report["presentedForm"] = [{"title": val("lab_title")}]
        entries.append({
            "fullUrl": ids["diagnostic_report"],
            "resource": diag_report,
            "request": {"method": "POST", "url": "DiagnosticReport"},
        })

    # ---- 20. Task: workflow tracker ----
    task_resource: Dict[str, Any] = {
        "resourceType": "Task",
        "meta": {"profile": [f"{PHEREF_SD}/ereferral-task"]},
        "status": "requested",
        "intent": "order",
        "priority": priority,
        "code": {"coding": [{"system": SCT, "code": "3457005", "display": "Patient referral"}]},
        "focus": {"reference": ids["service_request"]},
        "for": patient_ref,
        "authoredOn": time_called,
        "lastModified": time_called,
        "requester": {"reference": ids["role_ref"], "display": referring_prac_display},
        "owner": {"reference": ids["role_rec"], "display": receiving_prac_display},
    }
    if val("task_note"):
        task_resource["note"] = [{"text": val("task_note")}]
    entries.append({
        "fullUrl": ids["task"],
        "resource": task_resource,
        "request": {"method": "POST", "url": "Task"},
    })

    # ---- 21. Provenance: attestation/signature ----
    entries.append({
        "fullUrl": ids["provenance"],
        "resource": {
            "resourceType": "Provenance",
            "meta": {"profile": [f"{PHEREF_SD}/ereferral-provenance"]},
            "target": [{"reference": ids["service_request"]}],
            "recorded": authored,
            "activity": {"coding": [{"system": V3_DATA_OPERATION, "code": "CREATE", "display": "create"}]},
            "agent": [{
                "type": {"coding": [{"system": PROVENANCE_PARTICIPANT_TYPE, "code": "author", "display": "Author"}]},
                "who": {"reference": ids["role_ref"]},
                "onBehalfOf": {"reference": ids["org_ref"]},
            }],
            "signature": [{
                "type": [{"system": SIGNATURE_SYSTEM, "code": "1.2.840.10065.1.12.1.1", "display": "Author's Signature"}],
                "when": authored,
                "who": {"reference": ids["role_ref"]},
            }],
        },
        "request": {"method": "POST", "url": "Provenance"},
    })

    bundle: Dict[str, Any] = {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": entries,
    }
    if authored:
        bundle["timestamp"] = authored
    pruned = _prune_none(bundle)
    if _with_index:
        # Map urn:uuid fullUrl -> logical key (e.g. "patient", "role_ref").
        index = {urn: key for key, urn in ids.items()}
        return pruned, index  # type: ignore[return-value]
    return pruned


# ---------------------------------------------------------------------------
# Granular module catalogue (mirrors the PH eReferral Postman collection)
# ---------------------------------------------------------------------------
# Each transaction entry maps to one "module" — an individually inspectable /
# submittable FHIR operation. ``MODULE_GROUPS`` orders and labels them exactly
# like the Postman collection folders. ``group`` drives the UI grouping:
#   * ``master``  — idempotent conditional PUT (?identifier=...) upserts.
#   * ``clinical``— POST create operations.
# Logical key -> (label, group). Keys match the ``ids`` map in the builder.
MODULE_META: Dict[str, Dict[str, str]] = {
    "patient": {"label": "Patient", "group": "master"},
    "prac_ref": {"label": "Practitioner (Sending)", "group": "master"},
    "prac_rec": {"label": "Practitioner (Receiving)", "group": "master"},
    "org_ref": {"label": "Organization (Sending)", "group": "master"},
    "org_rec": {"label": "Organization (Receiving)", "group": "master"},
    "role_ref": {"label": "PractitionerRole (Sending)", "group": "master"},
    "role_rec": {"label": "PractitionerRole (Receiving)", "group": "master"},
    "service_request": {"label": "ServiceRequest", "group": "clinical"},
    "encounter": {"label": "Encounter", "group": "clinical"},
    "cond_chief": {"label": "Condition (Chief Complaint)", "group": "clinical"},
    "cond_dx": {"label": "Condition (Working Impression)", "group": "clinical"},
    "obs_bp": {"label": "Observation — Blood Pressure", "group": "clinical"},
    "obs_hr": {"label": "Observation — Heart Rate", "group": "clinical"},
    "obs_rr": {"label": "Observation — Respiratory Rate", "group": "clinical"},
    "obs_spo2": {"label": "Observation — Oxygen Saturation", "group": "clinical"},
    "obs_temp": {"label": "Observation — Temperature", "group": "clinical"},
    "obs_weight": {"label": "Observation — Weight", "group": "clinical"},
    "procedure": {"label": "Procedure", "group": "clinical"},
    "diagnostic_report": {"label": "DiagnosticReport", "group": "clinical"},
    "task": {"label": "Task", "group": "clinical"},
    "provenance": {"label": "Provenance", "group": "clinical"},
}


def build_modules(
    form: Optional[Dict[str, Any]] = None,
    *,
    use_defaults: bool = False,
) -> List[Dict[str, Any]]:
    """Return the ordered list of granular FHIR modules for the given form.

    Every module mirrors one Postman-collection request and carries enough
    metadata for the UI to render a self-describing card:

        {
          "key":      "patient",
          "label":    "Patient",
          "group":    "master" | "clinical",
          "method":   "PUT" | "POST",
          "url":      "Patient?identifier=...",
          "resource": { ...FHIR resource... },
          "references": { "<urn:uuid>": "<logical key>" }  # cross-refs to resolve
        }

    The order matches the transaction Bundle so the console reads top-to-bottom
    exactly like the collection.
    """
    bundle, index = build_referral_bundle(  # type: ignore[misc]
        form, use_defaults=use_defaults, _with_index=True
    )
    modules: List[Dict[str, Any]] = []
    for entry in bundle.get("entry", []):
        full_url = entry.get("fullUrl", "")
        resource = entry.get("resource", {})
        request = entry.get("request", {})
        key = index.get(full_url, "")
        meta = dict(MODULE_META.get(key, {}))

        # Resolve nicer labels where one resourceType maps to several modules.
        rtype = resource.get("resourceType", "")
        label = meta.get("label") or rtype
        group = meta.get("group") or ("master" if request.get("method") == "PUT" else "clinical")

        # Identify cross-entry references (urn:uuid) that an individual submit
        # would need to resolve to real server ids or conditional references.
        references = _collect_references(resource, index)

        modules.append({
            "key": key or full_url,
            "label": label,
            "group": group,
            "method": request.get("method", "POST"),
            "url": request.get("url", rtype),
            "resourceType": rtype,
            "fullUrl": full_url,
            "resource": resource,
            "references": references,
        })
    return modules


def _collect_references(node: Any, index: Dict[str, str]) -> Dict[str, str]:
    """Walk a resource and return {urn:uuid: logical-key} for internal refs."""
    found: Dict[str, str] = {}

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            ref = value.get("reference")
            if isinstance(ref, str) and ref in index:
                found[ref] = index[ref]
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(node)
    return found


# ---------------------------------------------------------------------------
# FHIR field documentation (drives hover tooltips in the module console)
# ---------------------------------------------------------------------------
# Keyed by JSON pointer-ish dotted path (``*`` matches any array index). The UI
# resolves the most specific matching key for each rendered field.
FHIR_FIELD_DOCS: Dict[str, str] = {
    "resourceType": "FHIR resource type. Determines the schema and the REST endpoint.",
    "meta.profile": "Canonical URL(s) of the StructureDefinition this resource claims to conform to (PH Core / PH eReferral IG).",
    "language": "Base language of the resource content (BCP-47), e.g. 'en'.",
    "identifier": "Business identifier(s). Used for conditional PUT upserts (?identifier=system|value).",
    "identifier.system": "Namespace URI that scopes the identifier value (PhilSys, PhilHealth, PRC, NHFR, HCPN).",
    "identifier.value": "The identifier value within its system.",
    "active": "Whether this record is in active use.",
    "name": "Human name. 'use=official' is the registered legal name.",
    "name.family": "Surname / family name.",
    "name.given": "Given name(s); ordered array.",
    "name.prefix": "Name prefix (e.g. 'Dr.').",
    "telecom": "Contact points (phone, email).",
    "telecom.system": "Contact channel: phone | email | fax | url.",
    "telecom.value": "The actual phone number or address.",
    "telecom.use": "Context of the contact point: home | work | mobile.",
    "gender": "Administrative gender: male | female | other | unknown.",
    "birthDate": "Date of birth (YYYY-MM-DD).",
    "address": "Postal/physical address. PH Core carries PSGC codes in extensions.",
    "address.extension": "PH Core PSGC slices (region / province / city-municipality / barangay).",
    "address.extension.url": "Canonical URL of the PH Core address-part StructureDefinition.",
    "address.extension.valueCoding": "PSGC-coded geographic unit with code + display.",
    "address.line": "Street / building / barangay free-text line(s).",
    "address.postalCode": "Postal (ZIP) code.",
    "address.country": "ISO country code; 'PH' for the Philippines.",
    "address.use": "home | work | temp | billing.",
    "contact": "Patient's next of kin / emergency contact.",
    "contact.relationship": "Coded relationship of the contact to the patient (v3 RoleCode).",
    "status": "Resource workflow/state code (varies by resource type).",
    "intent": "ServiceRequest/Task intent: 'order' for an actionable referral.",
    "priority": "Urgency: routine | urgent | asap | stat.",
    "category": "Classifier coding (e.g. referral category, vital-signs, condition-category).",
    "code": "The primary concept this resource is about (SNOMED CT / LOINC).",
    "code.coding": "One or more codings; PH eReferral uses dual LOINC + SNOMED on vitals.",
    "code.coding.system": "Code system URI (SNOMED 'http://snomed.info/sct', LOINC 'http://loinc.org').",
    "code.coding.code": "The code value within the system.",
    "code.coding.display": "Human-readable term for the code.",
    "code.text": "Free-text description of the concept.",
    "subject": "The Patient the resource is about (reference).",
    "encounter": "The Encounter during which the resource was recorded (reference).",
    "requester": "PractitionerRole that initiated the referral (Sending).",
    "performer": "PractitionerRole expected to fulfil the referral (Receiving).",
    "reasonCode": "Coded reason for the referral (SNOMED CT).",
    "reasonReference": "Reference to the Condition justifying the referral.",
    "occurrenceDateTime": "When the requested service should occur.",
    "authoredOn": "When the request was authored / referral date.",
    "requisition": "Shared identifier grouping all requests of one referral order.",
    "clinicalStatus": "Condition clinical status: active | recurrence | inactive | resolved.",
    "verificationStatus": "Condition verification: provisional | differential | confirmed.",
    "effectiveDateTime": "Clinically relevant time of the observation.",
    "valueQuantity": "Measured value with UCUM unit.",
    "valueQuantity.value": "Numeric measurement.",
    "valueQuantity.unit": "Human-readable unit.",
    "valueQuantity.system": "UCUM system URI.",
    "valueQuantity.code": "UCUM unit code (e.g. 'mm[Hg]', '/min', 'Cel', 'kg').",
    "component": "Sub-observations (e.g. systolic & diastolic for a BP panel).",
    "class": "Encounter class (v3 ActCode): AMB = ambulatory.",
    "focus": "Task focus — the ServiceRequest being tracked.",
    "for": "Task beneficiary — the Patient.",
    "owner": "Task owner — the receiving PractitionerRole.",
    "lastModified": "When the Task was last updated.",
    "note": "Free-text annotation(s).",
    "conclusion": "DiagnosticReport narrative conclusion.",
    "presentedForm": "Attached report document(s).",
    "target": "Provenance target — the resource whose history is described.",
    "recorded": "When the Provenance was recorded.",
    "activity": "Provenance activity (v3 DataOperation), e.g. CREATE.",
    "agent": "Who participated (author PractitionerRole) and on whose behalf (Organization).",
    "agent.who": "The acting PractitionerRole.",
    "agent.onBehalfOf": "The Organization the agent acted for.",
    "signature": "Attestation signature block.",
    "practitioner": "PractitionerRole -> the Practitioner who holds the role.",
    "organization": "PractitionerRole -> the Organization where the role is held.",
    "reference": "Relative/absolute reference to another resource (or urn:uuid within a Bundle).",
    "display": "Human-readable label accompanying a reference or coding.",
}
