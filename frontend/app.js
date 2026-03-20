const API = '';  // same origin

// ─── Tab routing ──────────────────────────────────────────────────────────────
function switchTab(name) {
  document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab-pane').forEach(p => {
    p.classList.remove('active');
    p.classList.add('hidden');
  });
  const tab = document.querySelector(`.nav-tab[data-tab="${name}"]`);
  if (tab) tab.classList.add('active');
  const pane = document.getElementById('tab-' + name);
  if (pane) { pane.classList.remove('hidden'); pane.classList.add('active'); }
  if (name === 'services') loadServices();
  if (name === 'demo') loadDemoStats();
}

document.querySelectorAll('.nav-tab').forEach(tab => {
  tab.addEventListener('click', () => switchTab(tab.dataset.tab));
});

function prefillExplain(serviceId, question) {
  document.getElementById('explain-service-id').value = serviceId;
  document.getElementById('explain-question').value = question || '';
}

function prefillCompare(idA, verA, idB, verB) {
  document.getElementById('compare-id-a').value = idA;
  document.getElementById('compare-ver-a').value = verA || '';
  document.getElementById('compare-id-b').value = idB;
  document.getElementById('compare-ver-b').value = verB || '';
}

function prefillChangelog(serviceId, from, to) {
  document.getElementById('changelog-service-id').value = serviceId;
  document.getElementById('changelog-from').value = from;
  document.getElementById('changelog-to').value = to;
}

function prefillGaps(serviceId) {
  document.getElementById('gap-service-id').value = serviceId;
  document.getElementById('gap-recommendations').checked = true;
}

function runScenario(name) { /* handled by individual buttons */ }

function switchInnerTab(name) {
  document.querySelectorAll('.inner-tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.inner-pane').forEach(p => {
    p.classList.remove('active');
    p.classList.add('hidden');
  });
  const tab = document.querySelector(`.inner-tab[data-inner="${name}"]`);
  if (tab) tab.classList.add('active');
  const pane = document.getElementById('inner-' + name);
  if (pane) { pane.classList.remove('hidden'); pane.classList.add('active'); }
}

document.querySelectorAll('.inner-tab').forEach(tab => {
  tab.addEventListener('click', () => switchInnerTab(tab.dataset.inner));
});

// ─── Utilities ────────────────────────────────────────────────────────────────
function showToast(msg, type = 'success') {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = `toast ${type}`;
  setTimeout(() => t.classList.add('hidden'), 3500);
}

function showThinking() {
  document.getElementById('ai-thinking').classList.remove('hidden');
}
function hideThinking() {
  document.getElementById('ai-thinking').classList.add('hidden');
}

function setLoading(btn, loading, label = '') {
  if (loading) {
    btn._orig = btn.innerHTML;
    btn.innerHTML = `<span class="spinner"></span> ${label || 'Processing…'}`;
    btn.disabled = true;
  } else {
    btn.innerHTML = btn._orig;
    btn.disabled = false;
  }
}

async function apiFetch(path, method = 'GET', body = null) {
  const opts = {
    method,
    headers: { 'Content-Type': 'application/json' },
  };
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch(API + path, opts);
  const text = await res.text();
  let data;
  try {
    data = JSON.parse(text);
  } catch {
    throw new Error(`Server returned non-JSON response (${res.status}): ${text.slice(0, 200)}`);
  }
  if (!res.ok) throw new Error(data.detail || JSON.stringify(data));
  return data;
}

// ─── Demo Stats ───────────────────────────────────────────────────────────────
async function loadDemoStats() {
  try {
    const data = await apiFetch('/api/stats');
    const set = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
    set('stat-service-count', data.services_count);
    set('stat-endpoints-count', data.endpoints_count);
    set('stat-documented-count', data.documented_count);
    set('stat-undocumented-count', data.undocumented_count);
    // accent pill: remove accent if nothing undocumented
    const pill = document.querySelector('#stat-undocumented-count')?.closest('.demo-stat-pill');
    if (pill) pill.classList.toggle('accent', data.undocumented_count > 0);
  } catch (e) {
    console.warn('Could not load demo stats:', e.message);
  }
}

// ─── Services Tab ─────────────────────────────────────────────────────────────
let currentServiceId = null;

async function loadServices() {
  const list = document.getElementById('services-list');
  list.innerHTML = '<div class="loading"><span class="spinner"></span> Loading…</div>';
  try {
    const data = await apiFetch('/api/services');
    if (!data.services.length) {
      list.innerHTML = '<div class="loading">No services yet. Ingest an artifact to get started.</div>';
      return;
    }
    list.innerHTML = data.services.map(s => `
      <div class="service-card" onclick="openService('${s.service_id}')">
        <div class="service-card-header">
          <h3>${s.name}</h3>
          <span class="badge accent">${s.latest_version}</span>
        </div>
        <p>${s.service_id}</p>
        <div class="service-card-meta">
          ${(s.has_doc || s.has_documentation) ? '<span class="badge success">Documented</span>' : '<span class="badge danger">No Docs</span>'}
          ${(s.last_doc_at || s.last_updated) ? `<span class="badge">Updated ${new Date(s.last_doc_at || s.last_updated).toLocaleDateString()}</span>` : ''}
        </div>
      </div>
    `).join('');
  } catch (e) {
    list.innerHTML = `<div class="loading" style="color:var(--danger)">${e.message}</div>`;
  }
}

async function openService(serviceId) {
  currentServiceId = serviceId;
  document.getElementById('services-list').classList.add('hidden');
  const panel = document.getElementById('service-detail');
  panel.classList.remove('hidden');

  // Always reset to Overview inner tab when opening a service
  switchInnerTab('overview');

  document.getElementById('detail-name').textContent = serviceId;
  document.getElementById('detail-version').textContent = 'Loading…';
  document.getElementById('doc-summary').textContent = 'Loading documentation…';
  document.getElementById('doc-description').textContent = '';
  document.getElementById('doc-capabilities').innerHTML = '';
  document.getElementById('doc-auth').textContent = '';
  document.getElementById('endpoints-list').innerHTML = '';

  document.getElementById('btn-generate').onclick = () => generateDocForService(serviceId);
  document.getElementById('btn-publish').onclick = () => publishService(serviceId);

  try {
    const doc = await apiFetch(`/api/services/${serviceId}/doc`);
    renderServiceDoc(doc);
  } catch (e) {
    if (e.message.includes('No documentation')) {
      document.getElementById('doc-summary').textContent = 'No documentation yet. Click "Generate Docs" to create AI-powered documentation.';
      const svc = await apiFetch(`/api/services/${serviceId}`);
      document.getElementById('detail-name').textContent = svc.name;
      document.getElementById('detail-version').textContent = svc.latest_version;
    } else {
      showToast(e.message, 'error');
    }
  }
}

function renderServiceDoc(doc) {
  document.getElementById('detail-name').textContent = doc.name;
  document.getElementById('detail-version').textContent = doc.version;
  document.getElementById('doc-summary').textContent = doc.summary || 'No summary available.';
  document.getElementById('doc-description').textContent = doc.description || '';
  document.getElementById('doc-auth').textContent = doc.authentication_requirements || 'Not specified.';

  const caps = document.getElementById('doc-capabilities');
  caps.innerHTML = (doc.capabilities || []).map(c => `<li>${c}</li>`).join('') || '<li>No capabilities listed.</li>';

  const epList = document.getElementById('endpoints-list');
  if (!doc.endpoints || !doc.endpoints.length) {
    epList.innerHTML = '<div class="loading">No endpoints documented.</div>';
    return;
  }
  epList.innerHTML = doc.endpoints.map((ep, i) => `
    <div class="endpoint-item">
      <div class="endpoint-header" onclick="toggleEndpoint(${i})">
        <span class="method-badge method-${ep.method}">${ep.method}</span>
        <span class="endpoint-path">${ep.path}</span>
        <span class="endpoint-summary">${ep.summary || ''}</span>
        ${ep.is_deprecated ? '<span class="deprecated-badge">DEPRECATED</span>' : ''}
      </div>
      <div class="endpoint-body" id="ep-body-${i}">
        ${ep.description ? `<p>${ep.description}</p>` : ''}
        ${ep.deprecation_notice ? `<p style="color:var(--warning)">&#9888; ${ep.deprecation_notice}</p>` : ''}
        ${ep.authentication ? `<div style="margin-bottom:12px"><label>Auth</label><br><span class="auth-chip">&#128274; ${ep.authentication}</span></div>` : ''}
        ${ep.sample_request ? `
          <div class="sample-block">
            <label>Sample Request</label>
            <pre>${escHtml(ep.sample_request)}</pre>
          </div>` : ''}
        ${ep.sample_response ? `
          <div class="sample-block">
            <label>Sample Response</label>
            <pre>${escHtml(ep.sample_response)}</pre>
          </div>` : ''}
      </div>
    </div>
  `).join('');
}

function toggleEndpoint(i) {
  const body = document.getElementById(`ep-body-${i}`);
  body.classList.toggle('open');
}

function closeDetail() {
  document.getElementById('service-detail').classList.add('hidden');
  document.getElementById('services-list').classList.remove('hidden');
  currentServiceId = null;
}

async function generateDocForService(serviceId) {
  const btn = document.getElementById('btn-generate');
  setLoading(btn, true, 'Generating…');
  showThinking();
  try {
    // Try cached first; if no cached doc exists, fall back to regenerate
    let data;
    try {
      data = await apiFetch('/api/generate', 'POST', { service_id: serviceId, regenerate: false });
    } catch (e) {
      // If cached lookup failed, try fetching existing doc directly
      data = { doc: await apiFetch(`/api/services/${serviceId}/doc`) };
    }
    if (data.doc) {
      renderServiceDoc(data.doc);
      showToast(data.status === 'cached' ? 'Loaded cached documentation.' : 'Documentation generated!');
    }
  } catch (e) {
    const msg = typeof e.message === 'string' ? e.message : JSON.stringify(e.message);
    showToast('Error: ' + msg, 'error');
  } finally {
    setLoading(btn, false);
    hideThinking();
  }
}

async function publishService(serviceId) {
  const btn = document.getElementById('btn-publish');
  setLoading(btn, true, 'Publishing…');
  try {
    const data = await apiFetch('/api/publish', 'POST', { service_id: serviceId });
    showToast(data.message);
  } catch (e) {
    showToast(e.message, 'error');
  } finally {
    setLoading(btn, false);
  }
}

// ─── Ingest Tab ───────────────────────────────────────────────────────────────
const EXAMPLES = {
  openapi: JSON.stringify({
    openapi: "3.0.0",
    info: { title: "Payment Service", version: "v2", description: "Handles payment processing" },
    servers: [{ url: "https://api.example.com/payments" }],
    paths: {
      "/charge": {
        post: {
          summary: "Create a charge",
          tags: ["Payments"],
          security: [{ bearerAuth: [] }],
          requestBody: {
            content: {
              "application/json": {
                schema: { type: "object", properties: { amount: { type: "integer", example: 1000 }, currency: { type: "string", example: "USD" }, source: { type: "string", example: "tok_visa" } }, required: ["amount", "currency", "source"] }
              }
            }
          },
          responses: { "200": { description: "Charge created", content: { "application/json": { schema: { type: "object", properties: { id: { type: "string", example: "ch_123" }, status: { type: "string", example: "succeeded" } } } } } } }
        }
      },
      "/refunds/{chargeId}": {
        post: {
          summary: "Refund a charge",
          tags: ["Refunds"],
          deprecated: true,
          parameters: [{ name: "chargeId", in: "path", required: true, schema: { type: "string" } }],
          responses: { "200": { description: "Refund processed" } }
        }
      }
    },
    components: { securitySchemes: { bearerAuth: { type: "http", scheme: "bearer" } } }
  }, null, 2),
  logs: JSON.stringify([
    { method: "POST", path: "/charge", status: 200, timestamp: "2024-01-01T10:00:00Z" },
    { method: "GET",  path: "/charges/ch_123", status: 200, timestamp: "2024-01-01T10:01:00Z" },
    { method: "POST", path: "/refunds/ch_456", status: 200, timestamp: "2024-01-01T10:02:00Z" },
    { method: "GET",  path: "/webhooks", status: 404, timestamp: "2024-01-01T10:03:00Z" },
    { method: "POST", path: "/webhooks/register", status: 200, timestamp: "2024-01-01T10:04:00Z" },
  ], null, 2),
  schema: JSON.stringify({ $schema: "http://json-schema.org/draft-07/schema#", title: "ChargeRequest", type: "object", properties: { amount: { type: "integer", description: "Amount in cents", example: 1000 }, currency: { type: "string", description: "ISO 4217 currency code", example: "USD" }, source: { type: "string", description: "Payment token", example: "tok_visa" } }, required: ["amount", "currency", "source"] }, null, 2),
  git: "https://github.com/stripe/stripe-python.git",
  registry: JSON.stringify({ service_id: "payment-service", owner: "payments-team", tier: "critical", sla: "99.99%" }, null, 2),
};

function updateIngestPlaceholder() {
  const type = document.getElementById('ingest-type').value;
  const placeholders = {
    openapi: "Paste your OpenAPI / Swagger spec here (JSON or YAML)…",
    git: "Enter Git repository URL…",
    logs: "Paste HTTP access logs as JSON array or CLF format…",
    schema: "Paste JSON Schema or Avro schema…",
    registry: "Paste registry metadata as JSON…",
  };
  document.getElementById('ingest-content').placeholder = placeholders[type] || '';
  document.getElementById('ingest-result').classList.add('hidden');
}

function loadExample() {
  const type = document.getElementById('ingest-type').value;
  document.getElementById('ingest-content').value = EXAMPLES[type] || '';
  if (!document.getElementById('ingest-service-id').value) {
    document.getElementById('ingest-service-id').value = 'payment-service';
    document.getElementById('ingest-service-name').value = 'Payment Service';
    document.getElementById('ingest-version').value = 'v1';
  }
}

async function ingestArtifact() {
  const btn = document.querySelector('#tab-ingest .btn-primary');
  const serviceId   = document.getElementById('ingest-service-id').value.trim();
  const serviceName = document.getElementById('ingest-service-name').value.trim();
  const version     = document.getElementById('ingest-version').value.trim();
  const type        = document.getElementById('ingest-type').value;
  const content     = document.getElementById('ingest-content').value.trim();
  const resultBox   = document.getElementById('ingest-result');

  if (!serviceId || !serviceName || !version || !content) {
    showToast('All fields are required', 'error'); return;
  }

  setLoading(btn, true, 'Ingesting…');
  resultBox.classList.add('hidden');

  try {
    const data = await apiFetch('/api/ingest', 'POST', {
      service_id: serviceId, service_name: serviceName,
      version, artifact_type: type, content
    });
    resultBox.className = 'result-box success';
    resultBox.textContent = `✓ Ingested successfully!\n\n${JSON.stringify(data, null, 2)}`;
    resultBox.classList.remove('hidden');
    showToast('Artifact ingested!');
  } catch (e) {
    resultBox.className = 'result-box error';
    resultBox.textContent = `Error: ${e.message}`;
    resultBox.classList.remove('hidden');
    showToast(e.message, 'error');
  } finally {
    setLoading(btn, false);
  }
}

// ─── Streaming helper ─────────────────────────────────────────────────────────
async function streamPost(path, body, onChunk) {
  const res = await fetch(API + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || res.statusText);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let accumulated = '';
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    const chunk = decoder.decode(value, { stream: true });
    accumulated += chunk;
    onChunk(chunk, accumulated);
  }
  return accumulated;
}

// ─── Explain Tab ──────────────────────────────────────────────────────────────
async function explainService() {
  const btn = document.querySelector('#tab-explain .btn-primary');
  const serviceId = document.getElementById('explain-service-id').value.trim();
  const version   = document.getElementById('explain-version').value.trim() || undefined;
  const question  = document.getElementById('explain-question').value.trim() || undefined;
  const box       = document.getElementById('explain-result');

  if (!serviceId) { showToast('Service ID is required', 'error'); return; }

  setLoading(btn, true, 'Thinking…');
  showThinking();
  box.textContent = '';
  box.classList.remove('hidden');

  try {
    await streamPost('/api/explain', { service_id: serviceId, version, question },
      (_chunk, all) => { box.textContent = all; }
    );
  } catch (e) {
    box.className = 'result-box error';
    box.textContent = `Error: ${e.message}`;
    showToast(e.message, 'error');
  } finally {
    setLoading(btn, false);
    hideThinking();
  }
}

// ─── Compare Tab ──────────────────────────────────────────────────────────────
async function compareServices() {
  const btn = document.querySelector('#tab-compare .btn-primary');
  const idA  = document.getElementById('compare-id-a').value.trim();
  const verA = document.getElementById('compare-ver-a').value.trim() || undefined;
  const idB  = document.getElementById('compare-id-b').value.trim();
  const verB = document.getElementById('compare-ver-b').value.trim() || undefined;
  const resultDiv = document.getElementById('compare-result');

  if (!idA || !idB) { showToast('Both service IDs are required', 'error'); return; }

  setLoading(btn, true, 'Thinking…');
  showThinking();
  // Keep result hidden until we have parsed data to show
  resultDiv.classList.add('hidden');
  document.getElementById('compare-narrative').textContent = '';
  document.getElementById('compare-similarities').innerHTML = '';
  document.getElementById('compare-differences').innerHTML = '';
  document.getElementById('compare-recommendation').innerHTML = '';

  try {
    // Silently accumulate the streamed JSON — don't show raw text
    const raw = await streamPost(
      '/api/compare',
      { service_id_a: idA, version_a: verA, service_id_b: idB, version_b: verB },
      () => {}
    );

    const start = raw.indexOf('{');
    const end   = raw.lastIndexOf('}') + 1;
    const c = JSON.parse(raw.slice(start, end));

    document.getElementById('compare-narrative').textContent = c.comparison_narrative || '';
    document.getElementById('compare-similarities').innerHTML =
      (c.similarities || []).map(s => `<li>${s}</li>`).join('');
    document.getElementById('compare-differences').innerHTML =
      (c.differences || []).map(d => `<li>${d}</li>`).join('');
    document.getElementById('compare-recommendation').innerHTML =
      c.recommendation ? `<strong>Recommendation:</strong> ${c.recommendation}` : '';

    resultDiv.classList.remove('hidden');
  } catch (e) {
    showToast(e.message, 'error');
  } finally {
    setLoading(btn, false);
    hideThinking();
  }
}

// ─── Changelog Tab ────────────────────────────────────────────────────────────
async function generateChangelog() {
  const btn = document.querySelector('#tab-changelog .btn-primary');
  const serviceId  = document.getElementById('changelog-service-id').value.trim();
  const fromVer    = document.getElementById('changelog-from').value.trim();
  const toVer      = document.getElementById('changelog-to').value.trim();
  const resultDiv  = document.getElementById('changelog-result');

  if (!serviceId || !fromVer || !toVer) {
    showToast('All fields required', 'error'); return;
  }

  setLoading(btn, true, 'Thinking…');
  showThinking();
  resultDiv.classList.add('hidden');

  try {
    const data = await apiFetch('/api/changelog', 'POST', {
      service_id: serviceId, from_version: fromVer, to_version: toVer
    });

    document.getElementById('changelog-summary').textContent = data.summary || '';
    document.getElementById('stat-total').innerHTML =
      `<div class="stat-num">${data.total_changes}</div><div class="stat-label">Total Changes</div>`;
    document.getElementById('stat-breaking').innerHTML =
      `<div class="stat-num" style="color:var(--danger)">${data.breaking_changes_count}</div><div class="stat-label">Breaking</div>`;

    const entries = document.getElementById('changelog-entries');
    entries.innerHTML = (data.changes || []).map(c => `
      <div class="change-entry">
        <span class="change-type-badge type-${c.change_type}">${c.change_type}</span>
        <div class="change-content">
          ${c.path ? `<div class="change-path">${c.path}</div>` : ''}
          <div class="change-desc">
            ${c.description}
            ${c.breaking ? '<span class="breaking-flag">&#9888; BREAKING</span>' : ''}
          </div>
          ${c.details ? `<div class="change-details">${c.details}</div>` : ''}
        </div>
        <span class="badge" style="flex-shrink:0">${c.category}</span>
      </div>
    `).join('') || '<div class="loading">No changes detected.</div>';

    resultDiv.classList.remove('hidden');
  } catch (e) {
    showToast(e.message, 'error');
  } finally {
    setLoading(btn, false);
    hideThinking();
  }
}

// ─── Gap Analysis Tab ─────────────────────────────────────────────────────────
async function analyzeGaps() {
  const btn = document.querySelector('#tab-gaps .btn-primary');
  const serviceId = document.getElementById('gap-service-id').value.trim();
  const version   = document.getElementById('gap-version').value.trim() || undefined;
  const withRecs  = document.getElementById('gap-recommendations').checked;
  const resultDiv = document.getElementById('gap-result');

  if (!serviceId) { showToast('Service ID is required', 'error'); return; }

  setLoading(btn, true, 'Thinking…');
  showThinking();
  resultDiv.classList.add('hidden');

  try {
    const params = new URLSearchParams();
    if (version) params.append('version', version);
    if (withRecs) params.append('with_recommendations', 'true');

    const data = await apiFetch(`/api/services/${serviceId}/gaps?${params}`);

    const pct = data.documentation_coverage_pct ?? 100;
    const sev = data.severity || 'none';
    const sevColors = { none: 'good', low: 'good', medium: 'warn', high: 'bad' };

    document.getElementById('gap-coverage').className = `gap-stat-card ${pct >= 80 ? 'good' : pct >= 60 ? 'warn' : 'bad'}`;
    document.getElementById('gap-coverage').innerHTML =
      `<div class="stat-num">${pct}%</div><div class="stat-label">Coverage</div>`;

    const undocCount = (data.undocumented_endpoints || []).length;
    document.getElementById('gap-undoc-count').className = `gap-stat-card ${undocCount === 0 ? 'good' : undocCount < 5 ? 'warn' : 'bad'}`;
    document.getElementById('gap-undoc-count').innerHTML =
      `<div class="stat-num">${undocCount}</div><div class="stat-label">Undocumented</div>`;

    document.getElementById('gap-severity').className = `gap-stat-card ${sevColors[sev] || 'warn'}`;
    document.getElementById('gap-severity').innerHTML =
      `<div class="stat-num" style="text-transform:capitalize">${sev}</div><div class="stat-label">Severity</div>`;

    document.getElementById('gap-undocumented').innerHTML =
      (data.undocumented_endpoints || []).length === 0
        ? '<div class="loading" style="color:var(--success)">No undocumented endpoints found!</div>'
        : (data.undocumented_endpoints || []).map(ep => `
            <div class="gap-item">
              <div>
                <span class="method-badge method-${ep.method}" style="margin-right:8px">${ep.method}</span>
                <span class="gap-item-path">${ep.path}</span>
              </div>
              <span class="gap-item-hits">${ep.hit_count} hits</span>
            </div>
          `).join('');

    document.getElementById('gap-missing').innerHTML =
      (data.missing_doc_endpoints || []).length === 0
        ? '<div class="loading" style="color:var(--success)">All endpoints have descriptions!</div>'
        : (data.missing_doc_endpoints || []).map(ep => `
            <div class="gap-missing-item">&#9888; ${ep}</div>
          `).join('');

    const recsBox = document.getElementById('gap-recommendations-box');
    if (data.recommendations) {
      recsBox.textContent = data.recommendations;
      recsBox.classList.remove('hidden');
    } else {
      recsBox.classList.add('hidden');
    }

    resultDiv.classList.remove('hidden');
  } catch (e) {
    showToast(e.message, 'error');
  } finally {
    setLoading(btn, false);
    hideThinking();
  }
}

// ─── Helpers ──────────────────────────────────────────────────────────────────
function escHtml(str) {
  if (!str) return '';
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// ─── Init ─────────────────────────────────────────────────────────────────────
// Start on Demo tab; load services in background for stats
switchTab('demo');
loadServices();
