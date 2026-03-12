const https = require('https');
const http = require('http');
const net = require('net');
const fs = require('fs');
const path = require('path');

// Load .env
const env = require('./lib/env-loader')();

const results = [];

function testTCP(name, host, port, timeout = 5000) {
  return new Promise(resolve => {
    const start = Date.now();
    const sock = net.createConnection(port, host);
    sock.setTimeout(timeout);
    sock.on('connect', () => {
      const ms = Date.now() - start;
      results.push({ name, host: host + ':' + port, status: 'OK', ms });
      sock.destroy();
      resolve();
    });
    sock.on('error', () => {
      results.push({ name, host: host + ':' + port, status: 'FAIL', ms: '-' });
      resolve();
    });
    sock.on('timeout', () => {
      results.push({ name, host: host + ':' + port, status: 'TIMEOUT', ms: '-' });
      sock.destroy();
      resolve();
    });
  });
}

function testHTTP(name, host, port, reqPath, headers, useHttps = false) {
  return new Promise(resolve => {
    const start = Date.now();
    const mod = useHttps ? https : http;
    const options = {
      hostname: host, port, path: reqPath, headers,
      rejectUnauthorized: false, timeout: 5000
    };
    mod.get(options, res => {
      let body = '';
      res.on('data', d => body += d);
      res.on('end', () => {
        const ms = Date.now() - start;
        const ok = res.statusCode >= 200 && res.statusCode < 300;
        results.push({ name, host: host + ':' + port, status: ok ? 'OK (' + res.statusCode + ')' : 'HTTP ' + res.statusCode, ms });
        resolve();
      });
    }).on('error', e => {
      results.push({ name, host: host + ':' + port, status: 'FAIL: ' + e.message, ms: '-' });
      resolve();
    }).on('timeout', () => {
      results.push({ name, host: host + ':' + port, status: 'TIMEOUT', ms: '-' });
      resolve();
    });
  });
}

async function main() {
  console.log('Testing connections...\n');

  await Promise.all([
    // UDM Pro API
    testHTTP('UDM Pro API', env.UDM_HOST, 443, '/proxy/network/api/s/default/stat/health',
      { 'X-API-KEY': env.UDM_API_KEY }, true),
    // UDM Pro SSH
    testTCP('UDM Pro SSH', env.UDM_HOST, 22),
    // Proxmox API
    testHTTP('Proxmox API', env.PROXMOX_HOST, parseInt(env.PROXMOX_PORT), '/api2/json/version',
      { 'Authorization': 'PVEAPIToken=' + env.PROXMOX_TOKEN }, true),
    // Proxmox SSH
    testTCP('Proxmox SSH', env.PROXMOX_HOST, 22),
    // Home Assistant API
    testHTTP('Home Assistant API', env.HA_HOST, parseInt(env.HA_PORT), '/api/',
      { 'Authorization': 'Bearer ' + env.HA_TOKEN }, false),
    // Bike Computer SSH
    testTCP('Bike Computer SSH', env.BIKE_HOST, 22),
    // NAS SSH
    testTCP('NAS SSH', env.NAS_HOST, 22),
    // MQTT Broker
    testTCP('MQTT Broker', env.HA_HOST, 1883),
  ]);

  // Print results table
  console.log('+----------------------+----------------------+----------+--------+');
  console.log('| System               | Host                 | Status   | ms     |');
  console.log('+----------------------+----------------------+----------+--------+');
  results.forEach(r => {
    const name = r.name.padEnd(20);
    const host = r.host.padEnd(20);
    const status = (r.status.startsWith('OK') ? 'OK' : 'FAIL').padEnd(8);
    const ms = (r.ms + '').padEnd(6);
    console.log('| ' + name + ' | ' + host + ' | ' + status + ' | ' + ms + ' |');
  });
  console.log('+----------------------+----------------------+----------+--------+');

  const failed = results.filter(r => !r.status.startsWith('OK'));
  if (failed.length === 0) {
    console.log('\nAll systems operational!');
  } else {
    console.log('\n' + failed.length + ' system(s) unreachable:');
    failed.forEach(r => console.log('  - ' + r.name + ' (' + r.host + '): ' + r.status));
  }
}

main();
