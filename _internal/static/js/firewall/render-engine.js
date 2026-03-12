// ── Stats ──
let stats = { total: 0, blocked: 0, allowed: 0 };
const uniqueIPs = new Set();

function resetStats() {
  stats = { total: 0, blocked: 0, allowed: 0 };
  uniqueIPs.clear();
  updateStatsDisplay();
}

function updateStatsDisplay() {
  document.getElementById('stat-total').textContent = stats.total;
  document.getElementById('stat-blocked').textContent = stats.blocked;
  document.getElementById('stat-allowed').textContent = stats.allowed;
  document.getElementById('stat-unique').textContent = uniqueIPs.size;
}

// ── Render Throttle ──
const SPEED_PRESETS = {
  realtime: { interval: 0,    label: 'Realtime' },
  fast:     { interval: 250,  label: 'Fast' },
  normal:   { interval: 500,  label: 'Normal' },
  slow:     { interval: 1000, label: 'Slow' },
  batch:    { interval: 3000, label: 'Batch' }
};
let currentSpeed = 'realtime';
let renderBuffer = [];
let renderTimer = null;
let paused = false;
let autoScroll = true;
let pauseBuffer = [];  // lines received while paused
let ppsCount = 0;
let ppsDisplay = 0;
let ppsTimer = null;

// ── rAF Batching (for realtime mode) ──
let rafBuffer = [];
let rafScheduled = false;

function flushRafBuffer() {
  rafScheduled = false;
  if (rafBuffer.length === 0) return;

  const frag = document.createDocumentFragment();
  const batch = rafBuffer.splice(0, rafBuffer.length);
  batch.forEach(raw => frag.appendChild(buildRow(raw)));

  logTbody.appendChild(frag);
  updateStatsDisplay();

  while (logTbody.children.length > MAX_LINES) {
    const removed = logTbody.firstChild;
    unregisterRowElements(removed);
    logTbody.removeChild(removed);
  }

  if (autoScroll) {
    logContainer.scrollTop = logContainer.scrollHeight;
  }
}

function startPpsCounter() {
  if (ppsTimer) return;
  ppsTimer = setInterval(() => {
    ppsDisplay = ppsCount;
    ppsCount = 0;
    const el = document.getElementById('stat-pps');
    if (el) el.textContent = ppsDisplay;
    // Purge stale DNS request queue entries (older than 30s)
    const now = Date.now();
    for (const [ip, ts] of dnsRequestQueue) {
      if (now - ts > 30000) dnsRequestQueue.delete(ip);
    }
  }, 1000);
}

function buildRow(raw) {
  const parsed = parseLine(raw);

  // Update stats
  stats.total++;
  ppsCount++;
  if (parsed.action === 'DROP' || parsed.action === 'REJECT') stats.blocked++;
  else if (parsed.action === 'ACCEPT' || parsed.action === 'ALLOW') stats.allowed++;
  if (parsed.src) uniqueIPs.add(parsed.src);
  if (parsed.dst) uniqueIPs.add(parsed.dst);

  const tr = document.createElement('tr');
  tr.dataset.raw = raw;
  tr.className = 'border-b border-gray-800/50 hover:bg-gray-900/50';

  if (parsed.parseable) {
    if (parsed.src) requestDnsResolution(parsed.src);
    if (parsed.dst) requestDnsResolution(parsed.dst);
    const descrHtml = parsed.descr
      ? `<div class="text-[10px] text-gray-500 truncate max-w-[200px]" title="${escapeHtml(parsed.descr)}">${escapeHtml(parsed.descr)}</div>`
      : '';
    tr.innerHTML =
      `<td class="px-3 py-1.5 text-gray-500 whitespace-nowrap">${escapeHtml(parsed.time || '')}</td>` +
      `<td class="px-3 py-1.5">${actionBadge(parsed.action)}${descrHtml}</td>` +
      `<td class="px-3 py-1.5${parsed.src && parsed.src !== '-' ? ' cursor-pointer' : ''}" data-ip-src="${escapeHtml(parsed.src || '')}">${formatIpWithHostname(parsed.src, 'text-cyan-400')}</td>` +
      `<td class="px-3 py-1.5${parsed.dst && parsed.dst !== '-' ? ' cursor-pointer' : ''}" data-ip-dst="${escapeHtml(parsed.dst || '')}">${formatIpWithHostname(parsed.dst, 'text-yellow-400')}</td>` +
      `<td class="px-3 py-1.5">${escapeHtml(parsed.dpt || '-')}</td>` +
      `<td class="px-3 py-1.5">${escapeHtml(parsed.proto || '-')}</td>`;
    // Register elements in IP→Element maps for O(1) DNS update
    const srcTd = tr.querySelector('td[data-ip-src]');
    const dstTd = tr.querySelector('td[data-ip-dst]');
    if (srcTd && parsed.src) registerIpElement(parsed.src, srcTd, ipSrcElements);
    if (dstTd && parsed.dst) registerIpElement(parsed.dst, dstTd, ipDstElements);
  } else {
    tr.innerHTML = `<td colspan="6" class="px-3 py-1.5 text-gray-400">${escapeHtml(raw)}</td>`;
  }
  return tr;
}

function flushBuffer() {
  if (renderBuffer.length === 0) return;
  // Wrap in rAF to avoid jank in non-realtime modes (2B)
  requestAnimationFrame(() => {
    const frag = document.createDocumentFragment();
    const batch = renderBuffer.splice(0, renderBuffer.length);
    batch.forEach(raw => frag.appendChild(buildRow(raw)));

    logTbody.appendChild(frag);
    updateStatsDisplay();

    while (logTbody.children.length > MAX_LINES) {
      const removed = logTbody.firstChild;
      unregisterRowElements(removed);
      logTbody.removeChild(removed);
    }

    if (autoScroll) {
      logContainer.scrollTop = logContainer.scrollHeight;
    }
  });
}

function setSpeed(speed) {
  currentSpeed = speed;
  // Update button styles
  Object.keys(SPEED_PRESETS).forEach(s => {
    const btn = document.getElementById('btn-speed-' + s);
    if (!btn) return;
    if (s === speed) {
      btn.classList.add('bg-indigo-600', 'text-white');
      btn.classList.remove('text-gray-500', 'dark:text-gray-400');
    } else {
      btn.classList.remove('bg-indigo-600', 'text-white');
      btn.classList.add('text-gray-500', 'dark:text-gray-400');
    }
  });

  // Reset render timer
  if (renderTimer) { clearInterval(renderTimer); renderTimer = null; }
  const ms = SPEED_PRESETS[speed].interval;
  if (ms > 0) {
    renderTimer = setInterval(flushBuffer, ms);
  }
}

function togglePause() {
  paused = !paused;
  const btn = document.getElementById('btn-pause');
  const badge = document.getElementById('pause-badge');
  if (paused) {
    btn.classList.remove('bg-gray-600', 'hover:bg-gray-700');
    btn.classList.add('bg-amber-600', 'hover:bg-amber-700');
    btn.innerHTML = '<svg class="w-3.5 h-3.5 inline mr-1" fill="currentColor" viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>Resume';
    badge.classList.remove('hidden');
  } else {
    btn.classList.remove('bg-amber-600', 'hover:bg-amber-700');
    btn.classList.add('bg-gray-600', 'hover:bg-gray-700');
    btn.innerHTML = '<svg class="w-3.5 h-3.5 inline mr-1" fill="currentColor" viewBox="0 0 24 24"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>Pause';
    badge.classList.add('hidden');
    // Flush everything collected while paused
    renderBuffer.push(...pauseBuffer);
    pauseBuffer = [];
    flushBuffer();
  }
}

function toggleAutoScroll() {
  autoScroll = !autoScroll;
  const btn = document.getElementById('btn-autoscroll');
  if (autoScroll) {
    btn.classList.remove('bg-gray-600');
    btn.classList.add('bg-indigo-600');
    logContainer.scrollTop = logContainer.scrollHeight;
  } else {
    btn.classList.remove('bg-indigo-600');
    btn.classList.add('bg-gray-600');
  }
}
