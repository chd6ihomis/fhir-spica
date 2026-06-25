// Submit eReferral page logic.

const form = document.getElementById('referralForm');

const VS_CONDITION = 'condition-code';
const VS_KIN = 'relatedperson-relationshiptype';
const VS_PRACTITIONER_ROLE = 'practitioner-role';
const CONDITION_CANONICAL = 'http://hl7.org/fhir/ValueSet/condition-code';

const DEFAULT_GEO = {
  region_code: '0600000000',
  province_code: '0600400000',
  city_code: '0600407000',
  barangay_code: '0600407013',
};

const REQUIRED_FIELD_NAMES = [
  'patient_family',
  'patient_given',
  'patient_gender',
  'patient_birthdate',
  'philsys_id',
  'philhealth_id',
  'region_code',
  'province_code',
  'city_code',
  'barangay_code',
  'referring_org_nhfr',
  'referring_prac_family',
  'referring_prac_given',
  'referring_prac_prc',
  'referring_role_code',
  'receiving_org_nhfr',
  'receiving_prac_family',
  'receiving_prac_given',
  'receiving_prac_prc',
  'receiving_role_code',
  'referral_category_code',
  'reason_code',
  'authored_on',
  'time_called',
  'chief_complaint_text',
  'chief_complaint_code',
  'diagnosis_code',
  'working_impression',
];

const REQUIRED_NONSTANDARD_FIELDS = [
  { name: 'contact_relationship', message: 'Next of kin relationship is required.' },
  { name: 'referring_org_nhfr', message: 'Referring facility is required.' },
  { name: 'receiving_org_nhfr', message: 'Receiving facility is required.' },
];

function markRequiredLabels() {
  REQUIRED_FIELD_NAMES.forEach((name) => {
    const el = form.elements[name];
    if (!el) return;
    const wrap = el.closest('div');
    if (!wrap) return;
    const label = wrap.querySelector('label');
    if (label) label.classList.add('field-required-label');
  });
  const kinLabel = document.getElementById('inContactRelationshipQuery')
    ?.closest('div')
    ?.parentElement
    ?.closest('div')
    ?.querySelector('label');
  if (kinLabel) kinLabel.classList.add('field-required-label');
}

function validateRequiredNonstandardFields() {
  for (const item of REQUIRED_NONSTANDARD_FIELDS) {
    const val = String((form.elements[item.name] && form.elements[item.name].value) || '').trim();
    if (!val) return item.message;
  }
  return '';
}

function pad2(n) { return String(n).padStart(2, '0'); }

function isoToLocalDateTimeInput(value) {
  if (!value) return '';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return '';
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}T${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
}

function localDateTimeToIsoOffset(value) {
  if (!value) return value;
  if (/[zZ]$|[+-]\d{2}:\d{2}$/.test(value)) return value;
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  const y = d.getFullYear();
  const m = pad2(d.getMonth() + 1);
  const day = pad2(d.getDate());
  const hh = pad2(d.getHours());
  const mm = pad2(d.getMinutes());
  const offMin = -d.getTimezoneOffset();
  const sign = offMin >= 0 ? '+' : '-';
  const abs = Math.abs(offMin);
  const oh = pad2(Math.floor(abs / 60));
  const om = pad2(abs % 60);
  return `${y}-${m}-${day}T${hh}:${mm}:00${sign}${oh}:${om}`;
}

function formObject() {
  const obj = {};
  new FormData(form).forEach((v, k) => { if (v !== '') obj[k] = v; });
  if (obj.authored_on) obj.authored_on = localDateTimeToIsoOffset(obj.authored_on);
  if (obj.time_called) obj.time_called = localDateTimeToIsoOffset(obj.time_called);

  // Resolve lab mode: merge mode-specific fields into the canonical keys.
  // Only one of the two panels is active; the inactive panel's fields are ignored.
  const labMode = (form.elements.lab_mode && form.elements.lab_mode.value) || 'manual';
  if (labMode === 'manual') {
    // lab_title and lab_text come directly from the manual panel.
    delete obj.lab_title_file;
    delete obj.lab_text_file;
    // lab_attachment must be empty for manual mode.
    delete obj.lab_attachment;
  } else {
    // File mode: promote the file-panel fields into the canonical keys.
    if (obj.lab_title_file) { obj.lab_title = obj.lab_title_file; }
    if (obj.lab_text_file)  { obj.lab_text  = obj.lab_text_file;  }
    delete obj.lab_title_file;
    delete obj.lab_text_file;
    // lab_attachment is already in obj from the hidden field.
  }
  // Remove the mode discriminator — not a FHIR field.
  delete obj.lab_mode;

  try { localStorage.setItem('pheref:lastForm', JSON.stringify(obj)); } catch (e) { /* ignore */ }
  return obj;
}

function setField(name, value) {
  const el = form.elements[name];
  if (!el || value == null) return;
  if (el.type === 'datetime-local') {
    const converted = isoToLocalDateTimeInput(value);
    el.value = converted || '';
  } else if (el.type === 'date' && typeof value === 'string') {
    el.value = value.slice(0, 10);
  } else {
    el.value = value;
  }
}

function selectedOptionDisplay(selectEl) {
  if (!selectEl) return '';
  const opt = selectEl.options[selectEl.selectedIndex];
  if (!opt || !opt.value) return '';
  if (opt.dataset && opt.dataset.display) return String(opt.dataset.display).trim();
  const text = String(opt.textContent || '').trim();
  // PSA options are rendered as "Name (CODE)" — keep only the name.
  return text.replace(/\s+\([^)]+\)\s*$/, '').trim();
}

function syncGeoDisplayFields() {
  const region = document.getElementById('selRegion');
  const province = document.getElementById('selProvince');
  const city = document.getElementById('selCity');
  const barangay = document.getElementById('selBarangay');
  setField('region_display', selectedOptionDisplay(region));
  setField('province_display', selectedOptionDisplay(province));
  setField('city_display', selectedOptionDisplay(city));
  setField('barangay_display', selectedOptionDisplay(barangay));
}

function syncReferralCodingDisplays() {
  setField('referral_category_display', selectedOptionDisplay(form.elements.referral_category_code));
  setField('reason_display', selectedOptionDisplay(form.elements.reason_code));
}

function conceptLabel(c) {
  return `${c.display || c.code} [${c.code}]`;
}

function facilityLabel(facility) {
  return `${facility.name || ''} [${facility.nhfr_identifier || facility.code || facility.org_id || ''}]`;
}

function practitionerLabel(practitioner) {
  return `${practitioner.display || ''}${practitioner.prc ? ` [PRC ${practitioner.prc}]` : ''}`;
}

function setHint(id, message, isError = false) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = message || '';
  el.className = isError ? 'hint issue' : 'hint';
}

function setPrefillStatus(message, isError = false) {
  setHint('prefillStatus', message, isError);
}

function applyKinConcept(c) {
  document.getElementById('inContactRelationshipQuery').value = conceptLabel(c);
  document.getElementById('inContactRelationshipCode').value = c.code || '';
  document.getElementById('inContactRelationshipDisplay').value = c.display || '';
  document.getElementById('inContactRelationshipSystem').value =
    c.system || 'http://terminology.hl7.org/CodeSystem/v3-RoleCode';
  setHint('kinRelationshipHint', `Selected: ${c.display || c.code} (${c.code})`);
}

function applyClinicalConcept(prefix, c) {
  const searchId = prefix === 'chief' ? 'inChiefSearch' : 'inDiagSearch';
  const codeName = prefix === 'chief' ? 'chief_complaint_code' : 'diagnosis_code';
  const displayName = prefix === 'chief' ? 'chief_complaint_display' : 'diagnosis_display';
  const textName = prefix === 'chief' ? 'chief_complaint_text' : 'working_impression';
  const hintId = prefix === 'chief' ? 'chiefSearchHint' : 'diagSearchHint';

  document.getElementById(searchId).value = conceptLabel(c);
  setField(codeName, c.code || '');
  setField(displayName, c.display || '');
  if (!form.elements[textName].value) setField(textName, c.display || '');
  setHint(hintId, `Selected: ${c.display || c.code} (${c.code})`);
}

function applyFacilitySelection(side, facility) {
  if (!facility) return;
  const isRef = side === 'ref';
  const prefix = isRef ? 'referring' : 'receiving';
  const searchInputId = isRef ? 'inRefFacilitySearch' : 'inRecFacilitySearch';
  const hintId = isRef ? 'refFacilityHint' : 'recFacilityHint';

  setField(`${prefix}_org_name`, facility.name || '');
  setField(`${prefix}_org_nhfr`, facility.nhfr_identifier || facility.code || '');
  setField(`${prefix}_org_hcpn`, facility.hcpn_identifier || facility.nhfr_identifier || facility.code || '');
  setField(`${prefix}_org_phone`, facility.phone || '');

  // Address fields
  setField(`${prefix}_org_address_text`, facility.address_text || '');
  setField(`${prefix}_org_postal`, facility.postal || '');

  // PSGC extension fields
  setField(`${prefix}_org_region_code`,    facility.org_region_code    || '');
  setField(`${prefix}_org_region_display`, facility.org_region_display || '');
  setField(`${prefix}_org_province_code`,    facility.org_province_code    || '');
  setField(`${prefix}_org_province_display`, facility.org_province_display || '');
  setField(`${prefix}_org_city_code`,    facility.org_city_code    || '');
  setField(`${prefix}_org_city_display`, facility.org_city_display || '');
  setField(`${prefix}_org_barangay_code`,    facility.org_barangay_code    || '');
  setField(`${prefix}_org_barangay_display`, facility.org_barangay_display || '');

  const searchEl = document.getElementById(searchInputId);
  if (searchEl) searchEl.value = facilityLabel(facility);
  setHint(hintId, `Selected: ${facility.name || facility.code} (${facility.nhfr_identifier || facility.code || ''})`);
  void autoResolvePractitionerRole(side);
}

function applyPractitionerSelection(side, practitioner) {
  if (!practitioner) return;
  const isRef = side === 'ref';
  const prefix = isRef ? 'referring' : 'receiving';
  const hintId = isRef ? 'refPractitionerHint' : 'recPractitionerHint';

  setField(`${prefix}_prac_family`, practitioner.family || '');
  setField(`${prefix}_prac_given`, practitioner.given || '');
  setField(`${prefix}_prac_prc`, practitioner.prc || '');
  setHint(hintId, `Selected: ${practitioner.display || practitioner.id || ''}`);

  // Auto-apply role if the practitioner search result already includes role info
  if (practitioner.role_code || practitioner.role_display) {
    applyRoleSelection(side, {
      code: practitioner.role_code || '',
      display: practitioner.role_display || '',
    });
  }
  void autoResolvePractitionerRole(side);
}

function applyRoleSelection(side, concept) {
  if (!concept) return;
  const isRef = side === 'ref';
  const codeSelectId = isRef ? 'inRefRoleCode' : 'inRecRoleCode';
  const displayId = isRef ? 'inRefRoleDisplay' : 'inRecRoleDisplay';
  const hintId = isRef ? 'refRoleHint' : 'recRoleHint';

  const selectEl = document.getElementById(codeSelectId);
  if (selectEl && concept.code && !selectEl.querySelector(`option[value="${concept.code}"]`)) {
    const opt = document.createElement('option');
    opt.value = concept.code;
    opt.textContent = conceptLabel(concept);
    opt.dataset.display = concept.display || '';
    selectEl.appendChild(opt);
  }
  if (selectEl) selectEl.value = concept.code || '';
  document.getElementById(displayId).value = concept.display || '';
  setHint(hintId, `Selected: ${concept.display || concept.code} (${concept.code || ''})`);
}

async function autoResolvePractitionerRole(side) {
  const isRef = side === 'ref';
  const prefix = isRef ? 'referring' : 'receiving';
  const prc = String((form.elements[`${prefix}_prac_prc`] && form.elements[`${prefix}_prac_prc`].value) || '').trim();
  const orgNhfr = String((form.elements[`${prefix}_org_nhfr`] && form.elements[`${prefix}_org_nhfr`].value) || '').trim();
  const orgHcpn = String((form.elements[`${prefix}_org_hcpn`] && form.elements[`${prefix}_org_hcpn`].value) || '').trim();
  if (!prc || (!orgNhfr && !orgHcpn)) return;
  try {
    const qp = [
      `prc=${encodeURIComponent(prc)}`,
      `organization_nhfr=${encodeURIComponent(orgNhfr)}`,
      `organization_hcpn=${encodeURIComponent(orgHcpn)}`,
    ];
    const currentRole = String((form.elements[`${prefix}_role_code`] && form.elements[`${prefix}_role_code`].value) || '').trim();
    if (currentRole) qp.push(`role_code=${encodeURIComponent(currentRole)}`);
    const data = await API.get(`/api/practitioner-roles/resolve?${qp.join('&')}`);
    if (data && data.found && data.role) {
      applyRoleSelection(side, data.role);
    }
  } catch (_e) {
    // Do not block form use if role auto-resolution is unavailable.
  }
}

function clearResultCards() {
  document.getElementById('previewCard').style.display = 'none';
  document.getElementById('resultCard').style.display = 'none';
  document.getElementById('previewJson').textContent = '';
  document.getElementById('resultJson').textContent = '';
  document.getElementById('createdList').innerHTML = '';
  document.getElementById('resultIssues').innerHTML = '';
}

async function loadGeo(level, parent, selectEl, selected) {
  if (!selectEl) return;
  const url = '/api/psa/' + level + (parent ? '?parent=' + encodeURIComponent(parent) : '');
  const data = await API.get(url);
  selectEl.innerHTML = '<option value="">- select -</option>';
  data.entries.forEach((e) => {
    const opt = document.createElement('option');
    opt.value = e.code;
    opt.textContent = `${e.name} (${e.code})`;
    selectEl.appendChild(opt);
  });
  if (selected) selectEl.value = selected;
  const tag = document.querySelector('#selRegion').closest('.field-row').querySelector('.source-tag');
  if (tag && level === 'regions') { tag.textContent = data.source; tag.className = 'source-tag ' + data.source; }
}

async function initTerminology() {
  await Promise.all([
    fillValueSet(form.elements.patient_gender, 'administrative-gender'),
    fillValueSet(form.elements.referral_category_code, 'referral-category'),
    fillValueSet(form.elements.reason_code, 'reason-for-referral'),
  ]);

  // Keep first-load UX blank; user can intentionally pick values or load defaults.
  [
    [form.elements.patient_gender, '- select sex -'],
    [form.elements.referral_category_code, '- select category -'],
    [form.elements.reason_code, '- select reason -'],
  ].forEach(([selectEl, label]) => {
    if (!selectEl) return;
    if (!selectEl.querySelector('option[value=""]')) {
      const opt = document.createElement('option');
      opt.value = '';
      opt.textContent = label;
      selectEl.insertBefore(opt, selectEl.firstChild);
    }
    selectEl.value = '';
  });
  form.elements.referral_category_code.addEventListener('change', syncReferralCodingDisplays);
  form.elements.reason_code.addEventListener('change', syncReferralCodingDisplays);
  syncReferralCodingDisplays();
}

async function initGeo(prefill = null) {
  const region = document.getElementById('selRegion');
  const province = document.getElementById('selProvince');
  const city = document.getElementById('selCity');
  const barangay = document.getElementById('selBarangay');

  region.addEventListener('change', async () => {
    await loadGeo('provinces', region.value, province);
    city.innerHTML = '';
    barangay.innerHTML = '';
    setField('city_display', '');
    setField('barangay_display', '');
    syncGeoDisplayFields();
  });
  province.addEventListener('change', async () => {
    await loadGeo('municipalities', province.value, city);
    barangay.innerHTML = '';
    setField('barangay_display', '');
    syncGeoDisplayFields();
  });
  city.addEventListener('change', async () => {
    await loadGeo('barangays', city.value, barangay);
    syncGeoDisplayFields();
  });
  barangay.addEventListener('change', syncGeoDisplayFields);

  const geo = { ...DEFAULT_GEO, ...(prefill || {}) };
  await loadGeo('regions', null, region, geo.region_code);
  if (geo.region_code) await loadGeo('provinces', geo.region_code, province, geo.province_code);
  if (geo.province_code) await loadGeo('municipalities', geo.province_code, city, geo.city_code);
  if (geo.city_code) await loadGeo('barangays', geo.city_code, barangay, geo.barangay_code);
  syncGeoDisplayFields();
}

async function loadDefaults() {
  const d = await API.get('/api/referral/defaults');
  Object.entries(d).forEach(([k, v]) => setField(k, v));
  if (d.contact_relationship && d.contact_relationship_display) {
    document.getElementById('inContactRelationshipQuery').value =
      `${d.contact_relationship_display} [${d.contact_relationship}]`;
  }
  syncReferralCodingDisplays();
  syncGeoDisplayFields();
}

function currentTopbarFacility() {
  return window.PHEREF && typeof window.PHEREF.getSelectedFacility === 'function'
    ? window.PHEREF.getSelectedFacility()
    : null;
}

function syncReferringFacilityFromTopbar() {
  const facility = currentTopbarFacility();
  if (!facility) return;
  applyFacilitySelection('ref', facility);
  setPrefillStatus(`Referring facility set to ${facility.name} (${facility.code}).`);
}

function syncReceivingFacilityFromTopbar() {
  const facility = currentTopbarFacility();
  if (!facility) return;
  applyFacilitySelection('rec', facility);
}

function updateTopbarSelectionByCode(code) {
  const select = document.getElementById('topbarFacilitySelect');
  if (!select || !code || !select.querySelector(`option[value="${code}"]`)) return;
  select.value = code;
  select.dispatchEvent(new Event('change'));
}

function topbarOrganizationId() {
  const facility = currentTopbarFacility();
  return facility ? (facility.org_id || facility.code || '') : '';
}

const termModal = {
  target: null,
  mode: 'valueset',
  valueSet: null,
  strict: true,
};

function openTermModal({ title, target, mode = 'valueset', valueSet = null, strict = true, presetQuery = '' }) {
  termModal.target = target;
  termModal.mode = mode;
  termModal.valueSet = valueSet;
  termModal.strict = !!strict;
  document.getElementById('termModalTitle').textContent = title;
  document.getElementById('termModalQuery').value = presetQuery || '';
  document.getElementById('termModalResults').innerHTML = '<tr><td colspan="4" class="muted">No results yet.</td></tr>';
  document.getElementById('termModalStatus').textContent = 'Type search text then click Search.';
  document.getElementById('termModal').style.display = 'flex';
}

function closeTermModal() {
  document.getElementById('termModal').style.display = 'none';
}

function pickFromModal(target, item) {
  if (target === 'kin') applyKinConcept(item);
  if (target === 'chief') applyClinicalConcept('chief', item);
  if (target === 'diag') applyClinicalConcept('diag', item);
  if (target === 'refRole') applyRoleSelection('ref', item);
  if (target === 'recRole') applyRoleSelection('rec', item);
  if (target === 'refFacility') {
    applyFacilitySelection('ref', item);
    updateTopbarSelectionByCode(item.org_id || item.code || '');
  }
  if (target === 'recFacility') applyFacilitySelection('rec', item);
  if (target === 'refPractitioner') applyPractitionerSelection('ref', item);
  if (target === 'recPractitioner') applyPractitionerSelection('rec', item);
}

async function runTermModalSearch() {
  const query = document.getElementById('termModalQuery').value.trim();
  const tbody = document.getElementById('termModalResults');
  tbody.innerHTML = '<tr><td colspan="4" class="muted">Searching...</td></tr>';

  if ((termModal.mode === 'valueset' || termModal.mode === 'practitioners') && query.length < 2) {
    document.getElementById('termModalStatus').textContent = 'Enter at least 2 characters.';
    return;
  }

  try {
    let source = '';
    let items = [];
    if (termModal.mode === 'valueset') {
      const data = await searchValueSet(termModal.valueSet, query, 30, { strict: termModal.strict });
      source = data.source;
      items = (data.concepts || []).map((c) => ({ ...c }));
    } else if (termModal.mode === 'facilities') {
      const filters = (window.PHEREF && typeof window.PHEREF.getFacilityFilters === 'function')
        ? window.PHEREF.getFacilityFilters()
        : { province: '', city: '' };
      const qp = [
        `q=${encodeURIComponent(query)}`,
        'limit=30',
      ];
      if (filters.province) qp.push(`province=${encodeURIComponent(filters.province)}`);
      if (filters.city) qp.push(`city=${encodeURIComponent(filters.city)}`);
      const data = await API.get(`/api/facilities?${qp.join('&')}`);
      source = data.source || 'nhfr-csv';
      items = (data.facilities || []).map((f) => ({
        display: f.name,
        code: f.org_id || f.code,
        system: 'FHIR Organization',
        ...f,
      }));
    } else if (termModal.mode === 'practitioners') {
      const data = await API.get(`/api/practitioners/search?q=${encodeURIComponent(query)}&limit=30`);
      source = data.source || 'fhir';
      items = (data.practitioners || []).map((p) => ({
        display: p.display,
        code: p.prc || p.id,
        system: 'Practitioner',
        ...p,
      }));
    }

    document.getElementById('termModalStatus').textContent = `${items.length} result(s) from ${source}`;
    if (!items.length) {
      tbody.innerHTML = '<tr><td colspan="4" class="muted">No matching results.</td></tr>';
      return;
    }

    if (termModal.mode === 'facilities') {
      tbody.innerHTML = items.map((c) => {
        const addrParts = [c.address_text, c.barangay, c.city, c.province, c.region, c.postal].filter(Boolean);
        const addr = addrParts.join(', ');
        return `<tr>
          <td>${escapeHtml(c.display || c.name || '')}</td>
          <td>${escapeHtml(c.nhfr_identifier || c.code || '')}</td>
          <td class="muted" style="font-size:12px">${escapeHtml(addr)}</td>
          <td><button type="button" class="btn-secondary btn-sm select-concept"
            data-item="${encodeURIComponent(JSON.stringify(c))}">Select</button></td>
        </tr>`;
      }).join('');
    } else if (termModal.mode === 'practitioners') {
      tbody.innerHTML = items.map((c) => `
        <tr>
          <td>${escapeHtml(c.display || '')}</td>
          <td>${escapeHtml(c.prc ? 'PRC ' + c.prc : '')}</td>
          <td class="muted">${escapeHtml(c.role_display || c.role_code || '—')}</td>
          <td><button type="button" class="btn-secondary btn-sm select-concept"
            data-item="${encodeURIComponent(JSON.stringify(c))}">Select</button></td>
        </tr>`).join('');
    } else {
      tbody.innerHTML = items.map((c) => `
        <tr>
          <td>${escapeHtml(c.display || c.name || '')}</td>
          <td>${escapeHtml(c.code || '')}</td>
          <td class="muted">${escapeHtml(c.system || '')}</td>
          <td><button type="button" class="btn-secondary btn-sm select-concept"
            data-item="${encodeURIComponent(JSON.stringify(c))}">Select</button></td>
        </tr>`).join('');
    }

    tbody.querySelectorAll('.select-concept').forEach((btn) => {
      btn.addEventListener('click', () => {
        const item = JSON.parse(decodeURIComponent(btn.dataset.item || '{}'));
        pickFromModal(termModal.target, item);
        closeTermModal();
      });
    });
  } catch (e) {
    document.getElementById('termModalStatus').textContent = fhirErrorMessage(e);
    tbody.innerHTML = '<tr><td colspan="4" class="issue">Search failed.</td></tr>';
  }
}

async function initKinRelationship() {
  const tag = document.getElementById('kinSourceTag');
  try {
    const data = await searchValueSet(VS_KIN, 'spouse', 1, { strict: true });
    tag.textContent = data.source;
    tag.className = 'source-tag ' + data.source;
  } catch (e) {
    tag.textContent = 'error';
    tag.className = 'source-tag';
    setHint('kinRelationshipHint', fhirErrorMessage(e), true);
  }
}

async function initPractitionerRoles() {
  const refTag = document.getElementById('refRoleSourceTag');
  const recTag = document.getElementById('recRoleSourceTag');
  const refSelect = document.getElementById('inRefRoleCode');
  const recSelect = document.getElementById('inRecRoleCode');

  function bindRoleSelect(selectEl, displayInputId, hintId) {
    if (!selectEl) return;
    selectEl.addEventListener('change', () => {
      const option = selectEl.options[selectEl.selectedIndex];
      const display = option ? (option.dataset.display || option.textContent || '') : '';
      document.getElementById(displayInputId).value = display;
      if (!selectEl.value) {
        setHint(hintId, '');
      } else {
        setHint(hintId, `Selected: ${display || selectEl.value} (${selectEl.value})`);
      }
    });
  }

  function initSelect(selectEl, placeholder) {
    if (!selectEl) return;
    selectEl.innerHTML = '';
    const opt = document.createElement('option');
    opt.value = '';
    opt.textContent = placeholder;
    selectEl.appendChild(opt);
  }

  initSelect(refSelect, '- select referring role -');
  initSelect(recSelect, '- select receiving role -');
  bindRoleSelect(refSelect, 'inRefRoleDisplay', 'refRoleHint');
  bindRoleSelect(recSelect, 'inRecRoleDisplay', 'recRoleHint');

  try {
    const data = await searchValueSet(VS_PRACTITIONER_ROLE, '', 30, { strict: true });
    (data.concepts || []).forEach((concept) => {
      [refSelect, recSelect].forEach((selectEl) => {
        if (!selectEl) return;
        const opt = document.createElement('option');
        opt.value = concept.code || '';
        opt.textContent = conceptLabel(concept);
        opt.dataset.display = concept.display || '';
        selectEl.appendChild(opt);
      });
    });
    refTag.textContent = data.source;
    recTag.textContent = data.source;
    refTag.className = 'source-tag ' + data.source;
    recTag.className = 'source-tag ' + data.source;
  } catch (e) {
    refTag.textContent = 'error';
    recTag.textContent = 'error';
    setHint('refRoleHint', fhirErrorMessage(e), true);
    setHint('recRoleHint', fhirErrorMessage(e), true);
  }
}

function wireCodeValidation(prefix) {
  const codeEl = document.getElementById(prefix === 'chief' ? 'inChiefCode' : 'inDiagCode');
  const displayEl = document.getElementById(prefix === 'chief' ? 'inChiefDisplay' : 'inDiagDisplay');
  const resultEl = document.getElementById(prefix === 'chief' ? 'resChiefCode' : 'resDiagCode');
  if (!codeEl || !resultEl) return;

  wireSnomedInput(codeEl, resultEl, { valueSetUrl: CONDITION_CANONICAL });

  let timer;
  codeEl.addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      await snomedLookup(codeEl.value, ({ valid, display }) => {
        if (valid && display && displayEl && !displayEl.value.trim()) displayEl.value = display;
      });
    }, 650);
  });
}

async function resetSubmitFormCompletely() {
  form.reset();
  form.querySelectorAll('input, textarea, select').forEach((el) => {
    if (el.type === 'submit' || el.type === 'button') return;
    if (el.tagName === 'SELECT') {
      el.value = '';
    } else if (el.type !== 'hidden') {
      el.value = '';
    }
  });

  document.getElementById('inContactRelationshipQuery').value = '';
  document.getElementById('inChiefSearch').value = '';
  document.getElementById('inDiagSearch').value = '';
  setHint('kinRelationshipHint', '');
  setHint('chiefSearchHint', '');
  setHint('diagSearchHint', '');
  setHint('refFacilityHint', '');
  setHint('recFacilityHint', '');
  setHint('refPractitionerHint', '');
  setHint('recPractitionerHint', '');
  setHint('refRoleHint', '');
  setHint('recRoleHint', '');
  setHint('prefillStatus', '');
  document.getElementById('dedupResult').innerHTML = '';
  document.getElementById('resChiefCode').innerHTML = '';
  document.getElementById('resDiagCode').innerHTML = '';
  // Clear lab fields for both modes.
  const labFile = document.getElementById('inLabFile');
  if (labFile) labFile.value = '';
  const labAttach = document.getElementById('inLabAttachment');
  if (labAttach) labAttach.value = '';
  const labHint = document.getElementById('labFileHint');
  if (labHint) { labHint.textContent = ''; labHint.className = 'hint'; }
  const labTitleFile = document.getElementById('inLabTitleFile');
  if (labTitleFile) labTitleFile.value = '';
  const labTextFile = document.getElementById('inLabTextFile');
  if (labTextFile) labTextFile.value = '';
  // Reset to manual entry mode.
  const manualRadio = form.elements.lab_mode;
  if (manualRadio) { manualRadio.value = 'manual'; _applyLabMode('manual'); }
  clearResultCards();

  setPrefillStatus('Form reset. All values are blank.');
  toast('Form reset to blank', 'ok');
}

function applyPatientPrefill(detail) {
  const p = detail.summary || {};
  const raw = detail.patient || {};

  if (raw.name && raw.name[0]) {
    setField('patient_family', raw.name[0].family || '');
    setField('patient_given', (raw.name[0].given || []).join(' '));
  } else if (p.name) {
    const parts = p.name.trim().split(' ');
    setField('patient_family', parts.pop() || '');
    setField('patient_given', parts.join(' '));
  }

  setField('patient_birthdate', p.birthDate || '');
  if (p.gender) setField('patient_gender', p.gender);
  setField('patient_line', p.patient_line || '');
  setField('patient_postal', p.patient_postal || '');

  // Phone from raw FHIR telecom
  if (raw.telecom) {
    const phone = raw.telecom.find((t) => t.system === 'phone');
    if (phone && phone.value) setField('patient_phone', phone.value);
  }

  const philsys = (p.identifiers || []).find((i) => /philsys/i.test(i.system || '') || /philsys/i.test(i.label || ''));
  if (philsys) setField('philsys_id', philsys.value);
  const philhealth = (p.identifiers || []).find((i) => /philhealth/i.test(i.system || '') || /philhealth/i.test(i.label || ''));
  if (philhealth) setField('philhealth_id', philhealth.value);

  if (p.contact_relationship) {
    applyKinConcept({
      code: p.contact_relationship,
      display: p.contact_relationship_display || p.contact_relationship,
      system: p.contact_relationship_system || 'http://terminology.hl7.org/CodeSystem/v3-RoleCode',
    });
  }
  setField('contact_family', p.contact_family || '');
  setField('contact_given', p.contact_given || '');

  const conds = detail.conditions || [];
  if (conds.length) {
    const chief = conds[0];
    applyClinicalConcept('chief', chief);
    if (!form.elements.chief_complaint_text.value) {
      setField('chief_complaint_text', chief.display || chief.code || '');
    }
    // Pre-fill clinical history from Condition.note
    const clinicalNotes = conds
      .map((c) => c.note || '')
      .filter(Boolean);
    if (clinicalNotes.length && form.elements.clinical_history && !form.elements.clinical_history.value) {
      setField('clinical_history', clinicalNotes.join(' / '));
    }
    const dx = conds.find((c) => c.code && c.code !== chief.code) || conds[0];
    applyClinicalConcept('diag', dx);
  }

  // Pre-fill vitals from most recent observations
  const obs = detail.observations || [];
  const VITAL_LOINC_MAP = {
    '8480-6': 'bp_systolic', '271649006': 'bp_systolic',
    '8462-4': 'bp_diastolic', '271650006': 'bp_diastolic',
    '8867-4': 'heart_rate', '78564009': 'heart_rate',
    '9279-1': 'resp_rate', '86290005': 'resp_rate',
    '2708-6': 'spo2', '103228002': 'spo2', '59408-5': 'spo2',
    '8310-5': 'temperature', '386725007': 'temperature',
    '29463-7': 'weight', '27113001': 'weight',
    '85354-9': null, // BP panel — handled via components
  };
  const filledVitals = new Set();
  obs.forEach((o) => {
    // Handle panel components (e.g. BP panel)
    if (Array.isArray(o.components) && o.components.length) {
      o.components.forEach((comp) => {
        const field = VITAL_LOINC_MAP[comp.code];
        if (field && !filledVitals.has(field) && comp.value != null) {
          setField(field, String(comp.value));
          filledVitals.add(field);
        }
      });
      return;
    }
    const field = VITAL_LOINC_MAP[o.code];
    if (field && !filledVitals.has(field) && o.numericValue != null) {
      setField(field, String(o.numericValue));
      filledVitals.add(field);
    }
  });

  // Pre-fill treatment_given from most recent Procedure.note
  const procs = detail.procedures || [];
  if (procs.length && form.elements.treatment_given && !form.elements.treatment_given.value) {
    const notes = procs.map((pr) => pr.note || '').filter(Boolean);
    if (notes.length) setField('treatment_given', notes.join(' / '));
  }

  // Pre-fill lab_text and lab_title from most recent DiagnosticReport
  const drs = detail.diagnosticReports || [];
  if (drs.length) {
    const latest = drs[0];
    if (latest.conclusion && form.elements.lab_text && !form.elements.lab_text.value) {
      setField('lab_text', latest.conclusion);
    }
    if (latest.display && form.elements.lab_title && !form.elements.lab_title.value) {
      setField('lab_title', latest.display);
    }
  }
}

document.getElementById('btnDefaults').addEventListener('click', async () => {
  await loadDefaults();
  await initGeo(DEFAULT_GEO);
  await initPractitionerRoles();
  syncReferringFacilityFromTopbar();
  toast('Loaded defaults with selected referring facility', 'ok');
});

// Lab mode toggle: show/hide the manual vs file panels.
function _applyLabMode(mode) {
  const manual = document.getElementById('labManualPanel');
  const file   = document.getElementById('labFilePanel');
  if (!manual || !file) return;
  if (mode === 'file') {
    manual.style.display = 'none';
    file.style.display = '';
  } else {
    manual.style.display = '';
    file.style.display = 'none';
    // Clear file-side data so it is never included in the payload.
    const fi = document.getElementById('inLabFile');
    if (fi) fi.value = '';
    const ha = document.getElementById('inLabAttachment');
    if (ha) ha.value = '';
    const fh = document.getElementById('labFileHint');
    if (fh) { fh.textContent = ''; fh.className = 'hint'; }
  }
}
(function wireLabModeToggle() {
  const radios = document.querySelectorAll('input[name="lab_mode"]');
  radios.forEach(r => r.addEventListener('change', () => _applyLabMode(r.value)));
  // Apply initial state (default: manual).
  _applyLabMode('manual');
})();

// Lab file attachment — read as base64 and store in hidden field (max 512 KB)
(function wireLabFileInput() {
  const fileInput = document.getElementById('inLabFile');
  const hiddenField = document.getElementById('inLabAttachment');
  const hintEl = document.getElementById('labFileHint');
  if (!fileInput || !hiddenField) return;
  fileInput.addEventListener('change', () => {
    const file = fileInput.files && fileInput.files[0];
    if (!file) {
      hiddenField.value = '';
      if (hintEl) hintEl.textContent = '';
      return;
    }
    const MAX_BYTES = 512 * 1024;
    if (file.size > MAX_BYTES) {
      hiddenField.value = '';
      fileInput.value = '';
      if (hintEl) { hintEl.textContent = 'File exceeds 512 KB limit. Please choose a smaller file.'; hintEl.className = 'hint issue'; }
      return;
    }
    const reader = new FileReader();
    reader.onload = (ev) => {
      const dataUrl = ev.target.result;
      const base64 = dataUrl.split(',')[1] || '';
      hiddenField.value = base64;
      if (hintEl) {
        const kb = (file.size / 1024).toFixed(1);
        hintEl.textContent = `Attached: ${file.name} (${kb} KB)`;
        hintEl.className = 'hint';
      }
      // Auto-populate lab_title_file from filename if blank.
      const titleEl = document.getElementById('inLabTitleFile');
      if (titleEl && !titleEl.value) {
        titleEl.value = file.name.replace(/\.[^.]+$/, '');
      }
    };
    reader.readAsDataURL(file);
  });
})();

document.getElementById('btnResetForm').addEventListener('click', resetSubmitFormCompletely);

document.getElementById('btnDedup').addEventListener('click', async () => {
  const family = (form.elements.patient_family.value || '').trim();
  const given = (form.elements.patient_given.value || '').trim();
  const birthDate = (form.elements.patient_birthdate.value || '').trim();
  const philsys = (form.elements.philsys_id.value || '').trim();
  const philhealth = (form.elements.philhealth_id.value || '').trim();
  const box = document.getElementById('dedupResult');
  if (!family || !given || !birthDate || !philsys || !philhealth) {
    box.innerHTML = '<p class="muted">Enter family name, given name, birth date, PhilSys ID, and PhilHealth ID to run composite duplicate check.</p>';
    return;
  }
  box.innerHTML = '<p class="muted">Checking...</p>';
  try {
    const r = await API.get(
      '/api/patients/check-composite?'
      + 'family=' + encodeURIComponent(family)
      + '&given=' + encodeURIComponent(given)
      + '&birth_date=' + encodeURIComponent(birthDate)
      + '&philsys_id=' + encodeURIComponent(philsys)
      + '&philhealth_id=' + encodeURIComponent(philhealth)
    );
    if (r.exists) {
      box.innerHTML = '<div class="issue warning">Patient already exists: ' +
        r.matches.map((m) => escapeHtml(m.name + ' (' + m.id + ')')).join(', ') +
        '. Submit will update the matched patient record.</div>';
    } else {
      box.innerHTML = '<div class="issue information">No composite match found (name + birth date + PhilSys + PhilHealth). A new patient may be created.</div>';
    }
  } catch (e) { box.innerHTML = '<div class="issue">' + escapeHtml(fhirErrorMessage(e)) + '</div>'; }
});

document.getElementById('btnPreview').addEventListener('click', async () => {
  try {
    const bundle = await API.send('POST', '/api/referral/preview', formObject());
    document.getElementById('previewCard').style.display = '';
    document.getElementById('entryCount').textContent = '(' + bundle.entry.length + ' entries)';
    document.getElementById('previewJson').textContent = JSON.stringify(bundle, null, 2);
    document.getElementById('previewCard').scrollIntoView({ behavior: 'smooth' });
  } catch (e) { toast(fhirErrorMessage(e), 'err'); }
});

document.getElementById('btnOpenModules').addEventListener('click', () => {
  // Persist the current form (formObject() writes pheref:lastForm) then hand off.
  formObject();
  window.location.href = '/modules';
});

form.addEventListener('submit', async (ev) => {
  ev.preventDefault();
  if (!form.reportValidity()) return;
  const nonstandardError = validateRequiredNonstandardFields();
  if (nonstandardError) {
    toast(nonstandardError, 'err');
    return;
  }
  const btn = document.getElementById('btnSubmit');
  btn.disabled = true; btn.textContent = 'Submitting...';
  const resultCard = document.getElementById('resultCard');
  try {
    const r = await API.send('POST', '/api/referral/submit', formObject());
    resultCard.style.display = '';
    document.getElementById('resultIssues').innerHTML =
      (r.outcome && r.outcome.has_errors) ? renderIssues(r.outcome)
        : '<div class="issue information">Bundle accepted by the server.</div>';
    document.getElementById('createdList').innerHTML = (r.created || []).length
      ? '<h2>Created resources</h2><table><tr><th>Type</th><th>ID</th><th>Status</th></tr>' +
        r.created.map((c) => `<tr><td>${escapeHtml(c.type)}</td><td>${escapeHtml(c.id)}</td><td>${escapeHtml(c.status)}</td></tr>`).join('') + '</table>'
      : '';
    document.getElementById('resultJson').textContent = JSON.stringify(r.response, null, 2);
    resultCard.scrollIntoView({ behavior: 'smooth' });
    toast('Referral submitted', 'ok');
  } catch (e) {
    resultCard.style.display = '';
    const d = e.data && e.data.detail;
    document.getElementById('resultIssues').innerHTML =
      (d && d.outcome) ? renderIssues(d.outcome) : '<div class="issue">' + escapeHtml(fhirErrorMessage(e)) + '</div>';
    document.getElementById('createdList').innerHTML = '';
    document.getElementById('resultJson').textContent = JSON.stringify((d && d.body) || (e.data || {}), null, 2);
    toast('Submission failed', 'err');
  } finally {
    btn.disabled = false; btn.textContent = 'Submit eReferral';
  }
});

document.getElementById('btnKinSearch').addEventListener('click', () => openTermModal({
  title: 'Search next of kin relationship',
  mode: 'valueset',
  valueSet: VS_KIN,
  strict: true,
  target: 'kin',
}));
document.getElementById('btnChiefSearch').addEventListener('click', () => openTermModal({
  title: 'Search chief complaint concept',
  mode: 'valueset',
  valueSet: VS_CONDITION,
  strict: true,
  target: 'chief',
}));
document.getElementById('btnDiagSearch').addEventListener('click', () => openTermModal({
  title: 'Search diagnosis concept',
  mode: 'valueset',
  valueSet: VS_CONDITION,
  strict: true,
  target: 'diag',
}));
document.getElementById('btnRefFacilitySearch').addEventListener('click', () => openTermModal({
  title: 'Search referring facility (NHFR)',
  mode: 'facilities',
  target: 'refFacility',
  presetQuery: document.getElementById('inRefFacilitySearch').value,
}));
document.getElementById('btnRecFacilitySearch').addEventListener('click', () => openTermModal({
  title: 'Search receiving facility (NHFR)',
  mode: 'facilities',
  target: 'recFacility',
  presetQuery: document.getElementById('inRecFacilitySearch').value,
}));
document.getElementById('btnRefPractitionerSearch').addEventListener('click', () => openTermModal({
  title: 'Search referring practitioner (FHIR)',
  mode: 'practitioners',
  target: 'refPractitioner',
  presetQuery: document.getElementById('inRefPractitionerSearch').value,
}));
document.getElementById('btnRecPractitionerSearch').addEventListener('click', () => openTermModal({
  title: 'Search receiving practitioner (FHIR)',
  mode: 'practitioners',
  target: 'recPractitioner',
  presetQuery: document.getElementById('inRecPractitionerSearch').value,
}));

document.getElementById('btnTermModalSearch').addEventListener('click', runTermModalSearch);
document.getElementById('termModalQuery').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') { e.preventDefault(); runTermModalSearch(); }
});
document.getElementById('btnCloseTermModal').addEventListener('click', closeTermModal);
document.getElementById('btnCloseTermModal2').addEventListener('click', closeTermModal);
document.getElementById('termModal').addEventListener('click', (e) => {
  if (e.target === e.currentTarget) closeTermModal();
});

window.addEventListener('pheref:facility-change', () => {
  syncReferringFacilityFromTopbar();
});

(async function init() {
  const urlParams = new URLSearchParams(window.location.search);
  const patientId = urlParams.get('patientId');
  const patientPromise = patientId ? API.get('/api/patients/' + patientId) : null;
  if (patientId) setPrefillStatus(`Loading patient ${patientId}...`);

  if (window.PHEREF && window.PHEREF.ready) await window.PHEREF.ready;

  await Promise.all([initTerminology(), initKinRelationship(), initPractitionerRoles()]);

  let patientDetail = null;
  if (patientPromise) {
    try {
      patientDetail = await patientPromise;
    } catch (e) {
      setPrefillStatus(`Could not load patient ${patientId}: ${fhirErrorMessage(e)}`, true);
    }
  }

  await initGeo(patientDetail ? (patientDetail.summary || null) : DEFAULT_GEO);
  wireCodeValidation('chief');
  wireCodeValidation('diag');
  markRequiredLabels();

  syncReferringFacilityFromTopbar();

  if (patientDetail) {
    applyPatientPrefill(patientDetail);
    setPrefillStatus(`Patient ${patientId} prefilled.`);
    toast('Pre-filled from Patient ' + patientId, 'ok');
  } else {
    if (form.elements.contact_relationship_display.value && form.elements.contact_relationship.value) {
      document.getElementById('inContactRelationshipQuery').value =
        `${form.elements.contact_relationship_display.value} [${form.elements.contact_relationship.value}]`;
    }
    setPrefillStatus('Form is ready and starts blank. Use "Load Ana Reyes defaults" if needed.');
  }
})();
