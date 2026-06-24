"""Application configuration.

Effective settings are computed as: built-in defaults -> environment / .env ->
runtime overrides saved by the Admin portal (config/runtime-config.json).

Clinical data is never persisted locally; only operational configuration is.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Dict

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repository / package roots.
APP_DIR = Path(__file__).resolve().parent
BASE_DIR = APP_DIR.parent
CONFIG_DIR = BASE_DIR / "config"
RUNTIME_CONFIG_PATH = Path(
    os.environ.get("PHEREF_RUNTIME_CONFIG", CONFIG_DIR / "runtime-config.json")
)

# Fields that the Admin portal is allowed to override at runtime.
EDITABLE_FIELDS = {
    "fhir_base_url",
    "terminology_base_url",
    "psa_base_url",
    "psa_version",
    "psoc_version",
    "psa_enable_huc_rules",
    "psa_token",
    "fhir_auth_token",
    "http_timeout",
}

# Fields treated as secrets — masked in API responses.
SECRET_FIELDS = {"psa_token", "fhir_auth_token"}


class Settings(BaseSettings):
    """Base settings sourced from environment variables / .env file."""

    model_config = SettingsConfigDict(
        env_prefix="PHEREF_",
        env_file=os.environ.get("PHEREF_ENV_FILE", str(BASE_DIR / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    fhir_base_url: str = "https://cdr.pheref.fhirlab.net/fhir"
    terminology_base_url: str = "https://tx.fhirlab.net/fhir"
    psa_base_url: str = "https://classification.psa.gov.ph"
    psa_version: str = "Q1_2026"
    psoc_version: str = "2022"
    psa_enable_huc_rules: bool = True
    psa_token: str = ""
    fhir_auth_token: str = ""
    http_timeout: float = 30.0
    host: str = "0.0.0.0"
    port: int = 8000


class EffectiveConfig(BaseModel):
    """The merged configuration used by the running application."""

    fhir_base_url: str
    terminology_base_url: str
    psa_base_url: str
    psa_version: str
    psoc_version: str
    psa_enable_huc_rules: bool
    psa_token: str
    fhir_auth_token: str
    http_timeout: float
    host: str
    port: int

    def public_dict(self) -> Dict[str, Any]:
        """Return config with secrets masked, for display in the UI."""
        data = self.model_dump()
        for field in SECRET_FIELDS:
            data[f"{field}_set"] = bool(data.get(field))
            data[field] = "********" if data.get(field) else ""
        return data


_lock = threading.Lock()
_cache: EffectiveConfig | None = None


def _normalise_base(url: str) -> str:
    return url.rstrip("/") if url else url


def _load_runtime_overrides() -> Dict[str, Any]:
    if RUNTIME_CONFIG_PATH.exists():
        try:
            return json.loads(RUNTIME_CONFIG_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _compute() -> EffectiveConfig:
    base = Settings()
    overrides = _load_runtime_overrides()
    merged = base.model_dump()
    for key, value in overrides.items():
        if key in EDITABLE_FIELDS and value is not None:
            merged[key] = value
    for key in ("fhir_base_url", "terminology_base_url", "psa_base_url"):
        merged[key] = _normalise_base(merged[key])
    return EffectiveConfig(**merged)


def get_config(refresh: bool = False) -> EffectiveConfig:
    """Return the effective configuration (cached)."""
    global _cache
    with _lock:
        if _cache is None or refresh:
            _cache = _compute()
        return _cache


def update_runtime_config(updates: Dict[str, Any]) -> EffectiveConfig:
    """Persist editable overrides and refresh the cached config."""
    overrides = _load_runtime_overrides()
    for key, value in updates.items():
        if key not in EDITABLE_FIELDS:
            continue
        # Keep an existing secret if the caller submits the mask/blank.
        if key in SECRET_FIELDS and (value in ("", "********", None)):
            continue
        overrides[key] = value
    RUNTIME_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME_CONFIG_PATH.write_text(
        json.dumps(overrides, indent=2), encoding="utf-8"
    )
    return get_config(refresh=True)
