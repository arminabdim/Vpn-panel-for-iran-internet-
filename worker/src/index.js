/**
 * OpenPath Worker  -  a free "server" that lives on Cloudflare's edge.
 * ---------------------------------------------------------------------------
 * No VPS, no card, no domain required: paste this file into
 * Workers & Pages -> Create Worker  (or let `openpath.py` deploy it for you
 * through the Cloudflare API) and you get:
 *
 *   * VLESS  over WebSocket   (v2rayNG / MahsaNG / NekoBox / Hiddify / sing-box)
 *   * Trojan over WebSocket
 *   * a subscription endpoint: /sub -> text, base64, Clash, sing-box, Xray
 *   * an HTTP relay endpoint:  /relay?url=...  (Apps-Script-style fallback)
 *   * optional upstream chaining (SOCKS5 / HTTP-CONNECT) and "proxy IP"
 *
 * Free-plan limits that matter: 100,000 requests/day, 10 ms CPU per request,
 * 6 simultaneous outgoing connections, 128 MB memory. TCP only - Cloudflare
 * Workers cannot open UDP sockets, so Hysteria2 / TUIC / WireGuard cannot
 * terminate on a Worker (see ../paas/ for those).
 *
 * Deploy:  wrangler deploy  |  Cloudflare dashboard  |  openpath.py (API)
 */

import { connect } from 'cloudflare:sockets';

/* ------------------------------------------------------------------ */
/* Settings - OpenPath fills these in for you                           */
/* ------------------------------------------------------------------ */
const SETTINGS = {
  uuid: '{{UUID}}',                       // VLESS auth
  trojanPassword: '{{TROJAN_PASSWORD}}',  // Trojan auth (plain text; empty = off)
  wsPath: '{{WS_PATH}}',                  // WebSocket path
  subPath: '{{SUB_PATH}}',                // subscription path
  nodeName: '{{NODE_NAME}}',              // name shown in clients
  proxyIP: '{{PROXY_IP}}',                // optional transparent relay target
  proxyPort: {{PROXY_PORT}},
  upstreamMode: '{{UPSTREAM_MODE}}',      // direct | socks5 | http
  upstreamHost: '{{UPSTREAM_HOST}}',
  upstreamPort: {{UPSTREAM_PORT}},
  upstreamUser: '{{UPSTREAM_USER}}',
  upstreamPass: '{{UPSTREAM_PASS}}',
  relayEnabled: {{RELAY_ENABLED}},
  extraNodes: `{{EXTRA_NODES}}`,          // extra share links in the subscription
};

// Cloudflare accepts TLS on these ports, and plain HTTP on the others.
const TLS_PORTS = [443, 8443, 2053, 2083, 2087];
const PLAIN_PORTS = [80, 8080, 8880, 2052, 2082, 2086];

/* ------------------------------------------------------------------ */
/* entry point                                                          */
/* ------------------------------------------------------------------ */
export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    try {
      if ((request.headers.get('Upgrade') || '').toLowerCase() === 'websocket') {
        return await handleWebsocket(url);
      }
      if (url.pathname === '/' || url.pathname === '') return homePage(url);
      if (url.pathname === '/health') return new Response('ok', { headers: corsHeaders() });
      if (SETTINGS.relayEnabled && url.pathname.startsWith('/relay')) return await handleRelay(request, url);
      if (url.pathname.startsWith('/' + SETTINGS.subPath)) return subscriptionResponse(url);
      return new Response('Not found\n', { status: 404, headers: corsHeaders() });
    } catch (error) {
      return new Response('OpenPath error: ' + ((error && error.message) || String(error)), {
        status: 500,
        headers: corsHeaders(),
      });
    }
  },
};

function corsHeaders() {
  return {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, POST, PUT, OPTIONS',
    'Access-Control-Allow-Headers': '*',
  };
}

/* ------------------------------------------------------------------ */
/* home page                                                            */
/* ------------------------------------------------------------------ */
function homePage(url) {
  const host = url.hostname;
  const sub = `https://${host}/${SETTINGS.subPath}`;
  const links = nodeLinks(host);
  const html = `<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>OpenPath Worker</title>
<style>
body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:#0f1115;color:#e6e6e6;margin:0;padding:24px;line-height:1.55}
.wrap{max-width:840px;margin:0 auto}
h1{font-size:22px;margin:0 0 4px}
code{background:#1a1d24;color:#9fe870;padding:2px 6px;border-radius:6px;word-break:break-all;font-size:12px}
textarea{width:100%;background:#1a1d24;color:#cfd3dc;border:1px solid #2a2f3a;border-radius:8px;padding:10px;margin:6px 0 14px;font-size:12px}
a{color:#7cc4ff}
.card{background:#151821;border:1px solid #232936;border-radius:12px;padding:16px;margin:14px 0}
button{background:#2f81f7;border:0;color:#fff;padding:6px 12px;border-radius:8px;cursor:pointer;font-size:13px}
small{color:#8b93a7}
</style></head><body><div class="wrap">
<h1>OpenPath Worker is running</h1>
<small>Free edge tunnel on Cloudflare. Import the subscription below into v2rayNG / MahsaNG / Hiddify / NekoBox / sing-box.</small>
<div class="card"><b>Subscription URL</b>
<textarea id="sub" rows="2" readonly>${sub}</textarea>
<button onclick="copy('sub')">Copy</button>
<small style="display:block;margin-top:8px">Add <code>?format=b64</code> (default), <code>?format=clash</code>, <code>?format=singbox</code> or <code>?format=xray</code>.</small></div>
<div class="card"><b>Share links</b>
${links.map((l) => `<textarea rows="2" readonly id="${b64(String(l)).slice(0, 8)}">${escapeHtml(l)}</textarea>`).join('')}
<button onclick="copyAll()">Copy all</button></div>
<div class="card"><small>Client settings: network <b>ws</b>, path <b>${escapeHtml(
    SETTINGS.wsPath
  )}</b>, TLS <b>on</b> (443 / 2053 / 2083 / 2087 / 8443) or <b>off</b> (80 / 8080 / 2052 / 2082 / 2086), SNI <b>${escapeHtml(
    host
  )}</b>. If your ISP throttles Cloudflare ranges, set a <b>clean IP</b> in the client (see docs/METHODS.md).</small></div>
<script>
function copy(id){const el=document.getElementById(id);el.select();navigator.clipboard.writeText(el.value);}
function copyAll(){const t=[...document.querySelectorAll('textarea')].map(e=>e.value).join('\\n');navigator.clipboard.writeText(t);}
</script>
</div></body></html>`;
  return new Response(html, { status: 200, headers: { 'Content-Type': 'text/html; charset=utf-8', ...corsHeaders() } });
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

/* ------------------------------------------------------------------ */
/* share links + subscription                                           */
/* ------------------------------------------------------------------ */
function nodeLinks(host) {
  const out = [];
  const name = encodeURIComponent(SETTINGS.nodeName || 'OpenPath');
  const path = encodeURIComponent(SETTINGS.wsPath || '/');

  const mk = (port, security) => {
    const p = new URLSearchParams({
      encryption: 'none',
      security,
      type: 'ws',
      host,
      path: SETTINGS.wsPath || '/',
      fp: 'chrome',
    });
    if (security !== 'none') p.set('sni', host);
    return `vless://${SETTINGS.uuid}@${host}:${port}?${p.toString()}#${name}-${port}`;
  };

  if (SETTINGS.uuid) {
    for (const port of TLS_PORTS) out.push(mk(port, 'tls'));
    for (const port of PLAIN_PORTS) out.push(mk(port, 'none'));
  }
  if (SETTINGS.trojanPassword) {
    const p = new URLSearchParams({ security: 'tls', type: 'ws', host, path: SETTINGS.wsPath || '/', sni: host, fp: 'chrome' });
    out.push(`trojan://${encodeURIComponent(SETTINGS.trojanPassword)}@${host}:443?${p.toString()}#${name}-trojan`);
  }
  if (SETTINGS.extraNodes && SETTINGS.extraNodes.trim()) {
    for (const line of SETTINGS.extraNodes.split('\n')) {
      const t = line.trim();
      if (t) out.push(t);
    }
  }
  return out;
}

function b64(text) {
  const bytes = new TextEncoder().encode(text);
  let binary = '';
  for (const b of bytes) binary += String.fromCharCode(b);
  return btoa(binary);
}

function subscriptionResponse(url) {
  const links = nodeLinks(url.hostname);
  const text = links.join('\n');
  const format = (url.searchParams.get('format') || 'b64').toLowerCase();
  const plain = { 'Content-Type': 'text/plain; charset=utf-8', ...corsHeaders() };
  const json = { 'Content-Type': 'application/json; charset=utf-8', ...corsHeaders() };

  if (format === 'text' || format === 'v2ray') return new Response(text + '\n', { headers: plain });
  if (format === 'clash') return new Response(buildClash(links), { headers: { 'Content-Type': 'text/yaml; charset=utf-8', ...corsHeaders() } });
  if (format === 'singbox' || format === 'sing-box' || format === 'sfa') return new Response(JSON.stringify(buildSingbox(links), null, 2), { headers: json });
  if (format === 'xray') return new Response(JSON.stringify(buildXray(links), null, 2), { headers: json });
  return new Response(b64(text) + '\n', { headers: plain });
}

/* ------------------------------------------------------------------ */
/* tiny converters (kept in sync with openpath/core/configs.py)         */
/* ------------------------------------------------------------------ */
function parseLink(link) {
  try {
    const u = new URL(link);
    const proto = u.protocol.replace(':', '');
    const q = u.searchParams;
    const name = decodeURIComponent(u.hash.replace(/^#/, '') || u.hostname);
    const port = Number(u.port || 443);
    const security = (q.get('security') || 'tls').toLowerCase();
    const net = (q.get('type') || 'tcp').toLowerCase();
    if (proto === 'vless' || proto === 'trojan') {
      const ob = {
        type: proto,
        name,
        server: u.hostname,
        server_port: port,
        tls:
          security === 'none'
            ? undefined
            : {
                enabled: true,
                server_name: q.get('sni') || u.hostname,
                insecure: q.get('allowInsecure') === '1',
                utls: { enabled: true, fingerprint: q.get('fp') || 'chrome' },
              },
        transport:
          net === 'tcp'
            ? undefined
            : {
                type: net,
                path: q.get('path') || '/',
                headers: { Host: q.get('host') || u.hostname },
                service_name: q.get('serviceName') || undefined,
              },
      };
      if (proto === 'vless') {
        ob.uuid = u.username;
        ob.packet_encoding = 'xudp';
      } else {
        ob.password = decodeURIComponent(u.username);
      }
      return ob;
    }
  } catch (e) {
    /* not a link we understand */
  }
  return null;
}

function buildSingbox(links) {
  const outbounds = [];
  const tags = [];
  let i = 0;
  for (const l of links) {
    const ob = parseLink(l);
    if (!ob) continue;
    i += 1;
    ob.tag = `${ob.type}-${i}`;
    tags.push(ob.tag);
    outbounds.push(ob);
  }
  return {
    log: { level: 'warn' },
    dns: {
      servers: [{ tag: 'remote', address: 'https://1.1.1.1/dns-query', detour: 'select' }],
      final: 'remote',
      strategy: 'prefer_ipv4',
    },
    inbounds: [
      { type: 'mixed', tag: 'mixed-in', listen: '127.0.0.1', listen_port: 2080, sniff: true },
      {
        type: 'tun',
        tag: 'tun-in',
        address: ['172.19.0.1/30', 'fdfe:dcba:9876::1/126'],
        auto_route: true,
        strict_route: true,
        stack: 'mixed',
        mtu: 9000,
        sniff: true,
        endpoint_independent_nat: true,
      },
    ],
    outbounds: [
      { type: 'selector', tag: 'select', outbounds: ['auto', ...tags], default: 'auto' },
      { type: 'urltest', tag: 'auto', outbounds: tags, url: 'https://www.gstatic.com/generate_204', interval: '5m', tolerance: 100 },
      ...outbounds,
      { type: 'direct', tag: 'direct' },
      { type: 'block', tag: 'block' },
      { type: 'dns', tag: 'dns-out' },
    ],
    route: { rules: [{ action: 'sniff' }, { ip_is_private: true, outbound: 'direct' }], final: 'select', auto_detect_interface: true },
  };
}

function buildXray(links) {
  const outbounds = [];
  let i = 0;
  for (const l of links) {
    const ob = parseLink(l);
    if (!ob) continue;
    i += 1;
    const net = ob.transport ? ob.transport.type : 'tcp';
    const stream = { network: net, security: ob.tls ? 'tls' : 'none' };
    if (net === 'ws') {
      stream.wsSettings = {
        path: ob.transport.path || '/',
        headers: { Host: (ob.transport.headers && ob.transport.headers.Host) || ob.server },
      };
    }
    if (ob.tls) {
      stream.tlsSettings = { serverName: ob.tls.server_name, fingerprint: (ob.tls.utls && ob.tls.utls.fingerprint) || 'chrome' };
    }
    if (ob.type === 'vless') {
      outbounds.push({
        protocol: 'vless',
        tag: `proxy-${i}`,
        settings: { vnext: [{ address: ob.server, port: ob.server_port, users: [{ id: ob.uuid, encryption: 'none' }] }] },
        streamSettings: stream,
      });
    } else {
      outbounds.push({
        protocol: 'trojan',
        tag: `proxy-${i}`,
        settings: { servers: [{ address: ob.server, port: ob.server_port, password: ob.password }] },
        streamSettings: stream,
      });
    }
  }
  outbounds.push({ protocol: 'freedom', tag: 'direct' });
  return {
    log: { loglevel: 'warning' },
    inbounds: [
      {
        port: 10808,
        listen: '127.0.0.1',
        protocol: 'socks',
        settings: { auth: 'noauth', udp: true },
        sniffing: { enabled: true, destOverride: ['http', 'tls'] },
      },
    ],
    outbounds,
    routing: { domainStrategy: 'IPIfNonMatch' },
  };
}

function buildClash(links) {
  const proxies = [];
  const names = [];
  for (const l of links) {
    const ob = parseLink(l);
    if (!ob) continue;
    const p = { name: ob.name, type: ob.type, server: ob.server, port: Number(ob.server_port), udp: true };
    if (ob.type === 'vless') {
      p.uuid = ob.uuid;
      if (ob.tls) {
        p.tls = true;
        p.servername = ob.tls.server_name;
        p['client-fingerprint'] = (ob.tls.utls && ob.tls.utls.fingerprint) || 'chrome';
      }
    } else {
      p.password = ob.password;
      if (ob.tls) p.sni = ob.tls.server_name;
    }
    if (ob.transport && ob.transport.type === 'ws') {
      p.network = 'ws';
      p['ws-opts'] = { path: ob.transport.path || '/', headers: ob.transport.headers || {} };
    }
    proxies.push(p);
    names.push(p.name);
  }
  const q = (v) => `"${String(v).replace(/"/g, '\\"')}"`;
  // numbers and booleans must stay unquoted in YAML: a quoted port is a string,
  // and strict clients (mihomo / Clash) reject it
  const yv = (v) => (typeof v === 'boolean' || typeof v === 'number' ? String(v) : q(v));
  const lines = [
    'mixed-port: 7890',
    'allow-lan: false',
    'mode: rule',
    'log-level: warning',
    'ipv6: true',
    'dns:',
    '  enable: true',
    '  enhanced-mode: fake-ip',
    '  nameserver:',
    '    - https://1.1.1.1/dns-query',
    '    - https://8.8.8.8/dns-query',
    'proxies:',
  ];
  for (const p of proxies) {
    lines.push(`  - name: ${q(p.name)}`);
    for (const [k, v] of Object.entries(p)) {
      if (k === 'name' || v === undefined) continue;
      if (typeof v === 'object' && v !== null) {
        lines.push(`    ${k}:`);
        for (const [k2, v2] of Object.entries(v)) {
          if (typeof v2 === 'object' && v2 !== null) {
            lines.push(`      ${k2}:`);
            for (const [k3, v3] of Object.entries(v2)) lines.push(`        ${k3}: ${yv(v3)}`);
          } else {
            lines.push(`      ${k2}: ${yv(v2)}`);
          }
        }
      } else {
        lines.push(`    ${k}: ${yv(v)}`);
      }
    }
  }
  lines.push('proxy-groups:');
  lines.push(`  - name: ${q('PROXY')}`, '    type: select', '    proxies:', `      - ${q('AUTO')}`);
  for (const n of names) lines.push(`      - ${q(n)}`);
  lines.push(
    `  - name: ${q('AUTO')}`,
    '    type: url-test',
    '    url: https://www.gstatic.com/generate_204',
    '    interval: 300',
    '    proxies:'
  );
  for (const n of names) lines.push(`      - ${q(n)}`);
  lines.push('rules:', '  - MATCH,PROXY');
  return lines.join('\n') + '\n';
}

/* ------------------------------------------------------------------ */
/* HTTP relay (last-resort fallback, Apps-Script style)                 */
/* ------------------------------------------------------------------ */
async function handleRelay(request, url) {
  if (request.method === 'OPTIONS') return new Response(null, { headers: corsHeaders() });
  const target = url.searchParams.get('url') || url.searchParams.get('u');
  if (!target) {
    return new Response('OpenPath relay\nUsage: /relay?url=https%3A%2F%2Fexample.com\n', {
      headers: { 'Content-Type': 'text/plain; charset=utf-8', ...corsHeaders() },
    });
  }
  let t;
  try {
    t = new URL(target);
  } catch (e) {
    return new Response('bad url', { status: 400, headers: corsHeaders() });
  }
  if (t.protocol !== 'http:' && t.protocol !== 'https:') {
    return new Response('unsupported scheme', { status: 400, headers: corsHeaders() });
  }

  const headers = new Headers();
  for (const h of ['user-agent', 'accept', 'accept-language', 'range', 'content-type', 'authorization', 'cookie']) {
    const v = request.headers.get(h);
    if (v) headers.set(h, v);
  }
  headers.set('host', t.hostname);

  const init = { method: request.method, headers, redirect: 'follow' };
  if (request.method !== 'GET' && request.method !== 'HEAD') init.body = await request.arrayBuffer();

  const resp = await fetch(t.toString(), init);
  const out = new Headers(corsHeaders());
  for (const h of ['content-type', 'content-length', 'content-range', 'etag', 'last-modified', 'cache-control', 'content-disposition']) {
    const v = resp.headers.get(h);
    if (v) out.set(h, v);
  }
  return new Response(resp.body, { status: resp.status, headers: out });
}

/* ------------------------------------------------------------------ */
/* WebSocket: VLESS + Trojan                                            */
/* ------------------------------------------------------------------ */
async function handleWebsocket(url) {
  const requested = url.pathname;
  if (requested !== SETTINGS.wsPath) return new Response('not found', { status: 404 });

  const pair = new WebSocketPair();
  const client = pair[0];
  const server = pair[1];
  server.accept();

  let remote = null;
  let closed = false;

  const safeClose = () => {
    if (closed) return;
    closed = true;
    try {
      server.close();
    } catch (e) {}
    try {
      if (remote) remote.close();
    } catch (e) {}
  };

  server.addEventListener('message', async (event) => {
    try {
      const chunk = await toArrayBuffer(event.data);
      if (!remote) {
        const parsed = parseHeader(chunk);
        if (!parsed) {
          safeClose();
          return;
        }
        remote = await openOutbound(parsed.address, parsed.port);
        if (!remote) {
          safeClose();
          return;
        }
        const writer = remote.writable.getWriter();
        if (parsed.payload && parsed.payload.byteLength > 0) await writer.write(new Uint8Array(parsed.payload));
        writer.releaseLock();
        pump();
        return;
      }
      const writer = remote.writable.getWriter();
      await writer.write(new Uint8Array(chunk));
      writer.releaseLock();
    } catch (e) {
      safeClose();
    }
  });

  server.addEventListener('close', safeClose);
  server.addEventListener('error', safeClose);

  // remote -> websocket
  async function pump() {
    try {
      const reader = remote.readable.getReader();
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        if (server.readyState === 1) server.send(value);
      }
    } catch (e) {
      safeClose();
    }
  }

  return new Response(null, { status: 101, webSocket: client });
}

async function toArrayBuffer(data) {
  if (data instanceof ArrayBuffer) return data;
  if (ArrayBuffer.isView(data)) return data.buffer.slice(data.byteOffset, data.byteOffset + data.byteLength);
  if (typeof data === 'string') return new TextEncoder().encode(data).buffer;
  if (data && typeof data.arrayBuffer === 'function') return await data.arrayBuffer();
  throw new Error('unsupported ws frame');
}

/* ---------------------------- header parsing ------------------------- */
function hexOf(bytes) {
  let s = '';
  for (const b of bytes) s += b.toString(16).padStart(2, '0');
  return s;
}

function parseHeader(buffer) {
  if (!buffer || buffer.byteLength < 8) return null;
  if (SETTINGS.trojanPassword) {
    const trojan = parseTrojan(buffer);
    if (trojan) return trojan;
  }
  return parseVless(buffer);
}

/** Trojan: hex(sha224(password)) + CRLF + cmd + atyp + addr + port + CRLF */
function parseTrojan(buffer) {
  const b = new Uint8Array(buffer);
  if (b.length < 58) return null;
  const hex = hexOf(b.subarray(0, 56));
  if (hex !== sha224Hex(SETTINGS.trojanPassword)) return null;
  if (b[56] !== 0x0d || b[57] !== 0x0a) return null;

  let o = 58;
  const cmd = b[o++];
  if (cmd !== 1 && cmd !== 3) return null;
  const atyp = b[o++];
  let address = '';
  if (atyp === 1) {
    address = [...b.subarray(o, o + 4)].join('.');
    o += 4;
  } else if (atyp === 3) {
    const len = b[o++];
    address = new TextDecoder().decode(b.subarray(o, o + len));
    o += len;
  } else if (atyp === 4) {
    const parts = [];
    for (let i = 0; i < 8; i++) parts.push(((b[o + i * 2] << 8) | b[o + i * 2 + 1]).toString(16));
    address = parts.join(':');
    o += 16;
  } else {
    return null;
  }
  const port = (b[o] << 8) | b[o + 1];
  o += 2;
  if (b[o] === 0x0d && b[o + 1] === 0x0a) o += 2;
  return { protocol: 'trojan', address, port, payload: buffer.slice(o) };
}

/** VLESS request header (TCP only - Workers cannot open UDP sockets). */
function parseVless(buffer) {
  const b = new Uint8Array(buffer);
  if (b[0] !== 0) return null;
  const uuid = hexOf(b.subarray(1, 17));
  const expected = String(SETTINGS.uuid || '').replace(/-/g, '').toLowerCase();
  if (uuid !== expected) return null;

  const optLen = b[17];
  let o = 18 + optLen; // command
  const cmd = b[o];
  if (cmd !== 1) return null; // 1 = TCP, 2 = UDP (unsupported)
  const port = (b[o + 1] << 8) | b[o + 2];
  const atyp = b[o + 3];
  o += 4;

  let address = '';
  if (atyp === 1) {
    address = [...b.subarray(o, o + 4)].join('.');
    o += 4;
  } else if (atyp === 2) {
    const len = b[o++];
    address = new TextDecoder().decode(b.subarray(o, o + len));
    o += len;
  } else if (atyp === 3) {
    const parts = [];
    for (let i = 0; i < 8; i++) parts.push(((b[o + i * 2] << 8) | b[o + i * 2 + 1]).toString(16));
    address = parts.join(':');
    o += 16;
  } else {
    return null;
  }
  return { protocol: 'vless', address, port, payload: buffer.slice(o) };
}

/* ------------------------------------------------------------------ */
/* SHA-224 (WebCrypto has no SHA-224; Trojan needs exactly it)          */
/* ------------------------------------------------------------------ */
let _sha224Cache = null;

function sha224Hex(text) {
  if (typeof text !== 'string') return '';
  if (_sha224Cache && _sha224Cache.input === text) return _sha224Cache.out;
  const out = hexOf(sha224(new TextEncoder().encode(text)));
  _sha224Cache = { input: text, out };
  return out;
}

function sha224(message) {
  const H = [0xc1059ed8, 0x367cd507, 0x3070dd17, 0xf70e5939, 0xffc00b31, 0x68581511, 0x64f98fa7, 0xbefa4fa4];
  const K = [
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01,
    0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc,
    0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147,
    0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116, 0x1e376c08,
    0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
    0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
  ];
  const ml = message.length;
  const withOne = ml + 1;
  const zeroPad = ((56 - withOne) % 64 + 64) % 64;
  const total = withOne + zeroPad + 8;
  const buf = new Uint8Array(total);
  buf.set(message, 0);
  buf[ml] = 0x80;
  const bitLenHi = Math.floor((ml * 8) / 4294967296);
  const bitLenLo = (ml * 8) >>> 0;
  const dv = new DataView(buf.buffer);
  dv.setUint32(total - 8, bitLenHi);
  dv.setUint32(total - 4, bitLenLo);

  const w = new Uint32Array(64);
  for (let i = 0; i < total; i += 64) {
    for (let t = 0; t < 16; t++) w[t] = dv.getUint32(i + t * 4);
    for (let t = 16; t < 64; t++) {
      const s0 = rotr(w[t - 15], 7) ^ rotr(w[t - 15], 18) ^ (w[t - 15] >>> 3);
      const s1 = rotr(w[t - 2], 17) ^ rotr(w[t - 2], 19) ^ (w[t - 2] >>> 10);
      w[t] = (w[t - 16] + s0 + w[t - 7] + s1) >>> 0;
    }
    let [a, b, c, d, e, f, g, h] = H;
    for (let t = 0; t < 64; t++) {
      const S1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
      const ch = (e & f) ^ (~e & g);
      const t1 = (h + S1 + ch + K[t] + w[t]) >>> 0;
      const S0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
      const maj = (a & b) ^ (a & c) ^ (b & c);
      const t2 = (S0 + maj) >>> 0;
      h = g;
      g = f;
      f = e;
      e = (d + t1) >>> 0;
      d = c;
      c = b;
      b = a;
      a = (t1 + t2) >>> 0;
    }
    H[0] = (H[0] + a) >>> 0;
    H[1] = (H[1] + b) >>> 0;
    H[2] = (H[2] + c) >>> 0;
    H[3] = (H[3] + d) >>> 0;
    H[4] = (H[4] + e) >>> 0;
    H[5] = (H[5] + f) >>> 0;
    H[6] = (H[6] + g) >>> 0;
    H[7] = (H[7] + h) >>> 0;
  }
  const out = new Uint8Array(28);
  const odv = new DataView(out.buffer);
  for (let i = 0; i < 7; i++) odv.setUint32(i * 4, H[i]);
  return out;
}

function rotr(x, n) {
  return ((x >>> n) | (x << (32 - n))) >>> 0;
}

/* ------------------------------------------------------------------ */
/* outbound: direct / proxy IP / SOCKS5 / HTTP CONNECT                  */
/* ------------------------------------------------------------------ */
async function openOutbound(address, port) {
  const mode = (SETTINGS.upstreamMode || 'direct').toLowerCase();

  if (mode === 'socks5' && SETTINGS.upstreamHost) {
    const sock = tcpConnect(SETTINGS.upstreamHost, SETTINGS.upstreamPort || 1080);
    if (!sock) return null;
    try {
      await socks5Handshake(sock, address, port, SETTINGS.upstreamUser, SETTINGS.upstreamPass);
      return sock;
    } catch (e) {
      try {
        sock.close();
      } catch (x) {}
      return null;
    }
  }

  if (mode === 'http' && SETTINGS.upstreamHost) {
    const sock = tcpConnect(SETTINGS.upstreamHost, SETTINGS.upstreamPort || 8080);
    if (!sock) return null;
    try {
      await httpConnect(sock, address, port, SETTINGS.upstreamUser, SETTINGS.upstreamPass);
      return sock;
    } catch (e) {
      try {
        sock.close();
      } catch (x) {}
      return null;
    }
  }

  if (SETTINGS.proxyIP) return tcpConnect(SETTINGS.proxyIP, SETTINGS.proxyPort || port);
  return tcpConnect(address, port);
}

function tcpConnect(hostname, port) {
  try {
    return connect({ hostname, port: Number(port) || 443 });
  } catch (e) {
    return null;
  }
}

async function socks5Handshake(socket, host, port, user, pass) {
  const writer = socket.writable.getWriter();
  const reader = socket.readable.getReader();
  try {
    const methods = user ? [0x00, 0x02] : [0x00];
    await writer.write(new Uint8Array([0x05, methods.length, ...methods]));
    let res = await readExactly(reader, 2);
    if (res[1] === 0x02 && user) {
      const u = new TextEncoder().encode(user);
      const p = new TextEncoder().encode(pass || '');
      await writer.write(new Uint8Array([0x01, u.length, ...u, p.length, ...p]));
      res = await readExactly(reader, 2);
      if (res[1] !== 0x00) throw new Error('socks auth failed');
    } else if (res[1] !== 0x00) {
      throw new Error('socks: no acceptable method');
    }
    const isIp = /^\d{1,3}(\.\d{1,3}){3}$/.test(host);
    const hostBytes = isIp ? host.split('.').map(Number) : new TextEncoder().encode(host);
    const req = new Uint8Array([
      0x05,
      0x01,
      0x00,
      isIp ? 0x01 : 0x03,
      ...(isIp ? [] : [hostBytes.length]),
      ...hostBytes,
      (port >> 8) & 0xff,
      port & 0xff,
    ]);
    await writer.write(req);
    const reply = await readExactly(reader, 10);
    if (reply[1] !== 0x00) throw new Error('socks connect failed: ' + reply[1]);
  } finally {
    writer.releaseLock();
    reader.releaseLock();
  }
}

async function httpConnect(socket, host, port, user, pass) {
  const writer = socket.writable.getWriter();
  const reader = socket.readable.getReader();
  try {
    let req = `CONNECT ${host}:${port} HTTP/1.1\r\nHost: ${host}:${port}\r\n`;
    if (user) req += `Proxy-Authorization: Basic ${b64(`${user}:${pass || ''}`)}\r\n`;
    req += '\r\n';
    await writer.write(new TextEncoder().encode(req));
    let buf = '';
    const decoder = new TextDecoder();
    while (!buf.includes('\r\n\r\n')) {
      const { done, value } = await reader.read();
      if (done) throw new Error('http proxy closed');
      buf += decoder.decode(value, { stream: true });
    }
    if (!/ 2\d\d /.test(buf.split('\r\n')[0])) throw new Error('http proxy refused: ' + buf.split('\r\n')[0]);
  } finally {
    writer.releaseLock();
    reader.releaseLock();
  }
}

async function readExactly(reader, n) {
  const chunks = [];
  let total = 0;
  while (total < n) {
    const { done, value } = await reader.read();
    if (done) throw new Error('closed');
    chunks.push(value);
    total += value.length;
  }
  const out = new Uint8Array(total);
  let off = 0;
  for (const c of chunks) {
    out.set(c, off);
    off += c.length;
  }
  return out;
}
