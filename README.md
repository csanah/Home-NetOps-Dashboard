# NetOps Dashboard

A self-hosted network operations dashboard for monitoring and managing home lab infrastructure. Built with Flask, HTMX, and Tailwind CSS.

## Features

- **Real-time system monitoring** — CPU, RAM, disk, and network stats for all systems
- **Live firewall logs** — Stream tcpdump or blocked-traffic logs with filtering, DNS resolution, and IP lookup
- **Device picker** — Browse connected clients from your UDM Pro, filter by status/type, click to filter logs
- **Downloads manager** — Monitor SABnzbd, Sonarr, Radarr, and Prowlarr from one page
- **Plex integration** — Library stats, active sessions, and media search
- **Overseerr integration** — Request stats, pending approvals, and trending media
- **Claude Chat relay** — Chat with Claude CLI directly from the dashboard (read-only mode)
- **Dark/light theme** — System-aware with manual toggle
- **Mobile responsive** — Works on phones and tablets over LAN
- **System tray app** — Start/stop server from the system tray with color-coded status icon
- **PIN protection** — Optional login gate for LAN access
- **Settings page** — Configure all connections, test connectivity, auto-detect API keys

## Supported Systems

| System | Connection | Features |
|--------|-----------|----------|
| UDM Pro | REST API + SSH | Health, clients, firewall rules, live logs |
| Proxmox | REST API + SSH | Node status, VM/CT list with CPU/RAM/net |
| Home Assistant | REST API | Entity states, automations, MQTT status |
| Synology NAS | SSH | Disk usage, volume health, temperatures |
| Bike Computer | SSH (Windows) | Online status, HASS.Agent integration |
| Media Center | SSH (Windows) | VM stats via Proxmox, downloads monitoring |

## Quick Start

### 1. Clone and install dependencies

```bash
# Python dependencies
pip install -r requirements.txt

# Node dependencies (for startup scripts)
npm install
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env with your system IPs, credentials, and API keys
```

### 3. Run

**Option A — System tray (recommended):**
```bash
cd dashboard
python tray.py
```

**Option B — Direct:**
```bash
cd dashboard
python app.py
```

The dashboard will be available at `http://localhost:7000` (or your configured port).

### 4. First-time setup

Visit the dashboard and go to **Settings** to:
1. Enter your system IPs and credentials
2. Use **Test Connection** buttons to verify each system
3. Use **Auto-Detect** to find API keys for Plex, Overseerr, and media services
4. Toggle card visibility and page features

## Project Structure

```
├── dashboard/
│   ├── app.py                 # Flask app + SocketIO + routes
│   ├── tray.py                # System tray launcher
│   ├── services/              # Backend service modules
│   │   ├── dashboard.py       # Main dashboard data aggregator
│   │   ├── udm.py             # UDM Pro API + SSH
│   │   ├── proxmox.py         # Proxmox API
│   │   ├── homeassistant.py   # Home Assistant API
│   │   ├── nas.py             # Synology NAS SSH
│   │   ├── firewall.py        # Live firewall log streaming
│   │   ├── dns_cache.py       # DNS reverse lookup cache
│   │   ├── downloads.py       # SABnzbd/Sonarr/Radarr/Prowlarr
│   │   ├── plex.py            # Plex Media Server API
│   │   ├── overseerr.py       # Overseerr API
│   │   ├── settings.py        # Settings management + connection tests
│   │   ├── claude_relay.py    # Claude CLI chat relay
│   │   ├── claude_md_generator.py  # Auto-generate CLAUDE.md from template
│   │   ├── http_client.py     # Shared HTTP client utilities
│   │   └── portcheck.py       # TCP port connectivity checks
│   ├── templates/             # Jinja2 templates (HTMX partials)
│   ├── static/                # CSS, JS, favicon
│   └── data/                  # Runtime data (chat history, etc.)
├── scripts/
│   ├── startup-dashboard.js   # CLI startup health check
│   └── test-connections.js    # Simple port connectivity test
├── .env.example               # Template for environment variables
├── requirements.txt           # Python dependencies
├── package.json               # Node.js dependencies
└── claude-template.md         # Template for auto-generated CLAUDE.md
```

## Environment Variables

See `.env.example` for the full list. Key variables:

- **DASHBOARD_PIN** — Optional PIN for login protection (leave empty to disable)
- **DASHBOARD_PORT** — Server port (default: 9000)
- **\*_HOST** — IP addresses for each system
- **\*_API_KEY / \*_TOKEN** — API credentials
- **\*_SSH_USER / \*_SSH_PASS** — SSH credentials
- **SHOW_\*** — Toggle dashboard cards and pages
- **PLEX_ENABLED / OVERSEERR_ENABLED** — Enable optional integrations

## Notes

- Uses **HTTP** for Home Assistant (not HTTPS) — standard for LAN installations
- Uses **HTTPS with self-signed certs** for UDM Pro and Proxmox (certificate verification disabled)
- SSH to UDM Pro and Synology NAS uses **keyboard-interactive** auth
- SSH to Windows machines (Bike Computer, Media Center) uses **PowerShell** commands
- The Claude Chat relay runs in **read-only mode** by default (no file edits)
- CLAUDE.md is auto-generated from `claude-template.md` when settings are saved

## License

MIT
