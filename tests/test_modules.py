"""Tests for the granular module catalogue and module console API.

The module console mirrors the PH eReferral Postman collection: every
transaction-Bundle entry is exposed as an individually inspectable operation.
The full Bundle stays the canonical submission path.
"""
import pytest
from fastapi.testclient import TestClient

from app.bundle import FHIR_FIELD_DOCS, build_modules
from app.main import app

client = TestClient(app)


@pytest.fixture
def modules():
    return build_modules(use_defaults=True)


def test_build_modules_has_21_ordered_modules(modules):
    assert len(modules) == 21
    # First seven are the master resources, in collection order.
    labels = [m["label"] for m in modules[:7]]
    assert labels == [
        "Patient",
        "Practitioner (Sending)",
        "Practitioner (Receiving)",
        "Organization (Sending)",
        "Organization (Receiving)",
        "PractitionerRole (Sending)",
        "PractitionerRole (Receiving)",
    ]


def test_master_modules_are_conditional_put(modules):
    master = [m for m in modules if m["group"] == "master"]
    assert len(master) == 7
    for m in master:
        assert m["method"] == "PUT"
        assert "?identifier=" in m["url"]


def test_clinical_modules_are_post(modules):
    clinical = [m for m in modules if m["group"] == "clinical"]
    assert len(clinical) == 14
    for m in clinical:
        assert m["method"] == "POST"


def test_practitioner_role_references_resolved(modules):
    role = next(m for m in modules if m["key"] == "role_ref")
    # PractitionerRole points at a Practitioner and an Organization.
    assert set(role["references"].values()) == {"prac_ref", "org_ref"}


def test_observation_modules_disambiguated_by_loinc(modules):
    obs_labels = sorted(m["label"] for m in modules if m["key"].startswith("obs_"))
    assert obs_labels == [
        "Observation — Blood Pressure",
        "Observation — Heart Rate",
        "Observation — Oxygen Saturation",
        "Observation — Respiratory Rate",
        "Observation — Temperature",
        "Observation — Weight",
    ]


def test_modules_preview_endpoint_empty_form():
    # No data encoded → only resources with real content render; valueless
    # clinical resources (vitals, conditions, etc.) are omitted, never faked.
    resp = client.post("/api/modules/preview", json={"form": {}})
    assert resp.status_code == 200
    data = resp.json()
    keys = {m["key"] for m in data["modules"]}
    # The 7 master resources plus the always-structural clinical resources.
    assert {"patient", "service_request", "encounter", "task", "provenance"} <= keys
    # No vital-sign observation is invented from an empty form.
    assert not any(m["key"].startswith("obs_") for m in data["modules"])
    patient = next(m for m in data["modules"] if m["key"] == "patient")
    # Empty form must not invent an actual name or birthDate.
    name = (patient["resource"].get("name") or [{}])[0]
    assert "family" not in name and "given" not in name
    assert "birthDate" not in patient["resource"]


def test_field_docs_endpoint_matches_constant():
    resp = client.get("/api/modules/field-docs")
    assert resp.status_code == 200
    assert resp.json() == FHIR_FIELD_DOCS


def test_defaults_refused_when_form_has_real_data():
    # No-fallback rule: defaults may NEVER back-fill partial real input.
    resp = client.post(
        "/api/modules/preview",
        json={"form": {"patient_family": "Reyes"}, "use_defaults": True},
    )
    assert resp.status_code == 400
    assert "empty form" in resp.json()["detail"]["message"].lower()


def test_defaults_allowed_only_for_pure_sample():
    resp = client.post(
        "/api/modules/preview",
        json={"form": {}, "use_defaults": True},
    )
    assert resp.status_code == 200
    patient = next(m for m in resp.json()["modules"] if m["key"] == "patient")
    # Pure sample mode renders the demo Patient name.
    assert patient["resource"]["name"][0]["family"] == "Reyes"


def test_fetch_rejects_clinical_module():
    # Task always renders structurally; fetch is master-only.
    resp = client.post("/api/modules/fetch", json={"key": "task", "form": {}})
    assert resp.status_code == 400


def test_submit_module_requires_key():
    resp = client.post("/api/modules/submit", json={"form": {}})
    assert resp.status_code == 400
