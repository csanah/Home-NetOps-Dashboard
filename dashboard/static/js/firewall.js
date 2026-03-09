// ── Tab Switching ──
function switchTab(name) {
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.add('hidden'));
  document.querySelectorAll('.tab-btn').forEach(b => {
    b.classList.remove('bg-white', 'dark:bg-gray-600', 'text-gray-900', 'dark:text-white', 'shadow-sm');
    b.classList.add('text-gray-600', 'dark:text-gray-300');
  });
  document.getElementById('tab-' + name).classList.remove('hidden');
  const btn = document.querySelector(`.tab-btn[data-tab="${name}"]`);
  btn.classList.add('bg-white', 'dark:bg-gray-600', 'text-gray-900', 'dark:text-white', 'shadow-sm');
  btn.classList.remove('text-gray-600', 'dark:text-gray-300');

  if (name === 'rules' && !rulesLoaded) {
    refreshRules();
  }
}

// ── DNS Hostname Resolution ──
// Bounded LRU cache: max 500 entries
const hostnameCache = new Map();   // ip -> hostname
const HOSTNAME_CACHE_MAX = 500;

function hostnameCacheSet(ip, hostname) {
  // LRU: delete+re-insert moves to end; evict oldest if over limit
  if (hostnameCache.has(ip)) hostnameCache.delete(ip);
  hostnameCache.set(ip, hostname);
  if (hostnameCache.size > HOSTNAME_CACHE_MAX) {
    const oldest = hostnameCache.keys().next().value;
    hostnameCache.delete(oldest);
  }
}

function hostnameCacheGet(ip) {
  if (!hostnameCache.has(ip)) return undefined;
  // LRU touch: delete+re-insert
  const val = hostnameCache.get(ip);
  hostnameCache.delete(ip);
  hostnameCache.set(ip, val);
  return val;
}

// Bounded DNS request queue: Map<ip, timestamp> with 30s TTL
const dnsRequestQueue = new Map(); // ip -> timestamp
let dnsFlushTimer = null;

function isExternalIP(ip) {
  if (!ip) return false;
  return !(ip.startsWith('192.168.') || ip.startsWith('10.') ||
           ip.startsWith('172.16.') || ip.startsWith('172.17.') ||
           ip.startsWith('172.18.') || ip.startsWith('172.19.') ||
           ip.startsWith('172.20.') || ip.startsWith('172.21.') ||
           ip.startsWith('172.22.') || ip.startsWith('172.23.') ||
           ip.startsWith('172.24.') || ip.startsWith('172.25.') ||
           ip.startsWith('172.26.') || ip.startsWith('172.27.') ||
           ip.startsWith('172.28.') || ip.startsWith('172.29.') ||
           ip.startsWith('172.30.') || ip.startsWith('172.31.') ||
           ip.startsWith('127.') || ip === '0.0.0.0' || ip === '255.255.255.255');
}

function requestDnsResolution(ip) {
  if (!ip || !isExternalIP(ip) || hostnameCache.has(ip) || dnsRequestQueue.has(ip)) return;
  dnsRequestQueue.set(ip, Date.now());
  if (!dnsFlushTimer) {
    dnsFlushTimer = setTimeout(flushDnsQueue, 200);
  }
}

function flushDnsQueue() {
  dnsFlushTimer = null;
  if (dnsRequestQueue.size === 0) return;
  const batch = Array.from(dnsRequestQueue.keys()).slice(0, 20);
  batch.forEach(ip => dnsRequestQueue.delete(ip));
  fwSocket.emit('resolve_ips', { ips: batch });
  // If more remain, schedule another flush
  if (dnsRequestQueue.size > 0) {
    dnsFlushTimer = setTimeout(flushDnsQueue, 200);
  }
}

function formatIpWithHostname(ip, colorClass) {
  if (!ip || ip === '-') return `<span class="${colorClass}">${escapeHtml(ip || '-')}</span>`;
  const escaped = escapeHtml(ip);
  const hostname = hostnameCacheGet(ip);
  if (hostname) {
    const shortHost = hostname.length > 30 ? hostname.slice(0, 27) + '...' : hostname;
    return `<span class="text-gray-400" title="${escapeHtml(hostname)}">${escapeHtml(shortHost)}</span> <span class="${colorClass}">(${escaped})</span>`;
  }
  return `<span class="${colorClass}">${escaped}</span>`;
}

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

// ── Log Parsing ──
const RE_SRC = /SRC=([\d.]+)/;
const RE_DST = /DST=([\d.]+)/;
const RE_PROTO = /PROTO=(\w+)/;
const RE_DPT = /DPT=(\d+)/;
const RE_SPT = /SPT=(\d+)/;
const RE_TIME = /^(\w+\s+\d+\s+[\d:]+)/;

// tcpdump format: "12:01:23.456789 IP 192.168.1.100.52341 > 8.8.8.8.443: tcp 52"
const RE_TCPDUMP = /^([\d:.]+)\s+IP\s+([\d.]+)\.(\d+)\s+>\s+([\d.]+)\.(\d+):\s+(\w+)/;

function parseAction(line) {
  if (/\bDROP\b/i.test(line) || /\bBLOCK\b/i.test(line) || /\[-D-\d+\]/.test(line)) return 'DROP';
  if (/\bREJECT\b/i.test(line) || /\[-R-\d+\]/.test(line)) return 'REJECT';
  if (/\bACCEPT\b/i.test(line) || /\bALLOW\b/i.test(line) || /\[-A-\d+\]/.test(line)) return 'ACCEPT';
  return null;
}

function actionBadge(action) {
  if (!action) return '<span class="text-gray-500">-</span>';
  const colors = {
    DROP: 'bg-red-500/20 text-red-400',
    REJECT: 'bg-orange-500/20 text-orange-400',
    ACCEPT: 'bg-green-500/20 text-green-400',
    ALLOW: 'bg-green-500/20 text-green-400'
  };
  const cls = colors[action] || 'bg-gray-500/20 text-gray-400';
  return `<span class="px-1.5 py-0.5 rounded text-xs font-bold ${cls}">${action}</span>`;
}

function parseTcpdump(raw) {
  const m = RE_TCPDUMP.exec(raw);
  if (!m) return null;
  return {
    time: m[1].split('.')[0],  // strip microseconds
    action: 'ALLOW',
    src: m[2],
    dst: m[4],
    dpt: m[5],
    proto: m[6].toUpperCase(),
    parseable: true
  };
}

const RE_DESCR = /DESCR="([^"]+)"/;

function parseThreatJson(raw) {
  // threat.log lines: timestamp hostname daemon[pid]: {json}
  const jsonStart = raw.indexOf('{"alert"');
  if (jsonStart === -1) return null;
  try {
    const obj = JSON.parse(raw.substring(jsonStart));
    const alert = obj.alert || {};
    const time = (obj.timestamp || '').split('T')[1]?.split('.')[0] || '';
    return {
      time,
      action: (alert.action === 'blocked') ? 'DROP' : (alert.action || '').toUpperCase(),
      src: obj.src_ip || '',
      dst: obj.dest_ip || '',
      dpt: String(obj.dest_port || ''),
      proto: (obj.proto || '').toUpperCase(),
      descr: alert.signature || alert.category || '',
      parseable: true
    };
  } catch (e) {
    return null;
  }
}

function parseLine(raw) {
  // Try tcpdump format first
  const td = parseTcpdump(raw);
  if (td) return td;

  // Try threat.log JSON format (IDS/IPS alerts)
  const threat = parseThreatJson(raw);
  if (threat) return threat;

  // Fall back to iptables/syslog format
  const src = (RE_SRC.exec(raw) || [])[1];
  const dst = (RE_DST.exec(raw) || [])[1];
  const proto = (RE_PROTO.exec(raw) || [])[1];
  const dpt = (RE_DPT.exec(raw) || [])[1];
  const time = (RE_TIME.exec(raw) || [])[1];
  const action = parseAction(raw);
  const descr = (RE_DESCR.exec(raw) || [])[1] || '';
  return { time, action, src, dst, dpt, proto, descr, parseable: !!(src || dst) };
}

function escapeHtml(str) {
  const d = document.createElement('div');
  d.textContent = str;
  return d.innerHTML;
}

// ── Live Log Stream ──
const fwSocket = io('/firewall');
const logContainer = document.getElementById('log-container');
const logTbody = document.getElementById('log-tbody');
const streamStatus = document.getElementById('stream-status');
const btnStart = document.getElementById('btn-start');
const btnStop = document.getElementById('btn-stop');
const MAX_LINES = 500;

let logFilterIP = '';
let placeholderCleared = false;
let currentMode = 'all';  // 'all' or 'blocked'
let currentScope = 'both';  // 'both', 'local', 'external'
let streamRunning = false;

// ── Render Throttle ──
// Buffer incoming lines, flush to DOM on a timer
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
    logTbody.removeChild(logTbody.firstChild);
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
      `<td class="px-3 py-1.5${parsed.src && parsed.src !== '-' ? ' cursor-pointer' : ''}" data-ip-src="${escapeHtml(parsed.src || '')}"${parsed.src && parsed.src !== '-' ? ` onclick="showIpPopover(event,'${escapeHtml(parsed.src)}')"` : ''}>${formatIpWithHostname(parsed.src, 'text-cyan-400')}</td>` +
      `<td class="px-3 py-1.5${parsed.dst && parsed.dst !== '-' ? ' cursor-pointer' : ''}" data-ip-dst="${escapeHtml(parsed.dst || '')}"${parsed.dst && parsed.dst !== '-' ? ` onclick="showIpPopover(event,'${escapeHtml(parsed.dst)}')"` : ''}>${formatIpWithHostname(parsed.dst, 'text-yellow-400')}</td>` +
      `<td class="px-3 py-1.5">${escapeHtml(parsed.dpt || '-')}</td>` +
      `<td class="px-3 py-1.5">${escapeHtml(parsed.proto || '-')}</td>`;
  } else {
    tr.innerHTML = `<td colspan="6" class="px-3 py-1.5 text-gray-400">${escapeHtml(raw)}</td>`;
  }
  return tr;
}

function flushBuffer() {
  if (renderBuffer.length === 0) return;

  const frag = document.createDocumentFragment();
  const batch = renderBuffer.splice(0, renderBuffer.length);
  batch.forEach(raw => frag.appendChild(buildRow(raw)));

  logTbody.appendChild(frag);
  updateStatsDisplay();

  while (logTbody.children.length > MAX_LINES) {
    logTbody.removeChild(logTbody.firstChild);
  }

  if (autoScroll) {
    logContainer.scrollTop = logContainer.scrollHeight;
  }
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

fwSocket.on('log_line', function(data) {
  if (!placeholderCleared) {
    logTbody.innerHTML = '';
    placeholderCleared = true;
  }
  startPpsCounter();

  const raw = data.line;

  if (paused) {
    // Still count stats but don't render
    pauseBuffer.push(raw);
    const parsed = parseLine(raw);
    stats.total++;
    ppsCount++;
    if (parsed.action === 'DROP' || parsed.action === 'REJECT') stats.blocked++;
    else if (parsed.action === 'ACCEPT' || parsed.action === 'ALLOW') stats.allowed++;
    if (parsed.src) uniqueIPs.add(parsed.src);
    if (parsed.dst) uniqueIPs.add(parsed.dst);
    updateStatsDisplay();
    const badge = document.getElementById('pause-badge');
    if (badge) badge.textContent = pauseBuffer.length + ' buffered';
    return;
  }

  if (currentSpeed === 'realtime') {
    // rAF batching: collect lines, flush once per animation frame
    rafBuffer.push(raw);
    if (!rafScheduled) {
      rafScheduled = true;
      requestAnimationFrame(flushRafBuffer);
    }
  } else {
    renderBuffer.push(raw);
  }
});

// ── DNS Result Handler ──
fwSocket.on('dns_result', function(data) {
  const { ip, hostname } = data;
  if (!ip || !hostname) return;
  hostnameCacheSet(ip, hostname);

  // Update all source cells with this IP
  document.querySelectorAll(`td[data-ip-src="${ip}"]`).forEach(td => {
    td.innerHTML = formatIpWithHostname(ip, 'text-cyan-400');
  });
  // Update all destination cells with this IP
  document.querySelectorAll(`td[data-ip-dst="${ip}"]`).forEach(td => {
    td.innerHTML = formatIpWithHostname(ip, 'text-yellow-400');
  });

  // Live-update popover if showing this IP
  if (popoverIP === ip) {
    document.getElementById('ip-popover-hostname').textContent = hostname;
  }
});

// ── Server Icon ──
const serverIcon = document.getElementById('server-icon');

function updateServerIcon(status) {
  serverIcon.classList.remove('bg-red-500', 'bg-green-500', 'bg-yellow-500');
  if (status === 'connected') {
    serverIcon.classList.add('bg-green-500');
    serverIcon.title = 'Stream: Running (right-click for options)';
  } else if (status === 'connecting') {
    serverIcon.classList.add('bg-yellow-500');
    serverIcon.title = 'Stream: Connecting...';
  } else {
    serverIcon.classList.add('bg-red-500');
    serverIcon.title = 'Stream: Stopped (click to start, right-click for options)';
  }
}

function showServerMenu(e) {
  e.preventDefault();
  const menu = document.getElementById('server-menu');
  menu.classList.remove('hidden');
  menu.style.left = e.pageX + 'px';
  menu.style.top = e.pageY + 'px';
}

function hideServerMenu() {
  document.getElementById('server-menu').classList.add('hidden');
}

document.addEventListener('click', function(e) {
  const menu = document.getElementById('server-menu');
  if (!menu.contains(e.target) && e.target.id !== 'server-icon') {
    menu.classList.add('hidden');
  }
  // Dismiss IP popover on outside click
  const popover = document.getElementById('ip-popover');
  if (!popover.contains(e.target)) {
    hideIpPopover();
  }
});

fwSocket.on('stream_status', function(data) {
  streamStatus.textContent = data.status.charAt(0).toUpperCase() + data.status.slice(1);
  if (data.message) {
    streamStatus.textContent += ': ' + data.message;
  }

  if (data.status === 'connected') {
    streamStatus.className = 'text-xs text-green-400';
    const modeLabel = data.mode === 'blocked' ? ' (blocked only)' : ' (all traffic)';
    streamStatus.textContent += modeLabel;
    btnStart.disabled = true;
    btnStop.disabled = false;
    streamRunning = true;
    updateServerIcon('connected');
    if (!placeholderCleared) {
      logTbody.innerHTML = '';
      placeholderCleared = true;
    }
  } else {
    streamStatus.className = 'text-xs text-gray-400';
    btnStart.disabled = false;
    btnStop.disabled = true;
    streamRunning = false;
    updateServerIcon('disconnected');
  }
});

function startStream() {
  fwSocket.emit('start_stream', { mode: currentMode, filter_ip: logFilterIP || null, scope: currentScope });
  streamStatus.textContent = 'Connecting...';
  updateServerIcon('connecting');
}

function stopStream() {
  fwSocket.emit('stop_stream');
}

function restartStream() {
  if (streamRunning) {
    fwSocket.emit('stop_stream');
    setTimeout(() => { startStream(); }, 300);
  }
}

function setMode(mode) {
  currentMode = mode;
  const btnBlocked = document.getElementById('btn-blocked-only');

  if (mode === 'blocked') {
    btnBlocked.classList.remove('bg-gray-600', 'hover:bg-gray-700');
    btnBlocked.classList.add('bg-red-600', 'hover:bg-red-700');
  } else {
    btnBlocked.classList.remove('bg-red-600', 'hover:bg-red-700');
    btnBlocked.classList.add('bg-gray-600', 'hover:bg-gray-700');
  }
  restartStream();
}

function toggleBlockedOnly() {
  setMode(currentMode === 'blocked' ? 'all' : 'blocked');
}

function setScope(scope) {
  currentScope = scope;
  ['both', 'local', 'external'].forEach(s => {
    const btn = document.getElementById('btn-scope-' + s);
    if (s === scope) {
      btn.classList.add('bg-blue-600', 'text-white');
      btn.classList.remove('text-gray-500', 'dark:text-gray-400');
    } else {
      btn.classList.remove('bg-blue-600', 'text-white');
      btn.classList.add('text-gray-500', 'dark:text-gray-400');
    }
  });
  restartStream();
}

function clearLogs() {
  logTbody.innerHTML = '';
  placeholderCleared = true;
  renderBuffer = [];
  pauseBuffer = [];
  rafBuffer = [];
  hostnameCache.clear();
  dnsRequestQueue.clear();
  resetStats();
}

// ── Log Filter (server-side — restarts stream) ──
function setLogFilter(ip) {
  const prevIP = logFilterIP;
  logFilterIP = ip;
  const badge = document.getElementById('filter-badge');
  const badgeText = document.getElementById('filter-badge-text');

  if (ip) {
    badge.style.display = 'flex';
    badgeText.textContent = ip;
  } else {
    badge.style.display = 'none';
  }

  // Restart stream with new filter if it changed while running
  if (prevIP !== ip) {
    restartStream();
  }
}

function clearLogFilter() {
  document.getElementById('log-filter-input').value = '';
  document.querySelectorAll('.device-row').forEach(r => r.classList.remove('bg-blue-50', 'dark:bg-blue-900/20', 'ring-1', 'ring-blue-500'));
  setLogFilter('');
}

function applyLogFilterInput() {
  const val = document.getElementById('log-filter-input').value.trim();
  setLogFilter(val);
}

// ── Device Picker ──
function selectDevice(ip, el) {
  document.querySelectorAll('.device-row').forEach(r => r.classList.remove('bg-blue-50', 'dark:bg-blue-900/20', 'ring-1', 'ring-blue-500'));
  el.classList.add('bg-blue-50', 'dark:bg-blue-900/20', 'ring-1', 'ring-blue-500');

  // Put IP in the Live Logs filter field and switch to that tab
  document.getElementById('log-filter-input').value = ip;
  switchTab('logs');
  document.getElementById('log-filter-input').focus();
}

function filterDevices() {
  const query = (document.getElementById('device-filter')?.value || '').toLowerCase();
  const statusFilter = currentDeviceStatusFilter || 'all';
  const connectionFilter = currentDeviceConnectionFilter || 'all';
  const rows = document.querySelectorAll('.device-row');
  const groups = document.querySelectorAll('.device-group');

  rows.forEach(row => {
    const name = (row.dataset.name || '').toLowerCase();
    const ip = (row.dataset.ip || '').toLowerCase();
    const isOnline = row.dataset.online === 'true';
    const wired = row.dataset.wired; // 'true', 'false', or 'unknown'

    const matchesText = !query || name.includes(query) || ip.includes(query);
    const matchesStatus = statusFilter === 'all' ||
      (statusFilter === 'online' && isOnline) ||
      (statusFilter === 'offline' && !isOnline);
    const matchesConnection = connectionFilter === 'all' ||
      (connectionFilter === 'wired' && wired === 'true') ||
      (connectionFilter === 'wireless' && wired === 'false');

    row.style.display = (matchesText && matchesStatus && matchesConnection) ? '' : 'none';
  });

  groups.forEach(group => {
    const visible = group.querySelectorAll('.device-row:not([style*="display: none"])');
    const header = group.querySelector('div:first-child');
    if (header) header.style.display = visible.length ? '' : 'none';
  });
}

function refreshClients() {
  const btn = document.getElementById('btn-refresh-clients');
  btn.textContent = 'Loading...';
  btn.disabled = true;

  fetch('/firewall/clients')
    .then(r => r.json())
    .then(clients => {
      renderDeviceList(clients);
      btn.innerHTML = '<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg> Refresh';
      btn.disabled = false;
    })
    .catch(() => {
      btn.innerHTML = '<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg> Refresh';
      btn.disabled = false;
    });
}

let currentDeviceStatusFilter = 'all';
let currentDeviceConnectionFilter = 'all';

function renderDeviceList(clients) {
  const container = document.getElementById('device-list');
  if (!clients.length) {
    container.innerHTML = '<div class="px-4 py-6 text-center text-sm text-gray-400">No devices found</div>';
    updateDeviceCountBadge(0, 0);
    return;
  }

  const groups = { phone: [], computer: [], other: [] };
  let totalOnline = 0;
  clients.forEach(c => {
    (groups[c.category] || groups.other).push(c);
    if (c.online) totalOnline++;
  });

  updateDeviceCountBadge(totalOnline, clients.length);

  const icons = {
    phone: { svg: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 18h.01M8 21h8a2 2 0 002-2V5a2 2 0 00-2-2H8a2 2 0 00-2 2v14a2 2 0 002 2z"/>', bg: 'bg-blue-100 dark:bg-blue-900/40', fg: 'text-blue-600 dark:text-blue-400', label: 'Phones' },
    computer: { svg: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"/>', bg: 'bg-purple-100 dark:bg-purple-900/40', fg: 'text-purple-600 dark:text-purple-400', label: 'Computers' },
    other: { svg: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8.111 16.404a5.5 5.5 0 017.778 0M12 20h.01m-7.08-7.071c3.904-3.905 10.236-3.905 14.141 0M1.394 9.393c5.857-5.858 15.355-5.858 21.213 0"/>', bg: 'bg-gray-100 dark:bg-gray-700', fg: 'text-gray-500 dark:text-gray-400', label: 'Other Devices' }
  };

  let html = '';
  for (const [key, items] of Object.entries(groups)) {
    if (!items.length) continue;
    const ic = icons[key];
    const groupOnline = items.filter(d => d.online).length;
    html += `<div class="device-group" data-group="${key}">`;
    html += `<div class="px-4 py-2 bg-gray-50 dark:bg-gray-750 text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide border-b border-gray-100 dark:border-gray-700/50 flex items-center gap-1.5">
      <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">${ic.svg}</svg>
      ${ic.label} <span class="text-gray-400 font-normal">(${groupOnline}/${items.length})</span>
    </div>`;
    items.forEach(d => {
      const safeName = d.name.replace(/</g, '&lt;').replace(/>/g, '&gt;');
      const isOnline = !!d.online;
      const statusDotColor = isOnline ? 'bg-green-400' : 'bg-gray-400';
      const opacityClass = isOnline ? '' : ' opacity-60';
      const wiredVal = d.wired === true ? 'true' : (d.wired === false ? 'false' : 'unknown');
      const connIcon = d.wired === true
        ? '<svg class="w-3 h-3 text-gray-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" title="Wired"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 9l3 3-3 3m5 0h3M5 20h14a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"/></svg>'
        : (d.wired === false
          ? '<svg class="w-3 h-3 text-gray-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" title="Wireless"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8.111 16.404a5.5 5.5 0 017.778 0M12 20h.01m-7.08-7.071c3.904-3.905 10.236-3.905 14.141 0M1.394 9.393c5.857-5.858 15.355-5.858 21.213 0"/></svg>'
          : '');
      html += `<button onclick="selectDevice('${d.ip}', this)" data-name="${safeName}" data-ip="${d.ip}" data-online="${isOnline}" data-wired="${wiredVal}"
        class="device-row w-full text-left px-4 py-2.5 flex items-center gap-3 hover:bg-blue-50 dark:hover:bg-blue-900/20 transition-colors border-b border-gray-50 dark:border-gray-700/30 last:border-0${opacityClass}">
        <div class="relative shrink-0">
          <div class="w-8 h-8 rounded-full ${ic.bg} flex items-center justify-center">
            <svg class="w-4 h-4 ${ic.fg}" fill="none" stroke="currentColor" viewBox="0 0 24 24">${ic.svg}</svg>
          </div>
          <span class="absolute -bottom-0.5 -right-0.5 w-2.5 h-2.5 rounded-full border-2 border-white dark:border-gray-800 ${statusDotColor}"></span>
        </div>
        <div class="min-w-0 flex-1">
          <div class="text-sm font-medium truncate flex items-center gap-1">${safeName} ${connIcon}</div>
          <div class="text-xs text-gray-400 font-mono">${d.ip || 'No IP'}</div>
        </div>
      </button>`;
    });
    html += '</div>';
  }
  container.innerHTML = html;

  // Re-apply current filters
  filterDevices();
}

function updateDeviceCountBadge(online, total) {
  const badge = document.getElementById('device-count-badge');
  if (badge) badge.textContent = online + '/' + total;
}

function filterDeviceStatus(status) {
  currentDeviceStatusFilter = status;

  // Update pill styling
  document.querySelectorAll('.status-filter-btn').forEach(btn => {
    if (btn.dataset.statusFilter === status) {
      btn.classList.add('bg-blue-600', 'text-white');
      btn.classList.remove('text-gray-500', 'dark:text-gray-400');
    } else {
      btn.classList.remove('bg-blue-600', 'text-white');
      btn.classList.add('text-gray-500', 'dark:text-gray-400');
    }
  });

  filterDevices();
}

function filterDeviceConnection(type) {
  currentDeviceConnectionFilter = type;

  document.querySelectorAll('.connection-filter-btn').forEach(btn => {
    if (btn.dataset.connectionFilter === type) {
      btn.classList.add('bg-blue-600', 'text-white');
      btn.classList.remove('text-gray-500', 'dark:text-gray-400');
    } else {
      btn.classList.remove('bg-blue-600', 'text-white');
      btn.classList.add('text-gray-500', 'dark:text-gray-400');
    }
  });

  filterDevices();
}

// ── Firewall Rules ──
let rulesLoaded = false;

function refreshRules() {
  const tbody = document.getElementById('rules-tbody');
  tbody.innerHTML = '<tr><td colspan="6" class="px-4 py-8 text-center text-gray-400">Loading rules...</td></tr>';

  fetch('/firewall/rules')
    .then(r => r.json())
    .then(rules => {
      rulesLoaded = true;
      if (!rules.length) {
        tbody.innerHTML = '<tr><td colspan="6" class="px-4 py-8 text-center text-gray-400">No firewall rules found</td></tr>';
        return;
      }
      let html = '';
      rules.forEach(rule => {
        const actionColor = {
          allow: 'bg-green-500/20 text-green-600 dark:text-green-400',
          accept: 'bg-green-500/20 text-green-600 dark:text-green-400',
          block: 'bg-red-500/20 text-red-600 dark:text-red-400',
          drop: 'bg-red-500/20 text-red-600 dark:text-red-400',
          reject: 'bg-orange-500/20 text-orange-600 dark:text-orange-400'
        }[rule.action?.toLowerCase()] || 'bg-gray-500/20 text-gray-500';

        const enabledDot = rule.enabled
          ? '<span class="inline-block w-2.5 h-2.5 rounded-full bg-green-500"></span>'
          : '<span class="inline-block w-2.5 h-2.5 rounded-full bg-gray-400"></span>';

        html += `<tr class="hover:bg-gray-50 dark:hover:bg-gray-750 transition-colors">
          <td class="px-4 py-3 font-medium">${escapeHtml(rule.name || '-')}</td>
          <td class="px-4 py-3"><span class="px-2 py-0.5 rounded text-xs font-bold uppercase ${actionColor}">${escapeHtml(rule.action || '-')}</span></td>
          <td class="px-4 py-3 text-gray-500 dark:text-gray-400">${escapeHtml(rule.source_zone || '-')}</td>
          <td class="px-4 py-3 text-gray-500 dark:text-gray-400">${escapeHtml(rule.dest_zone || '-')}</td>
          <td class="px-4 py-3 text-gray-500 dark:text-gray-400">${escapeHtml(rule.protocol || 'Any')}</td>
          <td class="px-4 py-3 text-center">${enabledDot}</td>
        </tr>`;
      });
      tbody.innerHTML = html;
    })
    .catch(err => {
      tbody.innerHTML = `<tr><td colspan="6" class="px-4 py-8 text-center text-red-400">Failed to load rules: ${escapeHtml(err.message)}</td></tr>`;
    });
}

// ── IP Popover ──
let popoverIP = '';

function showIpPopover(event, ip) {
  event.stopPropagation();
  const popover = document.getElementById('ip-popover');
  const ipEl = document.getElementById('ip-popover-ip');
  const hostnameEl = document.getElementById('ip-popover-hostname');

  popoverIP = ip;
  ipEl.textContent = ip;

  // Reset copy icon
  document.getElementById('ip-popover-copy-icon').classList.remove('hidden');
  document.getElementById('ip-popover-check-icon').classList.add('hidden');

  // Resolve hostname
  const cached = hostnameCacheGet(ip);
  if (cached) {
    hostnameEl.textContent = cached;
  } else if (!isExternalIP(ip)) {
    hostnameEl.textContent = 'Local device';
  } else {
    hostnameEl.textContent = 'Resolving...';
    requestDnsResolution(ip);
  }

  // Position near click, clamped to viewport
  const pad = 12;
  let x = event.clientX + pad;
  let y = event.clientY + pad;

  // Show briefly to measure
  popover.classList.remove('hidden');
  const rect = popover.getBoundingClientRect();

  if (x + rect.width > window.innerWidth - pad) {
    x = event.clientX - rect.width - pad;
  }
  if (y + rect.height > window.innerHeight - pad) {
    y = event.clientY - rect.height - pad;
  }
  if (x < pad) x = pad;
  if (y < pad) y = pad;

  popover.style.left = x + 'px';
  popover.style.top = y + 'px';
}

function hideIpPopover() {
  document.getElementById('ip-popover').classList.add('hidden');
  popoverIP = '';
}

function copyPopoverIP() {
  if (!popoverIP) return;
  navigator.clipboard.writeText(popoverIP).then(() => {
    // Flash checkmark
    document.getElementById('ip-popover-copy-icon').classList.add('hidden');
    document.getElementById('ip-popover-check-icon').classList.remove('hidden');
    setTimeout(() => {
      hideIpPopover();
    }, 600);
  });
}

function popoverFilterIP() {
  if (!popoverIP) return;
  document.getElementById('log-filter-input').value = popoverIP;
  setLogFilter(popoverIP);
  hideIpPopover();
}

function popoverLookup() {
  if (!popoverIP) return;
  const ip = popoverIP;
  hideIpPopover();
  switchTab('lookup');
  const input = document.getElementById('lookup-input');
  input.value = ip;
  // Trigger HTMX submit
  htmx.trigger(document.getElementById('lookup-form'), 'submit');
}

// ── Keyboard Shortcuts ──
function toggleShortcutHelp() {
  const overlay = document.getElementById('shortcut-help');
  if (overlay) overlay.classList.toggle('hidden');
}

document.addEventListener('keydown', function(e) {
  // Skip when focus is in an input/textarea
  const tag = document.activeElement?.tagName;
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;

  switch (e.key) {
    case 's': case 'S': startStream(); break;
    case 'x': case 'X': stopStream(); break;
    case 'p': case 'P': togglePause(); break;
    case 'c': case 'C': clearLogs(); break;
    case '1': switchTab('logs'); break;
    case '2': switchTab('lookup'); break;
    case '3': switchTab('rules'); break;
    case '?': toggleShortcutHelp(); break;
    case 'Escape':
      hideIpPopover();
      hideServerMenu();
      const help = document.getElementById('shortcut-help');
      if (help && !help.classList.contains('hidden')) help.classList.add('hidden');
      break;
  }
});
