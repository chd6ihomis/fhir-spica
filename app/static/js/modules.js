// Granular FHIR module console.
// Mirrors the PH eReferral Postman collection: every transaction-Bundle entry is
// shown as an individually inspectable / (for master resources) submittable
// operation, with method+URL badges, JSON preview, hover field docs, and GET
// fetch of the existing server copy.

const FORM_KEY = 'pheref:lastForm';
let currentForm = null;      // object | null
let usingDefaults = false;   // sample mode
let fieldDocs = {};          // path -> description

const $ = (id) => document.getElementById(id);

function methodBadgeClass(method) {
  return method === 'PUT' ? 'routine' : 'requested';
}

// ----- JSON rendering with hover field documentation -----------------------
function lookupDoc(path) {
  if (fieldDocs[path]) return fieldDocs[path];
  const parts = path.split('.');
  for (let i = 1; i < parts.length; i++) {
    const suffix = parts.slice(i).join('.');
    if (fieldDocs[suffix]) return fieldDocs[suffix];
  }
  return '';
}

function renderJsonHtml(value, path, indent) {
  const pad = '  '.repeat(indent);
  const padIn = '  '.repeat(indent + 1);
  if (value === null) return '<span class="jnull">null</span>';
  if (Array.isArray(value)) {
    if (!value.length) return '[]';
    const items = value.map((v) => padIn + renderJsonHtml(v, path, indent + 1));
    return '[\n' + items.join(',\n') + '\n' + pad + ']';
  }
  if (typeof value === 'object') {
    const keys = Object.keys(value);
    if (!keys.length) return '{}';
    const rows = keys.map((k) => {
      const childPath = path ? path + '.' + k : k;
      const doc = lookupDoc(childPath);
      const keyAttrs = doc
        ? ` class="jkey jkey-doc" data-doc="${escapeHtml(doc)}"`
        : ' class="jkey"';
      const keyHtml = `<span${keyAttrs}>"${escapeHtml(k)}"</span>`;
      return padIn + keyHtml + ': ' + renderJsonHtml(value[k], childPath, indent + 1);
    });
    return '{\n' + rows.join(',\n') + '\n' + pad + '}';
  }
  if (typeof value === 'string') return '<span class="jstr">"' + escapeHtml(value) + '"</span>';
  if (typeof value === 'number') return '<span class="jnum">' + value + '</span>';
  if (typeof value === 'boolean') return '<span class="jbool">' + value + '</span>';
  return escapeHtml(String(value));
}

function jsonViewerInto(el, obj) {
  el.innerHTML = renderJsonHtml(obj, '', 0);
  el.style.display = '';
}

// Tooltip wiring (delegated, set up once).
function setupTooltip() {
  const tip = $('fieldTooltip');
  document.addEventListener('mouseover', (e) => {
    const k = e.target.closest('.jkey-doc');
    if (!k) return;
    tip.textContent = k.dataset.doc;
    tip.style.display = 'block';
  });
  document.addEventListener('mousemove', (e) => {
    if (tip.style.display !== 'block') return;
    tip.style.left = (e.pageX + 14) + 'px';
    tip.style.top = (e.pageY + 14) + 'px';
  });
  document.addEventListener('mouseout', (e) => {
    if (e.target.closest('.jkey-doc')) tip.style.display = 'none';
  });
}

// ----- Module cards --------------------------------------------------------
function moduleCard(mod) {
  const card = document.createElement('div');
  card.className = 'card module-card';
  const isMaster = mod.group === 'master';
  const refList = Array.from(new Set(Object.values(mod.references || {})));
  card.innerHTML = `
    <div class="module-head">
      <h3>${escapeHtml(mod.label)}</h3>
      <span class="badge ${methodBadgeClass(mod.method)}">${escapeHtml(mod.method)}</span>
    </div>
    <code class="module-url">${escapeHtml(mod.url)}</code>
    ${refList.length ? `<p class="muted module-refs">References: ${refList.map(escapeHtml).join(', ')}</p>` : ''}
    <div class="btn-row">
      <button class="btn-secondary act-preview">Preview JSON</button>
      ${isMaster ? '<button class="btn-ghost act-fetch">Fetch existing (GET)</button>' : ''}
      ${isMaster ? '<button class="act-submit">Send (PUT)</button>'
                 : '<button class="act-submit" title="Clinical resources depend on records the Bundle creates; submit through the Bundle.">Send (POST)</button>'}
    </div>
    <div class="json-viewer module-json" style="display:none"></div>
    <div class="module-result"></div>`;

  const jsonEl = card.querySelector('.module-json');
  const resultEl = card.querySelector('.module-result');

  card.querySelector('.act-preview').addEventListener('click', () => {
    if (jsonEl.style.display !== 'none') { jsonEl.style.display = 'none'; return; }
    jsonViewerInto(jsonEl, mod.resource);
  });

  const fetchBtn = card.querySelector('.act-fetch');
  if (fetchBtn) {
    fetchBtn.addEventListener('click', async () => {
      if (!ensureForm(resultEl)) return;
      fetchBtn.disabled = true;
      try {
        const r = await API.send('POST', '/api/modules/fetch',
          { key: mod.key, form: currentForm, use_defaults: usingDefaults });
        const n = r.matches ? r.matches.length : 0;
        resultEl.innerHTML = `<p class="muted">GET ${escapeHtml(r.query)} — ${n} match(es), total ${escapeHtml(String(r.total))}.</p>`;
        if (n) {
          const v = document.createElement('div');
          v.className = 'json-viewer';
          jsonViewerInto(v, r.matches.length === 1 ? r.matches[0] : r.matches);
          resultEl.appendChild(v);
        } else {
          resultEl.innerHTML += '<div class="issue information">No existing record — a Send would create one.</div>';
        }
      } catch (e) { showErr(resultEl, e); }
      finally { fetchBtn.disabled = false; }
    });
  }

  card.querySelector('.act-submit').addEventListener('click', async (ev) => {
    if (!ensureForm(resultEl)) return;
    const btn = ev.currentTarget;
    btn.disabled = true; const label = btn.textContent; btn.textContent = 'Sending…';
    try {
      const r = await API.send('POST', '/api/modules/submit',
        { key: mod.key, form: currentForm, use_defaults: usingDefaults });
      const loc = (r.response && r.response.id)
        ? `${mod.resourceType}/${r.response.id}` : '(see response)';
      resultEl.innerHTML = `<div class="issue information">${escapeHtml(r.method)} ${escapeHtml(r.url)} → ${escapeHtml(loc)}</div>`;
      const v = document.createElement('div');
      v.className = 'json-viewer';
      jsonViewerInto(v, r.response);
      resultEl.appendChild(v);
      toast(mod.label + ' sent', 'ok');
    } catch (e) { showErr(resultEl, e); toast('Send failed', 'err'); }
    finally { btn.disabled = false; btn.textContent = label; }
  });

  return card;
}

function showErr(el, e) {
  const d = e.data && e.data.detail;
  if (d && d.outcome) { el.innerHTML = renderIssues(d.outcome); return; }
  const msg = (d && d.message) ? d.message : fhirErrorMessage(e);
  let html = '<div class="issue">' + escapeHtml(msg) + '</div>';
  if (d && d.unresolved) html += '<p class="muted">Unresolved: ' + escapeHtml(d.unresolved.join(', ')) + '. Submit the Bundle instead.</p>';
  el.innerHTML = html;
}

function ensureForm(el) {
  if (currentForm) return true;
  if (el) el.innerHTML = '<div class="issue">Load a form first (Load last form or Load sample).</div>';
  toast('Load a form first', 'err');
  return false;
}

// ----- Load + render lifecycle ---------------------------------------------
async function renderModules() {
  $('masterModules').innerHTML = '';
  $('clinicalModules').innerHTML = '';
  if (!currentForm) return;
  let modules;
  try {
    const r = await API.send('POST', '/api/modules/preview',
      { form: currentForm, use_defaults: usingDefaults });
    modules = r.modules || [];
  } catch (e) { toast(fhirErrorMessage(e), 'err'); return; }
  modules.forEach((mod) => {
    const target = mod.group === 'master' ? $('masterModules') : $('clinicalModules');
    target.appendChild(moduleCard(mod));
  });
}

function setSource(text) { $('moduleSource').textContent = text; }

async function loadLastForm() {
  let raw;
  try { raw = localStorage.getItem(FORM_KEY); } catch (e) { raw = null; }
  if (!raw) { toast('No saved form. Preview/submit on the Submit page first.', 'err'); return; }
  try { currentForm = JSON.parse(raw); } catch (e) { toast('Saved form is corrupt.', 'err'); return; }
  usingDefaults = false;
  setSource('Loaded the last form previewed/submitted on the Submit page.');
  await renderModules();
}

async function loadSample() {
  currentForm = {};
  usingDefaults = true;
  setSource('Loaded the IG Ana Reyes sample (DEFAULTS) — testing only, never a production fallback.');
  await renderModules();
}

// ----- Bundle card ---------------------------------------------------------
$('btnBundlePreview').addEventListener('click', async () => {
  if (!ensureForm($('bundleResult'))) return;
  try {
    const bundle = await API.send('POST', '/api/modules/bundle/preview',
      { form: currentForm, use_defaults: usingDefaults });
    jsonViewerInto($('bundleJson'), bundle);
  } catch (e) { showErr($('bundleResult'), e); }
});

$('btnBundleSubmit').addEventListener('click', async () => {
  if (!ensureForm($('bundleResult'))) return;
  const btn = $('btnBundleSubmit');
  btn.disabled = true; btn.textContent = 'Submitting…';
  try {
    const r = await API.send('POST', '/api/modules/bundle/submit',
      { form: currentForm, use_defaults: usingDefaults });
    const created = (r.created || []).length
      ? '<table><tr><th>Type</th><th>ID</th><th>Status</th></tr>' +
        r.created.map((c) => `<tr><td>${escapeHtml(c.type)}</td><td>${escapeHtml(c.id)}</td><td>${escapeHtml(c.status)}</td></tr>`).join('') + '</table>'
      : '';
    $('bundleResult').innerHTML =
      ((r.outcome && r.outcome.has_errors) ? renderIssues(r.outcome)
        : '<div class="issue information">Bundle accepted by the server.</div>') + created;
    toast('Bundle submitted', 'ok');
  } catch (e) { showErr($('bundleResult'), e); toast('Submission failed', 'err'); }
  finally { btn.disabled = false; btn.textContent = 'Submit Bundle'; }
});

$('btnLoadForm').addEventListener('click', loadLastForm);
$('btnLoadSample').addEventListener('click', loadSample);

(async function init() {
  setupTooltip();
  try { fieldDocs = await API.get('/api/modules/field-docs'); } catch (e) { fieldDocs = {}; }
  // Auto-load the handoff form if present.
  let raw = null;
  try { raw = localStorage.getItem(FORM_KEY); } catch (e) { /* ignore */ }
  if (raw) { await loadLastForm(); }
})();
