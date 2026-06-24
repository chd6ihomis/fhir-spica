"""Philippine Statistics Authority (PSA) PSGC classification API integration.

Implements the PSGC geographic hierarchy used by the PH Core address extensions
(region → province → city/municipality → barangay).

API base: https://classification.psa.gov.ph/psgc/{version}/{level}?token={token}&{filters}

Response shapes vary by level:
  - regions:  {"psgc_data": [...]}
  - others:   {"count": N, "results": {"psgc_data": [...]}}

Filter parameters use *numeric* field values (not full PSGC codes):
  - provinces by region:       ?reg={int(code[0:2])}
  - municipalities by province: ?prv={int(code[2:5])}
  - barangays by municipality:  ?prv={int(code[2:5])}&mun={int(code[5:7])}

HUC (Highly Urbanized Cities) are returned under the provinces level but have
city_class="HUC" and no municipality subdivision. For those:
  - The municipalities endpoint returns a static district list.
  - The barangays endpoint uses ?prv={prv_numeric}&mun=0 (no municipality filter).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .config import EffectiveConfig, get_config
from .fhir_client import FHIRError, _request

PSGC_SYSTEM = "https://psa.gov.ph/classification/psgc"

VALID_LEVELS = {"regions", "provinces", "municipalities", "barangays"}

# Static district table for HUC cities (PSA API has no municipality subdivision).
# prv_numeric key → list of {code, name} virtual municipalities.
HUC_DISTRICTS: Dict[int, List[Dict[str, str]]] = {
    303: [  # City of Baguio
        {"code": f"HUC-303-D{i:02d}", "name": f"District {i}"} for i in range(1, 21)
    ],
    304: [  # City of Calbayog
        {"code": "HUC-304-D01", "name": "Calbayog District"},
        {"code": "HUC-304-D02", "name": "Oquendo District"},
        {"code": "HUC-304-D03", "name": "Tinambac District"},
    ],
    305: [  # Davao City
        {"code": f"HUC-305-{d.replace(' ', '_')}", "name": d} for d in [
            "Agdao", "Baguio District", "Buhangin", "Bunawan",
            "Calinan", "Marilog", "Paquibato", "Poblacion",
            "Talomo", "Toril", "Tugbok",
        ]
    ],
    310: [  # City of Iloilo
        {"code": f"HUC-310-{d.replace(' ', '_')}", "name": d} for d in [
            "Arevalo", "City Proper", "Jaro", "La Paz",
            "Lapuz", "Mandurriao", "Molo",
        ]
    ],
    306: [  # Malaybalay
        {"code": f"HUC-306-{d.replace(' ', '_')}", "name": d} for d in [
            "Basakan", "North Highway", "Poblacion",
            "South Highway", "Upper Pulangi",
        ]
    ],
    # Manila (prv=39) districts 1–16
    39: [  # City of Manila
        {"code": f"HUC-39-{d.replace(' ', '_')}", "name": d} for d in [
            "Binondo", "Ermita", "Intramuros", "Malate", "Paco",
            "Pandacan", "Port Area", "Quiapo", "Sampaloc",
            "San Andres", "San Miguel", "San Nicolas",
            "Santa Ana", "Santa Cruz", "Santa Mesa", "Tondo",
        ]
    ],
    307: [  # Samal
        {"code": "HUC-307-Babak", "name": "Babak"},
        {"code": "HUC-307-Kaputian", "name": "Kaputian"},
        {"code": "HUC-307-Peñaplata", "name": "Peñaplata"},
    ],
    308: [  # Sorsogon City
        {"code": "HUC-308-Bacon", "name": "Bacon"},
        {"code": "HUC-308-Sorsogon", "name": "Sorsogon"},
    ],
    309: [  # Zamboanga City
        {"code": f"HUC-309-{d.replace(' ', '_')}", "name": d} for d in [
            "Ayala", "Baliwasan", "Curuan", "Islands", "Labuan",
            "Manicahan", "Mercedes", "Putik", "Santa Barbara",
            "Santa Maria", "Tetuan", "Vitali", "Zamboanga Central",
        ]
    ],
}


def _psgc_numerics(psgc_code: str) -> Dict[str, int]:
    """Derive numeric filter field values from a 10-digit PSGC code.

    PSGC format: RRPPPMMBBB (R=region 2-digit, P=province 3-digit,
    M=municipality 2-digit, B=barangay 3-digit).
    Filter API uses integer values of those segments.
    """
    code = str(psgc_code).zfill(10)
    return {
        "reg": int(code[0:2]),
        "prv": int(code[2:5]),
        "mun": int(code[5:7]),
        "bgy": int(code[7:10]),
    }


def _build_url(config: EffectiveConfig, level: str, params: Dict[str, Any]) -> str:
    url = f"{config.psa_base_url}/psgc/{config.psa_version}/{level}"
    query: List[str] = []
    if config.psa_token:
        query.append(f"token={config.psa_token}")
    for key, value in params.items():
        query.append(f"{key}={value}")
    if query:
        url = f"{url}?{'&'.join(query)}"
    return url


def _extract_psgc_data(body: Any) -> List[Dict[str, Any]]:
    """Pull the psgc_data list from any PSA API response shape."""
    if not isinstance(body, dict):
        return []
    # Shape 1: {"psgc_data": [...]}
    if "psgc_data" in body:
        return body["psgc_data"] if isinstance(body["psgc_data"], list) else []
    # Shape 2: {"results": {"psgc_data": [...]}}
    results = body.get("results")
    if isinstance(results, dict) and "psgc_data" in results:
        return results["psgc_data"] if isinstance(results["psgc_data"], list) else []
    # Shape 3: {"results": [...]}
    if isinstance(results, list):
        return results
    return []


def _normalise(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Map PSA psgc_data records to {code, name, ...filter fields}."""
    out = []
    for rec in records:
        if not isinstance(rec, dict):
            continue
        code = str(rec.get("psgc_code") or rec.get("code") or "")
        name = str(rec.get("area_name") or rec.get("name") or code).strip()
        entry: Dict[str, Any] = {"code": code, "name": name}
        # Preserve numeric filter fields for downstream use.
        for field in ("reg", "prv", "mun", "bgy"):
            if field in rec:
                entry[field] = rec[field]
        # Preserve city_class for HUC detection.
        if rec.get("city_class"):
            entry["city_class"] = rec["city_class"]
        if rec.get("geographic_level"):
            entry["geographic_level"] = rec["geographic_level"]
        out.append(entry)
    return out


async def list_geography(
    level: str,
    parent: Optional[str] = None,
    config: Optional[EffectiveConfig] = None,
) -> Dict[str, Any]:
    """List PSGC entries for *level*, optionally filtered by parent PSGC code.

    For HUC provinces, municipalities are synthesised from the static district
    table (PSA API does not subdivide HUCs into municipalities).

    Raises ValueError for unknown levels, FHIRError for API failures.
    """
    config = config or get_config()
    if level not in VALID_LEVELS:
        raise ValueError(f"Unknown PSGC level '{level}'. Valid: {sorted(VALID_LEVELS)}")

    # ---- Municipalities for an HUC province → return static districts ----------
    if config.psa_enable_huc_rules and level == "municipalities" and parent:
        nums = _psgc_numerics(parent)
        districts = HUC_DISTRICTS.get(nums["prv"])
        if districts is None:
            # Check whether the API will return results for this province; if the
            # province is not HUC the API handles it normally (falls through below).
            pass
        else:
            return {
                "source": "huc-districts",
                "level": level,
                "system": PSGC_SYSTEM,
                "huc": True,
                "huc_rules_enabled": True,
                "entries": districts,
            }

    # ---- Build API filter params from numeric PSGC segments -------------------
    filter_params: Dict[str, Any] = {}
    if parent:
        if (
            config.psa_enable_huc_rules
            and level == "barangays"
            and isinstance(parent, str)
            and parent.startswith("HUC-")
        ):
            # Parent came from a synthetic HUC district code (e.g. HUC-310-Molo).
            # PSA barangays endpoint for HUCs expects province numeric + mun=0.
            parts = parent.split("-", 2)
            if len(parts) >= 2 and parts[1].isdigit():
                filter_params["prv"] = int(parts[1])
                filter_params["mun"] = 0
            else:
                raise ValueError(f"Invalid HUC district parent code: {parent}")
            nums = None
        else:
            nums = _psgc_numerics(parent)
        if level == "provinces":
            filter_params["reg"] = nums["reg"]
        elif level == "municipalities":
            filter_params["prv"] = nums["prv"]
        elif level == "barangays":
            if nums is not None:
                filter_params["prv"] = nums["prv"]
                # HUC barangays: mun=0; regular municipality: use mun numeric.
                filter_params["mun"] = nums["mun"]

    url = _build_url(config, level, filter_params)
    body = await _request(
        "psa", "GET", url,
        headers={"Accept": "application/json"},
        timeout=config.http_timeout,
    )
    records = _normalise(_extract_psgc_data(body))
    return {
        "source": "server",
        "level": level,
        "system": PSGC_SYSTEM,
        "huc_rules_enabled": bool(config.psa_enable_huc_rules),
        "entries": records,
    }
