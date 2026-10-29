/*
 * OpenPath config engine (browser build).
 *
 * A faithful port of openpath/core/configs.py: the same canonical model, the
 * same share-link formats, the same sing-box / Clash / Xray exports. If you
 * change a format here, change it there too (the self test compares them).
 *
 * No dependencies, no network calls, works from file:// too.
 */
(function (global) {
  'use strict';

  const DEFAULTS = {
    name: 'OpenPath',
    proto: 'vless',
    server: '',
    port: 443,
    uuid: '',
    password: '',
    method: 'none',
    aid: 0,
    network: 'ws',
    security: 'tls',
    sni: '',
    host: '',
    path: '/',
    alpn: '',
    fp: 'chrome',
    flow: '',
    serviceName: '',
    mode: 'auto',
    headerType: 'none',
    pbk: '',
    sid: '',
    spx: '',
    obfs: '',
    obfs_password: '',
    up: '',
    down: '',
    congestion: 'bbr',
    udp_relay_mode: 'native',
    reduce_rtt: false,
    wg_private_key: '',
    wg_public_key: '',
    wg_preshared_key: '',
    wg_local_address: '172.16.0.2/32',
    wg_mtu: 1280,
    wg_reserved: '',
    insecure: false,
    udp: true,
    packet_encoding: 'xudp',
    fragment: false,
    fragment_size: '10-30',
    fragment_sleep: '10-20',
    record_fragment: false,
    tag: '',
  };

  /* ---------------------------- helpers ---------------------------- */
  function b64encode(str) {
    return btoa(unescape(encodeURIComponent(str)));
  }
  function b64decode(str) {
    try {
      return decodeURIComponent(escape(atob(String(str).trim())));
    } catch (e) {
      return '';
    }
  }
  function newUUID() {
    if (global.crypto && global.crypto.randomUUID) return global.crypto.randomUUID();
    const b = new Uint8Array(16);
    (global.crypto || global.msCrypto).getRandomValues(b);
    b[6] = (b[6] & 0x0f) | 0x40;
    b[8] = (b[8] & 0x3f) | 0x80;
    const h = Array.from(b, (x) => x.toString(16).padStart(2, '0')).join('');
    return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
  }
  function randPassword(n) {
    const alphabet = 'abcdefghijkmnopqrstuvwxyzACDEFGHJKLMNPQRSTUVWXYZ23456789';
    let out = '';
    const buf = new Uint32Array(n || 16);
    (global.crypto || global.msCrypto).getRandomValues(buf);
    for (let i = 0; i < buf.length; i++) out += alphabet[buf[i] % alphabet.length];
    return out;
  }
  function isUUID(v) {
    return /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/.test(v || '');
  }
  function coerceUUID(v) {
    v = (v || '').trim();
    if (isUUID(v)) return v;
    if (/^[0-9a-fA-F]{32}$/.test(v)) {
      const h = v.toLowerCase();
      return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
    }
    return '';
  }
  function isIP(v) {
    if (!v) return false;
    if (v.indexOf(':') >= 0) return /^[0-9a-fA-F:]+$/.test(v);
    return /^\d{1,3}(\.\d{1,3}){3}$/.test(v);
  }
  const int = (v, d) => {
    const n = parseInt(v, 10);
    return isNaN(n) ? d : n;
  };

  /* ---------------------------- normalize ---------------------------- */
  function normalize(cfg) {
    const c = Object.assign({}, DEFAULTS);
    Object.keys(cfg || {}).forEach((k) => {
      if (cfg[k] !== undefined && cfg[k] !== null) c[k] = cfg[k];
    });
    c.proto = String(c.proto || 'vless').toLowerCase().trim();
    if (c.proto === 'hy2') c.proto = 'hysteria2';
    if (c.proto === 'shadowsocks') c.proto = 'ss';
    c.server = String(c.server || '').trim();
    c.port = int(c.port, 443) || 443;
    c.uuid = coerceUUID(c.uuid);
    if (['vless', 'vmess', 'tuic'].indexOf(c.proto) >= 0 && !c.uuid) c.uuid = newUUID();
    if (['trojan', 'ss', 'hysteria2', 'hysteria'].indexOf(c.proto) >= 0 && !c.password) c.password = randPassword();
    c.network = String(c.network || 'ws').toLowerCase();
    c.security = String(c.security || 'tls').toLowerCase();
    if (!c.sni) c.sni = c.host || (isIP(c.server) ? '' : c.server);
    if (!c.host && ['ws', 'xhttp', 'httpupgrade', 'h2'].indexOf(c.network) >= 0) c.host = c.server;
    if (c.path && !String(c.path).startsWith('/') && ['ws', 'xhttp', 'httpupgrade', 'h2'].indexOf(c.network) >= 0) {
      c.path = '/' + c.path;
    }
    c.name = String(c.name || 'OpenPath').slice(0, 64);
    if (!c.tag) c.tag = c.name;
    c.insecure = !!c.insecure;
    c.udp = c.udp !== false;
    return c;
  }

  /* ---------------------------- share links ---------------------------- */
  function q(params) {
    return Object.keys(params)
      .filter((k) => params[k] !== undefined && params[k] !== null && params[k] !== '')
      .map((k) => `${encodeURIComponent(k)}=${encodeURIComponent(params[k])}`)
      .join('&');
  }
  const enc = encodeURIComponent;

  function vlessURI(c) {
    const p = { encryption: 'none', security: c.security, type: c.network };
    if (c.network !== 'tcp') {
      if (c.host) p.host = c.host;
      if (c.path) p.path = c.path;
    }
    if (c.security === 'tls' || c.security === 'reality') {
      if (c.sni) p.sni = c.sni;
      if (c.fp) p.fp = c.fp;
      if (c.alpn) p.alpn = c.alpn;
    }
    if (c.security === 'reality') {
      p.pbk = c.pbk;
      p.sid = c.sid;
      if (c.spx) p.spx = c.spx;
    }
    if (c.flow) p.flow = c.flow;
    if (c.network === 'grpc' && c.serviceName) p.serviceName = c.serviceName;
    if (c.network === 'xhttp') p.mode = c.mode || 'auto';
    if (c.network === 'ws' && c.packet_encoding) p.packetEncoding = c.packet_encoding;
    p.headerType = c.headerType || 'none';
    return `vless://${c.uuid}@${c.server}:${c.port}?${q(p)}#${enc(c.name)}`;
  }

  function trojanURI(c) {
    const p = { security: c.security || 'tls', type: c.network };
    if (['tcp', 'raw'].indexOf(c.network) < 0) {
      if (c.host) p.host = c.host;
      if (c.path) p.path = c.path;
    }
    if (c.sni) p.sni = c.sni;
    if (c.alpn) p.alpn = c.alpn;
    if (c.fp) p.fp = c.fp;
    if (c.network === 'grpc' && c.serviceName) p.serviceName = c.serviceName;
    return `trojan://${enc(c.password)}@${c.server}:${c.port}?${q(p)}#${enc(c.name)}`;
  }

  function vmessURI(c) {
    const obj = {
      v: '2',
      ps: c.name,
      add: c.server,
      port: String(c.port),
      id: c.uuid,
      aid: String(c.aid || 0),
      scy: c.method || 'none',
      net: c.network,
      type: c.headerType || 'none',
      host: c.host || '',
      path: c.network === 'grpc' ? c.serviceName || c.path || '' : c.path || '',
      tls: c.security === 'tls' || c.security === 'reality' ? 'tls' : '',
      sni: c.sni || '',
      alpn: c.alpn || '',
      fp: c.fp || '',
    };
    return 'vmess://' + b64encode(JSON.stringify(obj));
  }

  function ssURI(c) {
    const method = c.method || 'chacha20-ietf-poly1305';
    const userinfo = btoa(`${method}:${c.password}`).replace(/=+$/, '');
    let plugin = '';
    if (c.obfs && ['plain', 'none', ''].indexOf(c.obfs) < 0) {
      plugin = `?plugin=${enc(c.obfs)}`;
      if (c.host) plugin += `;${enc('obfs-host=' + c.host)}`;
    }
    return `ss://${userinfo}@${c.server}:${c.port}${plugin}#${enc(c.name)}`;
  }

  function hy2URI(c) {
    const p = {};
    if (c.sni) p.sni = c.sni;
    if (c.obfs) {
      p.obfs = c.obfs;
      if (c.obfs_password) p['obfs-password'] = c.obfs_password;
    }
    if (c.insecure) p.insecure = '1';
    if (c.up) p.up = c.up;
    if (c.down) p.down = c.down;
    if (c.alpn) p.alpn = c.alpn;
    const qs = q(p);
    return `hysteria2://${enc(c.password)}@${c.server}:${c.port}${qs ? '?' + qs : '/'}#${enc(c.name)}`;
  }

  function tuicURI(c) {
    const p = {};
    if (c.sni) p.sni = c.sni;
    if (c.alpn) p.alpn = c.alpn;
    if (c.congestion) p.congestion_control = c.congestion;
    if (c.udp_relay_mode) p.udp_relay_mode = c.udp_relay_mode;
    if (c.insecure) p.allow_insecure = '1';
    if (c.reduce_rtt) p.reduce_rtt = '1';
    const qs = q(p);
    return `tuic://${c.uuid}:${enc(c.password)}@${c.server}:${c.port}${qs ? '?' + qs : ''}#${enc(c.name)}`;
  }

  function wireguardURI(c) {
    const p = {
      address: c.wg_local_address || '172.16.0.2/32',
      publickey: c.wg_public_key || '',
      privatekey: c.wg_private_key || '',
    };
    if (c.wg_preshared_key) p.presharedkey = c.wg_preshared_key;
    if (c.wg_mtu) p.mtu = String(c.wg_mtu);
    if (c.wg_reserved) p.reserved = c.wg_reserved;
    if (!c.udp) p.udp = '0';
    return `wireguard://${c.server}:${c.port}?${q(p)}#${enc(c.name)}`;
  }

  function toUri(cfg) {
    const c = normalize(cfg);
    switch (c.proto) {
      case 'vless':
        return vlessURI(c);
      case 'trojan':
        return trojanURI(c);
      case 'vmess':
        return vmessURI(c);
      case 'ss':
        return ssURI(c);
      case 'hysteria2':
      case 'hysteria':
        return hy2URI(c);
      case 'tuic':
        return tuicURI(c);
      case 'wireguard':
        return wireguardURI(c);
      case 'socks':
      case 'http':
      case 'https': {
        const user = c.uuid || c.password ? `${enc(c.uuid || '')}:${enc(c.password || '')}@` : '';
        return `${c.proto}://${user}${c.server}:${c.port}#${enc(c.name)}`;
      }
      default:
        throw new Error('unsupported protocol: ' + c.proto);
    }
  }

  /* ---------------------------- parsing ---------------------------- */
  function parseQuery(uri) {
    const out = {};
    const idx = uri.indexOf('?');
    if (idx < 0) return out;
    const raw = uri.slice(idx + 1).split('#')[0];
    raw.split('&').forEach((pair) => {
      if (!pair) return;
      const [k, v] = pair.split('=');
      out[decodeURIComponent(k)] = decodeURIComponent((v || '').replace(/\+/g, ' '));
    });
    return out;
  }
  function fragment(uri) {
    const i = uri.indexOf('#');
    return i < 0 ? '' : decodeURIComponent(uri.slice(i + 1));
  }
  function hostPort(netloc) {
    let s = netloc.trim();
    if (s.indexOf('@') >= 0) s = s.slice(s.lastIndexOf('@') + 1);
    if (s.startsWith('[')) {
      const close = s.indexOf(']');
      return [s.slice(0, close + 1), s.slice(close + 2) || '443'];
    }
    const i = s.lastIndexOf(':');
    return i < 0 ? [s, '443'] : [s.slice(0, i), s.slice(i + 1) || '443'];
  }

  function parseUri(uri) {
    uri = String(uri || '').trim();
    if (uri.indexOf('://') < 0) return null;
    const scheme = uri.slice(0, uri.indexOf('://')).toLowerCase();
    const rest = uri.slice(scheme.length + 3);
    let cfg = null;

    if (scheme === 'vless') {
      const [userinfo, tail] = splitRight(rest, '@');
      const [host, port] = hostPort(tail.split('?')[0].split('#')[0]);
      const p = parseQuery(uri);
      cfg = {
        proto: 'vless',
        name: fragment(uri) || 'vless',
        uuid: coerceUUID(userinfo) || userinfo,
        server: host,
        port: int(port, 443),
        network: p.type || 'tcp',
        security: p.security || 'none',
        sni: p.sni || '',
        host: p.host || '',
        path: p.path || '',
        alpn: p.alpn || '',
        fp: p.fp || 'chrome',
        flow: p.flow || '',
        pbk: p.pbk || '',
        sid: p.sid || '',
        spx: p.spx || '',
        serviceName: p.serviceName || '',
        mode: p.mode || 'auto',
        headerType: p.headerType || 'none',
        packet_encoding: p.packetEncoding || 'xudp',
      };
    } else if (scheme === 'trojan') {
      const [userinfo, tail] = splitRight(rest, '@');
      const [host, port] = hostPort(tail.split('?')[0].split('#')[0]);
      const p = parseQuery(uri);
      cfg = {
        proto: 'trojan',
        name: fragment(uri) || 'trojan',
        password: decodeURIComponent(userinfo),
        server: host,
        port: int(port, 443),
        network: p.type || 'tcp',
        security: p.security || 'tls',
        sni: p.sni || '',
        host: p.host || '',
        path: p.path || '',
        alpn: p.alpn || '',
        fp: p.fp || 'chrome',
        serviceName: p.serviceName || '',
      };
    } else if (scheme === 'vmess') {
      let obj = null;
      const decoded = b64decode(rest.split('#')[0]);
      try {
        obj = JSON.parse(decoded);
      } catch (e) {
        try {
          obj = JSON.parse(decodeURIComponent(rest));
        } catch (e2) {
          obj = null;
        }
      }
      if (!obj) return null;
      cfg = {
        proto: 'vmess',
        name: obj.ps || 'vmess',
        server: obj.add || '',
        port: int(obj.port, 443),
        uuid: coerceUUID(obj.id || ''),
        aid: int(obj.aid, 0),
        method: obj.scy || 'none',
        network: obj.net || 'tcp',
        host: obj.host || '',
        path: obj.path || '',
        security: String(obj.tls || '').toLowerCase() === 'tls' ? 'tls' : 'none',
        sni: obj.sni || '',
        alpn: obj.alpn || '',
        fp: obj.fp || '',
        headerType: obj.type || 'none',
        serviceName: obj.net === 'grpc' ? obj.path || '' : '',
      };
    } else if (scheme === 'ss') {
      let payload = rest.split('#')[0];
      let plugin = '';
      const marker = payload.indexOf('?plugin=') >= 0 ? '?plugin=' : '&plugin=';
      if (payload.indexOf(marker) >= 0) {
        const parts = payload.split(marker);
        payload = parts[0];
        plugin = decodeURIComponent(parts[1] || '');
      }
      let method = 'chacha20-ietf-poly1305';
      let password = '';
      let host = '';
      let port = 443;
      if (payload.indexOf('@') >= 0) {
        const [userinfo, tail] = splitRight(payload, '@');
        [host, port] = hostPort(tail);
        const decoded = b64decode(decodeURIComponent(userinfo)) || atob(decodeURIComponent(userinfo));
        const i = decoded.indexOf(':');
        if (i > 0) {
          method = decoded.slice(0, i);
          password = decoded.slice(i + 1);
        } else {
          password = decoded;
        }
      } else {
        const decoded = b64decode(payload);
        if (!decoded || decoded.indexOf('@') < 0) return null;
        const [creds, tail] = splitRight(decoded, '@');
        [host, port] = hostPort(tail);
        const i = creds.indexOf(':');
        method = creds.slice(0, i);
        password = creds.slice(i + 1);
      }
      let obfs = '';
      let obfsHost = '';
      if (plugin) {
        const semi = plugin.indexOf(';');
        obfs = semi >= 0 ? plugin.slice(0, semi) : plugin;
        const opts = semi >= 0 ? plugin.slice(semi + 1) : '';
        opts.split(';').forEach((pair) => {
          const [k, v] = pair.split('=');
          if (k === 'obfs-host' || k === 'host') obfsHost = v || '';
        });
      }
      cfg = {
        proto: 'ss',
        name: fragment(uri) || 'ss',
        server: host,
        port: int(port, 443),
        method,
        password,
        obfs,
        host: obfsHost,
        network: 'tcp',
        security: 'none',
      };
    } else if (['hysteria2', 'hy2', 'hysteria'].indexOf(scheme) >= 0) {
      const [userinfo, tail] = splitRight(rest, '@');
      const [host, port] = hostPort(tail.split('?')[0].split('#')[0]);
      const p = parseQuery(uri);
      cfg = {
        proto: 'hysteria2',
        name: fragment(uri) || 'hysteria2',
        password: decodeURIComponent(userinfo),
        server: host,
        port: int(port, 443),
        sni: p.sni || '',
        obfs: p.obfs || '',
        obfs_password: p['obfs-password'] || '',
        insecure: p.insecure === '1' || p.insecure === 'true',
        up: p.up || '',
        down: p.down || '',
        alpn: p.alpn || '',
        network: 'raw',
        security: 'tls',
      };
    } else if (scheme === 'tuic') {
      const [userinfo, tail] = splitRight(rest, '@');
      const [host, port] = hostPort(tail.split('?')[0].split('#')[0]);
      const p = parseQuery(uri);
      const colon = userinfo.indexOf(':');
      cfg = {
        proto: 'tuic',
        name: fragment(uri) || 'tuic',
        uuid: coerceUUID(userinfo.slice(0, colon)) || userinfo.slice(0, colon),
        password: decodeURIComponent(userinfo.slice(colon + 1)),
        server: host,
        port: int(port, 443),
        sni: p.sni || '',
        alpn: p.alpn || '',
        congestion: p.congestion_control || 'bbr',
        udp_relay_mode: p.udp_relay_mode || 'native',
        insecure: p.allow_insecure === '1' || p.allow_insecure === 'true',
        reduce_rtt: p.reduce_rtt === '1',
        network: 'raw',
        security: 'tls',
      };
    } else if (scheme === 'wireguard') {
      const [host, port] = hostPort(rest.split('?')[0].split('#')[0]);
      const p = parseQuery(uri);
      cfg = {
        proto: 'wireguard',
        name: fragment(uri) || 'wireguard',
        server: host,
        port: int(port, 51820),
        wg_public_key: p.publickey || '',
        wg_private_key: p.privatekey || '',
        wg_preshared_key: p.presharedkey || '',
        wg_local_address: p.address || '172.16.0.2/32',
        wg_mtu: int(p.mtu, 1280),
        wg_reserved: p.reserved || '',
        network: 'raw',
        security: 'none',
      };
    } else if (['socks', 'socks5', 'http', 'https'].indexOf(scheme) >= 0) {
      let body = rest;
      let userinfo = '';
      if (body.indexOf('@') >= 0) {
        userinfo = body.slice(0, body.lastIndexOf('@'));
        body = body.slice(body.lastIndexOf('@') + 1);
      }
      const [host, port] = hostPort(body.split('#')[0]);
      const [user, pwd] = decodeURIComponent(userinfo).split(':');
      cfg = {
        proto: scheme.startsWith('socks') ? 'socks' : scheme,
        name: fragment(uri) || scheme,
        server: host,
        port: int(port, 1080),
        uuid: user || '',
        password: pwd || '',
        network: 'tcp',
        security: 'none',
      };
    } else {
      return null;
    }
    if (!cfg.server) return null;
    cfg._raw = uri;
    return normalize(cfg);
  }

  function splitRight(text, sep) {
    const i = text.lastIndexOf(sep);
    return i < 0 ? ['', text] : [text.slice(0, i), text.slice(i + 1)];
  }

  function parseAny(text) {
    const out = [];
    text = String(text || '').trim();
    if (text.startsWith('{')) {
      try {
        const obj = JSON.parse(text);
        if (obj && Array.isArray(obj.outbounds)) {
          obj.outbounds.forEach((ob) => {
            if (['selector', 'urltest', 'direct', 'block', 'dns'].indexOf(ob.type) >= 0) return;
            const c = fromSingbox(ob);
            if (c) out.push(c);
          });
          if (out.length) return out;
        }
      } catch (e) {
        /* fall through */
      }
    }
    const lines = text.split(/\r?\n/);
    const push = (line) => {
      const c = parseUri(line.trim());
      if (c) out.push(c);
    };
    lines.forEach((line) => {
      line = line.trim();
      if (!line) return;
      const direct = parseUri(line);
      if (direct) {
        out.push(direct);
        return;
      }
      const decoded = b64decode(line);
      if (decoded && decoded !== line && /^(vless|vmess|trojan|ss|tuic|hy2|hysteria2|wireguard|socks|http):\/\//m.test(decoded)) {
        decoded.split(/\r?\n/).forEach((l) => push(l));
      }
    });
    return out;
  }

  function fromSingbox(ob) {
    try {
      const tr = ob.transport || {};
      const tls = ob.tls || {};
      const base = {
        name: ob.tag || ob.type,
        server: ob.server || '',
        port: ob.server_port || 0,
      };
      if (ob.type === 'vless') {
        Object.assign(base, {
          proto: 'vless',
          uuid: ob.uuid,
          network: tr.type || 'tcp',
          path: tr.path || '',
          host: (tr.headers || {}).Host || '',
          serviceName: tr.service_name || '',
          security: (tls.reality || {}).enabled ? 'reality' : tls.enabled ? 'tls' : 'none',
          sni: tls.server_name || '',
          alpn: (tls.alpn || []).join(','),
          fp: ((tls.utls || {}).fingerprint) || '',
          flow: ob.flow || '',
          pbk: ((tls.reality || {}).public_key) || '',
          sid: ((tls.reality || {}).short_id) || '',
        });
      } else if (ob.type === 'trojan') {
        Object.assign(base, {
          proto: 'trojan',
          password: ob.password || '',
          network: tr.type || 'tcp',
          path: tr.path || '',
          host: (tr.headers || {}).Host || '',
          security: tls.enabled ? 'tls' : 'none',
          sni: tls.server_name || '',
        });
      } else if (ob.type === 'vmess') {
        Object.assign(base, {
          proto: 'vmess',
          uuid: ob.uuid || '',
          aid: ob.alter_id || 0,
          method: ob.security || 'none',
          network: tr.type || 'tcp',
          path: tr.path || '',
          host: (tr.headers || {}).Host || '',
          security: tls.enabled ? 'tls' : 'none',
          sni: tls.server_name || '',
        });
      } else if (ob.type === 'shadowsocks') {
        Object.assign(base, { proto: 'ss', method: ob.method || '', password: ob.password || '', network: 'tcp', security: 'none' });
      } else if (ob.type === 'hysteria2') {
        Object.assign(base, {
          proto: 'hysteria2',
          password: ob.password || '',
          obfs: (ob.obfs || {}).type || '',
          obfs_password: (ob.obfs || {}).password || '',
          up: ob.up_mbps ? String(ob.up_mbps) : '',
          down: ob.down_mbps ? String(ob.down_mbps) : '',
          sni: (ob.tls || {}).server_name || '',
          insecure: !!(ob.tls || {}).insecure,
          network: 'raw',
          security: 'tls',
        });
      } else if (ob.type === 'tuic') {
        Object.assign(base, {
          proto: 'tuic',
          uuid: ob.uuid || '',
          password: ob.password || '',
          congestion: ob.congestion_control || 'bbr',
          udp_relay_mode: ob.udp_relay_mode || 'native',
          sni: (ob.tls || {}).server_name || '',
          alpn: ((ob.tls || {}).alpn || []).join(','),
          insecure: !!(ob.tls || {}).insecure,
          network: 'raw',
          security: 'tls',
        });
      } else if (ob.type === 'wireguard') {
        const peer = (ob.peers || [{}])[0] || {};
        Object.assign(base, {
          proto: 'wireguard',
          wg_private_key: ob.private_key || '',
          wg_public_key: peer.public_key || '',
          wg_preshared_key: peer.pre_shared_key || '',
          wg_local_address: (ob.local_address || ['172.16.0.2/32']).join(','),
          wg_mtu: ob.mtu || 1280,
          wg_reserved: (peer.reserved || []).join(','),
          network: 'raw',
          security: 'none',
        });
      } else if (ob.type === 'socks' || ob.type === 'http') {
        Object.assign(base, { proto: ob.type, uuid: ob.username || '', password: ob.password || '', network: 'tcp', security: 'none' });
      } else {
        return null;
      }
      return normalize(base);
    } catch (e) {
      return null;
    }
  }

  /* ---------------------------- sing-box ---------------------------- */
  function tlsObject(c) {
    if (c.security === 'none') return undefined;
    const tls = { enabled: true, server_name: c.sni || undefined, insecure: !!c.insecure };
    if (c.alpn) tls.alpn = c.alpn.split(',').map((s) => s.trim()).filter(Boolean);
    if (c.fp) tls.utls = { enabled: true, fingerprint: c.fp };
    if (c.security === 'reality') tls.reality = { enabled: true, public_key: c.pbk, short_id: c.sid };
    if (c.fragment) {
      tls.fragment = { enabled: true, size: c.fragment_size || '10-30', sleep: c.fragment_sleep || '10-20' };
      tls.fragment_fallback_delay = '500ms';
    }
    if (c.record_fragment) tls.record_fragment = true;
    return clean(tls);
  }

  function transportObject(c) {
    const net = c.network;
    if (['tcp', 'raw', ''].indexOf(net) >= 0) return undefined;
    if (net === 'ws') {
      const tr = { type: 'ws', path: c.path || '/' };
      if (c.host) tr.headers = { Host: c.host };
      return tr;
    }
    if (net === 'httpupgrade') {
      const tr = { type: 'httpupgrade', path: c.path || '/' };
      if (c.host) tr.host = c.host;
      return tr;
    }
    if (net === 'grpc') return { type: 'grpc', service_name: c.serviceName || (c.path || '').replace(/^\//, '') || 'GunService' };
    if (net === 'xhttp') {
      const tr = { type: 'http', path: c.path || '/' };
      if (c.host) tr.host = [c.host];
      return tr;
    }
    if (net === 'h2') return clean({ type: 'http', path: c.path || '/', host: c.host ? [c.host] : undefined });
    if (net === 'quic') return { type: 'quic' };
    return undefined;
  }

  function clean(obj) {
    const out = {};
    Object.keys(obj).forEach((k) => {
      if (obj[k] !== undefined && obj[k] !== null && obj[k] !== '') out[k] = obj[k];
    });
    return out;
  }

  function toSingboxOutbound(cfg, tag) {
    const c = normalize(cfg);
    const t = tag || c.tag || c.name;
    const tls = tlsObject(c);
    const tr = transportObject(c);
    const out = { type: c.proto, tag: t };

    if (c.proto === 'vless') {
      Object.assign(out, { server: c.server, server_port: c.port, uuid: c.uuid });
      if (c.flow && c.security !== 'none') out.flow = c.flow;
      if (c.packet_encoding) out.packet_encoding = c.packet_encoding;
    } else if (c.proto === 'vmess') {
      Object.assign(out, { server: c.server, server_port: c.port, uuid: c.uuid, security: c.method || 'none', alter_id: c.aid || 0 });
    } else if (c.proto === 'trojan') {
      Object.assign(out, { server: c.server, server_port: c.port, password: c.password });
    } else if (c.proto === 'ss') {
      Object.assign(out, {
        server: c.server,
        server_port: c.port,
        method: c.method || 'chacha20-ietf-poly1305',
        password: c.password,
      });
    } else if (c.proto === 'hysteria2') {
      Object.assign(out, { server: c.server, server_port: c.port, password: c.password });
      if (c.obfs) out.obfs = { type: c.obfs, password: c.obfs_password || '' };
      if (c.up) out.up_mbps = int(c.up, 0) || undefined;
      if (c.down) out.down_mbps = int(c.down, 0) || undefined;
      const t2 = tls || { enabled: true, server_name: c.sni || c.server, insecure: !!c.insecure };
      if (c.alpn) t2.alpn = c.alpn.split(',').map((s) => s.trim()).filter(Boolean);
      out.tls = t2;
      return clean(out);
    } else if (c.proto === 'tuic') {
      Object.assign(out, {
        server: c.server,
        server_port: c.port,
        uuid: c.uuid,
        password: c.password,
        congestion_control: c.congestion || 'bbr',
        udp_relay_mode: c.udp_relay_mode || 'native',
        zero_rtt_handshake: !!c.reduce_rtt,
      });
      const t2 = tls || { enabled: true, server_name: c.sni || c.server, insecure: !!c.insecure };
      if (!t2.alpn) t2.alpn = ['h3'];
      out.tls = t2;
      return clean(out);
    } else if (c.proto === 'wireguard') {
      const peer = {
        server: c.server,
        server_port: c.port,
        public_key: c.wg_public_key,
        allowed_ips: ['0.0.0.0/0', '::/0'],
        persistent_keepalive_interval: 25,
      };
      if (c.wg_preshared_key) peer.pre_shared_key = c.wg_preshared_key;
      if (c.wg_reserved) {
        const r = String(c.wg_reserved)
          .split(',')
          .map((x) => int(x.trim(), 0))
          .filter((x) => !isNaN(x));
        if (r.length) peer.reserved = r;
      }
      Object.assign(out, {
        local_address: String(c.wg_local_address || '172.16.0.2/32')
          .split(',')
          .map((s) => s.trim())
          .filter(Boolean),
        private_key: c.wg_private_key,
        peers: [peer],
        mtu: c.wg_mtu || 1280,
      });
      return clean(out);
    } else if (c.proto === 'socks' || c.proto === 'http') {
      Object.assign(out, { server: c.server, server_port: c.port, version: c.proto === 'socks' ? '5' : '1.1' });
      if (c.uuid || c.password) {
        out.username = c.uuid || '';
        out.password = c.password || '';
      }
      return out;
    } else {
      throw new Error('sing-box export not implemented for ' + c.proto);
    }
    if (tls) out.tls = tls;
    if (tr) out.transport = tr;
    return out;
  }

  function singboxConfig(cfgs, mode, port) {
    const list = (cfgs || []).map(normalize);
    const tags = [];
    const outbounds = [];
    list.forEach((c, i) => {
      const tag = `${c.proto}-${i + 1}`;
      tags.push(tag);
      outbounds.push(toSingboxOutbound(c, tag));
    });
    const section = [];
    if (tags.length) {
      section.push({ type: 'selector', tag: 'select', outbounds: ['auto'].concat(tags), default: 'auto' });
      section.push({
        type: 'urltest',
        tag: 'auto',
        outbounds: tags,
        url: 'https://www.gstatic.com/generate_204',
        interval: '5m',
        tolerance: 100,
      });
    }
    section.push(...outbounds);
    section.push({ type: 'direct', tag: 'direct' });
    section.push({ type: 'block', tag: 'block' });
    section.push({ type: 'dns', tag: 'dns-out' });

    const bypass = mode === 'bypass-ir';
    return {
      log: { level: 'warn' },
      dns: {
        servers: [
          { tag: 'remote', address: 'https://1.1.1.1/dns-query', detour: 'select' },
          { tag: 'local', address: '223.5.5.5', detour: 'direct' },
        ],
        rules: bypass ? [{ rule_set: ['geosite-category-ir'], server: 'local' }] : [],
        final: 'remote',
        strategy: 'prefer_ipv4',
      },
      inbounds: [
        {
          type: 'tun',
          tag: 'tun-in',
          interface_name: 'tun0',
          stack: 'mixed',
          mtu: 9000,
          sniff: true,
          address: ['172.19.0.1/30', 'fdfe:dcba:9876::1/126'],
          auto_route: true,
          strict_route: true,
          endpoint_independent_nat: true,
          platform: { http_proxy: { enabled: true, server: '127.0.0.1', server_port: port || 2080 } },
        },
        { type: 'mixed', tag: 'mixed-in', listen: '127.0.0.1', listen_port: port || 2080, sniff: true },
      ],
      outbounds: section,
      route: {
        rules: bypass
          ? [
              { action: 'sniff' },
              { protocol: 'dns', action: 'hijack-dns' },
              { ip_is_private: true, outbound: 'direct' },
              { rule_set: ['geosite-category-ir'], outbound: 'direct' },
              { geoip: ['ir'], outbound: 'direct' },
            ]
          : [{ action: 'sniff' }, { protocol: 'dns', action: 'hijack-dns' }, { ip_is_private: true, outbound: 'direct' }],
        rule_set: bypass
          ? [
              {
                tag: 'geosite-category-ir',
                type: 'remote',
                format: 'binary',
                url: 'https://raw.githubusercontent.com/SagerNet/sing-geosite/rule-set/geosite-category-ir.srs',
                download_detour: 'select',
              },
            ]
          : [],
        final: 'select',
        auto_detect_interface: true,
      },
      experimental: {
        cache_file: { enabled: true },
        clash_api: { external_controller: '127.0.0.1:9090', store_selected: true },
      },
    };
  }

  /* ---------------------------- clash ---------------------------- */
  function toClashProxy(cfg, name) {
    const c = normalize(cfg);
    const p = { name: name || c.name, type: c.proto, server: c.server, port: c.port };
    if (c.proto === 'vless') {
      p.uuid = c.uuid;
      p.tls = c.security !== 'none';
      p.udp = c.udp;
      if (c.network === 'ws') {
        p.network = 'ws';
        p['ws-opts'] = { path: c.path || '/' };
        if (c.host) p['ws-opts'].headers = { Host: c.host };
      } else if (c.network === 'grpc') {
        p.network = 'grpc';
        p['grpc-opts'] = { 'grpc-service-name': c.serviceName || 'GunService' };
      }
      if (c.security === 'reality') p['reality-opts'] = { 'public-key': c.pbk, 'short-id': c.sid };
      if (c.sni) p.servername = c.sni;
      if (c.fp) p['client-fingerprint'] = c.fp;
      if (c.flow) p.flow = c.flow;
    } else if (c.proto === 'trojan') {
      p.password = c.password;
      p.udp = c.udp;
      if (c.network === 'ws') {
        p.network = 'ws';
        p['ws-opts'] = { path: c.path || '/' };
        if (c.host) p['ws-opts'].headers = { Host: c.host };
      }
      if (c.sni) p.sni = c.sni;
      if (c.alpn) p.alpn = c.alpn.split(',').map((s) => s.trim());
    } else if (c.proto === 'vmess') {
      p.uuid = c.uuid;
      p.cipher = c.method || 'none';
      p.alterId = c.aid || 0;
      p.udp = c.udp;
      if (c.network === 'ws') {
        p.network = 'ws';
        p['ws-opts'] = { path: c.path || '/' };
        if (c.host) p['ws-opts'].headers = { Host: c.host };
      }
      if (c.security !== 'none') p.tls = true;
      if (c.sni) p.servername = c.sni;
    } else if (c.proto === 'ss') {
      p.cipher = c.method || 'chacha20-ietf-poly1305';
      p.password = c.password;
      p.udp = c.udp;
      if (c.obfs && c.obfs !== 'plain') {
        p.plugin = 'obfs';
        p['plugin-opts'] = { mode: c.obfs, host: c.host || 'bing.com' };
      }
    } else if (c.proto === 'hysteria2') {
      p.password = c.password;
      p.udp = true;
      if (c.obfs) {
        p.obfs = c.obfs;
        p['obfs-password'] = c.obfs_password;
      }
      if (c.up) p.up = `${c.up} Mbps`;
      if (c.down) p.down = `${c.down} Mbps`;
      if (c.sni) p.sni = c.sni;
      if (c.insecure) p['skip-cert-verify'] = true;
    } else if (c.proto === 'tuic') {
      Object.assign(p, {
        uuid: c.uuid,
        password: c.password,
        'congestion-controller': c.congestion || 'bbr',
        'udp-relay-mode': c.udp_relay_mode || 'native',
        'reduce-rtt': !!c.reduce_rtt,
        'request-timeout': 8000,
        'heartbeat-interval': 5000,
      });
      if (c.sni) p.sni = c.sni;
      p.alpn = c.alpn ? c.alpn.split(',').map((s) => s.trim()) : ['h3'];
      if (c.insecure) p['skip-cert-verify'] = true;
    } else if (c.proto === 'wireguard') {
      Object.assign(p, {
        'private-key': c.wg_private_key,
        'public-key': c.wg_public_key,
        ip: c.wg_local_address,
        mtu: c.wg_mtu || 1280,
        udp: true,
        'persistent-keepalive': 25,
      });
      if (c.wg_preshared_key) p['preshared-key'] = c.wg_preshared_key;
      if (c.wg_reserved) {
        const r = String(c.wg_reserved)
          .split(',')
          .map((x) => int(x.trim(), 0));
        if (r.length) p.reserved = r;
      }
    } else if (c.proto === 'socks' || c.proto === 'http') {
      p.udp = c.udp;
      if (c.uuid || c.password) {
        p.username = c.uuid || '';
        p.password = c.password || '';
      }
    }
    if (c.insecure && ['hysteria2', 'tuic'].indexOf(c.proto) < 0) p['skip-cert-verify'] = true;
    const out = {};
    Object.keys(p).forEach((k) => {
      if (p[k] !== undefined && p[k] !== '' && !(Array.isArray(p[k]) && !p[k].length)) out[k] = p[k];
    });
    return out;
  }

  function yamlScalar(v) {
    if (typeof v === 'boolean') return v ? 'true' : 'false';
    if (typeof v === 'number') return String(v);
    let s = String(v);
    if (s === '') return '""';
    if (/[:#{}[\],&*?|<>=!%@`"']/.test(s) || s.trim() !== s || ['yes', 'no', 'on', 'off', 'true', 'false', 'null'].indexOf(s.toLowerCase()) >= 0) {
      return '"' + s.replace(/\\/g, '\\\\').replace(/"/g, '\\"') + '"';
    }
    return s;
  }

  function yamlDump(obj, indent) {
    indent = indent || 0;
    const sp = '  '.repeat(indent);
    if (Array.isArray(obj)) {
      return obj
        .map((item) => {
          if (item && typeof item === 'object') {
            return `${sp}- ${yamlDump(item, indent + 1).replace(/^\s+/, '')}`;
          }
          return `${sp}- ${yamlScalar(item)}`;
        })
        .join('\n');
    }
    if (obj && typeof obj === 'object') {
      return Object.keys(obj)
        .filter((k) => obj[k] !== undefined && obj[k] !== null && obj[k] !== '')
        .map((k) => {
          const v = obj[k];
          if (Array.isArray(v)) {
            if (!v.length) return null;
            return `${sp}${k}:\n${yamlDump(v, indent + 1)}`;
          }
          if (v && typeof v === 'object') {
            if (!Object.keys(v).length) return null;
            return `${sp}${k}:\n${yamlDump(v, indent + 1)}`;
          }
          return `${sp}${k}: ${yamlScalar(v)}`;
        })
        .filter(Boolean)
        .join('\n');
    }
    return sp + yamlScalar(obj);
  }

  function clashConfig(cfgs, mode, port) {
    const list = (cfgs || []).map(normalize);
    const proxies = list.map((c) => toClashProxy(c));
    const names = proxies.map((p) => p.name);
    const doc = {
      'mixed-port': port || 7890,
      'allow-lan': false,
      mode: 'rule',
      'log-level': 'warning',
      ipv6: true,
      dns: {
        enable: true,
        'enhanced-mode': 'fake-ip',
        nameserver: ['https://1.1.1.1/dns-query', 'https://8.8.8.8/dns-query'],
        'fake-ip-range': '198.18.0.1/16',
      },
      proxies,
      'proxy-groups': [
        { name: 'PROXY', type: 'select', proxies: ['AUTO'].concat(names) },
        {
          name: 'AUTO',
          type: 'url-test',
          proxies: names,
          url: 'https://www.gstatic.com/generate_204',
          interval: 300,
          tolerance: 50,
        },
      ],
      rules: mode === 'bypass-ir' ? ['GEOIP,IR,DIRECT,no-resolve', 'GEOSITE,category-ir,DIRECT', 'MATCH,PROXY'] : ['MATCH,PROXY'],
    };
    return yamlDump(doc) + '\n';
  }

  /* ---------------------------- xray ---------------------------- */
  function toXrayOutbound(cfg, tag) {
    const c = normalize(cfg);
    const t = tag || c.tag || c.name;
    const net = c.network;
    const stream = { network: net };
    if (net === 'ws') {
      stream.wsSettings = { path: c.path || '/' };
      if (c.host) stream.wsSettings.headers = { Host: c.host };
    } else if (net === 'grpc') {
      stream.grpcSettings = { serviceName: c.serviceName || 'GunService' };
    } else if (net === 'httpupgrade') {
      stream.httpupgradeSettings = { path: c.path || '/', host: c.host || c.server };
    } else if (net === 'xhttp') {
      stream.xhttpSettings = { path: c.path || '/', host: c.host || c.server, mode: c.mode || 'auto' };
    } else if (net === 'h2') {
      stream.httpSettings = { path: c.path || '/', host: c.host ? [c.host] : [] };
    } else if (net === 'tcp' && c.headerType === 'http') {
      stream.tcpSettings = {
        header: { type: 'http', request: { path: [c.path || '/'], headers: { Host: [c.host || c.server] } } },
      };
    }
    if (c.security === 'tls') {
      const tls = { serverName: c.sni || c.host || c.server };
      if (c.alpn) tls.alpn = c.alpn.split(',').map((s) => s.trim());
      if (c.fp) tls.fingerprint = c.fp;
      if (c.insecure) tls.allowInsecure = true;
      stream.security = 'tls';
      stream.tlsSettings = tls;
    } else if (c.security === 'reality') {
      stream.security = 'reality';
      stream.realitySettings = {
        serverName: c.sni || c.server,
        publicKey: c.pbk,
        shortId: c.sid,
        fingerprint: c.fp || 'chrome',
        spiderX: c.spx || '/',
      };
    } else {
      stream.security = 'none';
    }

    if (c.proto === 'vless') {
      return {
        protocol: 'vless',
        tag: t,
        streamSettings: stream,
        settings: { vnext: [{ address: c.server, port: c.port, users: [{ id: c.uuid, encryption: 'none', flow: c.flow || undefined }] }] },
      };
    }
    if (c.proto === 'vmess') {
      return {
        protocol: 'vmess',
        tag: t,
        streamSettings: stream,
        settings: {
          vnext: [{ address: c.server, port: c.port, users: [{ id: c.uuid, alterId: c.aid || 0, security: c.method || 'none' }] }],
        },
      };
    }
    if (c.proto === 'trojan') {
      return {
        protocol: 'trojan',
        tag: t,
        streamSettings: stream,
        settings: { servers: [{ address: c.server, port: c.port, password: c.password }] },
      };
    }
    if (c.proto === 'ss') {
      return {
        protocol: 'shadowsocks',
        tag: t,
        streamSettings: stream,
        settings: {
          servers: [{ address: c.server, port: c.port, method: c.method || 'chacha20-ietf-poly1305', password: c.password }],
        },
      };
    }
    if (c.proto === 'socks' || c.proto === 'http') {
      const users = c.uuid || c.password ? [{ user: c.uuid || '', pass: c.password || '' }] : [];
      return { protocol: c.proto, tag: t, streamSettings: stream, settings: { servers: [{ address: c.server, port: c.port, users }] } };
    }
    throw new Error('Xray export not available for ' + c.proto + ' (use sing-box)');
  }

  function xrayConfig(cfgs, mode, port) {
    const list = (cfgs || []).map(normalize);
    const outbounds = [];
    const usable = [];
    list.forEach((c, i) => {
      if (['vless', 'vmess', 'trojan', 'ss', 'socks', 'http'].indexOf(c.proto) < 0) return;
      const tag = `proxy-${i + 1}`;
      usable.push(tag);
      outbounds.push(toXrayOutbound(c, tag));
    });
    outbounds.push({ protocol: 'freedom', tag: 'direct' });
    outbounds.push({ protocol: 'blackhole', tag: 'block' });
    return {
      log: { loglevel: 'warning' },
      dns: { servers: ['https+local://1.1.1.1/dns-query', 'localhost'] },
      inbounds: [
        {
          tag: 'socks-in',
          port: port || 10808,
          listen: '127.0.0.1',
          protocol: 'socks',
          sniffing: { enabled: true, destOverride: ['http', 'tls'] },
          settings: { auth: 'noauth', udp: true },
        },
        {
          tag: 'http-in',
          port: (port || 10808) + 1,
          listen: '127.0.0.1',
          protocol: 'http',
          sniffing: { enabled: true, destOverride: ['http', 'tls'] },
        },
      ],
      outbounds,
      routing: {
        domainStrategy: 'IPIfNonMatch',
        rules: mode === 'bypass-ir' ? [{ type: 'field', ip: ['geoip:private'], outboundTag: 'direct' }] : [],
        balancers: usable.length ? [{ tag: 'leastping', selector: usable }] : undefined,
      },
    };
  }

  function xrayFragmentConfig() {
    return {
      log: { loglevel: 'warning' },
      dns: { servers: ['https+local://1.1.1.1/dns-query', 'localhost'] },
      inbounds: [
        {
          tag: 'socks-in',
          port: 10808,
          listen: '127.0.0.1',
          protocol: 'socks',
          sniffing: { enabled: true, destOverride: ['http', 'tls'] },
          settings: { auth: 'noauth', udp: true },
        },
        {
          tag: 'http-in',
          port: 10809,
          listen: '127.0.0.1',
          protocol: 'http',
          sniffing: { enabled: true, destOverride: ['http', 'tls'] },
        },
      ],
      outbounds: [
        {
          protocol: 'freedom',
          tag: 'direct',
          settings: {
            domainStrategy: 'UseIPv4',
            fragment: { packets: 'tlshello', length: '100-200', interval: '10-20' },
          },
        },
        { protocol: 'blackhole', tag: 'block' },
      ],
      routing: { domainStrategy: 'IPIfNonMatch', rules: [{ type: 'field', ip: ['geoip:private'], outboundTag: 'direct' }] },
    };
  }

  /* ---------------------------- subscription ---------------------------- */
  function subscription(cfgs) {
    return (cfgs || []).map(normalize).filter((c) => c.server).map(toUri).join('\n');
  }
  function subBase64(cfgs) {
    return b64encode(subscription(cfgs));
  }
  function exportConfigs(cfgs, fmt, mode, port) {
    fmt = (fmt || 'b64').toLowerCase();
    if (fmt === 'text' || fmt === 'v2ray' || fmt === 'plain') return subscription(cfgs) + '\n';
    if (fmt === 'b64' || fmt === 'base64' || fmt === 'sub') return subBase64(cfgs) + '\n';
    if (fmt === 'clash' || fmt === 'yaml' || fmt === 'mihomo') return clashConfig(cfgs, mode || 'global', port || 7890);
    if (fmt === 'singbox' || fmt === 'sing-box' || fmt === 'json' || fmt === 'sfa')
      return JSON.stringify(singboxConfig(cfgs, mode || 'global', port || 2080), null, 2);
    if (fmt === 'xray') return JSON.stringify(xrayConfig(cfgs, mode || 'global', port || 10808), null, 2);
    if (fmt === 'fragment') return JSON.stringify(xrayFragmentConfig(), null, 2);
    return subscription(cfgs) + '\n';
  }
  function mergeConfigs(groups) {
    const seen = new Set();
    const out = [];
    (groups || []).forEach((group) => {
      (group || []).forEach((c) => {
        let key;
        try {
          key = toUri(c);
        } catch (e) {
          return;
        }
        if (seen.has(key)) return;
        seen.add(key);
        out.push(normalize(c));
      });
    });
    return out;
  }

  function wireguardConf(cfg) {
    const c = normalize(cfg);
    const lines = [
      '[Interface]',
      `PrivateKey = ${c.wg_private_key}`,
      `Address = ${c.wg_local_address}`,
      'DNS = 1.1.1.1, 1.0.0.1',
      `MTU = ${c.wg_mtu || 1280}`,
    ];
    if (c.wg_preshared_key) lines.push(`PresharedKey = ${c.wg_preshared_key}`);
    if (c.wg_reserved) {
      const r = String(c.wg_reserved)
        .split(',')
        .map((x) => int(x.trim(), 0));
      if (r.length === 3) lines.push(`Reserved = ${r[0]}, ${r[1]}, ${r[2]}`);
    }
    lines.push('', '[Peer]', `PublicKey = ${c.wg_public_key}`, `Endpoint = ${c.server}:${c.port}`, 'AllowedIPs = 0.0.0.0/0, ::/0', 'PersistentKeepalive = 25');
    return lines.join('\n') + '\n';
  }

  global.Engine = {
    DEFAULTS,
    normalize,
    newUUID,
    randPassword,
    toUri,
    parseUri,
    parseAny,
    fromSingbox,
    toSingboxOutbound,
    singboxConfig,
    toClashProxy,
    clashConfig,
    toXrayOutbound,
    xrayConfig,
    xrayFragmentConfig,
    subscription,
    subBase64,
    exportConfigs,
    mergeConfigs,
    wireguardConf,
    b64encode,
    b64decode,
  };
})(typeof window !== 'undefined' ? window : globalThis);
