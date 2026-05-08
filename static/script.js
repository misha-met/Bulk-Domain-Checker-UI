// Bulk Domain Checker monochrome terminal-themed frontend.

const $ = (id) => document.getElementById(id);

// DOM
const checkBtn = $('check-btn');
const cancelBtn = $('cancel-btn');
const buttonTextSpan = checkBtn.querySelector('.button-text');
const inputEl = $('domains-input');
const inputMetaText = $('input-meta-text');
const inputMetaExtra = $('input-meta-extra');
const timeoutInput = $('timeout-input');
const workersInput = $('workers-input');
const dnsModeInput = $('dns-mode-input');

const resultsContainer = $('results-container');
const resultsEmpty = $('results-empty');
const resultsTbody = $('results-tbody');
const resultsSearch = $('results-search');
const resultsCount = $('results-count');
const inputPanel = inputEl.closest('.panel');

const downloadButtonsContainer = $('download-buttons-container');
const downloadCsvBtn = $('download-csv-btn');
const downloadJsonBtn = $('download-json-btn');
const downloadTxtBtn = $('download-txt-btn');

const progressBarWrap = $('progress-bar-wrap');
const sparkArea = $('sparkline-area');
const sparkPath = $('sparkline-path');
const toastContainer = $('toast-container');
const clearInputBtn = $('clear-input-btn');
const inputWrap = $('input-wrap');
const postRunActions = $('post-run-actions');
const recheckFailedBtn = $('recheck-failed-btn');
const recheckAllBtn = $('recheck-all-btn');
const ORIGINAL_TITLE = document.title;
const STORAGE_KEY = 'bdc.prefs.v1';
const RESULTS_KEY = 'bdc.lastrun.v1';
const MAX_PERSISTED_RESULTS = 10_000; // ~1.5MB serialized; localStorage cap is ~5MB

const failureReasonsPanel = $('failure-reasons');
const failureReasonsList = $('failure-reasons-list');
const activeFilterPills = $('active-filter-pills');
const resultDetailModal = $('result-detail-modal');
const resultDetailTitle = $('result-detail-title');
const resultDetailSummary = $('result-detail-summary');
const detailOverviewGrid = $('detail-overview-grid');
const detailDnsAddresses = $('detail-dns-addresses');
const detailRedirectChain = $('detail-redirect-chain');
const detailResponseMeta = $('detail-response-meta');
const detailCopyBtn = $('detail-copy-btn');
const detailExportJsonBtn = $('detail-export-json-btn');
const detailExportTxtBtn = $('detail-export-txt-btn');
const detailCloseBtn = $('detail-close-btn');

const terminal = $('terminal');
const logsContainer = $('logs');
const logStatus = $('log-status');

// State
let currentResults = [];
let parsedDomains = [];
let runStartTime = null;
let elapsedTimer = null;
let sparkTimer = null;
let abortController = null;
let isRunning = false;

let sortKey = null;
let sortDir = 1;
let searchQuery = '';
let categoryFilter = null;
let currentRunMeta = {
  total: 0,
  timeout: Number(timeoutInput.value) || 5,
  workers: Number(workersInput.value) || 100,
  dnsMode: dnsModeInput.value || 'system',
  startedAt: null,
};
let selectedDetailDomain = null;
let lastFocusedBeforeModal = null;
let detailAbortController = null;
const detailDiagnosticsCache = new Map();

const speedSamples = [];
const SPARK_WINDOW_SEC = 60;
const ETA_WINDOW = 20;

// Categories follow a scheme where online is green, errors are red, and the rest use grayscale shades.
const CATEGORIES = {
  online:      { label: 'Online',      color: '#4ade80', dim: 'rgba(74,222,128,0.15)' },
  http_error:  { label: 'HTTP Error',  color: '#9ca3af', dim: 'rgba(156,163,175,0.15)' },
  timeout:     { label: 'Timeout',     color: '#737373', dim: 'rgba(115,115,115,0.15)' },
  dns:         { label: 'DNS Failed',  color: '#a3a3a3', dim: 'rgba(163,163,163,0.15)' },
  connection:  { label: 'Connection',  color: '#525252', dim: 'rgba(82,82,82,0.15)' },
  ssl:         { label: 'SSL / TLS',   color: '#ef4444', dim: 'rgba(239,68,68,0.15)' },
  other:       { label: 'Other',       color: '#404040', dim: 'rgba(64,64,64,0.15)' },
};

// ---------- Input parsing ----------
const VALID_HOST_RE = /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$/i;

function parseInput(raw) {
  let candidates = [];
  const trimmed = raw.trim();
  if (trimmed.startsWith('[') && trimmed.endsWith(']')) {
    try {
      const arr = JSON.parse(trimmed);
      if (Array.isArray(arr)) candidates = arr.map(String);
    } catch { /* fall through */ }
  }
  if (!candidates.length) candidates = raw.split(/[\s,;|]+/);

  const seen = new Set();
  const valid = [];
  let duplicates = 0;
  let invalid = 0;
  for (let token of candidates) {
    token = token.trim();
    if (!token) continue;
    // Normalize but preserve subdomains. www.foo.com and foo.com can
    // resolve differently, have different certs, or redirect differently,
    // stripping www. silently lies about what's being checked.
    let host = token;
    if (host.includes('://')) host = host.split('://')[1];
    host = host.split('/')[0].split('?')[0].split('#')[0].split(':')[0];
    host = host.toLowerCase();
    if (!host) continue;
    if (!VALID_HOST_RE.test(host)) { invalid++; continue; }
    if (seen.has(host)) { duplicates++; continue; }
    seen.add(host);
    valid.push(host);
  }
  return { domains: valid, duplicates, invalid };
}

function updateInputMeta() {
  const { domains, duplicates, invalid } = parseInput(inputEl.value);
  parsedDomains = domains;
  inputWrap.classList.toggle('has-text', inputEl.value.length > 0);
  if (!domains.length && !duplicates && !invalid) {
    inputMetaText.textContent = 'awaiting input…';
    inputMetaText.style.color = '';
    inputMetaExtra.textContent = '';
    return;
  }
  inputMetaText.innerHTML = `<span class="meta-ok">${domains.length.toLocaleString()} unique domain${domains.length === 1 ? '' : 's'}</span>`;
  const bits = [];
  if (duplicates) bits.push(`${duplicates} dupe${duplicates === 1 ? '' : 's'} removed`);
  if (invalid) bits.push(`${invalid} invalid skipped`);
  inputMetaExtra.textContent = bits.join(' · ');
}

inputEl.addEventListener('input', updateInputMeta);
clearInputBtn.addEventListener('click', () => {
  inputEl.value = '';
  updateInputMeta();
  inputEl.focus();
});

// ---------- Drag and drop ----------
['dragenter', 'dragover'].forEach(evt => {
  inputPanel.addEventListener(evt, (e) => {
    e.preventDefault(); e.stopPropagation();
    inputEl.classList.add('dropzone-active');
  });
});
['dragleave', 'drop'].forEach(evt => {
  inputPanel.addEventListener(evt, (e) => {
    e.preventDefault(); e.stopPropagation();
    inputEl.classList.remove('dropzone-active');
  });
});
inputPanel.addEventListener('drop', async (e) => {
  const file = e.dataTransfer.files?.[0];
  if (!file) return;
  const text = await file.text();
  if (file.name.endsWith('.json')) {
    try {
      const data = JSON.parse(text);
      if (Array.isArray(data)) {
        const lines = data.map(item => {
          if (typeof item === 'string') return item;
          if (item && typeof item === 'object') return item.domain || item.host || item.url || '';
          return '';
        }).filter(Boolean);
        inputEl.value = (inputEl.value ? inputEl.value + '\n' : '') + lines.join('\n');
        updateInputMeta();
        return;
      }
    } catch { /* fall through */ }
  }
  inputEl.value = (inputEl.value ? inputEl.value + '\n' : '') + text;
  updateInputMeta();
});

// ---------- Unified progress + status bar ----------
// Renders one stacked bar: online segment + each failure category segment +
// an "unchecked remainder" portion that shrinks as checks complete.  Width
// percentages are based on the total domain count, so the filled portion
// directly conveys progress.
function renderProgressBar(total) {
  const counts = countsByCategory();
  const denom = total || Object.values(counts).reduce((a, b) => a + b, 0) || 1;
  const failures = Object.entries(counts)
    .filter(([k]) => k !== 'online')
    .sort((a, b) => b[1] - a[1]);
  const order = [];
  if (counts.online) order.push(['online', counts.online]);
  for (const f of failures) order.push(f);

  const segments = order.map(([cat, n]) => {
    const info = CATEGORIES[cat] || CATEGORIES.other;
    const pct = (n / denom) * 100;
    const dim = (categoryFilter && categoryFilter !== cat) ? 'dim' : '';
    return `<div class="progress-seg ${cat} ${dim}" data-cat="${cat}" style="width:${pct}%;background:${info.color}" title="${info.label}: ${n.toLocaleString()}"></div>`;
  }).join('');
  progressBarWrap.innerHTML = segments;
  progressBarWrap.querySelectorAll('[data-cat]').forEach(seg => {
    if (seg.dataset.cat !== 'online') {
      seg.addEventListener('click', () => toggleCategoryFilter(seg.dataset.cat));
    }
  });
}

// ---------- Sparkline ----------
function renderSparkline() {
  if (!speedSamples.length) {
    sparkPath.setAttribute('d', '');
    sparkArea.setAttribute('d', '');
    return;
  }
  const W = 400, H = 40, PAD = 1;
  const recent = speedSamples.slice(-120);
  const maxSpeed = Math.max(1, ...recent.map(s => s.speed));
  const minT = recent[0].t;
  const maxT = Math.max(recent[recent.length - 1].t, minT + 1);
  const dx = (W - 2 * PAD) / Math.max(1, maxT - minT);

  let d = '', area = '';
  recent.forEach((s, i) => {
    const x = PAD + (s.t - minT) * dx;
    const y = H - PAD - (s.speed / maxSpeed) * (H - 2 * PAD);
    d += (i === 0 ? 'M' : 'L') + x.toFixed(1) + ',' + y.toFixed(1) + ' ';
    if (i === 0) area = `M${x.toFixed(1)},${H} L${x.toFixed(1)},${y.toFixed(1)} `;
    else area += `L${x.toFixed(1)},${y.toFixed(1)} `;
  });
  const lastX = PAD + (recent[recent.length - 1].t - minT) * dx;
  area += `L${lastX.toFixed(1)},${H} Z`;
  sparkPath.setAttribute('d', d);
  sparkArea.setAttribute('d', area);
}

// ---------- Helpers ----------
function statusBadge(r) {
  if (r.ok) return `<span class="badge badge-online">${CATEGORIES.online.label}</span>`;
  if (r.category === 'ssl') return `<span class="badge badge-error">${CATEGORIES.ssl.label}</span>`;
  return `<span class="badge badge-offline">${prettyCategory(r.category)}</span>`;
}
function prettyCategory(c) { return CATEGORIES[c]?.label || 'Offline'; }

function fmtMs(ms) {
  if (ms == null) return '<span style="color:var(--text-muted)">-</span>';
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(2)} s`;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

function describeOutcome(result) {
  if (result.ok) return CATEGORIES.online.label;
  return prettyCategory(result.category);
}

function describeRequestPath(result) {
  const attempts = result.attempted_protocols || [];
  if (attempts.length > 1) return attempts.join(' -> ');
  if (attempts.length === 1) return attempts[0];
  if (result.category === 'dns') return 'dns only';
  return result.protocol || '-';
}

function describeResultSummary(result) {
  if (result.ok) {
    const proto = result.protocol ? result.protocol.toUpperCase() : 'HTTP';
    const status = result.status_code != null ? `status ${result.status_code}` : 'a valid response';
    const speed = result.elapsed_ms != null ? ` in ${fmtMs(result.elapsed_ms)}` : '';
    return `${proto} returned ${status}${speed}.`;
  }
  if (result.category === 'dns') {
    return `${result.detail || 'DNS resolution failed'} before an HTTP request could begin.`;
  }
  if (result.category === 'ssl') {
    return `The hostname resolved, but TLS failed before the site could be considered browser-safe.`;
  }
  if (result.category === 'http_error') {
    const proto = result.protocol ? result.protocol.toUpperCase() : 'HTTP';
    return `${proto} reached the server, but it answered with ${result.detail || 'an error status'}.`;
  }
  if (result.category === 'timeout') {
    return `The hostname resolved, but no usable response arrived before the timeout window closed.`;
  }
  if (result.category === 'connection') {
    return `The hostname resolved, but the connection could not be established cleanly.`;
  }
  return result.detail || 'The check failed without a usable HTTP response.';
}

function dnsModeLabel(mode) {
  return mode === 'direct' ? 'Public Direct' : 'System';
}

function getRunMeta() {
  return {
    total: currentRunMeta.total || currentRunTotal || currentResults.length,
    timeout: currentRunMeta.timeout ?? (Number(timeoutInput.value) || 5),
    workers: currentRunMeta.workers ?? (Number(workersInput.value) || 100),
    dnsMode: currentRunMeta.dnsMode || dnsModeInput.value || 'system',
    startedAt: currentRunMeta.startedAt || null,
  };
}

function detailExportPayload(result) {
  const runMeta = getRunMeta();
  const diagnostics = detailDiagnosticsCache.get(result.domain) || null;
  const overview = {
    outcome: describeOutcome(result),
    request_path: describeRequestPath(result),
    dns_mode: dnsModeLabel(runMeta.dnsMode),
    timeout_seconds: runMeta.timeout,
    concurrency: runMeta.workers,
    batch_total: runMeta.total,
  };
  return {
    summary: describeResultSummary(result),
    overview,
    result: {
      domain: result.domain,
      ok: result.ok,
      detail: result.detail,
      category: result.category,
      status_code: result.status_code ?? null,
      elapsed_ms: result.elapsed_ms ?? null,
      protocol: result.protocol ?? null,
      dns_addresses: result.dns_addresses ?? [],
      attempted_protocols: result.attempted_protocols ?? [],
      request_method: result.request_method ?? null,
      http_version: result.http_version ?? null,
      redirect_location: result.redirect_location ?? null,
      server: result.server ?? null,
      content_type: result.content_type ?? null,
    },
    diagnostics: diagnostics ? {
      final_url: diagnostics.final_url ?? null,
      final_status_code: diagnostics.final_status_code ?? null,
      redirect_count: diagnostics.redirect_count ?? null,
      chain: diagnostics.chain ?? [],
    } : null,
    run: {
      started_at: runMeta.startedAt ? new Date(runMeta.startedAt).toISOString() : null,
      total_domains: runMeta.total,
      timeout_seconds: runMeta.timeout,
      workers: runMeta.workers,
      dns_mode: runMeta.dnsMode,
    },
  };
}

function detailExportText(result) {
  const payload = detailExportPayload(result);
  const lines = [
    'Bulk Domain Checker Detailed Result',
    '',
    `Domain: ${result.domain}`,
    `Outcome: ${payload.overview.outcome}`,
    `Detail: ${result.detail || '-'}`,
    `Request Path: ${payload.overview.request_path}`,
    `DNS Mode: ${payload.overview.dns_mode}`,
    `Protocol: ${result.protocol || '-'}`,
    `Method: ${result.request_method || '-'}`,
    `Status Code: ${result.status_code ?? '-'}`,
    `Elapsed: ${result.elapsed_ms != null ? `${result.elapsed_ms} ms` : '-'}`,
    `HTTP Version: ${result.http_version || '-'}`,
    `Server: ${result.server || '-'}`,
    `Content-Type: ${result.content_type || '-'}`,
    `Redirect Location: ${result.redirect_location || '-'}`,
    `Resolved Addresses: ${(result.dns_addresses || []).join(', ') || '-'}`,
    `Attempted Protocols: ${(result.attempted_protocols || []).join(' -> ') || '-'}`,
  ];
  if (payload.diagnostics?.final_url) lines.push(`Final URL: ${payload.diagnostics.final_url}`);
  if (payload.diagnostics?.final_status_code != null) lines.push(`Final Status Code: ${payload.diagnostics.final_status_code}`);
  if (payload.diagnostics?.redirect_count != null) lines.push(`Redirect Count: ${payload.diagnostics.redirect_count}`);
  if (payload.diagnostics?.chain?.length) {
    lines.push('');
    lines.push('Redirect Chain:');
    for (const hop of payload.diagnostics.chain) {
      lines.push(
        `${hop.step}. ${hop.method || 'HEAD'} ${hop.url} -> ${hop.status_code}${hop.next_url ? ` -> ${hop.next_url}` : ''}`
      );
    }
  }
  lines.push('');
  lines.push(`Run Settings: timeout=${payload.run.timeout_seconds}s | workers=${payload.run.workers} | dns=${payload.run.dns_mode}`);
  if (payload.run.started_at) lines.push(`Run Started At: ${payload.run.started_at}`);
  return lines.join('\n') + '\n';
}

function renderDetailChips(target, values) {
  if (!values?.length) {
    target.innerHTML = '<div class="detail-empty">No address data captured for this result.</div>';
    return;
  }
  target.innerHTML = `<div class="detail-chip-row">${values.map(value => `
    <span class="detail-chip">${escapeHtml(value)}</span>
  `).join('')}</div>`;
}

function renderRedirectChain(data) {
  if (!data) {
    detailRedirectChain.innerHTML = '<div class="detail-empty">Redirect diagnostics are unavailable for this result.</div>';
    return;
  }
  if (!data.chain?.length) {
    const reason = data.error
      ? escapeHtml(data.error)
      : 'No HTTP response was captured, so there is no redirect chain to inspect.';
    detailRedirectChain.innerHTML = `<div class="detail-empty">${reason}</div>`;
    return;
  }

  const summaryBits = [];
  if (data.redirect_count != null) summaryBits.push(`${data.redirect_count} Redirect${data.redirect_count === 1 ? '' : 's'}`);
  if (data.final_url) summaryBits.push(`Final URL: ${data.final_url}`);

  detailRedirectChain.innerHTML = `
    ${summaryBits.length ? `<div class="detail-empty" style="margin-bottom:.75rem">${escapeHtml(summaryBits.join(' · '))}</div>` : ''}
    <div class="redirect-chain-list">
      ${data.chain.map(hop => `
        <div class="redirect-hop">
          <div class="redirect-hop-step">${hop.step}</div>
          <div class="redirect-hop-main">
            <div class="redirect-hop-url">${escapeHtml(`${hop.method || 'HEAD'} ${hop.url}`)}</div>
            <div class="redirect-hop-next">${hop.next_url ? `Next: ${escapeHtml(hop.next_url)}` : 'Final response'}</div>
          </div>
          <div class="redirect-hop-status">${escapeHtml(String(hop.status_code))}</div>
        </div>
      `).join('')}
    </div>
  `;
}

function renderDetailMeta(result, diagnostics = null) {
  const meta = [
    ['Request Method', result.request_method],
    ['HTTP Version', result.http_version],
    ['Redirect Location', result.redirect_location],
    ['Server Header', result.server],
    ['Content-Type', result.content_type],
    ['Attempted Protocols', (result.attempted_protocols || []).join(' -> ') || null],
    ['Final URL', diagnostics?.final_url || null],
    ['Redirect Count', diagnostics?.redirect_count != null ? String(diagnostics.redirect_count) : null],
  ].filter(([, value]) => value);

  if (!meta.length) {
    detailResponseMeta.innerHTML = '<div class="detail-empty">No extra response metadata was available for this result.</div>';
    return;
  }

  detailResponseMeta.innerHTML = meta.map(([label, value]) => `
    <div class="detail-meta-item">
      <div class="detail-meta-label">${escapeHtml(label)}</div>
      <div class="detail-meta-value">${escapeHtml(value)}</div>
    </div>
  `).join('');
}

function countsByCategory() {
  const out = {};
  for (const r of currentResults) out[r.category] = (out[r.category] || 0) + 1;
  return out;
}

function buildResultRow(result, extraClass = '') {
  return `
    <tr class="${extraClass}" data-domain="${escapeHtml(result.domain)}" tabindex="0" aria-label="View details for ${escapeHtml(result.domain)}">
      <td>${escapeHtml(result.domain)}</td>
      <td>${statusBadge(result)}</td>
      <td>${escapeHtml(result.detail || '')}</td>
      <td>${fmtMs(result.elapsed_ms)}</td>
      <td>
        <button class="btn btn-ghost btn-sm row-copy-btn" type="button" data-action="copy" data-domain="${escapeHtml(result.domain)}">Copy</button>
      </td>
    </tr>
  `;
}

function createResultRowElement(result, extraClass = '') {
  const tr = document.createElement('tr');
  if (extraClass) tr.className = extraClass;
  tr.dataset.domain = result.domain;
  tr.tabIndex = 0;
  tr.setAttribute('aria-label', `View details for ${result.domain}`);
  tr.innerHTML = `
    <td>${escapeHtml(result.domain)}</td>
    <td>${statusBadge(result)}</td>
    <td>${escapeHtml(result.detail || '')}</td>
    <td>${fmtMs(result.elapsed_ms)}</td>
    <td>
      <button class="btn btn-ghost btn-sm row-copy-btn" type="button" data-action="copy" data-domain="${escapeHtml(result.domain)}">Copy</button>
    </td>
  `;
  return tr;
}

function getResultByDomain(domain) {
  return currentResults.find(r => r.domain === domain) || null;
}

function closeDetailModal() {
  if (detailAbortController) {
    detailAbortController.abort();
    detailAbortController = null;
  }
  if (resultDetailModal.classList.contains('hidden')) return;
  resultDetailModal.classList.add('hidden');
  resultDetailModal.setAttribute('aria-hidden', 'true');
  document.body.classList.remove('modal-open');
  selectedDetailDomain = null;
  if (lastFocusedBeforeModal && typeof lastFocusedBeforeModal.focus === 'function') {
    lastFocusedBeforeModal.focus();
  }
  lastFocusedBeforeModal = null;
}

async function loadDetailDiagnostics(result) {
  const cached = detailDiagnosticsCache.get(result.domain);
  if (cached) {
    renderRedirectChain(cached);
    renderDetailMeta(result, cached);
    return;
  }

  if (!(result.protocol || result.status_code != null)) {
    renderRedirectChain({
      error: 'No successful HTTP response was captured for this result, so there is no redirect chain to inspect.',
      chain: [],
    });
    renderDetailMeta(result);
    return;
  }

  if (detailAbortController) detailAbortController.abort();
  detailAbortController = new AbortController();
  const controller = detailAbortController;
  renderRedirectChain({ error: 'Loading redirect chain…', chain: [] });

  try {
    const runMeta = getRunMeta();
    const response = await fetch('/inspect', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        domain: result.domain,
        timeout: runMeta.timeout,
        dns_mode: runMeta.dnsMode,
        protocol: result.protocol || undefined,
      }),
      signal: controller.signal,
    });
    if (!response.ok) {
      const errTxt = await response.text().catch(() => '');
      throw new Error(`Inspect failed: ${response.status} ${errTxt.slice(0, 120)}`.trim());
    }
    const diagnostics = await response.json();
    if (controller !== detailAbortController || selectedDetailDomain !== result.domain) return;
    detailDiagnosticsCache.set(result.domain, diagnostics);
    renderRedirectChain(diagnostics);
    renderDetailMeta(result, diagnostics);
  } catch (err) {
    if (err.name === 'AbortError') return;
    if (controller !== detailAbortController || selectedDetailDomain !== result.domain) return;
    renderRedirectChain({
      error: err.message || 'Redirect diagnostics could not be loaded.',
      chain: [],
    });
    renderDetailMeta(result);
  } finally {
    if (controller === detailAbortController) detailAbortController = null;
  }
}

function openDetailModal(result, triggerEl = null) {
  if (!result) return;
  lastFocusedBeforeModal = triggerEl || document.activeElement;
  selectedDetailDomain = result.domain;
  const runMeta = getRunMeta();
  const overviewCards = [
    ['Outcome', describeOutcome(result)],
    ['Detail', result.detail || '-'],
    ['Request Path', describeRequestPath(result)],
    ['Response Time', result.elapsed_ms != null ? `${result.elapsed_ms} ms` : '-'],
    ['HTTP Status', result.status_code != null ? String(result.status_code) : '-'],
    ['Protocol', result.protocol || '-'],
    ['DNS Mode', dnsModeLabel(runMeta.dnsMode)],
    ['Run Settings', `${runMeta.timeout}s timeout · ${runMeta.workers} workers`],
  ];

  resultDetailTitle.textContent = result.domain;
  resultDetailSummary.textContent = describeResultSummary(result);
  detailOverviewGrid.innerHTML = overviewCards.map(([label, value]) => `
    <div class="detail-card">
      <div class="detail-card-label">${escapeHtml(label)}</div>
      <div class="detail-card-value${value === '-' ? ' muted' : ''}">${escapeHtml(value)}</div>
    </div>
  `).join('');
  renderDetailChips(detailDnsAddresses, result.dns_addresses || []);
  renderDetailMeta(result);
  renderRedirectChain({ error: 'Loading redirect chain…', chain: [] });

  resultDetailModal.classList.remove('hidden');
  resultDetailModal.setAttribute('aria-hidden', 'false');
  document.body.classList.add('modal-open');
  detailCopyBtn.focus();
  loadDetailDiagnostics(result);
}

function getVisibleResults() {
  let rows = currentResults;
  if (categoryFilter) rows = rows.filter(r => r.category === categoryFilter);
  if (searchQuery) {
    const q = searchQuery.toLowerCase();
    rows = rows.filter(r => r.domain.toLowerCase().includes(q) || (r.detail || '').toLowerCase().includes(q));
  }
  if (sortKey) {
    rows = rows.slice().sort((a, b) => {
      let av = a[sortKey], bv = b[sortKey];
      if (sortKey === 'ok') { av = a.ok ? 1 : 0; bv = b.ok ? 1 : 0; }
      if (av == null) av = '';
      if (bv == null) bv = '';
      if (typeof av === 'number' && typeof bv === 'number') return (av - bv) * sortDir;
      return String(av).localeCompare(String(bv)) * sortDir;
    });
  }
  return rows;
}

let renderScheduled = false;
function scheduleRender() {
  if (renderScheduled) return;
  renderScheduled = true;
  requestAnimationFrame(() => {
    renderTable();
    renderScheduled = false;
  });
}

let lastRenderCount = 0;
function renderTable() {
  const rows = getVisibleResults();
  const MAX = 5000;
  const visible = rows.slice(0, MAX);
  // If we're filtering / sorting / searching, do a full rewrite (no animation).
  // If results are simply growing in their natural order, append only the new
  // rows so we can mark them with the .appear animation class.
  const isAppendOnly = !categoryFilter && !searchQuery && !sortKey
    && visible.length >= lastRenderCount
    && visible.length === currentResults.length;
  if (isAppendOnly && lastRenderCount > 0 && visible.length > lastRenderCount) {
    const frag = document.createDocumentFragment();
    for (let i = lastRenderCount; i < visible.length; i++) {
      const r = visible[i];
      frag.appendChild(createResultRowElement(r, 'appear'));
    }
    resultsTbody.appendChild(frag);
    lastRenderCount = visible.length;
  } else {
    resultsTbody.innerHTML = visible.map(r => buildResultRow(r)).join('');
    lastRenderCount = visible.length;
  }

  updateResultsCount(rows, MAX);

  document.querySelectorAll('th[data-sort]').forEach(th => {
    th.classList.toggle('active', th.dataset.sort === sortKey);
    const arrow = th.querySelector('.sort-arrow');
    if (arrow) arrow.textContent = th.dataset.sort === sortKey ? (sortDir > 0 ? '↑' : '↓') : '↕';
  });
}

function updateResultsCount(rows, MAX) {
  const totalText = currentResults.length === 1 ? '1 Result' : `${currentResults.length.toLocaleString()} Results`;
  if (rows.length === currentResults.length) {
    resultsCount.textContent = totalText;
  } else {
    resultsCount.textContent = `${rows.length.toLocaleString()} of ${currentResults.length.toLocaleString()}`;
  }
  if (rows.length > MAX) {
    resultsCount.textContent += ` (Showing ${MAX.toLocaleString()})`;
  }
}

// Sort + search wires
document.querySelectorAll('th[data-sort]').forEach(th => {
  th.addEventListener('click', () => {
    const k = th.dataset.sort;
    if (sortKey === k) sortDir = -sortDir;
    else { sortKey = k; sortDir = 1; }
    scheduleRender();
  });
});
resultsSearch.addEventListener('input', (e) => {
  searchQuery = e.target.value;
  scheduleRender();
});

// ---------- Failure reasons ----------
function renderFailureReasons() {
  const counts = {};
  for (const r of currentResults) {
    if (!r.ok) counts[r.category] = (counts[r.category] || 0) + 1;
  }
  const entries = Object.entries(counts).sort((a, b) => b[1] - a[1]);
  if (!entries.length) {
    failureReasonsPanel.classList.add('hidden');
    return;
  }
  failureReasonsPanel.classList.remove('hidden');
  const totalFails = entries.reduce((a, [, n]) => a + n, 0);
  failureReasonsList.innerHTML = entries.map(([cat, n]) => {
    const info = CATEGORIES[cat] || CATEGORIES.other;
    const active = categoryFilter === cat;
    const pct = (n / totalFails) * 100;
    return `
      <div class="reason-row${active ? ' active' : ''}" data-cat="${cat}">
        <span style="display:flex;align-items:center"><span class="mark"></span>${info.label}</span>
        <span class="reason-bar"><span class="reason-bar-fill" style="width:${pct.toFixed(1)}%"></span></span>
        <span class="reason-count">${n.toLocaleString()}</span>
      </div>
    `;
  }).join('');
  failureReasonsList.querySelectorAll('[data-cat]').forEach(row => {
    row.addEventListener('click', () => toggleCategoryFilter(row.dataset.cat));
  });
}

function toggleCategoryFilter(cat) {
  categoryFilter = (categoryFilter === cat) ? null : cat;
  updateFilterPills();
  scheduleRender();
  renderFailureReasons();
  renderProgressBar(currentRunTotal);
}

let currentRunTotal = 0;

function updateFilterPills() {
  if (!categoryFilter) { activeFilterPills.innerHTML = ''; return; }
  const info = CATEGORIES[categoryFilter] || CATEGORIES.other;
  activeFilterPills.innerHTML = `
    <span class="filter-pill">${info.label}<button id="clear-filter-btn" title="Clear filter">×</button></span>
  `;
  $('clear-filter-btn').addEventListener('click', () => toggleCategoryFilter(categoryFilter));
}

// ---------- Stats ----------
function updateStats(total) {
  const checked = currentResults.length;
  const online = currentResults.filter(r => r.ok).length;
  const failed = checked - online;
  $('stat-total-value').textContent = total.toLocaleString();
  $('stat-checked-value').textContent = checked.toLocaleString();
  $('stat-checked-percent').textContent = total > 0 ? `${Math.round((checked / total) * 100)}%` : '0%';
  $('stat-online-value').textContent = online.toLocaleString();
  $('stat-online-percent').textContent = checked > 0 ? `${Math.round((online / checked) * 100)}%` : '0%';
  $('stat-failed-value').textContent = failed.toLocaleString();
  $('stat-failed-percent').textContent = checked > 0 ? `${Math.round((failed / checked) * 100)}%` : '0%';

  const elapsedSec = (performance.now() - runStartTime) / 1000;
  const speed = elapsedSec > 0 ? checked / elapsedSec : 0;
  $('stat-speed-value').textContent = speed.toFixed(1);

  const recent = speedSamples.slice(-ETA_WINDOW);
  const recentSpeed = recent.length ? recent[recent.length - 1].speed : speed;
  const remaining = total - checked;
  if (recentSpeed > 0 && remaining > 0) {
    $('stat-eta-value').textContent = formatDuration(remaining / recentSpeed);
  } else if (remaining === 0 && total > 0) {
    $('stat-eta-value').textContent = 'Done';
  } else {
    $('stat-eta-value').textContent = '-';
  }

  // Update tab title to mirror progress on long runs.
  if (isRunning && total > 0) {
    document.title = `${checked}/${total} · ${ORIGINAL_TITLE}`;
  }
}

function formatDuration(sec) {
  if (!isFinite(sec) || sec < 0) return '-';
  if (sec < 1) return '<1s';
  if (sec < 60) return `${Math.round(sec)}s`;
  const m = Math.floor(sec / 60);
  const s = Math.round(sec % 60);
  return `${m}m ${s}s`;
}

// ---------- Run flow ----------
async function startRun() {
  if (isRunning) return;
  updateInputMeta();
  const domains = parsedDomains;
  if (!domains.length) return;
  closeDetailModal();

  // Reset
  currentResults = [];
  speedSamples.length = 0;
  detailDiagnosticsCache.clear();
  categoryFilter = null;
  searchQuery = '';
  sortKey = null;
  sortDir = 1;
  resultsSearch.value = '';
  isRunning = true;

  resultsTbody.innerHTML = '';
  lastRenderCount = 0;
  postRunActions.classList.add('hidden');
  resultsContainer.classList.remove('hidden');
  resultsEmpty.classList.add('hidden');
  progressBarWrap.classList.add('shimmer');
  progressBarWrap.innerHTML = '';
  currentRunTotal = domains.length;
  currentRunMeta = {
    total: domains.length,
    timeout: parseFloat(timeoutInput.value) || 5,
    workers: parseInt(workersInput.value) || 100,
    dnsMode: dnsModeInput.value || 'system',
    startedAt: Date.now(),
  };
  downloadButtonsContainer.classList.add('hidden');
  failureReasonsPanel.classList.add('hidden');
  updateFilterPills();

  checkBtn.disabled = true;
  buttonTextSpan.innerHTML = '<span class="btn-shine">Checking…</span>';
  cancelBtn.classList.remove('hidden');

  terminal.classList.add('active');
  logsContainer.innerHTML = '';
  logStatus.textContent = 'Streaming…';

  const banner = [
    '  ___                 _         ___ _           _           ',
    ' |   \\ ___ _ __  __ _(_)_ _    / __| |_  ___ __| |_____ _ _ ',
    ' | |) / _ \\ \'  \\/ _` | | \' \\  | (__| \' \\/ -_) _| / / -_) \'_|',
    ' |___/\\___/_|_|_\\__,_|_|_||_|  \\___|_||_\\___\\__|_\\_\\___|_|  ',
    '                                                             '
  ];
  for (const line of banner) {
    const pre = document.createElement('pre');
    pre.textContent = line;
    logsContainer.appendChild(pre);
  }
  for (const line of [
    `▸ initializing domain-checker daemon v2.0`,
    `▸ ${domains.length} domain${domains.length === 1 ? '' : 's'} | concurrency=${workersInput.value} | timeout=${timeoutInput.value}s | dns=${dnsModeInput.value}`,
    `▸ ${new Date().toLocaleString()}`,
    ''
  ]) {
    const div = document.createElement('div');
    div.textContent = line;
    div.style.color = 'var(--text-dim)';
    logsContainer.appendChild(div);
  }

  runStartTime = performance.now();
  let lastSampleTime = runStartTime;
  let lastSampleCount = 0;

  if (elapsedTimer) clearInterval(elapsedTimer);
  elapsedTimer = setInterval(() => {
    if (!runStartTime) return;
    const elapsedSec = (performance.now() - runStartTime) / 1000;
    $('stat-elapsed-value').textContent = `${elapsedSec.toFixed(1)}s`;
  }, 100);

  if (sparkTimer) clearInterval(sparkTimer);
  sparkTimer = setInterval(() => {
    const now = performance.now();
    const dt = (now - lastSampleTime) / 1000;
    const dn = currentResults.length - lastSampleCount;
    const inst = dt > 0 ? dn / dt : 0;
    speedSamples.push({ t: (now - runStartTime) / 1000, speed: inst });
    while (speedSamples.length && (now - runStartTime) / 1000 - speedSamples[0].t > SPARK_WINDOW_SEC) {
      speedSamples.shift();
    }
    lastSampleTime = now;
    lastSampleCount = currentResults.length;
    renderSparkline();
  }, 500);

  // Batched flush
  let pending = [];
  let flushScheduled = false;
  function scheduleFlush() {
    if (flushScheduled) return;
    flushScheduled = true;
    setTimeout(flush, 100);
  }
  function flush() {
    flushScheduled = false;
    if (!pending.length) return;
    const ts = new Date();
    const tsStr = `${ts.getHours().toString().padStart(2,'0')}:${ts.getMinutes().toString().padStart(2,'0')}:${ts.getSeconds().toString().padStart(2,'0')}`;
    const frag = document.createDocumentFragment();
    for (const item of pending) {
      currentResults.push(item);
      const status = item.ok ? 'online' : prettyCategory(item.category);
      const color = item.ok ? 'var(--accent)' : (item.category === 'ssl' ? 'var(--error)' : 'var(--text-dim)');
      const ms = item.elapsed_ms != null ? `<span style="color:var(--text-muted)"> [${Math.round(item.elapsed_ms)}ms]</span>` : '';
      const line = document.createElement('div');
      line.innerHTML = `<span style="color:var(--text-muted)">${tsStr}</span> <span style="color:${color}">${status.padEnd(11)}</span> ${escapeHtml(item.domain)} <span style="color:var(--text-muted)">${escapeHtml(item.detail || '')}</span>${ms}`;
      frag.appendChild(line);
    }
    logsContainer.appendChild(frag);
    while (logsContainer.children.length > 800) {
      logsContainer.removeChild(logsContainer.firstChild);
    }
    logsContainer.scrollTop = logsContainer.scrollHeight;
    pending = [];
    updateStats(domains.length);
    renderProgressBar(domains.length);
    renderFailureReasons();
    scheduleRender();
  }

  abortController = new AbortController();
  let runOutcome = 'running';
  try {
    const response = await fetch('/check', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        domains,
        timeout: currentRunMeta.timeout,
        workers: currentRunMeta.workers,
        dns_mode: currentRunMeta.dnsMode,
      }),
      signal: abortController.signal,
    });
    if (!response.ok) {
      const errTxt = await response.text().catch(() => '');
      throw new Error(`Server returned ${response.status}: ${errTxt.slice(0, 200)}`);
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    let streamError = null;
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split('\n');
      buf = lines.pop();
      for (const line of lines) {
        const t = line.trim();
        if (!t) continue;
        try {
          const obj = JSON.parse(t);
          if (obj.error) {
            streamError = obj.detail || obj.error;
            const div = document.createElement('div');
            div.style.color = 'var(--error)';
            div.textContent = `[error] ${streamError}`;
            logsContainer.appendChild(div);
            continue;
          }
          pending.push(obj);
          scheduleFlush();
        } catch (e) {
          console.error('parse error:', line, e);
        }
      }
    }
    if (pending.length) flush();
    if (streamError) {
      runOutcome = 'error';
      logStatus.textContent = 'Error';
      if (currentResults.length > 0) downloadButtonsContainer.classList.remove('hidden');
    } else {
      runOutcome = 'completed';
      const finalLine = document.createElement('div');
      finalLine.textContent = `▸ Done. ${currentResults.length}/${domains.length} checked in ${$('stat-elapsed-value').textContent}.`;
      finalLine.style.color = 'var(--accent)';
      finalLine.style.marginTop = '0.4rem';
      logsContainer.appendChild(finalLine);
      logsContainer.scrollTop = logsContainer.scrollHeight;
      logStatus.textContent = `${currentResults.length} Complete`;
      if (currentResults.length > 0) downloadButtonsContainer.classList.remove('hidden');
    }
  } catch (err) {
    if (err.name === 'AbortError') {
      runOutcome = 'cancelled';
      const div = document.createElement('div');
      div.style.color = 'var(--text-dim)';
      div.textContent = `▸ cancelled at ${currentResults.length}/${domains.length}.`;
      logsContainer.appendChild(div);
      logStatus.textContent = 'Cancelled';
      if (currentResults.length > 0) downloadButtonsContainer.classList.remove('hidden');
    } else {
      runOutcome = 'error';
      const div = document.createElement('div');
      div.style.color = 'var(--error)';
      div.textContent = `[error] ${err.message}`;
      logsContainer.appendChild(div);
      logStatus.textContent = 'Error';
      if (currentResults.length > 0) downloadButtonsContainer.classList.remove('hidden');
    }
  } finally {
    isRunning = false;
    abortController = null;
    if (elapsedTimer) { clearInterval(elapsedTimer); elapsedTimer = null; }
    if (sparkTimer) { clearInterval(sparkTimer); sparkTimer = null; }
    progressBarWrap.classList.remove('shimmer');
    checkBtn.disabled = false;
    buttonTextSpan.innerHTML = 'Check Domains';
    cancelBtn.classList.add('hidden');
    terminal.classList.remove('active');
    updateStats(domains.length);
    renderProgressBar(domains.length);
    renderFailureReasons();
    scheduleRender();
    document.title = ORIGINAL_TITLE;
    const online = currentResults.filter(r => r.ok).length;
    const failed = currentResults.length - online;
    if (runOutcome === 'completed' && currentResults.length > 0) {
      showToast(`Done · ${online}/${currentResults.length} online`, true);
      if ((performance.now() - runStartTime) > 15_000) {
        notifyComplete(`${online}/${currentResults.length} online · ${failed} failed`);
      }
      if (failed > 0) postRunActions.classList.remove('hidden');
      saveLastRun(domains.length);
    }
  }
}

checkBtn.addEventListener('click', startRun);
cancelBtn.addEventListener('click', () => abortController?.abort());

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && !resultDetailModal.classList.contains('hidden')) {
    e.preventDefault();
    closeDetailModal();
  } else if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
    e.preventDefault();
    if (!isRunning) startRun();
  } else if (e.key === 'Escape' && isRunning) {
    abortController?.abort();
  }
});

// ---------- Downloads ----------
function downloadFile(filename, content, mimeType) {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function simpleExportResults() {
  return currentResults.map(r => ({
    domain: r.domain,
    ok: r.ok,
    detail: r.detail,
    category: r.category,
    status_code: r.status_code ?? null,
    elapsed_ms: r.elapsed_ms ?? null,
    protocol: r.protocol ?? null,
  }));
}

downloadCsvBtn.addEventListener('click', () => {
  if (!currentResults.length) return;
  const rows = ['Domain,Status,Category,Detail,Status Code,Elapsed (ms),Protocol'];
  for (const r of currentResults) {
    const status = r.ok ? 'Online' : 'Offline';
    const detail = `"${(r.detail || '').replace(/"/g, '""')}"`;
    rows.push(`${r.domain},${status},${r.category},${detail},${r.status_code ?? ''},${r.elapsed_ms ?? ''},${r.protocol ?? ''}`);
  }
  downloadFile('domain_results.csv', rows.join('\n') + '\n', 'text/csv;charset=utf-8;');
});
downloadJsonBtn.addEventListener('click', () => {
  if (!currentResults.length) return;
  downloadFile('domain_results.json', JSON.stringify(simpleExportResults(), null, 2), 'application/json;charset=utf-8;');
});
downloadTxtBtn.addEventListener('click', () => {
  if (!currentResults.length) return;
  let txt = '';
  for (const r of currentResults) {
    const symbol = r.ok ? '✔' : '✖';
    const ms = r.elapsed_ms != null ? ` [${Math.round(r.elapsed_ms)}ms]` : '';
    txt += `${symbol} ${r.domain} (${r.detail || ''})${ms}\n`;
  }
  downloadFile('domain_results.txt', txt, 'text/plain;charset=utf-8;');
});

// ---------- Toast ----------
function showToast(message, accent = false) {
  const t = document.createElement('div');
  t.className = 'toast' + (accent ? ' toast-accent' : '');
  t.textContent = message;
  toastContainer.appendChild(t);
  setTimeout(() => t.remove(), 2200);
}

// ---------- Result row actions ----------
async function copyText(text) {
  // Modern API first; fall back to a hidden textarea + execCommand for
  // browsers / privacy modes where the async clipboard API is blocked
  // (Brave shields, non-secure contexts, some embedded webviews).
  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch { /* fall through */ }
  }
  try {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.setAttribute('readonly', '');
    ta.style.position = 'fixed';
    ta.style.top = '0';
    ta.style.left = '-9999px';
    document.body.appendChild(ta);
    const prevSelection = document.getSelection()?.rangeCount ? document.getSelection().getRangeAt(0) : null;
    ta.select();
    const ok = document.execCommand('copy');
    document.body.removeChild(ta);
    if (prevSelection) {
      const sel = document.getSelection();
      sel?.removeAllRanges();
      sel?.addRange(prevSelection);
    }
    return ok;
  } catch {
    return false;
  }
}

resultsTbody.addEventListener('click', async (e) => {
  const tr = e.target.closest('tr');
  if (!tr) return;
  const copyBtn = e.target.closest('[data-action="copy"]');
  const domain = copyBtn?.dataset.domain || tr.dataset.domain;
  if (!domain) return;
  if (copyBtn) {
    const ok = await copyText(domain);
    showToast(ok ? `copied · ${domain}` : 'copy failed', ok);
    tr.classList.remove('flash');
    void tr.offsetWidth;
    tr.classList.add('flash');
    setTimeout(() => tr.classList.remove('flash'), 500);
    return;
  }
  openDetailModal(getResultByDomain(domain), tr);
});

resultsTbody.addEventListener('keydown', (e) => {
  const tr = e.target.closest('tr');
  if (!tr) return;
  if (e.key !== 'Enter' && e.key !== ' ') return;
  if (e.target.closest('button')) return;
  e.preventDefault();
  const domain = tr.dataset.domain;
  if (!domain) return;
  openDetailModal(getResultByDomain(domain), tr);
});

resultDetailModal.addEventListener('click', (e) => {
  if (e.target === resultDetailModal) closeDetailModal();
});
detailCloseBtn.addEventListener('click', closeDetailModal);

detailCopyBtn.addEventListener('click', async () => {
  if (!selectedDetailDomain) return;
  const ok = await copyText(selectedDetailDomain);
  showToast(ok ? `copied · ${selectedDetailDomain}` : 'copy failed', ok);
});

detailExportJsonBtn.addEventListener('click', () => {
  if (!selectedDetailDomain) return;
  const result = getResultByDomain(selectedDetailDomain);
  if (!result) return;
  downloadFile(
    `${result.domain.replace(/[^a-z0-9.-]+/gi, '_')}_detail.json`,
    JSON.stringify(detailExportPayload(result), null, 2),
    'application/json;charset=utf-8;',
  );
});

detailExportTxtBtn.addEventListener('click', () => {
  if (!selectedDetailDomain) return;
  const result = getResultByDomain(selectedDetailDomain);
  if (!result) return;
  downloadFile(
    `${result.domain.replace(/[^a-z0-9.-]+/gi, '_')}_detail.txt`,
    detailExportText(result),
    'text/plain;charset=utf-8;',
  );
});

// ---------- Re-check ----------
function rerunWith(domains) {
  if (!domains.length) return;
  inputEl.value = domains.join('\n');
  updateInputMeta();
  startRun();
}
recheckFailedBtn.addEventListener('click', () => {
  const failed = currentResults.filter(r => !r.ok).map(r => r.domain);
  if (!failed.length) { showToast('no failures to re-check'); return; }
  rerunWith(failed);
});
recheckAllBtn.addEventListener('click', () => {
  const all = currentResults.map(r => r.domain);
  rerunWith(all);
});

// ---------- Browser notification on long-run completion ----------
async function notifyComplete(body) {
  if (!('Notification' in window)) return;
  if (document.hasFocus()) return; // user is still here, no need to ping
  try {
    let perm = Notification.permission;
    if (perm === 'default') perm = await Notification.requestPermission();
    if (perm !== 'granted') return;
    const n = new Notification('Domain check complete', { body, icon: '/static/icon.svg' });
    setTimeout(() => n.close(), 5000);
    n.onclick = () => { window.focus(); n.close(); };
  } catch { /* best-effort */ }
}

// ---------- Persistence (localStorage) ----------
function savePrefs() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      input: inputEl.value,
      timeout: timeoutInput.value,
      workers: workersInput.value,
      dnsMode: dnsModeInput.value,
    }));
  } catch { /* ignore quota / privacy errors */ }
}
function loadPrefs() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return;
    const data = JSON.parse(raw);
    if (data.input != null) inputEl.value = data.input;
    if (data.timeout != null) timeoutInput.value = data.timeout;
    if (data.workers != null) workersInput.value = data.workers;
    if (data.dnsMode != null) dnsModeInput.value = data.dnsMode;
  } catch { /* corrupted; ignore */ }
}
loadPrefs();
let saveTimer = null;
function debouncedSave() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(savePrefs, 400);
}
inputEl.addEventListener('input', debouncedSave);
timeoutInput.addEventListener('change', debouncedSave);
workersInput.addEventListener('change', debouncedSave);
dnsModeInput.addEventListener('change', debouncedSave);

// ---------- Last-run results persistence ----------
function saveLastRun(total) {
  // Skip persisting huge result sets because they would blow the 5MB localStorage quota.
  // The user can still re-run; saved input + settings already survived.
  if (currentResults.length > MAX_PERSISTED_RESULTS) {
    try { localStorage.removeItem(RESULTS_KEY); } catch {}
    return;
  }
  try {
    const payload = {
      status: 'completed',
      total,
      meta: getRunMeta(),
      results: currentResults,
      completedAt: Date.now(),
      elapsedSec: (performance.now() - runStartTime) / 1000,
    };
    localStorage.setItem(RESULTS_KEY, JSON.stringify(payload));
  } catch (e) {
    // Quota exceeded or private mode; drop quietly.
    try { localStorage.removeItem(RESULTS_KEY); } catch {}
  }
}

function restoreLastRun() {
  let payload;
  try {
    const raw = localStorage.getItem(RESULTS_KEY);
    if (!raw) return;
    payload = JSON.parse(raw);
  } catch { return; }
  if (!payload?.results?.length) return;
  const total = payload.total || payload.results.length;
  const isCompletedRun = payload.status ? payload.status === 'completed' : payload.results.length >= total;
  if (!isCompletedRun) {
    try { localStorage.removeItem(RESULTS_KEY); } catch {}
    return;
  }

  currentResults = payload.results;
  currentRunTotal = total;
  detailDiagnosticsCache.clear();
  currentRunMeta = {
    total,
    timeout: payload.meta?.timeout ?? (Number(timeoutInput.value) || 5),
    workers: payload.meta?.workers ?? (Number(workersInput.value) || 100),
    dnsMode: payload.meta?.dnsMode || payload.meta?.dns_mode || dnsModeInput.value || 'system',
    startedAt: payload.meta?.startedAt || payload.meta?.started_at || payload.completedAt || null,
  };
  const online = currentResults.filter(r => r.ok).length;
  const failed = currentResults.length - online;

  // Bring the UI up as if the run just finished, but without timers.
  resultsContainer.classList.remove('hidden');
  resultsEmpty.classList.add('hidden');
  downloadButtonsContainer.classList.remove('hidden');
  lastRenderCount = 0;

  // Compute stats without runStartTime so we don't run live timers.
  $('stat-total-value').textContent = total.toLocaleString();
  $('stat-checked-value').textContent = currentResults.length.toLocaleString();
  $('stat-checked-percent').textContent = total > 0 ? `${Math.round((currentResults.length / total) * 100)}%` : '0%';
  $('stat-online-value').textContent = online.toLocaleString();
  $('stat-online-percent').textContent = currentResults.length > 0 ? `${Math.round((online / currentResults.length) * 100)}%` : '0%';
  $('stat-failed-value').textContent = failed.toLocaleString();
  $('stat-failed-percent').textContent = currentResults.length > 0 ? `${Math.round((failed / currentResults.length) * 100)}%` : '0%';
  if (payload.elapsedSec != null) $('stat-elapsed-value').textContent = `${payload.elapsedSec.toFixed(1)}s`;
  if (payload.elapsedSec > 0) $('stat-speed-value').textContent = (currentResults.length / payload.elapsedSec).toFixed(1);
  $('stat-eta-value').textContent = 'Done';

  renderProgressBar(total);
  renderFailureReasons();
  scheduleRender();

  if (failed > 0) postRunActions.classList.remove('hidden');
  else postRunActions.classList.add('hidden');

  // A subtle hint that this is restored, not freshly run.
  const ageMin = Math.round((Date.now() - (payload.completedAt || Date.now())) / 60000);
  const ageLabel = ageMin <= 0 ? 'Just Now' : ageMin < 60 ? `${ageMin}m Ago` : `${Math.round(ageMin / 60)}h Ago`;
  resultsCount.textContent = `${currentResults.length.toLocaleString()} Results · ${ageLabel}`;
}
restoreLastRun();

updateInputMeta();
