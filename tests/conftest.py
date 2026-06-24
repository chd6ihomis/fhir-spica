"""Test configuration.

Point external servers at an unroutable host with a short timeout so terminology
and PSA calls fail fast and exercise the curated fallback paths deterministically,
without depending on network access during CI.
"""
import os

os.environ.setdefault("PHEREF_TERMINOLOGY_BASE_URL", "http://127.0.0.1:9/fhir")
os.environ.setdefault("PHEREF_PSA_BASE_URL", "http://127.0.0.1:9")
os.environ.setdefault("PHEREF_FHIR_BASE_URL", "http://127.0.0.1:9/fhir")
os.environ.setdefault("PHEREF_HTTP_TIMEOUT", "2")
