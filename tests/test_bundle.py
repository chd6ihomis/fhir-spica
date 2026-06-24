"""Unit tests for the eReferral transaction Bundle builder.

These tests target the IG-aligned 21-entry Bundle (Ana Reyes sample shape).
The fixture uses ``use_defaults=True`` so the full clinical payload is rendered.
"""
import re
import json

import pytest

from app.bundle import build_referral_bundle


@pytest.fixture
def bundle():
    return build_referral_bundle(use_defaults=True)


def test_bundle_is_transaction_with_21_entries(bundle):
    assert bundle["resourceType"] == "Bundle"
    assert bundle["type"] == "transaction"
    assert bundle.get("timestamp")
    assert len(bundle["entry"]) == 21


def test_master_data_uses_conditional_put_by_identifier(bundle):
    master = bundle["entry"][:7]
    types = [e["resource"]["resourceType"] for e in master]
    assert types == [
        "Patient", "Practitioner", "Practitioner",
        "Organization", "Organization",
        "PractitionerRole", "PractitionerRole",
    ]
    for entry in master:
        assert entry["request"]["method"] == "PUT"
        assert "?identifier=" in entry["request"]["url"]


def test_clinical_data_uses_post(bundle):
    for entry in bundle["entry"][7:]:
        assert entry["request"]["method"] == "POST"


def test_every_ig_resource_has_profile(bundle):
    # All IG-profiled resources must carry meta.profile. DiagnosticReport is
    # base FHIR in the IG sample and intentionally has no eReferral profile.
    for entry in bundle["entry"]:
        r = entry["resource"]
        if r["resourceType"] == "DiagnosticReport":
            continue
        profiles = (r.get("meta") or {}).get("profile") or []
        assert profiles, f"{r['resourceType']} missing meta.profile"


def test_patient_has_psgc_address_extensions_with_display(bundle):
    patient = bundle["entry"][0]["resource"]
    ext = patient["address"][0]["extension"]
    slices = {e["url"].rsplit("/", 1)[1] for e in ext}
    assert slices == {"region", "province", "city-municipality", "barangay"}
    # Every PSGC valueCoding must carry display (no silent nulls).
    for e in ext:
        assert e["valueCoding"].get("display")
    assert "city" not in patient["address"][0]
    assert "state" not in patient["address"][0]


def test_patient_identifiers(bundle):
    patient = bundle["entry"][0]["resource"]
    systems = {i["system"] for i in patient["identifier"]}
    assert "http://philsys.gov.ph/fhir/Identifier/philsys-id" in systems
    assert "http://philhealth.gov.ph/fhir/Identifier/philhealth-id" in systems
    assert patient.get("active") is True


def test_practitioner_role_has_prc_identifier(bundle):
    roles = [e["resource"] for e in bundle["entry"]
             if e["resource"]["resourceType"] == "PractitionerRole"]
    assert len(roles) == 2
    for role in roles:
        idents = role.get("identifier") or []
        assert idents and idents[0]["system"] == "https://prc.gov.ph/"
        assert idents[0]["value"]


def test_blood_pressure_components(bundle):
    bp = next(
        e["resource"] for e in bundle["entry"]
        if e["resource"].get("resourceType") == "Observation"
        and e["resource"]["code"]["coding"][0]["code"] == "85354-9"
    )
    # IG sample includes a SNOMED secondary coding alongside LOINC.
    bp_systems = {c["system"] for c in bp["code"]["coding"]}
    assert bp_systems == {"http://loinc.org", "http://snomed.info/sct"}
    sys_coding = [c for c in bp["component"][0]["code"]["coding"]]
    dia_coding = [c for c in bp["component"][1]["code"]["coding"]]
    assert any(c["code"] == "8480-6" for c in sys_coding)
    assert any(c["code"] == "271649006" for c in sys_coding)
    assert any(c["code"] == "8462-4" for c in dia_coding)
    assert any(c["code"] == "271650006" for c in dia_coding)
    assert bp["component"][0]["valueQuantity"]["value"] == 180
    assert bp["component"][1]["valueQuantity"]["value"] == 110


def test_six_vital_observations_including_weight(bundle):
    obs_codes = []
    for e in bundle["entry"]:
        r = e["resource"]
        if r["resourceType"] != "Observation":
            continue
        obs_codes.append(r["code"]["coding"][0]["code"])
    assert sorted(obs_codes) == sorted([
        "85354-9", "8867-4", "9279-1", "2708-6", "8310-5", "29463-7",
    ])


def test_procedure_uses_ig_drug_therapy_code(bundle):
    proc = next(
        e["resource"] for e in bundle["entry"]
        if e["resource"]["resourceType"] == "Procedure"
    )
    assert proc["code"]["coding"][0]["code"] == "416608005"
    assert proc["code"]["coding"][0]["display"] == "Drug therapy"


def test_service_request_links_reason_reference_to_diagnosis(bundle):
    sr = next(e for e in bundle["entry"] if e["resource"]["resourceType"] == "ServiceRequest")
    cond_dx = next(
        e for e in bundle["entry"]
        if e["resource"]["resourceType"] == "Condition"
        and "encounter-diagnosis" in json.dumps(e["resource"].get("category") or [])
    )
    assert sr["resource"]["reasonReference"][0]["reference"] == cond_dx["fullUrl"]


def test_emergency_maps_to_stat_priority(bundle):
    sr = next(e["resource"] for e in bundle["entry"] if e["resource"]["resourceType"] == "ServiceRequest")
    assert sr["priority"] == "stat"


def test_outpatient_maps_to_routine_priority():
    b = build_referral_bundle(
        {"referral_category_code": "440655000", "referral_category_display": "Outpatient"},
        use_defaults=True,
    )
    sr = next(e["resource"] for e in b["entry"] if e["resource"]["resourceType"] == "ServiceRequest")
    assert sr["priority"] == "routine"


def test_task_initial_status_requested(bundle):
    task = next(e["resource"] for e in bundle["entry"] if e["resource"]["resourceType"] == "Task")
    assert task["status"] == "requested"
    assert task["focus"]["reference"].startswith("urn:uuid:")
    assert task["code"]["coding"][0]["code"] == "3457005"


def test_provenance_targets_service_request_and_has_organization(bundle):
    sr_entry = next(e for e in bundle["entry"] if e["resource"]["resourceType"] == "ServiceRequest")
    prov = next(e["resource"] for e in bundle["entry"] if e["resource"]["resourceType"] == "Provenance")
    assert prov["target"][0]["reference"] == sr_entry["fullUrl"]
    assert prov["agent"][0]["onBehalfOf"]["reference"].startswith("urn:uuid:")


def test_intra_bundle_references_resolve(bundle):
    full_urls = {e["fullUrl"] for e in bundle["entry"]}
    text = json.dumps(bundle)
    refs = set(re.findall(r'"reference":\s*"(urn:uuid:[0-9a-f-]+)"', text))
    assert refs
    assert refs.issubset(full_urls)


def test_no_fallback_when_use_defaults_false():
    # Minimal input must yield a minimal bundle (no demo data leakage).
    b = build_referral_bundle({"patient_family": "Cruz"}, use_defaults=False)
    patient = b["entry"][0]["resource"]
    assert patient["name"][0]["family"] == "Cruz"
    # No PhilSys/PhilHealth supplied → no identifier list present.
    assert "identifier" not in patient
    # No vitals provided → no Observation entries.
    rtypes = [e["resource"]["resourceType"] for e in b["entry"]]
    assert "Observation" not in rtypes
    assert "Procedure" not in rtypes
    assert "DiagnosticReport" not in rtypes


def test_form_override_applies():
    b = build_referral_bundle(
        {"patient_family": "Santos", "bp_systolic": 200, "bp_diastolic": 120},
        use_defaults=True,
    )
    patient = b["entry"][0]["resource"]
    assert patient["name"][0]["family"] == "Santos"
    bp = next(
        e["resource"] for e in b["entry"]
        if e["resource"].get("resourceType") == "Observation"
        and e["resource"]["code"]["coding"][0]["code"] == "85354-9"
    )
    assert bp["component"][0]["valueQuantity"]["value"] == 200
    assert bp["component"][1]["valueQuantity"]["value"] == 120
