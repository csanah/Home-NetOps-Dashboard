// ── Log Parsing ──
const RE_SRC = /SRC=([\d.]+)/;
const RE_DST = /DST=([\d.]+)/;
const RE_PROTO = /PROTO=(\w+)/;
const RE_DPT = /DPT=(\d+)/;
const RE_SPT = /SPT=(\d+)/;
const RE_TIME = /^(\w+\s+\d+\s+[\d:]+)/;

// tcpdump format: "12:01:23.456789 IP 10.0.0.50.52341 > 8.8.8.8.443: tcp 52"
const RE_TCPDUMP = /^([\d:.]+)\s+IP\s+([\d.]+)\.(\d+)\s+>\s+([\d.]+)\.(\d+):\s+(\w+)/;

const RE_DESCR = /DESCR="([^"]+)"/;

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
