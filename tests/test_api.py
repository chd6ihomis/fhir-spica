"""Tests for OperationOutcome parsing and the app surface."""
from fastapi.testclient import TestClient

from app.main import app
from app.outcome import summarise
from app.routers.api import _condition_summary
from app.routers.api import _observation_summary

client = TestClient(app)


def test_operation_outcome_parsed():
    oo = {
        "resourceType": "OperationOutcome",
        "issue": [
            {"severity": "error", "code": "invalid", "diagnostics": "Bad code",
             "details": {"text": "Code not in value set"}, "expression": ["Patient.gender"]},
            {"severity": "warning", "code": "informational", "details": {"text": "Minor"}},
        ],
    }
    result = summarise(oo)
    assert result["has_errors"] is True
    assert result["counts"]["error"] == 1
    assert result["issues"][0]["severity"] == "error"
    assert result["issues"][0]["location"] == "Patient.gender"


def test_transaction_response_bundle_errors():
    bundle = {
        "resourceType": "Bundle",
        "type": "transaction-response",
        "entry": [
            {"response": {"status": "201 Created"}},
            {"response": {"status": "422 Unprocessable Entity"}},
        ],
    }
    result = summarise(bundle)
    assert result["has_errors"] is True


def test_operation_outcome_tx_timeout_is_mapped_to_friendly_hint():
    oo = {
        "resourceType": "OperationOutcome",
        "issue": [
            {
                "severity": "error",
                "code": "processing",
                "diagnostics": (
                    "HAPI-1361: Failed to parse response from server when performing GET to URL "
                    "https://tx.fhir.org/r4/ValueSet?url=http%3A%2F%2Fhl7.org%2Ffhir%2FValueSet%2Fbundle-type"
                    "&version=4.0.1&_summary=false - java.net.SocketTimeoutException: Read timed out"
                ),
            }
        ],
    }

    result = summarise(oo)
    assert result["has_errors"] is True
    assert "Upstream terminology validation timeout" in result["issues"][0]["details"]


def test_healthz():
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_referral_preview_endpoint():
    # Strict no-fallback mode: minimal form yields a minimal bundle (only the
    # entries whose fields the user actually provided).
    resp = client.post("/api/referral/preview", json={"patient_family": "Cruz"})
    assert resp.status_code == 200
    bundle = resp.json()
    assert bundle["type"] == "transaction"
    assert bundle["entry"][0]["resource"]["resourceType"] == "Patient"
    assert bundle["entry"][0]["resource"]["name"][0]["family"] == "Cruz"
    # Clinical resources are pruned because no vitals/diagnosis were supplied.
    types = [e["resource"]["resourceType"] for e in bundle["entry"]]
    assert "Observation" not in types
    assert "Condition" not in types


def test_referral_preview_full_bundle_with_demo_defaults():
    from app.bundle import build_referral_bundle
    bundle = build_referral_bundle(use_defaults=True)
    assert bundle["type"] == "transaction"
    # IG-aligned Ana Reyes example: 21 entries with profiles on all IG resources.
    assert len(bundle["entry"]) == 21
    rtypes = [e["resource"]["resourceType"] for e in bundle["entry"]]
    assert rtypes.count("Observation") == 6  # BP, HR, RR, SpO2, Temp, Weight
    assert rtypes.count("PractitionerRole") == 2
    # Every PractitionerRole carries a PRC identifier (IG requirement).
    roles = [e["resource"] for e in bundle["entry"] if e["resource"]["resourceType"] == "PractitionerRole"]
    for role in roles:
        idents = role.get("identifier") or []
        assert idents and idents[0]["system"] == "https://prc.gov.ph/"


def test_terminology_expand_fallback():
    # No network in CI: should gracefully fall back to curated concepts.
    resp = client.get("/api/terminology/expand?url=administrative-gender")
    assert resp.status_code == 200
    data = resp.json()
    assert data["concepts"]
    codes = {c["code"] for c in data["concepts"]}
    assert {"male", "female"}.issubset(codes)


def test_facilities_endpoint_returns_fhir_organizations():
    resp = client.get("/api/facilities?q=kalibo&limit=20")
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "fhir"
    assert isinstance(data["facilities"], list)
    if data["facilities"]:
        sample = data["facilities"][0]
        assert "org_id" in sample
        assert "name" in sample
        assert "nhfr_identifier" in sample


def test_default_referring_facility_maps_to_demo_org():
    resp = client.get("/api/facilities/default-referring")
    assert resp.status_code in (200, 404)
    if resp.status_code == 200:
        facility = resp.json()["facility"]
        assert facility["org_id"]
        assert facility["code"] == facility["org_id"]


def test_practitioner_search_short_query_returns_empty_list():
    resp = client.get("/api/practitioners/search?q=a")
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "fhir"
    assert data["practitioners"] == []


def test_facilities_endpoint_supports_province_and_city_filters():
    resp = client.get("/api/facilities?province=AKLAN&city=KALIBO%20(CAPITAL)&limit=200")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data["facilities"], list)
    if data["facilities"]:
        assert all(item["province"] == "AKLAN" for item in data["facilities"])
        assert all(item["city"] == "KALIBO (CAPITAL)" for item in data["facilities"])


def test_duplicate_patient_check_remains_independent_of_facility():
    resp = client.get(
        "/api/patients/check"
        "?system=http%3A%2F%2Fphilsys.gov.ph%2Ffhir%2FIdentifier%2Fphilsys-id"
        "&value=7731-0812-4491-0326"
    )
    assert resp.status_code in (200, 502)


def test_pages_render():
    for path in ["/", "/submit", "/facility-onboarding", "/patients", "/worklist", "/admin", "/debug"]:
        resp = client.get(path)
        assert resp.status_code == 200
        assert "PHeRef" in resp.text


def test_config_roundtrip(tmp_path, monkeypatch):
    cfg = tmp_path / "runtime-config.json"
    monkeypatch.setenv("PHEREF_RUNTIME_CONFIG", str(cfg))
    import importlib
    from app import config as config_module
    importlib.reload(config_module)
    config_module.update_runtime_config({"psa_version": "Q1_2026"})
    assert config_module.get_config(refresh=True).psa_version == "Q1_2026"
    # restore default module state for other tests
    monkeypatch.delenv("PHEREF_RUNTIME_CONFIG", raising=False)
    importlib.reload(config_module)


def test_observation_summary_preserves_numeric_series_fields():
    summary = _observation_summary({
        "id": "obs-1",
        "code": {"coding": [{"system": "http://loinc.org", "code": "29463-7", "display": "Body weight"}]},
        "valueQuantity": {"value": 72, "unit": "kg", "code": "kg"},
        "effectiveDateTime": "2026-06-23T18:13:00+08:00",
    })

    assert summary["display"] == "Body weight"
    assert summary["value"] == "72"
    assert summary["unit"] == "kg"
    assert summary["numericValue"] == 72.0
    assert summary["components"] == []


def test_observation_summary_exposes_component_series():
    summary = _observation_summary({
        "id": "obs-2",
        "code": {"coding": [{
            "system": "http://loinc.org",
            "code": "85354-9",
            "display": "Blood pressure panel with all children optional",
        }]},
        "component": [
            {
                "code": {"coding": [{"system": "http://loinc.org", "code": "8480-6", "display": "Systolic blood pressure"}]},
                "valueQuantity": {"value": 180, "unit": "mmHg", "code": "mm[Hg]"},
            },
            {
                "code": {"coding": [{"system": "http://loinc.org", "code": "8462-4", "display": "Diastolic blood pressure"}]},
                "valueQuantity": {"value": 110, "unit": "mmHg", "code": "mm[Hg]"},
            },
        ],
        "effectiveDateTime": "2026-06-23T23:28:00+08:00",
    })

    assert summary["numericValue"] is None
    assert summary["components"] == [
        {
            "code": "8480-6",
            "system": "http://loinc.org",
            "display": "Systolic blood pressure",
            "value": 180,
            "unit": "mmHg",
        },
        {
            "code": "8462-4",
            "system": "http://loinc.org",
            "display": "Diastolic blood pressure",
            "value": 110,
            "unit": "mmHg",
        },
    ]


def test_condition_summary_prefers_onset_date_for_effective_timeline():
    summary = _condition_summary({
        "id": "cond-1",
        "code": {"coding": [{"system": "http://snomed.info/sct", "code": "398254007", "display": "Pre-eclampsia"}]},
        "clinicalStatus": {"coding": [{"code": "active"}]},
        "recordedDate": "2026-06-23T23:28:00+08:00",
        "onsetDateTime": "2026-06-21T08:30:00+08:00",
    })

    assert summary["recordedDate"] == "2026-06-23T23:28:00+08:00"
    assert summary["effectiveDateTime"] == "2026-06-21T08:30:00+08:00"
    assert summary["effectiveDateSource"] == "onsetDateTime"
    assert summary["effectiveDateText"] == ""


def test_condition_summary_supports_non_datetime_onset_text():
    summary = _condition_summary({
        "id": "cond-2",
        "code": {"coding": [{"system": "http://snomed.info/sct", "code": "25064002", "display": "Headache"}]},
        "clinicalStatus": {"coding": [{"code": "active"}]},
        "onsetString": "Symptoms started about 2 days ago",
    })

    assert summary["effectiveDateTime"] is None
    assert summary["effectiveDateText"] == "Symptoms started about 2 days ago"
    assert summary["effectiveDateSource"] == "onsetString"

