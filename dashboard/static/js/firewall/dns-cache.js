// ── DNS Hostname Resolution ──
// Bounded LRU cache: max 500 entries
const hostnameCache = new Map();   // ip -> hostname
const HOSTNAME_CACHE_MAX = 500;

// ── IP→Element Maps for O(1) DNS updates (2A) ──
const ipSrcElements = new Map();  // ip -> Set<HTMLElement>
const ipDstElements = new Map();  // ip -> Set<HTMLElement>

function registerIpElement(ip, td, map) {
  if (!ip || ip === '-') return;
  if (!map.has(ip)) map.set(ip, new Set());
  map.get(ip).add(td);
}

function unregisterRowElements(tr) {
  const srcTd = tr.querySelector('td[data-ip-src]');
  const dstTd = tr.querySelector('td[data-ip-dst]');
  if (srcTd) {
    const ip = srcTd.dataset.ipSrc;
    if (ip && ipSrcElements.has(ip)) {
      ipSrcElements.get(ip).delete(srcTd);
      if (ipSrcElements.get(ip).size === 0) ipSrcElements.delete(ip);
    }
  }
  if (dstTd) {
    const ip = dstTd.dataset.ipDst;
    if (ip && ipDstElements.has(ip)) {
      ipDstElements.get(ip).delete(dstTd);
      if (ipDstElements.get(ip).size === 0) ipDstElements.delete(ip);
    }
  }
}

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
