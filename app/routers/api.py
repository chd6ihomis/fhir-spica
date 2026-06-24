"""JSON API endpoints backing the portal UI.

All endpoints proxy to the configured external servers; no clinical data is
persisted by the portal. FHIR errors are surfaced with parsed OperationOutcome
detail so the UI can show actionable feedback.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException, Query

from .. import facilities, logstore, psa, terminology
from ..bundle import DEFAULTS, FHIR_FIELD_DOCS, build_modules, build_referral_bundle
from ..config import get_config, update_runtime_config
from ..fhir_client import FHIRClient, FHIRError
from ..outcome import summarise

router = APIRouter(prefix="/api", tags=["api"])


def _fhir_error(exc: FHIRError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code or 502,
        detail={
            "message": str(exc),
            "status_code": exc.status_code,
            "outcome": summarise(exc.body),
            "body": exc.body,
        },
    )


# --------------------------------------------------------------------------- #
# Configuration (Admin portal)
# --------------------------------------------------------------------------- #
@router.get("/config")
async def read_config() -> Dict[str, Any]:
    return get_config().public_dict()


@router.put("/config")
async def write_config(updates: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    config = update_runtime_config(updates)
    return config.public_dict()


@router.get("/health")
async def health() -> Dict[str, Any]:
    """Portal liveness plus a probe of the FHIR transactional server."""
    config = get_config()
    result: Dict[str, Any] = {"status": "ok", "fhir_base_url": config.fhir_base_url}
    try:
        cap = await FHIRClient(config).capability()
        result["fhir"] = {
            "reachable": True,
            "software": (cap or {}).get("software", {}).get("name"),
            "fhirVersion": (cap or {}).get("fhirVersion"),
        }
    except FHIRError as exc:
        result["fhir"] = {"reachable": False, "error": str(exc)}
    return result


# --------------------------------------------------------------------------- #
# Terminology + PSA dropdown data
# --------------------------------------------------------------------------- #
@router.get("/terminology/expand")
async def expand_valueset(
    url: str = Query(..., description="ValueSet key or canonical URL"),
    filter: Optional[str] = Query(None, description="Optional filter text"),
    count: Optional[int] = Query(None, description="Optional max concepts"),
    strict: bool = Query(False, description="If true, disable fallback and return server errors"),
) -> Dict[str, Any]:
    try:
        return await terminology.expand(url, filter_text=filter, count=count, allow_fallback=not strict)
    except FHIRError as exc:
        raise _fhir_error(exc)


@router.get("/terminology/lookup")
async def lookup_code(system: str, code: str) -> Any:
    try:
        return await terminology.lookup(system, code)
    except FHIRError as exc:
        raise _fhir_error(exc)


@router.get("/terminology/validate-code")
async def validate_code(
    url: str = Query(..., description="ValueSet canonical URL"),
    system: str = Query(..., description="Coding system URL"),
    code: str = Query(..., description="Code to validate"),
    display: Optional[str] = Query(None, description="Optional display"),
) -> Any:
    try:
        return await terminology.validate_code(url, system, code, display)
    except FHIRError as exc:
        raise _fhir_error(exc)


@router.get("/psa/{level}")
async def psa_geography(level: str, parent: Optional[str] = None) -> Dict[str, Any]:
    try:
        return await psa.list_geography(level, parent)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/facilities")
async def list_facilities(
    q: str = "",
    limit: int = 200,
    province: str = "",
    city: str = "",
) -> Dict[str, Any]:
    """Search facilities from FHIR Organization resources."""
    safe_limit = max(1, min(limit, 5000))
    query = (q or "").strip()
    params = [f"_count={safe_limit}"]
    if query:
        params.append(f"name={query}")

    try:
        bundle = await FHIRClient().search("Organization", "&".join(params))
    except FHIRError:
        # Gracefully degrade so the UI can surface no options instead of a hard crash.
        return {"source": "fhir", "facilities": []}

    province_filter = (province or "").strip().lower()
    city_filter = (city or "").strip().lower()
    facilities_out: List[Dict[str, str]] = []
    for entry in bundle.get("entry", []):
        resource = entry.get("resource", {})
        if resource.get("resourceType") != "Organization":
            continue
        mapped = _organization_summary(resource)
        if province_filter and mapped.get("province", "").lower() != province_filter:
            continue
        if city_filter and mapped.get("city", "").lower() != city_filter:
            continue
        facilities_out.append(mapped)

    return {"source": "fhir", "facilities": facilities_out[:safe_limit]}


@router.get("/facilities/default-referring")
async def default_referring_facility() -> Dict[str, Any]:
    client = FHIRClient()
    try:
        org = await client.read("Organization", "ExampleERefOrganizationKaliboHC")
        return {"source": "fhir", "facility": _organization_summary(org)}
    except FHIRError:
        pass

    # Fallback by NHFR identifier 3056 (Kalibo RHU I in sample assets).
    try:
        bundle = await client.search(
            "Organization",
            "identifier=https://fhir.doh.gov.ph/phcore/Identifier/doh-nhfr-code|3056&_count=1",
        )
        for entry in bundle.get("entry", []):
            resource = entry.get("resource", {})
            if resource.get("resourceType") == "Organization":
                return {"source": "fhir", "facility": _organization_summary(resource)}
    except FHIRError:
        pass

    raise HTTPException(status_code=404, detail="No default referring Organization found")


@router.get("/facilities/{organization_id}")
async def facility_by_code(organization_id: str) -> Dict[str, Any]:
    try:
        resource = await FHIRClient().read("Organization", organization_id)
    except FHIRError as exc:
        raise _fhir_error(exc)
    if resource.get("resourceType") != "Organization":
        raise HTTPException(status_code=404, detail=f"Organization {organization_id} not found")
    return {"source": "fhir", "facility": _organization_summary(resource)}


@router.get("/onboarding/nhfr")
async def onboarding_nhfr_prefill(
    q: str = "",
    limit: int = 50,
    province: str = "",
    city: str = "",
) -> Dict[str, Any]:
    safe_limit = max(1, min(limit, 500))
    return {
        "source": "nhfr-csv",
        "facilities": facilities.list_facilities(
            query=q,
            limit=safe_limit,
            province=province,
            city=city,
        ),
    }


@router.post("/onboarding/facility")
async def onboard_facility(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    """Create or update a FHIR Organization; validates duplicates before save."""
    organization_id = str(payload.get("organization_id", "")).strip()
    name = str(payload.get("name", "")).strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")

    nhfr_identifier = str(payload.get("nhfr_identifier", "")).strip()
    hcpn_identifier = str(payload.get("hcpn_identifier", "")).strip()
    phone = str(payload.get("phone", "")).strip()
    city_name = str(payload.get("city", "")).strip()
    province_name = str(payload.get("province", "")).strip()
    address_text = str(payload.get("address_text", "")).strip()
    active = bool(payload.get("active", True))

    identifiers = []
    if nhfr_identifier:
        identifiers.append({
            "system": "https://fhir.doh.gov.ph/phcore/Identifier/doh-nhfr-code",
            "value": nhfr_identifier,
        })
    if hcpn_identifier:
        identifiers.append({
            "system": "https://fhir.doh.gov.ph/phcore/Identifier/hcpn-code",
            "value": hcpn_identifier,
        })

    telecom = []
    if phone:
        telecom.append({"system": "phone", "value": phone, "use": "work"})

    address: Dict[str, Any] = {"country": "PH"}
    if city_name:
        address["city"] = city_name
    if province_name:
        address["district"] = province_name
    if address_text:
        address["text"] = address_text

    resource: Dict[str, Any] = {
        "resourceType": "Organization",
        "id": organization_id,
        "active": active,
        "name": name,
    }
    if identifiers:
        resource["identifier"] = identifiers
    if telecom:
        resource["telecom"] = telecom
    if any(k in address for k in ["city", "district", "text"]):
        resource["address"] = [address]

    duplicates = await _find_duplicate_organizations(
        name=name,
        nhfr_identifier=nhfr_identifier,
        hcpn_identifier=hcpn_identifier,
        exclude_org_id=organization_id or None,
    )
    if duplicates:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Possible duplicate organization detected",
                "duplicates": duplicates,
            },
        )

    try:
        client = FHIRClient()
        if organization_id:
            resource["id"] = organization_id
            saved = await client.update("Organization", organization_id, resource)
        else:
            resource.pop("id", None)
            saved = await client.create("Organization", resource)
    except FHIRError as exc:
        raise _fhir_error(exc)

    return {
        "saved": _organization_summary(saved if isinstance(saved, dict) else resource),
        "resource": saved,
    }


@router.get("/practitioners/search")
async def search_practitioners(q: str = "", limit: int = 20) -> Dict[str, Any]:
    """Search practitioners by name and PRC identifier from the FHIR server."""
    query = (q or "").strip()
    safe_limit = max(1, min(limit, 50))
    if len(query) < 2:
        return {"source": "fhir", "practitioners": []}

    client = FHIRClient()
    responses: List[Dict[str, Any]] = []
    try:
        responses.append(await client.search("Practitioner", f"name={query}&_count={safe_limit}"))
        if query.isdigit():
            responses.append(await client.search(
                "Practitioner", f"identifier=https://prc.gov.ph/|{query}&_count={safe_limit}"
            ))
    except FHIRError as exc:
        raise _fhir_error(exc)

    seen: set[str] = set()
    out: List[Dict[str, str]] = []
    for bundle in responses:
        for entry in bundle.get("entry", []):
            resource = entry.get("resource", {})
            if resource.get("resourceType") != "Practitioner":
                continue
            rid = str(resource.get("id", ""))
            if not rid or rid in seen:
                continue
            seen.add(rid)

            name_obj = (resource.get("name") or [{}])[0]
            family = str(name_obj.get("family", "")).strip()
            given_list = [str(p).strip() for p in (name_obj.get("given") or []) if str(p).strip()]
            given = " ".join(given_list)
            display = " ".join(p for p in [given, family] if p).strip() or rid

            prc_value = ""
            for ident in resource.get("identifier", []):
                if str(ident.get("system", "")).strip() == "https://prc.gov.ph/":
                    prc_value = str(ident.get("value", "")).strip()
                    break

            out.append({
                "id": rid,
                "display": display,
                "family": family,
                "given": given,
                "prc": prc_value,
            })
            if len(out) >= safe_limit:
                break
        if len(out) >= safe_limit:
            break

    return {"source": "fhir", "practitioners": out}


async def _find_practitioner_role(
    client: FHIRClient,
    *,
    prc_value: str,
    practitioner_id: str = "",
    organization_id: str = "",
    role_code: str = "",
) -> Dict[str, str]:
    prc_value = str(prc_value or "").strip()
    practitioner_id = str(practitioner_id or "").strip()
    organization_id = str(organization_id or "").strip()
    role_code = str(role_code or "").strip()
    if not prc_value and not practitioner_id:
        return {}

    bundles: List[Dict[str, Any]] = []
    seen_bundle_keys: set[str] = set()
    queries = []
    if prc_value:
        queries.append(f"identifier=https://prc.gov.ph/|{prc_value}&_count=50")
    if practitioner_id:
        queries.append(f"practitioner=Practitioner/{practitioner_id}&_count=50")

    for query in queries:
        if query in seen_bundle_keys:
            continue
        seen_bundle_keys.add(query)
        try:
            bundles.append(await client.search("PractitionerRole", query))
        except FHIRError:
            continue

    for bundle in bundles:
        for entry in bundle.get("entry", []):
            resource = entry.get("resource", {})
            if resource.get("resourceType") != "PractitionerRole":
                continue
            rid = str(resource.get("id", "") or "")
            if not rid:
                continue
            resource_prac_id = _reference_id(
                (resource.get("practitioner") or {}).get("reference", ""),
                "Practitioner",
            )
            resource_org_id = _reference_id(
                (resource.get("organization") or {}).get("reference", ""),
                "Organization",
            )
            if practitioner_id and resource_prac_id and resource_prac_id != practitioner_id:
                continue
            if organization_id and resource_org_id and resource_org_id != organization_id:
                continue
            codings = []
            for code_obj in resource.get("code") or []:
                codings.extend(code_obj.get("coding") or [])
            matched_coding = codings[0] if codings else {}
            if role_code:
                explicit = next((c for c in codings if str(c.get("code", "")) == role_code), None)
                if not explicit:
                    continue
                matched_coding = explicit
            return {
                "id": rid,
                "code": str(matched_coding.get("code", "") or ""),
                "display": str(matched_coding.get("display", "") or ""),
                "practitioner_id": resource_prac_id,
                "organization_id": resource_org_id,
            }
    return {}


@router.get("/practitioner-roles/resolve")
async def resolve_practitioner_role(
    prc: str,
    organization_nhfr: Optional[str] = None,
    organization_hcpn: Optional[str] = None,
    role_code: Optional[str] = None,
) -> Dict[str, Any]:
    client = FHIRClient()

    async def resolve_org_id() -> str:
        nhfr = str(organization_nhfr or "").strip()
        hcpn = str(organization_hcpn or "").strip()
        if nhfr:
            try:
                bundle = await client.search(
                    "Organization",
                    f"identifier=https://fhir.doh.gov.ph/phcore/Identifier/doh-nhfr-code|{nhfr}&_count=2",
                )
                for entry in bundle.get("entry", []):
                    resource = entry.get("resource", {})
                    if resource.get("resourceType") == "Organization" and resource.get("id"):
                        return str(resource.get("id"))
            except FHIRError:
                pass
        if hcpn:
            try:
                bundle = await client.search(
                    "Organization",
                    f"identifier=https://fhir.doh.gov.ph/phcore/Identifier/hcpn-code|{hcpn}&_count=2",
                )
                for entry in bundle.get("entry", []):
                    resource = entry.get("resource", {})
                    if resource.get("resourceType") == "Organization" and resource.get("id"):
                        return str(resource.get("id"))
            except FHIRError:
                pass
        return ""

    role = await _find_practitioner_role(
        client,
        prc_value=prc,
        organization_id=await resolve_org_id(),
        role_code=role_code or "",
    )
    return {"found": bool(role), "role": role}


# --------------------------------------------------------------------------- #
# Referral submission
# --------------------------------------------------------------------------- #
@router.get("/referral/defaults")
async def referral_defaults() -> Dict[str, Any]:
    return DEFAULTS


@router.post("/referral/preview")
async def preview_bundle(form: Dict[str, Any] = Body(default_factory=dict)) -> Dict[str, Any]:
    """Build (but do not submit) the transaction Bundle for inspection."""
    return build_referral_bundle(form)


@router.post("/referral/submit")
async def submit_referral(form: Dict[str, Any] = Body(default_factory=dict)) -> Dict[str, Any]:
    """Submit the referral transaction Bundle.

    The Bundle builder already issues conditional PUTs
    (``Resource?identifier=...``) for every master resource (Patient,
    Practitioner, Organization, PractitionerRole). HAPI handles upsert
    natively for those: 0 matches → create with a new server id; 1 match →
    update in place; ≥2 matches → ``412 Precondition Failed``.

    Earlier revisions of this endpoint performed an upstream search and
    rewrote each request URL to ``Resource/{server-id}``. That added a second
    failure mode — when the search picked the wrong record (e.g. legacy
    resources missing the IG identifier slice) the bundle would *overwrite*
    an unrelated record. We now trust the conditional PUTs.
    """
    bundle = build_referral_bundle(form)
    try:
        response = await FHIRClient().transaction(bundle)
    except FHIRError as exc:
        raise _fhir_error(exc)
    return {
        "submitted_bundle": bundle,
        "response": response,
        "outcome": summarise(response),
        "created": _extract_created(response),
    }


def _extract_created(response: Any) -> List[Dict[str, str]]:
    created = []
    if isinstance(response, dict) and response.get("resourceType") == "Bundle":
        for entry in response.get("entry", []):
            resp = entry.get("response", {})
            location = resp.get("location") or ""
            if location:
                parts = location.split("/")
                rtype = parts[0] if parts else ""
                rid = parts[1] if len(parts) > 1 else ""
                created.append({"type": rtype, "id": rid, "location": location, "status": str(resp.get("status", ""))})
    return created


# --------------------------------------------------------------------------- #
# Granular modules console (mirrors the PH eReferral Postman collection)
# --------------------------------------------------------------------------- #
def _safe_use_defaults(payload: Dict[str, Any], form: Dict[str, Any]) -> bool:
    """Resolve the opt-in demo flag while enforcing the no-fallback rule.

    Medical data must be exactly what the end-user encoded. ``DEFAULTS`` is a
    *pure* demo dataset, never a fallback for missing fields. We therefore only
    honour ``use_defaults`` when the submitted ``form`` is empty — i.e. the user
    explicitly loaded the sample and entered nothing of their own. If any real
    field is present, defaults are refused so partial input is NEVER silently
    completed with assumed clinical values.
    """
    if not payload.get("use_defaults"):
        return False
    if form:
        raise HTTPException(
            status_code=400,
            detail={
                "message": (
                    "Sample defaults can only be used with an empty form. Real "
                    "patient data must never be back-filled with assumed values — "
                    "clear the form to load the sample, or submit only the data "
                    "you encoded."
                )
            },
        )
    return True


@router.get("/modules/field-docs")
async def module_field_docs() -> Dict[str, str]:
    """Field-path → human description map powering the console hover tooltips."""
    return FHIR_FIELD_DOCS


@router.post("/modules/preview")
async def preview_modules(payload: Dict[str, Any] = Body(default_factory=dict)) -> Dict[str, Any]:
    """Decompose the referral form into individually inspectable modules.

    The full transaction Bundle remains the canonical submission path; these
    modules expose each underlying FHIR operation (method, URL, resource and
    cross-references) so a developer can debug them in isolation.
    """
    form = payload.get("form", {}) or {}
    use_defaults = _safe_use_defaults(payload, form)
    modules = build_modules(form, use_defaults=use_defaults)
    return {"modules": modules, "count": len(modules)}


@router.post("/modules/bundle/preview")
async def preview_module_bundle(payload: Dict[str, Any] = Body(default_factory=dict)) -> Dict[str, Any]:
    """Build the canonical transaction Bundle for the console (supports the
    opt-in Ana Reyes sample via ``use_defaults``)."""
    form = payload.get("form", {}) or {}
    use_defaults = _safe_use_defaults(payload, form)
    return build_referral_bundle(form, use_defaults=use_defaults)


@router.post("/modules/bundle/submit")
async def submit_module_bundle(payload: Dict[str, Any] = Body(default_factory=dict)) -> Dict[str, Any]:
    """Submit the canonical transaction Bundle from the console."""
    form = payload.get("form", {}) or {}
    use_defaults = _safe_use_defaults(payload, form)
    bundle = build_referral_bundle(form, use_defaults=use_defaults)
    try:
        response = await FHIRClient().transaction(bundle)
    except FHIRError as exc:
        raise _fhir_error(exc)
    return {
        "submitted_bundle": bundle,
        "response": response,
        "outcome": summarise(response),
        "created": _extract_created(response),
    }


def _find_module(modules: List[Dict[str, Any]], key: str) -> Optional[Dict[str, Any]]:
    return next((m for m in modules if m.get("key") == key), None)


async def _resolve_reference_url(client: FHIRClient, module: Dict[str, Any]) -> Optional[str]:
    """GET an existing master resource by its conditional identifier query and
    return ``Type/{id}`` if exactly one match exists, else ``None``."""
    url = module.get("url", "")
    if "?" not in url:
        return None
    rtype, query = url.split("?", 1)
    try:
        bundle = await client.search(rtype, query)
    except FHIRError:
        return None
    entries = bundle.get("entry", []) if isinstance(bundle, dict) else []
    if len(entries) == 1:
        rid = entries[0].get("resource", {}).get("id")
        if rid:
            return f"{rtype}/{rid}"
    return None


async def _resolve_module_references(
    client: FHIRClient,
    target: Dict[str, Any],
    modules: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Replace urn:uuid cross-references in a module's resource with real
    ``Type/{id}`` references resolved from the server (master resources only)."""
    references = target.get("references", {})
    if not references:
        return target["resource"]
    resolved: Dict[str, str] = {}
    unresolved: List[str] = []
    for urn, logical_key in references.items():
        ref_module = _find_module(modules, logical_key)
        if not ref_module or ref_module.get("group") != "master":
            unresolved.append(logical_key)
            continue
        real = await _resolve_reference_url(client, ref_module)
        if real:
            resolved[urn] = real
        else:
            unresolved.append(logical_key)
    if unresolved:
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "Cannot resolve all references for an individual submit. "
                    "Clinical resources depend on records created by the full "
                    "Bundle; submit the Bundle (or create those modules first)."
                ),
                "unresolved": sorted(set(unresolved)),
            },
        )

    def rewrite(node: Any) -> Any:
        if isinstance(node, dict):
            ref = node.get("reference")
            new = dict(node)
            if isinstance(ref, str) and ref in resolved:
                new["reference"] = resolved[ref]
            return {k: rewrite(v) for k, v in new.items()}
        if isinstance(node, list):
            return [rewrite(v) for v in node]
        return node

    return rewrite(target["resource"])


@router.post("/modules/fetch")
async def fetch_module(payload: Dict[str, Any] = Body(default_factory=dict)) -> Dict[str, Any]:
    """GET the existing server copy of a master module by its identifier.

    The Postman collection has no GET operations; this is the listing/parsing
    counterpart needed before updating an existing master resource.
    """
    key = payload.get("key")
    if not key:
        raise HTTPException(status_code=400, detail={"message": "Missing module 'key'."})
    form = payload.get("form", {}) or {}
    use_defaults = _safe_use_defaults(payload, form)
    modules = build_modules(form, use_defaults=use_defaults)
    module = _find_module(modules, key)
    if not module:
        raise HTTPException(status_code=404, detail={"message": f"Unknown module '{key}'."})
    url = module.get("url", "")
    if module.get("group") != "master" or "?" not in url:
        raise HTTPException(
            status_code=400,
            detail={"message": "Fetch is only available for master modules with an identifier query."},
        )
    rtype, query = url.split("?", 1)
    try:
        bundle = await FHIRClient().search(rtype, query)
    except FHIRError as exc:
        raise _fhir_error(exc)
    entries = bundle.get("entry", []) if isinstance(bundle, dict) else []
    matches = [e.get("resource", {}) for e in entries]
    return {
        "key": key,
        "query": url,
        "total": bundle.get("total", len(matches)) if isinstance(bundle, dict) else len(matches),
        "matches": matches,
    }


@router.post("/modules/submit")
async def submit_module(payload: Dict[str, Any] = Body(default_factory=dict)) -> Dict[str, Any]:
    """Submit a single module operation (conditional PUT upsert for master
    resources). Clinical resources should be submitted via the Bundle; an
    individual clinical submit is rejected unless all of its references resolve
    to existing server records.
    """
    key = payload.get("key")
    if not key:
        raise HTTPException(status_code=400, detail={"message": "Missing module 'key'."})
    form = payload.get("form", {}) or {}
    use_defaults = _safe_use_defaults(payload, form)
    modules = build_modules(form, use_defaults=use_defaults)
    module = _find_module(modules, key)
    if not module:
        raise HTTPException(status_code=404, detail={"message": f"Unknown module '{key}'."})
    client = FHIRClient()
    resource = await _resolve_module_references(client, module, modules)
    try:
        response = await client.send_module(module["method"], module["url"], resource)
    except FHIRError as exc:
        raise _fhir_error(exc)
    return {
        "key": key,
        "method": module["method"],
        "url": module["url"],
        "sent_resource": resource,
        "response": response,
        "outcome": summarise(response),
    }



# --------------------------------------------------------------------------- #
# Patient masterlist (dedup) + referral worklist
# --------------------------------------------------------------------------- #
@router.get("/patients")
async def list_patients(
    name: Optional[str] = None,
    identifier: Optional[str] = None,
    count: int = 50,
    organization_id: Optional[str] = None,
    facility_code: Optional[str] = None,
) -> Dict[str, Any]:
    params = [f"_count={count}", "_sort=-_lastUpdated"]
    if name:
        params.append(f"name={name}")
    if identifier:
        params.append(f"identifier={identifier}")
    try:
        bundle = await FHIRClient().search("Patient", "&".join(params))
    except FHIRError as exc:
        raise _fhir_error(exc)
    patients = [_patient_summary(e.get("resource", {})) for e in bundle.get("entry", [])]
    org_id = (organization_id or facility_code or "").strip()
    # Build patient_id → referring org map from ServiceRequests.
    patient_org_map: Dict[str, str] = {}
    if org_id:
        try:
            sr_bundle = await FHIRClient().search(
                "ServiceRequest",
                # Chain through PractitionerRole.organization since requester
                # is a PractitionerRole reference (per IG and our bundle).
                f"requester:PractitionerRole.organization=Organization/{org_id}&_count=500",
            )
            allowed_refs: set[str] = set()
            for entry in sr_bundle.get("entry", []):
                resource = entry.get("resource", {})
                if resource.get("resourceType") != "ServiceRequest":
                    continue
                subject_ref = (resource.get("subject") or {}).get("reference", "")
                pt_id = _reference_id(subject_ref, "Patient")
                if pt_id:
                    allowed_refs.add(subject_ref)
                    patient_org_map[pt_id] = org_id
            allowed_ids = {
                _reference_id(ref, "Patient")
                for ref in allowed_refs
                if _reference_id(ref, "Patient")
            }
            patients = [p for p in patients if p.get("id") in allowed_ids]
        except FHIRError:
            patients = []
    else:
        # No org filter — enrich all patients with their referring org where
        # available by pulling SR + the requester PractitionerRole via _include.
        try:
            sr_enrich = await FHIRClient().search(
                "ServiceRequest",
                f"_sort=-_lastUpdated&_count={min(count * 2, 500)}"
                f"&_include=ServiceRequest:requester",
            )
            role_org_map: Dict[str, str] = {}
            for entry in sr_enrich.get("entry", []):
                resource = entry.get("resource", {})
                if resource.get("resourceType") == "PractitionerRole":
                    role_key = f"PractitionerRole/{resource.get('id', '')}"
                    org_ref = (resource.get("organization") or {}).get("reference", "")
                    if org_ref:
                        role_org_map[role_key] = org_ref
            for entry in sr_enrich.get("entry", []):
                resource = entry.get("resource", {})
                if resource.get("resourceType") != "ServiceRequest":
                    continue
                subject_ref = (resource.get("subject") or {}).get("reference", "")
                requester_ref = (resource.get("requester") or {}).get("reference", "")
                pt_id = _reference_id(subject_ref, "Patient")
                # Resolve org through PractitionerRole chain.
                org_ref = role_org_map.get(requester_ref, "")
                req_org_id = _reference_id(org_ref, "Organization")
                if pt_id and req_org_id and pt_id not in patient_org_map:
                    patient_org_map[pt_id] = req_org_id
        except FHIRError:
            pass
    for p in patients:
        ref_org = patient_org_map.get(p.get("id") or "", "")
        p["facility_ref"] = f"Organization/{ref_org}" if ref_org else ""
        p["facility_label"] = ref_org
    return {"total": len(patients), "patients": patients}


@router.get("/patients/check")
async def check_patient(system: str, value: str) -> Dict[str, Any]:
    """Pre-submission duplicate check by identifier (e.g. PhilSys / PhilHealth)."""
    try:
        bundle = await FHIRClient().search("Patient", f"identifier={system}|{value}")
    except FHIRError as exc:
        raise _fhir_error(exc)
    matches = [_patient_summary(e.get("resource", {})) for e in bundle.get("entry", [])]
    return {"exists": bool(matches), "matches": matches}


@router.get("/patients/check-composite")
async def check_patient_composite(
    family: str = None,
    given: str = None,
    birth_date: str = None,
    philsys_id: str = None,
    philhealth_id: str = None,
) -> Dict[str, Any]:
    """Check for existing patient by FHIR identifier search (PhilSys or PhilHealth)."""
    client = FHIRClient()
    matches_found = []

    # Search by PhilSys ID (most unique)
    if philsys_id and str(philsys_id).strip():
        try:
            philsys_id_clean = str(philsys_id).strip()
            bundle = await client.search(
                "Patient",
                f"identifier=http://philsys.gov.ph/fhir/Identifier/philsys-id|{philsys_id_clean}",
            )
            for entry in bundle.get("entry", []):
                resource = entry.get("resource", {})
                if resource.get("resourceType") == "Patient":
                    matches_found.append(_patient_summary(resource))
        except FHIRError:
            pass

    # Search by PhilHealth ID if not found
    if not matches_found and philhealth_id and str(philhealth_id).strip():
        try:
            philhealth_id_clean = str(philhealth_id).strip()
            bundle = await client.search(
                "Patient",
                f"identifier=http://philhealth.gov.ph/fhir/Identifier/philhealth-id|{philhealth_id_clean}",
            )
            for entry in bundle.get("entry", []):
                resource = entry.get("resource", {})
                if resource.get("resourceType") == "Patient":
                    matches_found.append(_patient_summary(resource))
        except FHIRError:
            pass

    return {"exists": bool(matches_found), "matches": matches_found}


@router.get("/patients/{patient_id}")
async def get_patient(patient_id: str) -> Dict[str, Any]:
    """Fetch full Patient resource plus recent Conditions and Observations."""
    client = FHIRClient()
    try:
        patient = await client.read("Patient", patient_id)
        conditions = await client.search("Condition", f"subject=Patient/{patient_id}&_sort=-recorded-date&_count=20")
        observations = await client.search("Observation", f"subject=Patient/{patient_id}&_sort=-date&_count=20")
        tasks = await client.search("Task", f"patient=Patient/{patient_id}&_sort=-authored-on&_count=10")
    except FHIRError as exc:
        raise _fhir_error(exc)
    return {
        "patient": patient,
        "summary": _patient_summary(patient),
        "conditions": [_condition_summary(e.get("resource", {})) for e in conditions.get("entry", [])],
        "observations": [_observation_summary(e.get("resource", {})) for e in observations.get("entry", [])],
        "referrals": [_task_summary(e.get("resource", {})) for e in tasks.get("entry", [])],
    }


def _patient_summary(resource: Dict[str, Any]) -> Dict[str, Any]:
    name = ""
    if resource.get("name"):
        n = resource["name"][0]
        given = " ".join(n.get("given", []))
        family = n.get("family", "")
        name = f"{given} {family}".strip() if given else family
    identifiers = []
    for i in resource.get("identifier", []):
        sys = i.get("system", "")
        val = i.get("value", "")
        # Derive a short display label from the system URL.
        label = _system_label(sys)
        identifiers.append({"system": sys, "label": label, "value": val})
    telecom = []
    for t in resource.get("telecom", []):
        telecom.append({"system": t.get("system"), "value": t.get("value"), "use": t.get("use")})
    addr = ""
    line = ""
    postal = ""
    region_code = ""
    province_code = ""
    city_code = ""
    barangay_code = ""
    region_display = ""
    province_display = ""
    city_display = ""
    barangay_display = ""
    if resource.get("address"):
        a = resource["address"][0]
        line = ", ".join(a.get("line") or [])
        postal = a.get("postalCode", "")
        parts = (a.get("line") or []) + [a.get("city", ""), a.get("state", ""), a.get("postalCode", "")]
        for ext in a.get("extension", []) or []:
            if not isinstance(ext, dict):
                continue
            url = str(ext.get("url", ""))
            val_coding = ext.get("valueCoding") or {}
            code = (val_coding.get("code") or "")
            display = (val_coding.get("display") or "")
            if url.endswith("/region"):
                region_code = code
                region_display = display
            elif url.endswith("/province"):
                province_code = code
                province_display = display
            elif url.endswith("/city-municipality"):
                city_code = code
                city_display = display
            elif url.endswith("/barangay"):
                barangay_code = code
                barangay_display = display
        location_parts = [
            barangay_display or barangay_code,
            city_display or city_code,
            province_display or province_code,
            region_display or region_code,
            postal,
        ]
        location = ", ".join(str(p).strip() for p in location_parts if str(p).strip())
        addr = ", ".join(str(p).strip() for p in [line, location] if str(p).strip())

    contact_relationship = ""
    contact_relationship_display = ""
    contact_relationship_system = ""
    contact_family = ""
    contact_given = ""
    if resource.get("contact"):
        c0 = resource["contact"][0] or {}
        rel = (((c0.get("relationship") or [{}])[0].get("coding") or [{}])[0]) if c0.get("relationship") else {}
        contact_relationship = rel.get("code", "")
        contact_relationship_display = rel.get("display", "")
        contact_relationship_system = rel.get("system", "")
        c_name = c0.get("name") or {}
        contact_family = c_name.get("family", "")
        contact_given = " ".join(c_name.get("given", []) or [])
    return {
        "id": resource.get("id"),
        "name": name,
        "gender": resource.get("gender"),
        "birthDate": resource.get("birthDate"),
        "identifiers": identifiers,
        "telecom": telecom,
        "address": addr,
        "patient_line": line,
        "patient_postal": postal,
        "region_code": region_code,
        "province_code": province_code,
        "city_code": city_code,
        "barangay_code": barangay_code,
        "region_display": region_display,
        "province_display": province_display,
        "city_display": city_display,
        "barangay_display": barangay_display,
        "contact_relationship": contact_relationship,
        "contact_relationship_display": contact_relationship_display,
        "contact_relationship_system": contact_relationship_system,
        "contact_family": contact_family,
        "contact_given": contact_given,
    }


def _system_label(system: str) -> str:
    """Return a short human-readable label for a known identifier system."""
    labels = {
        "https://philsys.gov.ph/identifiers/psn": "PhilSys",
        "https://www.philhealth.gov.ph/identifiers/member": "PhilHealth",
        "https://www.philhealth.gov.ph": "PhilHealth",
        "urn:oid:2.16.840.1.113883.2.49.1.1.1": "PhilSys",
        "http://hapifhir.io/fhir/NamingSystem/mdm-golden-resource-enterprise-id": "MDM",
        "urn:ietf:rfc:3986": "URI",
    }
    if system in labels:
        return labels[system]
    # Extract last path segment for unknown URLs
    return system.rstrip("/").rsplit("/", 1)[-1] if system else "ID"


def _condition_summary(resource: Dict[str, Any]) -> Dict[str, Any]:
    code_obj = resource.get("code") or {}
    coding = (code_obj.get("coding") or [{}])[0]
    effective_dt = None
    effective_text = ""
    effective_source = ""

    onset_period = resource.get("onsetPeriod") or {}
    onset_age = resource.get("onsetAge") or {}
    onset_range = resource.get("onsetRange") or {}
    onset_date_time = resource.get("onsetDateTime")
    recorded_date = resource.get("recordedDate")

    if onset_date_time:
        effective_dt = onset_date_time
        effective_source = "onsetDateTime"
    elif onset_period.get("start"):
        effective_dt = onset_period.get("start")
        effective_source = "onsetPeriod.start"
    elif recorded_date:
        effective_dt = recorded_date
        effective_source = "recordedDate"
    elif resource.get("onsetString"):
        effective_text = resource.get("onsetString", "")
        effective_source = "onsetString"
    elif onset_age.get("value") is not None:
        age_unit = onset_age.get("unit") or onset_age.get("code") or ""
        effective_text = f"Age {onset_age.get('value')} {age_unit}".strip()
        effective_source = "onsetAge"
    elif onset_range:
        low = onset_range.get("low") or {}
        high = onset_range.get("high") or {}
        low_text = f"{low.get('value', '')} {low.get('unit') or low.get('code') or ''}".strip()
        high_text = f"{high.get('value', '')} {high.get('unit') or high.get('code') or ''}".strip()
        if low_text or high_text:
            effective_text = " to ".join(part for part in [low_text, high_text] if part)
            effective_source = "onsetRange"

    return {
        "id": resource.get("id"),
        "code": coding.get("code", ""),
        "system": coding.get("system", ""),
        "display": coding.get("display") or code_obj.get("text", ""),
        "clinicalStatus": ((resource.get("clinicalStatus") or {}).get("coding") or [{}])[0].get("code", ""),
        "recordedDate": recorded_date,
        "onsetDateTime": onset_date_time,
        "effectiveDateTime": effective_dt,
        "effectiveDateText": effective_text,
        "effectiveDateSource": effective_source,
    }


def _observation_summary(resource: Dict[str, Any]) -> Dict[str, Any]:
    code_obj = resource.get("code") or {}
    coding = (code_obj.get("coding") or [{}])[0]
    # Value: quantity, codeableConcept, string, boolean, etc.
    value = ""
    unit = ""
    numeric_value: Optional[float] = None
    components: List[Dict[str, Any]] = []
    if "valueQuantity" in resource:
        vq = resource["valueQuantity"]
        value = str(vq.get("value", ""))
        unit = vq.get("unit") or vq.get("code", "")
        raw_value = vq.get("value")
        if isinstance(raw_value, (int, float)):
            numeric_value = float(raw_value)
    elif "valueCodeableConcept" in resource:
        cc = resource["valueCodeableConcept"]
        c = (cc.get("coding") or [{}])[0]
        value = c.get("display") or cc.get("text", "")
    elif "valueString" in resource:
        value = resource["valueString"]
    elif "component" in resource:
        # e.g. Blood Pressure
        parts = []
        for comp in resource.get("component", []):
            c_code = (comp.get("code", {}).get("coding") or [{}])[0]
            c_val = comp.get("valueQuantity", {})
            comp_value = c_val.get("value")
            comp_unit = c_val.get("unit", "")
            components.append({
                "code": c_code.get("code", ""),
                "system": c_code.get("system", ""),
                "display": c_code.get("display", c_code.get("code", "")),
                "value": comp_value,
                "unit": comp_unit or c_val.get("code", ""),
            })
            parts.append(f"{c_code.get('display', c_code.get('code', ''))}: {c_val.get('value', '')} {c_val.get('unit', '')}")
        value = " / ".join(parts)
    return {
        "id": resource.get("id"),
        "code": coding.get("code", ""),
        "system": coding.get("system", ""),
        "display": coding.get("display") or code_obj.get("text", ""),
        "value": value,
        "unit": unit,
        "numericValue": numeric_value,
        "components": components,
        "effectiveDateTime": resource.get("effectiveDateTime"),
    }


@router.get("/referrals")
async def list_referrals(
    status: Optional[str] = None,
    owner: Optional[str] = None,
    count: int = 50,
    organization_id: Optional[str] = None,
    facility_code: Optional[str] = None,
) -> Dict[str, Any]:
    """Worklist of referrals (Tasks) with resolved patient names."""
    params = [f"_count={count}", "_sort=-authored-on", "_include=Task:patient"]
    if status:
        params.append(f"status={status}")
    if owner:
        params.append(f"owner={owner}")
    org_id = (organization_id or facility_code or "").strip()
    allowed_focus_ids: Optional[set[str]] = None
    if org_id:
        try:
            # Worklist scope: receiving organization is reachable through
            # ServiceRequest.performer -> PractitionerRole.organization.
            sr_bundle = await FHIRClient().search(
                "ServiceRequest",
                f"performer:PractitionerRole.organization=Organization/{org_id}&_count=1000",
            )
            allowed_focus_ids = {
                str(entry.get("resource", {}).get("id", ""))
                for entry in sr_bundle.get("entry", [])
                if entry.get("resource", {}).get("resourceType") == "ServiceRequest"
                and entry.get("resource", {}).get("id")
            }
            if not allowed_focus_ids:
                return {"total": 0, "referrals": []}
        except FHIRError:
            return {"total": 0, "referrals": []}
    try:
        bundle = await FHIRClient().search("Task", "&".join(params))
    except FHIRError as exc:
        raise _fhir_error(exc)
    # Build a patient name lookup from _include'd Patient resources.
    patient_names: Dict[str, str] = {}
    for entry in bundle.get("entry", []):
        resource = entry.get("resource", {})
        if resource.get("resourceType") == "Patient":
            pt = _patient_summary(resource)
            patient_names[f"Patient/{resource['id']}"] = pt["name"]
    referrals = [
        _task_summary(e.get("resource", {}), patient_names)
        for e in bundle.get("entry", [])
        if e.get("resource", {}).get("resourceType") == "Task"
    ]
    if allowed_focus_ids is not None:
        referrals = [
            r for r in referrals
            if _reference_id(r.get("focus") or "", "ServiceRequest") in allowed_focus_ids
        ]
    # Enrich each referral with requester/performer references from ServiceRequest.
    # Because requester/performer are PractitionerRole, we must chain through
    # PractitionerRole.organization to get the facility. _include pulls both
    # PractitionerRoles and their Organizations in one shot so we can resolve
    # facility ids / names without N+1 lookups.
    sr_requester_map: Dict[str, str] = {}  # sr_id -> requester reference (PractitionerRole)
    sr_performer_map: Dict[str, str] = {}  # sr_id -> performer reference (PractitionerRole)
    sr_requester_display_map: Dict[str, str] = {}  # sr_id -> requester practitioner display
    sr_performer_display_map: Dict[str, str] = {}  # sr_id -> performer practitioner display
    role_org_map: Dict[str, str] = {}  # PractitionerRole/{id} -> Organization/{id}
    org_name_map: Dict[str, str] = {}  # Organization/{id} -> name

    sr_params_extra = (
        "&_include=ServiceRequest:requester"
        "&_include=ServiceRequest:performer"
        "&_include:iterate=PractitionerRole:organization"
    )

    try:
        if org_id and allowed_focus_ids is not None:
            sr_enrich = await FHIRClient().search(
                "ServiceRequest",
                f"performer:PractitionerRole.organization=Organization/{org_id}"
                f"&_count=1000{sr_params_extra}",
            )
        else:
            focus_sr_ids = [
                _reference_id(r.get("focus") or "", "ServiceRequest")
                for r in referrals
                if _reference_id(r.get("focus") or "", "ServiceRequest")
            ]
            if focus_sr_ids:
                sr_enrich = await FHIRClient().search(
                    "ServiceRequest",
                    f"_sort=-_lastUpdated&_count={min(len(focus_sr_ids) + 50, 500)}"
                    f"{sr_params_extra}",
                )
            else:
                sr_enrich = {"entry": []}
    except FHIRError:
        sr_enrich = {"entry": []}

    for entry in sr_enrich.get("entry", []):
        resource = entry.get("resource", {})
        rtype = resource.get("resourceType")
        if rtype == "ServiceRequest":
            sr_id = str(resource.get("id", ""))
            if not sr_id:
                continue
            requester_ref = (resource.get("requester") or {}).get("reference", "")
            requester_display = (resource.get("requester") or {}).get("display", "")
            performers = resource.get("performer") or []
            performer_ref = (performers[0].get("reference") or "") if performers else ""
            performer_display = (performers[0].get("display") or "") if performers else ""
            sr_requester_map[sr_id] = requester_ref
            sr_performer_map[sr_id] = performer_ref
            sr_requester_display_map[sr_id] = requester_display
            sr_performer_display_map[sr_id] = performer_display
        elif rtype == "PractitionerRole":
            role_key = f"PractitionerRole/{resource.get('id', '')}"
            org_ref = (resource.get("organization") or {}).get("reference", "")
            if org_ref:
                role_org_map[role_key] = org_ref
        elif rtype == "Organization":
            org_key = f"Organization/{resource.get('id', '')}"
            org_name_map[org_key] = resource.get("name", "") or ""

    for r in referrals:
        focus_sr_id = _reference_id(r.get("focus") or "", "ServiceRequest")
        requester_ref = sr_requester_map.get(focus_sr_id, "")
        performer_ref = sr_performer_map.get(focus_sr_id, "")
        # Resolve facility through PractitionerRole.organization chain.
        requester_org_ref = role_org_map.get(requester_ref, "")
        performer_org_ref = role_org_map.get(performer_ref, "")
        requester_org = _reference_id(requester_org_ref, "Organization")
        performer_org = _reference_id(performer_org_ref, "Organization")
        r["performer_org"] = performer_org
        r["requester_org"] = requester_org
        r["requester_org_name"] = org_name_map.get(requester_org_ref, "")
        r["performer_org_name"] = org_name_map.get(performer_org_ref, "")
        # display from the SR carries the practitioner name (per bundle.py).
        r["requester_display"] = (
            sr_requester_display_map.get(focus_sr_id, "") or r.get("requester_display", "")
        )
        r["owner_display"] = (
            sr_performer_display_map.get(focus_sr_id, "") or r.get("owner_display", "")
        )
    return {"total": len(referrals), "referrals": referrals}


def _task_summary(task: Dict[str, Any], patient_names: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    note = ""
    if task.get("note"):
        note = task["note"][-1].get("text", "")
    for_ref = (task.get("for") or {}).get("reference", "")
    focus_ref = (task.get("focus") or {}).get("reference", "")
    patient_name = (patient_names or {}).get(for_ref, "")
    return {
        "id": task.get("id"),
        "status": task.get("status"),
        "priority": task.get("priority"),
        "focus": focus_ref,
        "for": for_ref,
        "patientName": patient_name,
        "requester": (task.get("requester") or {}).get("reference"),
        "owner": (task.get("owner") or {}).get("reference"),
        "requester_display": (task.get("requester") or {}).get("display", ""),
        "owner_display": (task.get("owner") or {}).get("display", ""),
        "authoredOn": task.get("authoredOn"),
        "lastModified": task.get("lastModified"),
        "note": note,
        # Enriched by list_referrals after SR lookup.
        "performer_org": "",
        "requester_org": "",
    }


@router.get("/referrals/{task_id}")
async def referral_detail(task_id: str) -> Dict[str, Any]:
    """Assemble a full referral view from the Task and its linked resources."""
    client = FHIRClient()
    try:
        task = await client.read("Task", task_id)
        detail: Dict[str, Any] = {"task": task}
        sr_ref = (task.get("focus") or {}).get("reference", "")
        if sr_ref.startswith("ServiceRequest/"):
            sr_id = sr_ref.split("/", 1)[1]
            service_request = await client.read("ServiceRequest", sr_id)
            detail["serviceRequest"] = service_request
        pt_ref = (task.get("for") or {}).get("reference", "")
        if pt_ref.startswith("Patient/"):
            pt_id = pt_ref.split("/", 1)[1]
            pt = await client.read("Patient", pt_id)
            detail["patient"] = pt
            detail["patientSummary"] = _patient_summary(pt)
            cond_bundle = await client.search("Condition", f"subject=Patient/{pt_id}&_sort=-recorded-date&_count=20")
            obs_bundle = await client.search("Observation", f"subject=Patient/{pt_id}&_sort=-date&_count=20")
            detail["conditions"] = [_condition_summary(e.get("resource", {})) for e in cond_bundle.get("entry", [])]
            detail["observations"] = [_observation_summary(e.get("resource", {})) for e in obs_bundle.get("entry", [])]

    except FHIRError as exc:
        raise _fhir_error(exc)
    return detail


@router.post("/referrals/{task_id}/status")
async def update_referral_status(task_id: str, payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    """Transition a Task to a new status via PATCH (PUT fallback)."""
    new_status = payload.get("status")
    note = payload.get("note")
    if not new_status:
        raise HTTPException(status_code=400, detail="`status` is required")
    now = payload.get("lastModified") or _now_iso()
    client = FHIRClient()

    patch_ops = [
        {"op": "replace", "path": "/status", "value": new_status},
        {"op": "replace", "path": "/lastModified", "value": now},
    ]
    try:
        try:
            result = await client.patch("Task", task_id, patch_ops)
            method = "PATCH"
        except FHIRError:
            # Fallback: read-modify-write full resource via PUT.
            task = await client.read("Task", task_id)
            task["status"] = new_status
            task["lastModified"] = now
            if note:
                task.setdefault("note", []).append({"text": note})
            result = await client.update("Task", task_id, task)
            method = "PUT"
    except FHIRError as exc:
        raise _fhir_error(exc)
    return {"method": method, "status": new_status, "task": result, "outcome": summarise(result)}


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


async def _find_duplicate_organizations(
    *,
    name: str,
    nhfr_identifier: str,
    hcpn_identifier: str,
    exclude_org_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    client = FHIRClient()
    candidates: Dict[str, Dict[str, Any]] = {}

    def _collect(bundle: Dict[str, Any]) -> None:
        for entry in bundle.get("entry", []):
            resource = entry.get("resource", {})
            if resource.get("resourceType") != "Organization":
                continue
            rid = str(resource.get("id", "") or "")
            if not rid:
                continue
            candidates[rid] = resource

    searches = []
    if name:
        searches.append(f"name={name}&_count=30")
    if nhfr_identifier:
        searches.append(
            "identifier=https://fhir.doh.gov.ph/phcore/Identifier/doh-nhfr-code|"
            f"{nhfr_identifier}&_count=30"
        )
    if hcpn_identifier:
        searches.append(
            "identifier=https://fhir.doh.gov.ph/phcore/Identifier/hcpn-code|"
            f"{hcpn_identifier}&_count=30"
        )

    for params in searches:
        try:
            _collect(await client.search("Organization", params))
        except FHIRError:
            # Ignore single search failures and keep evaluating whatever we can retrieve.
            continue

    name_norm = " ".join(name.lower().split())
    duplicates: List[Dict[str, Any]] = []
    for rid, org in candidates.items():
        if exclude_org_id and rid == exclude_org_id:
            continue
        org_name = str(org.get("name", "") or "")
        org_name_norm = " ".join(org_name.lower().split())
        org_nhfr = ""
        org_hcpn = ""
        for ident in org.get("identifier") or []:
            system = str(ident.get("system", ""))
            value = str(ident.get("value", "") or "").strip()
            if system.endswith("/doh-nhfr-code") and value:
                org_nhfr = value
            if system.endswith("/hcpn-code") and value:
                org_hcpn = value
        name_match = bool(name_norm and org_name_norm == name_norm)
        nhfr_match = bool(nhfr_identifier and org_nhfr and org_nhfr == nhfr_identifier)
        hcpn_match = bool(hcpn_identifier and org_hcpn and org_hcpn == hcpn_identifier)
        if name_match or nhfr_match or hcpn_match:
            duplicates.append({
                "id": rid,
                "name": org_name,
                "nhfr_identifier": org_nhfr,
                "hcpn_identifier": org_hcpn,
                "match": {
                    "name": name_match,
                    "nhfr": nhfr_match,
                    "hcpn": hcpn_match,
                },
            })
    return duplicates




def _reference_id(reference: str, resource_type: str) -> str:
    """Extract resource id from absolute or relative FHIR reference for a type."""
    ref = str(reference or "").strip()
    marker = f"{resource_type}/"
    idx = ref.find(marker)
    if idx == -1:
        return ""
    tail = ref[idx + len(marker):]
    if not tail:
        return ""
    return tail.split("/", 1)[0].split("?", 1)[0].strip()


def _organization_summary(resource: Dict[str, Any]) -> Dict[str, str]:
    identifiers = resource.get("identifier") or []
    nhfr_identifier = ""
    hcpn_identifier = ""
    for ident in identifiers:
        system = str(ident.get("system", ""))
        value = str(ident.get("value", "") or "").strip()
        if not value:
            continue
        if system.endswith("/doh-nhfr-code") and not nhfr_identifier:
            nhfr_identifier = value
        elif system.endswith("/hcpn-code") and not hcpn_identifier:
            hcpn_identifier = value

    telecom = resource.get("telecom") or []
    phone = ""
    for t in telecom:
        if str(t.get("system", "")) == "phone":
            phone = str(t.get("value", "") or "").strip()
            if phone:
                break

    address = (resource.get("address") or [{}])[0] or {}

    # Address line — FHIR uses line[] (list), not text, for org addresses
    lines = address.get("line") or []
    address_text = str(address.get("text", "") or (lines[0] if lines else "") or "").strip()
    postal = str(address.get("postalCode", "") or "").strip()

    # Extract PSGC extension codes and displays from address.extension[]
    _PSGC_SLICE = {
        "region": ("org_region_code", "org_region_display"),
        "province": ("org_province_code", "org_province_display"),
        "city-municipality": ("org_city_code", "org_city_display"),
        "barangay": ("org_barangay_code", "org_barangay_display"),
    }
    psgc_data: Dict[str, str] = {}
    for ext in (address.get("extension") or []):
        url = str(ext.get("url", ""))
        for slice_name, (code_key, display_key) in _PSGC_SLICE.items():
            if url.endswith(f"/{slice_name}"):
                vc = ext.get("valueCoding") or {}
                if vc.get("code"):
                    psgc_data[code_key] = str(vc["code"])
                if vc.get("display"):
                    psgc_data[display_key] = str(vc["display"])

    org_id = str(resource.get("id", "") or "").strip()
    summary: Dict[str, str] = {
        "org_id": org_id,
        "code": org_id,
        "name": str(resource.get("name", "") or "").strip(),
        "phone": phone,
        "nhfr_identifier": nhfr_identifier,
        "hcpn_identifier": hcpn_identifier or nhfr_identifier,
        "address_text": address_text,
        "postal": postal,
    }
    summary.update(psgc_data)
    return summary


# --------------------------------------------------------------------------- #
# Developer debugging suite
# --------------------------------------------------------------------------- #
@router.get("/logs")
async def list_logs(limit: int = 100) -> Dict[str, Any]:
    return {"entries": logstore.list_entries(limit)}


@router.get("/logs/{entry_id}")
async def get_log(entry_id: int) -> Dict[str, Any]:
    entry = logstore.get_entry(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Log entry not found")
    return entry


@router.delete("/logs")
async def clear_logs() -> Dict[str, str]:
    logstore.clear()
    return {"status": "cleared"}


@router.post("/outcome/parse")
async def parse_outcome(body: Any = Body(...)) -> Dict[str, Any]:
    return summarise(body)
