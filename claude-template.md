# Project: Home Network Management

This project manages 6 systems on your home network. All credentials are in `.env`.

## On Session Start

When starting a new session, run the startup dashboard `scripts/startup-dashboard.js` to check all systems. It shows health details, alerts, and quick commands. Display the output to the user.

For a simple port-check only, use `scripts/test-connections.js` instead.

## Quick Commands

When the user says any of these, respond accordingly:
- **"check firewall"** — Review UDM Pro firewall rules (query API or SSH)
- **"bike on/off"** — Control bike trainer power via Home Assistant
- **"proxmox vms"** — Show detailed VM/CT status from Proxmox API
- **"nas storage"** — Check NAS disk usage via SSH
- **"ha entities"** — List Home Assistant entities (optionally filtered)
- **"test connections"** or **"status"** — Re-run `node scripts/startup-dashboard.js` and show results

## Systems

| System | IP | Access Method | Details File |
|--------|-----|--------------|--------------|
| UDM Pro | {{UDM_HOST}} | API (X-API-KEY header) + SSH ({{UDM_SSH_USER}}) | unifi.md |
| Proxmox | {{PROXMOX_HOST}}:{{PROXMOX_PORT}} | API (PVEAPIToken) + SSH ({{PROXMOX_SSH_USER}}) | proxmox.md |
| Home Assistant | {{HA_HOST}}:{{HA_PORT}} | REST API (Bearer token) | homeassistant.md |
| Bike Computer | {{BIKE_HOST}} | SSH (Windows/OpenSSH) | bikecomputer.md |
| Synology NAS | {{NAS_HOST}} | SSH | nas.md |
| Media Center | {{MEDIA_HOST}} | SSH (Windows/OpenSSH) | — |

## How to Connect

### UDM Pro API
```javascript
// Node.js - HTTPS with self-signed cert
const https = require('https');
const options = {
  hostname: '{{UDM_HOST}}',
  path: '/proxy/network/api/s/default/...endpoint...',
  headers: { 'X-API-KEY': process.env.UDM_API_KEY },
  rejectUnauthorized: false
};
```

### UDM Pro SSH
```javascript
// Uses ssh2 npm package (install in project: npm install ssh2)
const {Client} = require('ssh2');
conn.connect({ host: '{{UDM_HOST}}', port: 22, username: '{{UDM_SSH_USER}}',
  password: process.env.UDM_SSH_PASS, tryKeyboard: true,
  authHandler: ['keyboard-interactive','password'] });
// keyboard-interactive handler must reply with password
```

### Proxmox API
```javascript
const https = require('https');
const options = {
  hostname: '{{PROXMOX_HOST}}', port: {{PROXMOX_PORT}},
  path: '/api2/json/...endpoint...',
  headers: { 'Authorization': 'PVEAPIToken=' + process.env.PROXMOX_TOKEN },
  rejectUnauthorized: false
};
```

### Home Assistant API
```javascript
const http = require('http'); // Note: HTTP not HTTPS
const options = {
  hostname: '{{HA_HOST}}', port: {{HA_PORT}},
  path: '/api/...endpoint...',
  headers: { 'Authorization': 'Bearer ' + process.env.HA_TOKEN }
};
```

### Bike Computer SSH
```javascript
// Standard SSH - password auth
conn.connect({ host: '{{BIKE_HOST}}', port: 22,
  username: '{{BIKE_SSH_USER}}', password: process.env.BIKE_SSH_PASS });
// Windows machine - use powershell commands
// For PowerShell scripts: write .ps1 file, encode as base64 UTF-16LE, run with powershell -EncodedCommand
```

### Media Center SSH
```javascript
// Standard SSH - password auth
conn.connect({ host: '{{MEDIA_HOST}}', port: 22,
  username: '{{MEDIA_SSH_USER}}', password: process.env.MEDIA_SSH_PASS });
// Windows machine - use powershell commands
// Windows machine - use powershell commands
```

### Synology NAS SSH
```javascript
conn.connect({ host: '{{NAS_HOST}}', port: 22,
  username: '{{NAS_SSH_USER}}', password: process.env.NAS_SSH_PASS,
  tryKeyboard: true, authHandler: ['keyboard-interactive','password'] });
```

## Important Notes

- **No python3 on Windows** — use Node.js for all scripting
- **ssh2 npm package required** — run `npm install ssh2` in project folder
- **UDM Pro SSH** requires keyboard-interactive auth (not just password)
- **NAS SSH** also requires keyboard-interactive auth (same pattern as UDM Pro)
- **Bike Computer** is Windows — use PowerShell commands over SSH. For complex scripts, write a .ps1 file, base64 encode it, and run with `powershell -EncodedCommand`
- **Home Assistant** uses HTTP (not HTTPS) on port {{HA_PORT}}. Only one instance at {{HA_HOST}} (other HA IPs in DHCP are old/unused)
- **Proxmox** uses HTTPS on port {{PROXMOX_PORT}} with self-signed cert. Node name is `{{PROXMOX_NODE}}`
- **HASS.Agent** runs on the bike computer, connects to HA via MQTT on {{HA_HOST}}:1883
- **NAS Docker CLI** not available via SSH — use DSM web UI Container Manager
- See **troubleshooting.md** for common issues and solutions

## Network Layout

- Main LAN: Default VLAN (untagged) — where all systems live
- IoT: Separate VLAN for smart home devices
- Additional VLANs as configured on UDM Pro

## File Index

| File | Purpose |
|------|---------|
| CLAUDE.md | This file — auto-loaded instructions |
| .env | All credentials |
| README.md | Quick reference |
| claude-template.md | Template for auto-generating CLAUDE.md |
| scripts/test-connections.js | Simple port-check for all systems |
| scripts/startup-dashboard.js | Rich startup dashboard with health, alerts, quick commands |
| dashboard/app.py | Flask web dashboard (port 9000) |
| dashboard/runtime.py | Path resolution for dev/frozen mode |
| dashboard/tray.py | System tray icon — starts/stops server, color status |
| dashboard/service_wrapper.py | Windows service wrapper (pywin32) |
| dashboard/service_tray.py | System tray icon for service mode |
| dashboard/services/dashboard.py | Health data aggregator with circuit breaker |
| dashboard/services/firewall.py | Firewall SSH stream (tcpdump + log tail, dual-mode) |
| dashboard/services/udm.py | UDM Pro API client |
| dashboard/services/proxmox.py | Proxmox API client |
| dashboard/services/homeassistant.py | Home Assistant API client |
| dashboard/services/nas.py | Synology NAS SSH health checks |
| dashboard/services/plex.py | Plex server stats, libraries, sessions |
| dashboard/services/overseerr.py | Overseerr media request integration |
| dashboard/services/downloads.py | SABnzbd/Sonarr/Radarr download status |
| dashboard/services/claude_relay.py | Claude CLI subprocess relay for chat |
| dashboard/services/claude_md_generator.py | Auto-generate CLAUDE.md from template |
| dashboard/services/settings.py | Settings page — read/write .env keys |
| dashboard/services/dns_cache.py | Async DNS reverse-lookup cache |
| dashboard/services/http_client.py | Shared requests session factory |
| dashboard/services/portcheck.py | TCP port-check utility |
| dashboard/services/ssh_utils.py | Shared SSH utilities |
| dashboard/services/config.py | Centralized timeout constants |
| dashboard/services/utils.py | Shared helpers (format_uptime, etc.) |
| dashboard/static/js/firewall.js | Live logs UI — main orchestrator |
| dashboard/static/js/firewall/ | Modular JS: dns-cache, log-parser, render-engine, device-picker, ip-popover, rules-viewer, keyboard-shortcuts |
| dashboard/data/chat_history.json | Persistent Claude Chat message history (auto-created) |
