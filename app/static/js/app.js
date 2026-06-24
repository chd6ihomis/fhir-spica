// Shared client-side helpers for the PHeRef portal.

const API = {
  async get(path) { return this._req('GET', path); },
  async del(path) { return this._req('DELETE', path); },
  async send(method, path, body) { return this._req(method, path, body); },
  async _req(method, path, body) {
    const opts = { method, headers: {} };
    if (body !== undefined) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
    const res = await fetch(path, opts);
    let data = null;
    const text = await res.text();
    try { data = text ? JSON.parse(text) : null; } catch (e) { data = text; }
    if (!res.ok) {
      const err = new Error('Request failed');
      err.status = res.status;
      err.data = data;
      throw err;
    }
    return data;
  },
};

function toast(message, kind = '') {
  const el = document.getElementById('toast');
  if (!el) return;
  el.textContent = message;
  el.className = 'toast show ' + kind;
  setTimeout(() => { el.className = 'toast ' + kind; }, 3500);
}

function escapeHtml(value) {
  return String(value == null ? '' : value)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

/**
 * Format an ISO 8601 date-time string to a human-readable local string.
 * Returns empty string for null/undefined inputs.
 * @param {string} iso - e.g. "2026-06-18T08:30:00+08:00"
 * @param {boolean} timeOnly - if true, return only the time portion
 */
function formatDateTime(iso, timeOnly = false) {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    if (isNaN(d)) return iso;
    if (timeOnly) {
      return d.toLocaleTimeString('en-PH', { hour: '2-digit', minute: '2-digit', hour12: true });
    }
    return d.toLocaleDateString('en-PH', {
      year: 'numeric', month: 'long', day: 'numeric',
      hour: '2-digit', minute: '2-digit', hour12: true,
    });
  } catch (e) { return iso; }
}

/**
 * Format an ISO date string (YYYY-MM-DD) to a readable date.
 */
function formatDate(iso) {
  if (!iso) return '';
  try {
    const [y, m, d] = iso.split('-').map(Number);
    return new Date(y, m - 1, d).toLocaleDateString('en-PH', { year: 'numeric', month: 'long', day: 'numeric' });
  } catch (e) { return iso; }
}

function formatFhirDate(value) {
  if (!value) return '';
  return /^\d{4}-\d{2}-\d{2}$/.test(value) ? formatDate(value) : formatDateTime(value);
}

function conditionDateSourceLabel(source) {
  const labels = {
    onsetDateTime: 'Onset',
    'onsetPeriod.start': 'Onset',
    onsetString: 'Onset',
    onsetAge: 'Onset age',
    onsetRange: 'Onset range',
    recordedDate: 'Recorded',
  };
  return labels[source] || 'Timeline';
}

function conditionTimestamp(condition) {
  if (!condition || !condition.effectiveDateTime) return 0;
  const ts = Date.parse(condition.effectiveDateTime);
  return Number.isNaN(ts) ? 0 : ts;
}

function conditionGroupKey(condition) {
  return [condition.system || '', condition.code || '', condition.display || 'Condition'].join('|');
}

function formatConditionTimeline(condition) {
  if (!condition) return 'No condition date';
  if (condition.effectiveDateTime) {
    return `${conditionDateSourceLabel(condition.effectiveDateSource)} ${formatFhirDate(condition.effectiveDateTime)}`;
  }
  if (condition.effectiveDateText) {
    return `${conditionDateSourceLabel(condition.effectiveDateSource)}: ${condition.effectiveDateText}`;
  }
  return 'No condition date';
}

function groupConditions(conditions) {
  const groups = new Map();
  [...(conditions || [])]
    .sort((a, b) => conditionTimestamp(b) - conditionTimestamp(a))
    .forEach(condition => {
      const key = conditionGroupKey(condition);
      if (!groups.has(key)) {
        groups.set(key, {
          key,
          code: condition.code || '',
          system: condition.system || '',
          label: condition.display || condition.code || 'Condition',
          entries: [],
        });
      }
      groups.get(key).entries.push(condition);
    });

  return [...groups.values()].map(group => ({
    ...group,
    latest: group.entries[0] || null,
  })).sort((a, b) => a.label.localeCompare(b.label));
}

function renderConditionSection(conditions, { heading = 'Conditions / Diagnoses', emptyText = 'No conditions recorded' } = {}) {
  const rows = conditions || [];
  const grouped = groupConditions(rows);
  const groupedHtml = grouped.length
    ? grouped.map(group => {
        const latest = group.latest || {};
        const timeline = group.entries.map(entry => `
          <li>
            <div class="obs-timeline-dot"></div>
            <div class="obs-timeline-card">
              <div class="obs-timeline-meta">${escapeHtml(formatConditionTimeline(entry))}</div>
              <div class="obs-timeline-value">
                <span class="badge ${escapeHtml(entry.clinicalStatus || '')}">${escapeHtml(entry.clinicalStatus || 'unknown')}</span>
                ${entry.code ? `<span class="id-chip">${escapeHtml(entry.code)}</span>` : ''}
              </div>
            </div>
          </li>`).join('');

        const latestText = latest && (latest.effectiveDateTime || latest.effectiveDateText)
          ? ` · Latest ${escapeHtml(formatConditionTimeline(latest))}`
          : '';

        return `<article class="obs-group-card">
          <div class="obs-group-header">
            <div>
              <h4>${escapeHtml(group.label)}</h4>
              <p>${group.entries.length} record${group.entries.length === 1 ? '' : 's'}${latestText}</p>
            </div>
            <div class="condition-header-meta">
              ${group.code ? `<span class="id-chip">${escapeHtml(group.code)}</span>` : ''}
              ${latest.clinicalStatus ? `<span class="badge ${escapeHtml(latest.clinicalStatus)}">${escapeHtml(latest.clinicalStatus)}</span>` : ''}
            </div>
          </div>
          <ol class="obs-timeline">${timeline}</ol>
        </article>`;
      }).join('')
    : `<p class="muted">${escapeHtml(emptyText)}</p>`;

  const tableRows = rows.length
    ? rows.map(condition => `
        <tr>
          <td>${escapeHtml(condition.display || condition.code)}</td>
          <td class="muted">${escapeHtml(condition.code || '')}</td>
          <td><span class="badge ${escapeHtml(condition.clinicalStatus || '')}">${escapeHtml(condition.clinicalStatus || 'unknown')}</span></td>
          <td class="muted">${escapeHtml(formatConditionTimeline(condition) === 'No condition date' ? '' : formatConditionTimeline(condition))}</td>
        </tr>`).join('')
    : `<tr><td colspan="4" class="muted">${escapeHtml(emptyText)}</td></tr>`;

  return `<section>
    <div class="obs-section-head">
      <div>
        <h3>${escapeHtml(heading)}</h3>
        <p class="muted">Group repeated diagnoses into dated history using condition onset when available and recorded time as the fallback.</p>
      </div>
      <div class="tabs obs-view-toggle" role="tablist" aria-label="Condition display options">
        <button type="button" class="tab active cond-view-btn" data-view="grouped">Grouped history</button>
        <button type="button" class="tab cond-view-btn" data-view="table">Table</button>
      </div>
    </div>
    <div class="cond-panel" data-panel="grouped">${groupedHtml}</div>
    <div class="cond-panel" data-panel="table" hidden>
      <table>
        <thead><tr><th>Condition</th><th>Code</th><th>Status</th><th>Timeline</th></tr></thead>
        <tbody>${tableRows}</tbody>
      </table>
    </div>
  </section>`;
}

function fhirErrorMessage(err) {
  const d = err && err.data && err.data.detail;
  if (d && typeof d === 'object') {
    let msg = d.message || 'FHIR error';
    if (d.outcome && d.outcome.issues && d.outcome.issues.length) {
      msg += ': ' + d.outcome.issues.map(i => i.details || i.diagnostics).filter(Boolean).join('; ');
    }
    return msg;
  }
  return (d && String(d)) || (err && err.message) || 'Request failed';
}

function renderIssues(outcome) {
  if (!outcome || !outcome.issues || !outcome.issues.length) return '';
  return outcome.issues.map(i =>
    `<div class="issue ${escapeHtml(i.severity)}">
       <strong>${escapeHtml(i.severity)}</strong> [${escapeHtml(i.code)}]
       ${i.location ? '<span class="muted"> @ ' + escapeHtml(i.location) + '</span>' : ''}
       <div>${escapeHtml(i.details || i.diagnostics || '')}</div>
     </div>`).join('');
}

const FACILITY_STORAGE_KEY = 'pheref.topbarOrganizationId';
const FACILITY_PROVINCE_STORAGE_KEY = 'pheref.topbarFacilityProvince';
const FACILITY_CITY_STORAGE_KEY = 'pheref.topbarFacilityCity';
const PHerefState = {
  selectedFacility: null,
  facilities: [],
  filteredFacilities: [],
  selectedProvince: '',
  selectedCity: '',
  ready: Promise.resolve(),
};

const ALL_FACILITIES_VALUE = '__ALL__';

window.PHEREF = {
  getSelectedFacility() {
    return PHerefState.selectedFacility;
  },
  getFacilities() {
    return [...PHerefState.facilities];
  },
  getFacilityFilters() {
    return {
      province: PHerefState.selectedProvince,
      city: PHerefState.selectedCity,
    };
  },
  ready: PHerefState.ready,
};

function formatFacilityOptionLabel(facility) {
  const city = facility.city ? ` - ${facility.city}` : '';
  const labelCode = facility.nhfr_identifier || facility.code || facility.org_id || '';
  return `${facility.name} (${labelCode})${city}`;
}

function setSelectedFacility(facility) {
  PHerefState.selectedFacility = facility || null;
  window.dispatchEvent(new CustomEvent('pheref:facility-change', { detail: PHerefState.selectedFacility }));
}

async function initTopbarFacilityIdentity() {
  const select = document.getElementById('topbarFacilitySelect');
  const provinceSelect = document.getElementById('topbarProvinceSelect');
  const citySelect = document.getElementById('topbarCitySelect');
  if (!select) return;

  let list = [];
  try {
    const response = await API.get('/api/facilities?limit=20000');
    list = response.facilities || [];
  } catch (e) {
    select.innerHTML = '<option value="">Facility list unavailable</option>';
    return;
  }

  PHerefState.facilities = list;
  const provinces = [...new Set(list.map((x) => x.province).filter(Boolean))].sort((a, b) => a.localeCompare(b));
  provinceSelect.innerHTML = '<option value="">All provinces</option>';
  provinces.forEach((province) => {
    const opt = document.createElement('option');
    opt.value = province;
    opt.textContent = province;
    provinceSelect.appendChild(opt);
  });

  const preferredProvince = localStorage.getItem(FACILITY_PROVINCE_STORAGE_KEY) || '';
  const preferredCity = localStorage.getItem(FACILITY_CITY_STORAGE_KEY) || '';
  if (preferredProvince && provinces.includes(preferredProvince)) {
    provinceSelect.value = preferredProvince;
    PHerefState.selectedProvince = preferredProvince;
  }
  PHerefState.selectedCity = preferredCity;

  function applyFacilityFilters() {
    const province = provinceSelect.value || '';
    const city = citySelect.value || '';
    PHerefState.selectedProvince = province;
    PHerefState.selectedCity = city;
    localStorage.setItem(FACILITY_PROVINCE_STORAGE_KEY, province);
    localStorage.setItem(FACILITY_CITY_STORAGE_KEY, city);

    const filtered = list.filter((facility) => {
      if (province && facility.province !== province) return false;
      if (city && facility.city !== city) return false;
      return true;
    });
    PHerefState.filteredFacilities = filtered;

    select.innerHTML = '';
    const allOpt = document.createElement('option');
    allOpt.value = ALL_FACILITIES_VALUE;
    allOpt.textContent = 'All Facility';
    select.appendChild(allOpt);

    filtered.forEach((facility) => {
      const opt = document.createElement('option');
      opt.value = facility.org_id || facility.code;
      opt.textContent = formatFacilityOptionLabel(facility);
      select.appendChild(opt);
    });
    if (!filtered.length) {
      const opt = document.createElement('option');
      opt.value = '';
      opt.textContent = 'No facilities in current filter';
      select.appendChild(opt);
    }
  }

  function refreshCityOptions() {
    const province = provinceSelect.value || '';
    const cities = [...new Set(
      list
        .filter((x) => !province || x.province === province)
        .map((x) => x.city)
        .filter(Boolean)
    )].sort((a, b) => a.localeCompare(b));

    citySelect.innerHTML = '<option value="">All cities/municipalities</option>';
    cities.forEach((city) => {
      const opt = document.createElement('option');
      opt.value = city;
      opt.textContent = city;
      citySelect.appendChild(opt);
    });

    const wanted = PHerefState.selectedCity;
    if (wanted && cities.includes(wanted)) {
      citySelect.value = wanted;
    } else {
      citySelect.value = '';
      PHerefState.selectedCity = '';
    }
  }

  provinceSelect.addEventListener('change', () => {
    PHerefState.selectedCity = '';
    refreshCityOptions();
    applyFacilityFilters();
    const selected = select.value === ALL_FACILITIES_VALUE
      ? null
      : (PHerefState.filteredFacilities.find((x) => (x.org_id || x.code) === select.value) || null);
    if (selected) {
      select.value = selected.org_id || selected.code;
      localStorage.setItem(FACILITY_STORAGE_KEY, selected.org_id || selected.code);
    } else {
      select.value = ALL_FACILITIES_VALUE;
      localStorage.removeItem(FACILITY_STORAGE_KEY);
    }
    setSelectedFacility(selected);
  });

  citySelect.addEventListener('change', () => {
    applyFacilityFilters();
    const selected = select.value === ALL_FACILITIES_VALUE
      ? null
      : (PHerefState.filteredFacilities.find((x) => (x.org_id || x.code) === select.value) || null);
    if (selected) {
      select.value = selected.org_id || selected.code;
      localStorage.setItem(FACILITY_STORAGE_KEY, selected.org_id || selected.code);
    } else {
      select.value = ALL_FACILITIES_VALUE;
      localStorage.removeItem(FACILITY_STORAGE_KEY);
    }
    setSelectedFacility(selected);
  });

  refreshCityOptions();
  applyFacilityFilters();

  // Product preference: site navigation should default to All Facility.
  let preferredCode = ALL_FACILITIES_VALUE;

  if (preferredCode === ALL_FACILITIES_VALUE) {
    select.value = ALL_FACILITIES_VALUE;
  } else if (preferredCode && PHerefState.filteredFacilities.some((x) => (x.org_id || x.code) === preferredCode)) {
    select.value = preferredCode;
  } else if (PHerefState.filteredFacilities.length) {
    select.value = PHerefState.filteredFacilities[0].org_id || PHerefState.filteredFacilities[0].code;
  }

  const selected = select.value === ALL_FACILITIES_VALUE
    ? null
    : (PHerefState.filteredFacilities.find((x) => (x.org_id || x.code) === select.value) || null);
  if (selected) {
    localStorage.setItem(FACILITY_STORAGE_KEY, selected.org_id || selected.code);
  } else {
    localStorage.removeItem(FACILITY_STORAGE_KEY);
  }
  setSelectedFacility(selected);

  select.addEventListener('change', () => {
    const facility = select.value === ALL_FACILITIES_VALUE
      ? null
      : (PHerefState.filteredFacilities.find((x) => (x.org_id || x.code) === select.value) || null);
    if (facility) {
      localStorage.setItem(FACILITY_STORAGE_KEY, facility.org_id || facility.code);
    } else {
      localStorage.removeItem(FACILITY_STORAGE_KEY);
    }
    setSelectedFacility(facility);
  });
}

// Populate a <select> from a terminology ValueSet expansion.
async function fillValueSet(selectEl, key, { valueField = 'code' } = {}) {
  if (!selectEl) return;
  try {
    const data = await API.get('/api/terminology/expand?url=' + encodeURIComponent(key));
    selectEl.innerHTML = '';
    data.concepts.forEach(c => {
      const opt = document.createElement('option');
      opt.value = valueField === 'code' ? c.code : `${c.system}|${c.code}`;
      opt.textContent = `${c.display} (${c.code})`;
      opt.dataset.system = c.system;
      opt.dataset.display = c.display;
      selectEl.appendChild(opt);
    });
    const tag = selectEl.parentElement && selectEl.parentElement.querySelector('.source-tag');
    if (tag) { tag.textContent = data.source; tag.className = 'source-tag ' + data.source; }
  } catch (e) {
    console.warn('ValueSet load failed', key, e);
  }
}

/**
 * Search a ValueSet with $expand filter for autocomplete.
 * Returns the same concept shape as fillValueSet.
 */
async function searchValueSet(key, query, count = 20, { strict = false } = {}) {
  const params = [
    'url=' + encodeURIComponent(key),
    'count=' + encodeURIComponent(String(count)),
  ];
  if (query && query.trim()) params.push('filter=' + encodeURIComponent(query.trim()));
  if (strict) params.push('strict=true');
  const data = await API.get('/api/terminology/expand?' + params.join('&'));
  return data;
}

function _parameterValue(parameters, name) {
  const p = (parameters && parameters.parameter || []).find((x) => x.name === name);
  if (!p) return null;
  if (Object.prototype.hasOwnProperty.call(p, 'valueBoolean')) return p.valueBoolean;
  if (Object.prototype.hasOwnProperty.call(p, 'valueString')) return p.valueString;
  if (Object.prototype.hasOwnProperty.call(p, 'valueCode')) return p.valueCode;
  if (Object.prototype.hasOwnProperty.call(p, 'valueUri')) return p.valueUri;
  if (Object.prototype.hasOwnProperty.call(p, 'valueCoding')) return p.valueCoding;
  return null;
}

/**
 * Validate code membership in a ValueSet using $validate-code.
 * Returns { ok, message }.
 */
async function validateCodeInValueSet(valueSetUrl, system, code, display) {
  const qs = [
    'url=' + encodeURIComponent(valueSetUrl),
    'system=' + encodeURIComponent(system),
    'code=' + encodeURIComponent(code),
  ];
  if (display) qs.push('display=' + encodeURIComponent(display));
  const result = await API.get('/api/terminology/validate-code?' + qs.join('&'));
  const ok = !!_parameterValue(result, 'result');
  const message = _parameterValue(result, 'message') || '';
  return { ok, message };
}

/**
 * Validate and look up a SNOMED CT code against the terminology server.
 * @param {string} code - SNOMED code to look up
 * @param {function} onResult - called with {valid, display, code} or {valid: false, error}
 */
async function snomedLookup(code, onResult) {
  if (!code || !/^\d+$/.test(code.trim())) {
    onResult({ valid: false, error: 'Enter a numeric SNOMED CT code' });
    return;
  }
  try {
    const result = await API.get(
      `/api/terminology/lookup?system=${encodeURIComponent('http://snomed.info/sct')}&code=${encodeURIComponent(code.trim())}`
    );
    const display = _parameterValue(result, 'display') || '';
    onResult({ valid: true, display, code: code.trim(), system: 'http://snomed.info/sct' });
  } catch (e) {
    const msg = fhirErrorMessage(e);
    onResult({ valid: false, error: msg });
  }
}

/**
 * Wire a text input for SNOMED CT auto-lookup with debounce.
 * Shows result in a companion element (class="snomed-result" next to input).
 * @param {HTMLInputElement} inputEl
 * @param {HTMLElement} resultEl  - element to show validation result
 */
function wireSnomedInput(inputEl, resultEl, { valueSetUrl = null } = {}) {
  if (!inputEl) return;
  let timer;
  inputEl.addEventListener('input', () => {
    clearTimeout(timer);
    if (!inputEl.value.trim()) { resultEl.innerHTML = ''; return; }
    resultEl.innerHTML = '<span class="muted">looking up…</span>';
    timer = setTimeout(async () => {
      await snomedLookup(inputEl.value, async ({ valid, display, error, system, code }) => {
        if (!valid) {
          resultEl.innerHTML = `<span class="badge err">✗ ${escapeHtml(error || 'Not found')}</span>`;
          return;
        }
        if (!valueSetUrl) {
          resultEl.innerHTML = `<span class="badge ok">✓ ${escapeHtml(display)}</span>`;
          return;
        }
        try {
          const v = await validateCodeInValueSet(valueSetUrl, system, code, display);
          if (v.ok) {
            resultEl.innerHTML = `<span class="badge ok">✓ ${escapeHtml(display)}</span>`;
          } else {
            const msg = v.message || 'Code is not in allowed ValueSet';
            resultEl.innerHTML = `<span class="badge err">✗ ${escapeHtml(msg)}</span>`;
          }
        } catch (e) {
          resultEl.innerHTML = `<span class="badge err">✗ ${escapeHtml(fhirErrorMessage(e))}</span>`;
        }
      });
    }, 600);
  });
}

// Refresh the server status pill in the header.
async function refreshServerPill() {
  const dot = document.getElementById('serverDot');
  const label = document.getElementById('serverLabel');
  if (!dot) return;
  try {
    const h = await API.get('/api/health');
    if (label) label.textContent = h.fhir_base_url;
    const reachable = h.fhir && h.fhir.reachable;
    dot.className = 'dot ' + (reachable ? 'ok' : 'bad');
    document.getElementById('serverPill').title = reachable
      ? `Connected: ${h.fhir.software || 'FHIR server'} (${h.fhir.fhirVersion || '?'})`
      : `Unreachable: ${(h.fhir && h.fhir.error) || 'no response'}`;
  } catch (e) {
    dot.className = 'dot bad';
  }
}

document.addEventListener('DOMContentLoaded', refreshServerPill);
PHerefState.ready = new Promise((resolve) => {
  document.addEventListener('DOMContentLoaded', async () => {
    await initTopbarFacilityIdentity();
    resolve();
  });
});
window.PHEREF.ready = PHerefState.ready;
