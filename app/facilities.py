"""NHFR facility catalog utilities.

Facilities are loaded from app/nhfr.csv and normalized to the fields needed by
this portal:
- `code` from "Health Facility Code Short"
- `name` from "Facility Name"
- `phone` from "Landline Number"

Both NHFR and HCPN identifiers use the same short facility code value.
"""
from __future__ import annotations

import csv
from pathlib import Path
from threading import Lock
from typing import Dict, List, Optional

APP_DIR = Path(__file__).resolve().parent
NHFR_CSV_PATH = APP_DIR / "nhfr.csv"

_lock = Lock()
_cache: Optional[List[Dict[str, str]]] = None
_index_by_code: Dict[str, Dict[str, str]] = {}


def _clean(value: object) -> str:
    text = str(value or "").strip()
    # Some rows contain placeholders like a single blank character.
    return "" if text == " " else text


def _row_to_facility(row: Dict[str, str]) -> Optional[Dict[str, str]]:
    code = _clean(row.get("Health Facility Code Short"))
    name = _clean(row.get("Facility Name"))
    if not code or not name:
        return None
    phone = _clean(row.get("Landline Number"))

    return {
        "code": code,
        "name": name,
        "phone": phone,
        "nhfr_identifier": code,
        "hcpn_identifier": code,
        "city": _clean(row.get("City/Municipality Name")),
        "province": _clean(row.get("Province Name")),
        "region": _clean(row.get("Region Name")),
    }


def _load_if_needed() -> None:
    global _cache, _index_by_code
    with _lock:
        if _cache is not None:
            return

        facilities: List[Dict[str, str]] = []
        index: Dict[str, Dict[str, str]] = {}
        with NHFR_CSV_PATH.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
            for row in csv.DictReader(handle):
                facility = _row_to_facility(row)
                if not facility:
                    continue
                facilities.append(facility)
                index[facility["code"]] = facility

        facilities.sort(key=lambda item: (item["name"], item["code"]))
        _cache = facilities
        _index_by_code = index


def list_facilities(
    query: str = "",
    limit: int = 100,
    province: str = "",
    city: str = "",
) -> List[Dict[str, str]]:
    _load_if_needed()
    assert _cache is not None

    q = query.strip().lower()
    province_filter = province.strip().lower()
    city_filter = city.strip().lower()
    if not q:
        out_all = [
            item for item in _cache
            if (not province_filter or item.get("province", "").lower() == province_filter)
            and (not city_filter or item.get("city", "").lower() == city_filter)
        ]
        return out_all[:limit]

    out: List[Dict[str, str]] = []
    for item in _cache:
        if province_filter and item.get("province", "").lower() != province_filter:
            continue
        if city_filter and item.get("city", "").lower() != city_filter:
            continue
        haystack = "|".join([
            item["code"],
            item["name"],
            item.get("city", ""),
            item.get("province", ""),
            item.get("region", ""),
        ]).lower()
        if q in haystack:
            out.append(item)
            if len(out) >= limit:
                break
    return out


def get_facility(code: str) -> Optional[Dict[str, str]]:
    _load_if_needed()
    return _index_by_code.get((code or "").strip())


def get_default_referring_facility() -> Optional[Dict[str, str]]:
    """Return the demo referring facility from the eReferral sample profile."""
    # Organization-ExampleERefOrganizationKaliboHC aligns with NHFR short code 3056.
    facility = get_facility("3056")
    if facility:
        return facility

    # Defensive fallback if the demo row is absent.
    candidates = list_facilities("kalibo", limit=20)
    for item in candidates:
        if "RURAL HEALTH UNIT" in item["name"].upper():
            return item
    return candidates[0] if candidates else None
