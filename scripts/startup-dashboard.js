const https = require('https');
const http = require('http');
const net = require('net');
const fs = require('fs');
const path = require('path');

// Load .env
const envPath = path.join(__dirname, '..', '.env');
const env = {};
fs.readFileSync(envPath, 'utf8').split('\n').forEach(line => {
  line = line.trim();
  if (line && !line.startsWith('#')) {
    const [key, ...val] = line.split('=');
    env[key.trim()] = val.join('=').trim();
  }
});

// ── Helpers ──

function httpGet(host, port, reqPath, headers, useHttps = false) {
  return new Promise(resolve => {
    const mod = useHttps ? https : http;
    const options = {
      hostname: host, port, path: reqPath, headers,
      rejectUnauthorized: false, timeout: 8000
    };
    mod.get(options, res => {
      let body = '';
      res.on('data', d => body += d);
      res.on('end', () => {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          try { resolve(JSON.parse(body)); } catch { resolve(null); }
        } else { resolve(null); }
      });
    }).on('error', () => resolve(null)).on('timeout', () => resolve(null));
  });
}

function tcpCheck(host, port, timeout = 5000) {
  return new Promise(resolve => {
    const sock = net.createConnection(port, host);
    sock.setTimeout(timeout);
    sock.on('connect', () => { sock.destroy(); resolve(true); });
    sock.on('error', () => resolve(false));
    sock.on('timeout', () => { sock.destroy(); resolve(false); });
  });
}

function formatUptime(seconds) {
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (d > 0) return `${d}d ${h}h ${m}m`;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

function formatBytes(bytes) {
  if (bytes >= 1e12) return (bytes / 1e12).toFixed(1) + ' TB';
  if (bytes >= 1e9) return (bytes / 1e9).toFixed(1) + ' GB';
  return (bytes / 1e6).toFixed(0) + ' MB';
}

function statusIcon(ok) { return ok ? '[OK]' : '[!!]'; }

function pad(str, len) { return (str + '').substring(0, len).padEnd(len); }

// ── Data Fetchers ──

async function getUDMInfo() {
  const info = { online: false, clients: '?', wanIP: '?', uptime: '?' };
  const health = await httpGet(env.UDM_HOST, 443,
    '/proxy/network/api/s/default/stat/health',
    { 'X-API-KEY': env.UDM_API_KEY }, true);
  if (!health) return info;
  info.online = true;

  const data = health.data || health;
  if (Array.isArray(data)) {
    for (const sub of data) {
      if (sub.subsystem === 'wan') {
        info.wanIP = sub.wan_ip || '?';
        info.clients = sub.num_sta || '?';
        const gwStats = sub['gw_system-stats'];
        if (gwStats && gwStats.uptime) info.uptime = formatUptime(Number(gwStats.uptime));
        if (gwStats && gwStats.mem) info.mem = gwStats.mem + '%';
        if (gwStats && gwStats.cpu) info.cpu = gwStats.cpu + '%';
        info.isp = sub.isp_name || '';
      }
    }
  }
  return info;
}

async function getProxmoxInfo() {
  const info = { online: false, vms: [], cpu: '?', ram: '?' };
  const headers = { 'Authorization': 'PVEAPIToken=' + env.PROXMOX_TOKEN };

  // Get node status
  const nodeStatus = await httpGet(env.PROXMOX_HOST, parseInt(env.PROXMOX_PORT),
    `/api2/json/nodes/${env.PROXMOX_NODE || 'pve'}/status`, headers, true);
  if (nodeStatus && nodeStatus.data) {
    info.online = true;
    const d = nodeStatus.data;
    if (d.cpu !== undefined) info.cpu = (d.cpu * 100).toFixed(0) + '%';
    if (d.memory) {
      const used = d.memory.used || 0;
      const total = d.memory.total || 1;
      info.ram = (used / total * 100).toFixed(0) + '% (' + formatBytes(used) + '/' + formatBytes(total) + ')';
    }
  }

  // Get VMs
  const qemu = await httpGet(env.PROXMOX_HOST, parseInt(env.PROXMOX_PORT),
    `/api2/json/nodes/${env.PROXMOX_NODE || 'pve'}/qemu`, headers, true);
  if (qemu && qemu.data) {
    info.online = true;
    info.vms = qemu.data.map(vm => ({
      id: vm.vmid,
      name: vm.name || 'VM ' + vm.vmid,
      status: vm.status || 'unknown'
    }));
  }

  // Get containers (LXC)
  const lxc = await httpGet(env.PROXMOX_HOST, parseInt(env.PROXMOX_PORT),
    `/api2/json/nodes/${env.PROXMOX_NODE || 'pve'}/lxc`, headers, true);
  if (lxc && lxc.data) {
    lxc.data.forEach(ct => {
      info.vms.push({
        id: ct.vmid,
        name: ct.name || 'CT ' + ct.vmid,
        status: ct.status || 'unknown'
      });
    });
  }

  // Sort by ID
  info.vms.sort((a, b) => a.id - b.id);
  return info;
}

async function getHAInfo() {
  const info = { online: false, version: '?', entityCount: 0, bikeEntities: [], unavailableBike: [] };

  const apiCheck = await httpGet(env.HA_HOST, parseInt(env.HA_PORT), '/api/',
    { 'Authorization': 'Bearer ' + env.HA_TOKEN }, false);
  if (!apiCheck) return info;
  info.online = true;

  const config = await httpGet(env.HA_HOST, parseInt(env.HA_PORT), '/api/config',
    { 'Authorization': 'Bearer ' + env.HA_TOKEN }, false);
  if (config) info.version = config.version || '?';

  const states = await httpGet(env.HA_HOST, parseInt(env.HA_PORT), '/api/states',
    { 'Authorization': 'Bearer ' + env.HA_TOKEN }, false);
  if (states && Array.isArray(states)) {
    info.entityCount = states.length;
    info.bikeEntities = states.filter(s => {
      const id = (s.entity_id || '').toLowerCase();
      const name = ((s.attributes || {}).friendly_name || '').toLowerCase();
      return id.includes('bike') || name.includes('bike');
    });
    info.unavailableBike = info.bikeEntities.filter(s => s.state === 'unavailable');
  }
  return info;
}

async function getBikeInfo() {
  const info = { online: false, hassAgentConnected: false };
  info.online = await tcpCheck(env.BIKE_HOST, 22);
  // HASS.Agent check: if bike entities are available in HA, agent is connected
  // This gets set from HA info later
  return info;
}

async function getNASInfo() {
  const info = { online: false, diskUsage: '?' };
  info.online = await tcpCheck(env.NAS_HOST, 22);
  return info;
}

async function getMQTTInfo() {
  return { online: await tcpCheck(env.HA_HOST, 1883) };
}

// ── Dashboard Renderer ──

function printSeparator(title) {
  const line = '='.repeat(60);
  console.log('\n' + line);
  if (title) console.log('  ' + title);
  console.log(line);
}

async function main() {
  console.log('\n  STARTUP DASHBOARD');
  console.log('  ' + new Date().toLocaleString());

  // Fetch all data in parallel
  const [udm, proxmox, ha, bike, nas, mqtt] = await Promise.all([
    getUDMInfo(),
    getProxmoxInfo(),
    getHAInfo(),
    getBikeInfo(),
    getNASInfo(),
    getMQTTInfo(),
  ]);

  // Determine HASS.Agent status from HA bike entities
  bike.hassAgentConnected = ha.online && ha.unavailableBike.length === 0 && ha.bikeEntities.length > 0;

  // ── System Health ──
  printSeparator('SYSTEM HEALTH');

  // UDM Pro
  console.log(`\n  ${statusIcon(udm.online)} UDM Pro (${env.UDM_HOST})`);
  if (udm.online) {
    console.log(`     Clients: ${udm.clients}  |  WAN IP: ${udm.wanIP}  |  Uptime: ${udm.uptime}`);
    if (udm.cpu || udm.mem) console.log(`     CPU: ${udm.cpu || '?'}  |  RAM: ${udm.mem || '?'}${udm.isp ? '  |  ISP: ' + udm.isp : ''}`);
  } else {
    console.log('     UNREACHABLE');
  }

  // Proxmox
  console.log(`\n  ${statusIcon(proxmox.online)} Proxmox (${env.PROXMOX_HOST}:${env.PROXMOX_PORT})`);
  if (proxmox.online) {
    console.log(`     CPU: ${proxmox.cpu}  |  RAM: ${proxmox.ram}`);
    if (proxmox.vms.length > 0) {
      console.log('     VMs/CTs:');
      proxmox.vms.forEach(vm => {
        const icon = vm.status === 'running' ? '[OK]' : '[!!]';
        console.log(`       ${icon} ${pad(vm.id, 5)} ${pad(vm.name, 25)} ${vm.status}`);
      });
    }
  } else {
    console.log('     UNREACHABLE');
  }

  // Home Assistant
  console.log(`\n  ${statusIcon(ha.online)} Home Assistant (${env.HA_HOST}:${env.HA_PORT})`);
  if (ha.online) {
    console.log(`     Version: ${ha.version}  |  Entities: ${ha.entityCount}`);
    if (ha.bikeEntities.length > 0) {
      console.log(`     Bike entities: ${ha.bikeEntities.length} total, ${ha.unavailableBike.length} unavailable`);
    }
  } else {
    console.log('     UNREACHABLE');
  }

  // Bike Computer
  console.log(`\n  ${statusIcon(bike.online)} Bike Computer (${env.BIKE_HOST})`);
  if (bike.online) {
    const agentStatus = bike.hassAgentConnected ? 'Connected' : 'Disconnected/Unknown';
    const agentIcon = bike.hassAgentConnected ? '[OK]' : '[!!]';
    console.log(`     SSH: Online  |  HASS.Agent: ${agentIcon} ${agentStatus}`);
  } else {
    console.log('     OFFLINE (SSH unreachable)');
  }

  // NAS
  console.log(`\n  ${statusIcon(nas.online)} Synology NAS (${env.NAS_HOST})`);
  if (nas.online) {
    console.log('     SSH: Online');
  } else {
    console.log('     OFFLINE (SSH unreachable)');
  }

  // MQTT
  console.log(`\n  ${statusIcon(mqtt.online)} MQTT Broker (${env.HA_HOST}:1883)`);
  if (!mqtt.online) {
    console.log('     UNREACHABLE');
  }

  // ── Alerts ──
  const alerts = [];
  if (!udm.online) alerts.push('UDM Pro is unreachable — no network management');
  if (!proxmox.online) alerts.push('Proxmox is unreachable — VMs may be down');
  if (!ha.online) alerts.push('Home Assistant is unreachable — automations offline');
  if (!bike.online) alerts.push('Bike Computer is offline');
  if (!nas.online) alerts.push('Synology NAS is offline — check power/network');
  if (!mqtt.online) alerts.push('MQTT Broker is down — HASS.Agent and IoT devices disconnected');
  if (ha.online && !bike.hassAgentConnected) {
    if (!bike.online) {
      alerts.push('HASS.Agent disconnected (bike computer is off) — bike buttons unavailable in HA');
    } else if (ha.bikeEntities.length === 0) {
      alerts.push('No bike entities found in HA — HASS.Agent may not be configured');
    } else {
      alerts.push(`HASS.Agent: ${ha.unavailableBike.length} bike entities unavailable — check HASS.Agent service`);
    }
  }

  // Flag stopped Proxmox VMs
  if (proxmox.online) {
    const stopped = proxmox.vms.filter(v => v.status === 'stopped');
    if (stopped.length > 0) {
      alerts.push(`Proxmox: ${stopped.length} VM(s) stopped: ${stopped.map(v => v.name).join(', ')}`);
    }
  }

  printSeparator('ALERTS');
  if (alerts.length === 0) {
    console.log('\n  No alerts — all systems operational!');
  } else {
    alerts.forEach(a => console.log(`\n  [!!] ${a}`));
  }

  // ── Quick Commands ──
  printSeparator('QUICK COMMANDS');
  console.log(`
  "check firewall"     - Review UDM Pro firewall rules
  "bike on/off"        - Control bike trainer power
  "proxmox vms"        - Show VM status details
  "nas storage"        - Check NAS disk usage
  "ha entities"        - List Home Assistant entities
  "test connections"   - Re-run this status check
  "status"             - Re-run this status check
`);

  console.log('='.repeat(60) + '\n');
}

main().catch(err => {
  console.error('Dashboard error:', err.message);
  process.exit(1);
});
