/*
 * OpenPath panel logic.
 *
 * Two modes:
 *   bridge     - the page is served by `openpath panel` from your own device,
 *                so it can deploy workers, start proxies and run tests.
 *   standalone - the page comes from GitHub Pages. Everything that can be done
 *                inside the browser still works; actions that need the device
 *                are clearly marked and tell you the command to run.
 */
(function () {
  'use strict';

  const { Engine, Methods, I18N } = window;
  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));
  const t = (key) => I18N.t(key);
  const pick = (value) => I18N.pick(value);

  const state = {
    tab: 'methods',
    filter: 'all',
    query: '',
    configs: [],
    worker: null, // last generated/deployed worker result
    bridge: null, // {base, code} or null
    busy: false,
  };

  /* ------------------------------ storage ------------------------------ */
  const store = {
    get(key, fallback) {
      try {
        const raw = localStorage.getItem('openpath.' + key);
        return raw ? JSON.parse(raw) : fallback;
      } catch (e) {
        return fallback;
      }
    },
    set(key, value) {
      try {
        localStorage.setItem('openpath.' + key, JSON.stringify(value));
      } catch (e) {
        /* ignore */
      }
    },
  };

  /* ------------------------------ helpers ------------------------------ */
  function escapeHtml(s) {
    return String(s === undefined || s === null ? '' : s).replace(/[&<>"']/g, (c) => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;',
    })[c]);
  }

  let toastTimer = null;
  function toast(message, kind) {
    const box = $('#toast');
    box.textContent = message;
    box.className = 'toast show ' + (kind || 'info');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
      box.className = 'toast';
    }, 3200);
  }

  function copyText(text) {
    const done = () => toast(t('copied'), 'ok');
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done, () => fallbackCopy(text, done));
    } else {
      fallbackCopy(text, done);
    }
  }
  function fallbackCopy(text, done) {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    try {
      document.execCommand('copy');
      done();
    } catch (e) {
      toast('copy failed - select and copy manually', 'err');
    }
    document.body.removeChild(ta);
  }

  function download(name, content, type) {
    const blob = new Blob([content], { type: type || 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => {
      URL.revokeObjectURL(url);
      document.body.removeChild(a);
    }, 200);
  }

  function qrSvg(text, size) {
    try {
      const qr = qrcode(0, 'M');
      // UTF-8 safe
      qrcode.stringToBytes = function (s) {
        const bytes = [];
        const enc = unescape(encodeURIComponent(s));
        for (let i = 0; i < enc.length; i++) bytes.push(enc.charCodeAt(i));
        return bytes;
      };
      qr.addData(text);
      qr.make();
      return qr.createSvgTag({ cellSize: size || 4, margin: 2, scalable: true });
    } catch (e) {
      return '<div class="muted">QR failed</div>';
    }
  }

  function qrButton(text, label) {
    const id = 'qr-' + Math.random().toString(36).slice(2, 9);
    const html = `<button class="btn tiny" data-qr="${escapeHtml(text)}" data-qr-target="${id}">${escapeHtml(label || t('show_qr'))}</button>
      <div class="qr-box" id="${id}" hidden></div>`;
    return html;
  }

  /* ------------------------------ bridge ------------------------------ */
  function detectBridge() {
    if (window.OPENPATH_CODE !== undefined && window.OPENPATH_CODE) {
      state.bridge = { base: window.OPENPATH_BRIDGE || '', code: window.OPENPATH_CODE };
      return;
    }
    const saved = store.get('bridge', null);
    if (saved && saved.base && saved.code) state.bridge = saved;
  }

  async function bridgeCall(path, body) {
    if (!state.bridge) throw new Error(t('no_bridge'));
    const url = state.bridge.base.replace(/\/$/, '') + path;
    const init = { headers: { 'X-OpenPath-Code': state.bridge.code } };
    if (body === undefined) {
      init.method = 'GET';
    } else {
      init.method = 'POST';
      init.headers['Content-Type'] = 'application/json';
      init.body = JSON.stringify(body);
    }
    let resp;
    try {
      resp = await fetch(url, init);
    } catch (e) {
      throw new Error(t('run_in_termux'));
    }
    let data;
    try {
      data = await resp.json();
    } catch (e) {
      throw new Error('bridge returned a non-JSON response');
    }
    if (!data.ok) throw new Error(data.error || 'request failed');
    return data;
  }

  function withBridge(el) {
    el.classList.toggle('needs-bridge', !state.bridge);
    if (!state.bridge) el.title = t('run_in_termux');
    return !!state.bridge;
  }

  /* ------------------------------ rendering ------------------------------ */
  function renderStatus() {
    const el = $('#bridge-status');
    const online = !!state.bridge;
    el.innerHTML = `<span class="dot ${online ? 'ok' : 'off'}"></span>
      <span>${online ? escapeHtml(t('bridge_online')) : escapeHtml(t('bridge_offline'))}</span>`;
    el.classList.toggle('online', online);
  }

  function renderTabs() {
    const tabs = [
      ['methods', t('nav_methods')],
      ['worker', t('nav_worker')],
      ['warp', t('nav_warp')],
      ['gas', t('nav_gas')],
      ['dpi', t('nav_dpi')],
      ['paas', t('nav_paas')],
      ['subs', t('nav_subs')],
      ['builder', t('nav_builder')],
      ['test', t('nav_test')],
      ['settings', t('nav_settings')],
      ['guide', t('nav_guide')],
    ];
    $('#tabs').innerHTML = tabs
      .map(([id, label]) => `<button class="tab ${state.tab === id ? 'active' : ''}" data-tab="${id}">${escapeHtml(label)}</button>`)
      .join('');
    $$('#tabs .tab').forEach((btn) =>
      btn.addEventListener('click', () => {
        state.tab = btn.dataset.tab;
        render();
      })
    );
  }

  function methodCard(m) {
    const tags = [`<span class="tag ${m.status}">${escapeHtml(t('status_' + m.status))}</span>`];
    if (m.best) tags.push('<span class="tag best">★</span>');
    return `<article class="card method" data-id="${m.id}">
      <header>
        <span class="icon">${m.icon || '🔌'}</span>
        <h3>${escapeHtml(pick(m.title))}</h3>
        ${tags.join('')}
      </header>
      <p class="summary">${escapeHtml(pick(m.summary))}</p>
      <div class="meta">
        <span><b>${escapeHtml(t('why'))}:</b> ${escapeHtml(pick(m.when))}</span>
        <span><b>${escapeHtml(t('limits'))}:</b> ${escapeHtml(pick(m.limits))}</span>
        <span><b>${escapeHtml(t('difficulty'))}:</b> ${'●'.repeat(m.difficulty)}${'○'.repeat(3 - m.difficulty)} · ${escapeHtml(m.cost)}</span>
      </div>
      <details>
        <summary>${escapeHtml(t('steps'))}</summary>
        <ol>${(pick(m.steps) || []).map((s) => `<li>${escapeHtml(s)}</li>`).join('')}</ol>
        ${(m.links || []).map((l) => `<a class="link" href="${escapeHtml(l.url)}" target="_blank" rel="noopener">${escapeHtml(l.label)} ↗</a>`).join(' ')}
      </details>
      <footer>
        ${m.action ? `<button class="btn" data-goto="${escapeHtml(m.action.target || m.id)}">${escapeHtml(t('open_tab'))}</button>` : ''}
      </footer>
    </article>`;
  }

  function renderMethods() {
    const filters = [
      ['all', t('filter_all')],
      ['fav', t('filter_fav')],
      ['serverless', t('filter_serverless')],
      ['local', t('filter_local')],
      ['free-tier', t('filter_free')],
      ['dns', t('filter_dns')],
      ['public', t('filter_public')],
      ['experimental', t('filter_all')],
    ];
    $('#method-filters').innerHTML = filters
      .filter((f) => f[0] !== 'experimental')
      .map(([id, label]) => `<button class="chip ${state.filter === id ? 'active' : ''}" data-filter="${id}">${escapeHtml(label)}</button>`)
      .join('');

    const q = state.query.trim().toLowerCase();
    let list = Methods.list.filter((m) => {
      if (state.filter === 'fav') return !!m.best;
      if (state.filter !== 'all' && m.category !== state.filter) return false;
      return true;
    });
    if (q) {
      list = list.filter((m) => JSON.stringify([pick(m.title), pick(m.summary), m.id, m.category, m.status]).toLowerCase().includes(q));
    }
    $('#methods-list').innerHTML = list.map(methodCard).join('') || '<p class="muted">no method matches</p>';
    $$('#method-filters .chip').forEach((c) =>
      c.addEventListener('click', () => {
        state.filter = c.dataset.filter;
        renderMethods();
      })
    );
    $$('#methods-list [data-goto]').forEach((b) =>
      b.addEventListener('click', () => {
        state.tab = b.dataset.goto;
        render();
      })
    );
  }

  /* ------------------------------ worker tab ------------------------------ */
  function workerSettings() {
    return {
      uuid: $('#w-uuid').value.trim(),
      trojan_password: $('#w-trojan').value.trim(),
      ws_path: $('#w-ws').value.trim() || '/openpath',
      sub_path: $('#w-sub').value.trim() || 'sub',
      node_name: $('#w-name').value.trim() || 'OpenPath',
      proxy_ip: $('#w-proxy').value.trim(),
      proxy_port: 443,
      upstream_mode: 'direct',
      upstream_host: '',
      upstream_port: 1080,
      upstream_user: '',
      upstream_pass: '',
      relay_enabled: $('#w-relay').checked,
      extra_nodes: [],
    };
  }

  function renderWorkerResult(payload) {
    state.worker = payload;
    const cfgs = payload.configs || [];
    state.configs = Engine.mergeConfigs([state.configs, cfgs]);
    const links = cfgs.map((c) => Engine.toUri(c));
    $('#worker-result').innerHTML = `
      <div class="panel-inset">
        <label>${escapeHtml(t('worker_sub_url'))}</label>
        <div class="row">
          <input class="in" readonly value="${escapeHtml(payload.subscription || '')}">
          <button class="btn" data-copy="${escapeHtml(payload.subscription || '')}">${escapeHtml(t('copy'))}</button>
          ${qrButton(payload.subscription || '', t('show_qr'))}
        </div>
        <small class="muted">Add <code>?format=clash</code>, <code>?format=singbox</code> or <code>?format=xray</code> for other clients.</small>
      </div>
      ${renderConfigList(cfgs, 'worker-configs')}`;
    wireConfigList();
    wireCopyButtons();
  }

  function renderConfigList(cfgs, id) {
    if (!cfgs.length) return '<p class="muted">no configs yet</p>';
    return `<div class="config-list" id="${id}">${cfgs
      .map((c, i) => {
        const uri = Engine.toUri(c);
        return `<div class="config-row">
          <div class="config-main">
            <b>${escapeHtml(c.name)}</b>
            <code>${escapeHtml(uri.length > 96 ? uri.slice(0, 96) + '…' : uri)}</code>
          </div>
          <div class="config-actions">
            <button class="btn tiny" data-copy="${escapeHtml(uri)}">${escapeHtml(t('copy'))}</button>
            ${qrButton(uri, t('show_qr'))}
            <button class="btn tiny" data-export-one="${i}">JSON</button>
          </div>
        </div>`;
      })
      .join('')}</div>`;
  }

  function wireConfigList() {
    $$('[data-export-one]').forEach((b) =>
      b.addEventListener('click', () => {
        const c = state.configs[parseInt(b.dataset.exportOne, 10)];
        if (!c) return;
        const text = JSON.stringify(Engine.singboxConfig([c]), null, 2);
        download(Engine.normalize(c).name + '-singbox.json', text, 'application/json');
      })
    );
    $$('[data-qr]').forEach((b) =>
      b.addEventListener('click', () => {
        const target = document.getElementById(b.dataset.qrTarget);
        if (!target) return;
        if (!target.hidden) {
          target.hidden = true;
          target.innerHTML = '';
          return;
        }
        target.innerHTML = qrSvg(b.dataset.qr, 5);
        target.hidden = false;
      })
    );
  }

  function wireCopyButtons() {
    $$('[data-copy]').forEach((b) => b.addEventListener('click', () => copyText(b.dataset.copy)));
  }

  async function workerGenerate() {
    const settings = workerSettings();
    if (!settings.uuid) {
      settings.uuid = Engine.newUUID();
      $('#w-uuid').value = settings.uuid;
    }
    if (state.bridge) {
      try {
        const res = await bridgeCall('/api/cf/render', { settings });
        state.workerCode = res.code;
        toast('worker code generated', 'ok');
      } catch (e) {
        toast(e.message, 'err');
      }
    }
    // Always produce a local copy too (works in standalone mode).
    if (!state.workerCode) state.workerCode = buildWorkerCodeLocal(settings);
    download('openpath-worker.js', state.workerCode, 'application/javascript');
    toast(t('download') + ': openpath-worker.js', 'ok');
  }

  // Standalone fallback: the panel keeps its own copy of the template so it can
  // render a Worker even with no bridge at all.
  let templateCache = null;
  async function getTemplate() {
    if (templateCache) return templateCache;
    try {
      const resp = await fetch('../worker/src/index.js');
      if (resp.ok) {
        templateCache = await resp.text();
        return templateCache;
      }
    } catch (e) {
      /* ignore */
    }
    return null;
  }

  async function buildWorkerCodeLocal(settings) {
    const tpl = await getTemplate();
    if (!tpl) {
      toast('worker template unavailable - run openpath cf code', 'err');
      return '';
    }
    const map = {
      '{{UUID}}': settings.uuid,
      '{{TROJAN_PASSWORD}}': settings.trojan_password || '',
      '{{WS_PATH}}': settings.ws_path,
      '{{SUB_PATH}}': settings.sub_path,
      '{{NODE_NAME}}': settings.node_name,
      '{{PROXY_IP}}': settings.proxy_ip || '',
      '{{PROXY_PORT}}': '443',
      '{{UPSTREAM_MODE}}': 'direct',
      '{{UPSTREAM_HOST}}': '',
      '{{UPSTREAM_PORT}}': '1080',
      '{{UPSTREAM_USER}}': '',
      '{{UPSTREAM_PASS}}': '',
      '{{RELAY_ENABLED}}': settings.relay_enabled ? 'true' : 'false',
      '{{EXTRA_NODES}}': '',
    };
    let out = tpl;
    Object.keys(map).forEach((k) => {
      out = out.split(k).join(map[k]);
    });
    return out;
  }

  async function workerDeploy() {
    if (!withBridge($('#w-deploy'))) return toast(t('run_in_termux'), 'warn');
    const token = $('#w-token').value.trim() || store.get('cf_token', '');
    if (token) store.set('cf_token', token);
    const settings = workerSettings();
    settings.uuid = settings.uuid || Engine.newUUID();
    $('#w-uuid').value = settings.uuid;
    setBusy(true, 'deploying worker...');
    try {
      const res = await bridgeCall('/api/cf/deploy', {
        settings,
        token,
        script_name: $('#w-script').value.trim() || undefined,
      });
      renderWorkerResult(res);
      toast('deployed: ' + (res.deployment.url || 'ok'), 'ok');
    } catch (e) {
      toast(e.message, 'err');
    } finally {
      setBusy(false);
    }
  }

  /* ------------------------------ busy state ------------------------------ */
  function setBusy(busy, label) {
    state.busy = busy;
    const el = $('#busy');
    el.hidden = !busy;
    el.textContent = label || 'working...';
  }

  /* ------------------------------ tabs ------------------------------ */
  const VIEWS = {
    methods: () => `
      <div class="toolbar">
        <input id="method-search" class="in" placeholder="${escapeHtml(t('search_placeholder'))}" value="${escapeHtml(state.query)}">
        <div id="method-filters" class="chips"></div>
      </div>
      <p class="muted small">${escapeHtml(t('bridge_hint'))}</p>
      <div id="methods-list" class="grid"></div>`,

    worker: () => `
      <p class="muted">${escapeHtml(t('worker_intro'))}</p>
      <div class="form">
        <label>${escapeHtml(t('worker_node_name'))}<input class="in" id="w-name" value="OpenPath"></label>
        <label>${escapeHtml(t('worker_uuid'))}<div class="row"><input class="in" id="w-uuid" placeholder="auto"><button class="btn tiny" id="w-uuid-new">⟳</button></div></label>
        <label>${escapeHtml(t('worker_trojan'))}<input class="in" id="w-trojan" placeholder="auto"></label>
        <label>${escapeHtml(t('worker_ws_path'))}<input class="in" id="w-ws" value="/openpath"></label>
        <label>${escapeHtml(t('worker_sub_path'))}<input class="in" id="w-sub" value="sub"></label>
        <label>${escapeHtml(t('worker_proxy_ip'))}<input class="in" id="w-proxy" placeholder=""></label>
        <label class="check"><input type="checkbox" id="w-relay" checked> ${escapeHtml(t('worker_relay'))}</label>
      </div>
      <div class="row wrap">
        <button class="btn" id="w-generate">${escapeHtml(t('worker_generate'))}</button>
        <button class="btn primary" id="w-deploy">${escapeHtml(t('worker_deploy'))}</button>
      </div>
      <div class="form advanced">
        <label>${escapeHtml(t('worker_token'))}<input class="in" id="w-token" type="password" placeholder="API token (stored in your browser)"></label>
        <label>${escapeHtml(t('worker_script_name'))}<input class="in" id="w-script" placeholder="openpath-xxxx"></label>
      </div>
      <details><summary>${escapeHtml(t('worker_manual'))}</summary><p class="muted">${escapeHtml(t('worker_manual_steps'))}</p></details>
      <div id="worker-result"></div>`,

    warp: () => `
      <p class="muted">${escapeHtml(t('warp_intro'))}</p>
      <div class="form">
        <label>${escapeHtml(t('warp_count'))}<input class="in" id="wp-count" type="number" min="1" max="5" value="1"></label>
        <label>${escapeHtml(t('warp_license'))}<input class="in" id="wp-license" placeholder="(optional)"></label>
      </div>
      <div class="row wrap">
        <button class="btn primary" id="wp-generate">${escapeHtml(t('warp_generate'))}</button>
      </div>
      <div id="warp-result"></div>`,

    gas: () => `
      <p class="muted">${escapeHtml(t('gas_intro'))}</p>
      <div class="form">
        <label>${escapeHtml(t('gas_url'))}<input class="in" id="g-url" placeholder="https://script.google.com/macros/s/.../exec"></label>
        <label>${escapeHtml(t('gas_key'))}<input class="in" id="g-key" placeholder="secret key"></label>
      </div>
      <div class="row wrap">
        <button class="btn" id="g-create">${escapeHtml(t('gas_create'))}</button>
        <button class="btn" id="g-save">${escapeHtml(t('gas_save'))}</button>
        <button class="btn" id="g-test">${escapeHtml(t('gas_test'))}</button>
        <button class="btn primary" id="g-serve">${escapeHtml(t('gas_serve'))}</button>
        <button class="btn" id="g-stop">${escapeHtml(t('gas_stop'))}</button>
      </div>
      <div id="gas-result"></div>
      <details><summary>${escapeHtml(t('gas_steps'))}</summary>
        <ol>
          <li>Open <a href="https://script.google.com" target="_blank" rel="noopener">script.google.com</a> → New project</li>
          <li>Delete the sample code, paste the generated <code>Code.gs</code></li>
          <li>Deploy → New deployment → Web app → Execute as: <b>Me</b>, Access: <b>Anyone</b></li>
          <li>Copy the <code>/exec</code> URL into the field above, then press Start local proxy</li>
          <li>Point apps at <code>127.0.0.1:8080</code> (HTTP or SOCKS5)</li>
        </ol>
      </details>`,

    dpi: () => `
      <p class="muted">${escapeHtml(t('dpi_intro'))}</p>
      <div class="form">
        <label>${escapeHtml(t('dpi_port'))}<input class="in" id="d-port" type="number" value="8081"></label>
        <label>${escapeHtml(t('dpi_segments'))}<input class="in" id="d-chunks" type="number" min="1" max="10" value="3"></label>
        <label class="check"><input type="checkbox" id="d-fake" checked> ${escapeHtml(t('dpi_decoy'))}</label>
      </div>
      <div class="row wrap">
        <button class="btn primary" id="d-start">${escapeHtml(t('dpi_start'))}</button>
        <button class="btn" id="d-stop">${escapeHtml(t('dpi_stop'))}</button>
      </div>
      <div id="dpi-result"></div>
      <div class="panel-inset">
        <b>${escapeHtml(t('dpi_running'))}</b>
        <p class="muted">Set it as the upstream proxy in MahsaNG / v2rayNG, or as the Wi-Fi proxy
        (hostname <code>127.0.0.1</code>, port <code>8081</code>). Add <code>openpath dpi start</code> to your Termux
        startup if you want it always on.</p>
      </div>`,

    paas: () => `
      <p class="muted">${escapeHtml(t('paas_intro'))}</p>
      <div class="form">
        <label>${escapeHtml(t('paas_preset'))}<select class="in" id="p-preset"></select></label>
        <label>${escapeHtml(t('paas_repo'))}<input class="in" id="p-repo" placeholder="you/openpath-paas"></label>
      </div>
      <div class="row wrap">
        <button class="btn primary" id="p-render">${escapeHtml(t('paas_render'))}</button>
        <button class="btn" id="p-codespace">${escapeHtml(t('paas_codespace'))}</button>
      </div>
      <div id="paas-result"></div>`,

    subs: () => `
      <p class="muted">${escapeHtml(t('subs_intro'))}</p>
      <p class="warn-box">${escapeHtml(t('subs_warning'))}</p>
      <div class="row wrap">
        <button class="btn primary" id="s-fetch">${escapeHtml(t('subs_fetch'))}</button>
        <button class="btn" id="s-import">${escapeHtml(t('subs_import'))}</button>
        <select class="in" id="s-format">
          <option value="b64">Base64 subscription</option>
          <option value="text">Share links (text)</option>
          <option value="singbox">sing-box JSON</option>
          <option value="clash">Clash / Mihomo YAML</option>
          <option value="xray">Xray JSON</option>
          <option value="fragment">Xray fragment (no server)</option>
        </select>
        <button class="btn" id="s-export">${escapeHtml(t('download'))}</button>
        <button class="btn" id="s-serve">${escapeHtml(t('subs_serve'))}</button>
        <button class="btn tiny" id="s-qr">${escapeHtml(t('show_qr'))}</button>
      </div>
      <textarea id="s-input" class="in code" rows="5" placeholder="paste share links or a subscription here"></textarea>
      <div id="subs-result"></div>`,

    builder: () => `
      <p class="muted">${escapeHtml(t('builder_intro'))}</p>
      <div class="form" id="b-form"></div>
      <div class="row wrap">
        <button class="btn primary" id="b-build">${escapeHtml(t('generate'))}</button>
      </div>
      <div id="builder-result"></div>`,

    test: () => `
      <p class="muted">${escapeHtml(t('test_intro'))}</p>
      <div class="row wrap">
        <button class="btn primary" id="t-run">${escapeHtml(t('test_run'))}</button>
      </div>
      <div id="test-result"></div>`,

    settings: () => `
      <p class="muted">${escapeHtml(t('settings_intro'))}</p>
      <div class="form">
        <label>${escapeHtml(t('settings_bridge_url'))}<input class="in" id="st-base" placeholder="http://127.0.0.1:8765"></label>
        <label>${escapeHtml(t('settings_code'))}<input class="in" id="st-code" placeholder="ABC123"></label>
      </div>
      <div class="row wrap">
        <button class="btn primary" id="st-connect">${escapeHtml(t('settings_connect'))}</button>
        <button class="btn" id="st-lang">${escapeHtml(t('lang_toggle'))}</button>
        <button class="btn" id="st-selftest">${escapeHtml('Run self test')}</button>
      </div>
      <div id="settings-result"></div>`,

    guide: () => `
      <h3>${escapeHtml(t('guide_intro'))}</h3>
      <ol class="guide">
        <li><b>Install</b> — Termux: <code>pkg update &amp;&amp; pkg install python git -y</code> then
            <code>git clone https://github.com/arminabdim/Vpn-panel-for-iran-internet &amp;&amp; cd Vpn-panel-for-iran-internet &amp;&amp; python openpath.py</code></li>
        <li><b>Open the panel</b> — <code>python openpath.py panel</code> and open the printed URL (or type the code here).</li>
        <li><b>Make your own node</b> — Worker tab → Deploy. That is a free VLESS/Trojan node on Cloudflare.</li>
        <li><b>Add a safety net</b> — WARP tab → Generate, and Apps Script tab → deploy the relay.</li>
        <li><b>When sites are filtered but the internet works</b> — DPI tab → Start.</li>
        <li><b>During a shutdown</b> — try the Apps Script relay first, then DNSTT/SlipNet, then Tor bridges.</li>
      </ol>
      <p class="muted">Full documentation lives in the repository: <code>GUIDE.md</code> (simple),
      <code>docs/METHODS.md</code> (comparison of every method) and <code>docs/TROUBLESHOOTING.md</code>.</p>`,
  };

  function render() {
    document.documentElement.lang = I18N.lang;
    document.documentElement.dir = I18N.rtl ? 'rtl' : 'ltr';
    document.body.classList.toggle('rtl', I18N.rtl);
    $('#lang-btn').textContent = t('lang_toggle');
    $('#subtitle').textContent = t('app_subtitle');
    renderStatus();
    renderTabs();
    const hint = state.bridge
      ? ''
      : `<div class="warn-box" id="standalone-hint">
           <b>${escapeHtml(t('standalone_title'))}</b><br>${escapeHtml(t('standalone_body'))}
           <code>${escapeHtml('python3 openpath.py panel')}</code>
         </div>`;
    $('#view').innerHTML = hint + (VIEWS[state.tab] ? VIEWS[state.tab]() : '');
    wireTab();
  }

  /* ------------------------------ tab wiring ------------------------------ */
  function wireTab() {
    wireCopyButtons();
    switch (state.tab) {
      case 'methods': {
        renderMethods();
        const search = $('#method-search');
        if (search)
          search.addEventListener('input', () => {
            state.query = search.value;
            renderMethods();
            const s2 = $('#method-search');
            s2.focus();
            s2.setSelectionRange(s2.value.length, s2.value.length);
          });
        break;
      }
      case 'worker': {
        const saved = store.get('worker', null);
        if (saved) {
          if (saved.uuid) $('#w-uuid').value = saved.uuid;
          if (saved.node_name) $('#w-name').value = saved.node_name;
        }
        $('#w-token').value = store.get('cf_token', '');
        $('#w-uuid-new').addEventListener('click', () => {
          $('#w-uuid').value = Engine.newUUID();
        });
        $('#w-generate').addEventListener('click', workerGenerate);
        $('#w-deploy').addEventListener('click', workerDeploy);
        withBridge($('#w-deploy'));
        break;
      }
      case 'warp': {
        $('#wp-generate').addEventListener('click', async () => {
          if (!withBridge($('#wp-generate'))) return toast(t('run_in_termux'), 'warn');
          setBusy(true, 'registering with Cloudflare WARP...');
          try {
            const res = await bridgeCall('/api/warp/generate', {
              count: parseInt($('#wp-count').value, 10) || 1,
              license: $('#wp-license').value.trim(),
            });
            state.configs = Engine.mergeConfigs([state.configs, res.configs]);
            $('#warp-result').innerHTML =
              res.configs
                .map(
                  (c, i) => `<div class="panel-inset">
                    <b>${escapeHtml(c.name)}</b> — ${escapeHtml(c.server)}:${c.port}
                    <div class="row"><button class="btn tiny" data-copy="${escapeHtml(res.conf[i])}">${escapeHtml(t('warp_conf'))} · ${escapeHtml(t('copy'))}</button>
                    <button class="btn tiny" data-dl-conf="${i}">${escapeHtml(t('download'))}</button></div>
                    <pre class="code">${escapeHtml(res.conf[i])}</pre></div>`
                )
                .join('') || '<p class="muted">no profile</p>';
            $$('[data-dl-conf]').forEach((b) =>
              b.addEventListener('click', () => {
                const i = parseInt(b.dataset.dlConf, 10);
                download(res.configs[i].name + '.conf', res.conf[i]);
              })
            );
            wireCopyButtons();
            toast('WARP ready', 'ok');
          } catch (e) {
            toast(e.message, 'err');
          } finally {
            setBusy(false);
          }
        });
        withBridge($('#wp-generate'));
        break;
      }
      case 'gas': {
        const cfg = store.get('gas', {});
        $('#g-url').value = cfg.url || '';
        $('#g-key').value = cfg.key || '';
        $('#g-create').addEventListener('click', async () => {
          if (state.bridge) {
            try {
              const res = await bridgeCall('/api/gas/script', {});
              $('#g-key').value = res.key;
              store.set('gas', { url: $('#g-url').value, key: res.key });
              download('Code.gs', res.code);
              toast('Code.gs downloaded - deploy it on script.google.com', 'ok');
            } catch (e) {
              toast(e.message, 'err');
            }
          } else {
            try {
              const resp = await fetch('../gas/Code.gs');
              const text = await resp.text();
              const key = Engine.randPassword(18);
              download('Code.gs', text.replace('{{AUTH_KEY}}', key));
              $('#g-key').value = key;
              toast('Code.gs downloaded (key: ' + key + ')', 'ok');
            } catch (e) {
              toast('could not load the template', 'err');
            }
          }
        });
        $('#g-save').addEventListener('click', async () => {
          const body = { url: $('#g-url').value.trim(), key: $('#g-key').value.trim() };
          store.set('gas', body);
          if (state.bridge) {
            try {
              await bridgeCall('/api/gas/configure', body);
              toast('saved', 'ok');
            } catch (e) {
              toast(e.message, 'err');
            }
          } else {
            toast('saved in this browser', 'ok');
          }
        });
        $('#g-test').addEventListener('click', async () => {
          if (!withBridge($('#g-test'))) return toast(t('run_in_termux'), 'warn');
          setBusy(true, 'testing relay...');
          try {
            const res = await bridgeCall('/api/gas/test', {});
            if (res.ok) toast('relay answered in ' + res.ms + ' ms', 'ok');
            else toast('relay did not answer', 'err');
          } catch (e) {
            toast(e.message, 'err');
          } finally {
            setBusy(false);
          }
        });
        $('#g-serve').addEventListener('click', async () => {
          if (!withBridge($('#g-serve'))) return toast(t('run_in_termux'), 'warn');
          store.set('gas', { url: $('#g-url').value.trim(), key: $('#g-key').value.trim() });
          await bridgeCall('/api/gas/configure', { url: $('#g-url').value.trim(), key: $('#g-key').value.trim() }).catch(() => {});
          try {
            const res = await bridgeCall('/api/gas/serve', { port: 8080 });
            $('#gas-result').innerHTML = `<div class="panel-inset">HTTP + SOCKS5 proxy on <code>127.0.0.1:${res.port}</code>
              <p class="muted">Android: Wi-Fi → modify network → Proxy manual → 127.0.0.1:${res.port}.
              For HTTPS install the CA shown by <code>openpath gas ca</code>.</p></div>`;
          } catch (e) {
            toast(e.message, 'err');
          }
        });
        $('#g-stop').addEventListener('click', async () => {
          if (!state.bridge) return;
          await bridgeCall('/api/gas/stop', {}).catch(() => {});
          toast('stopped', 'ok');
        });
        [$('#g-test'), $('#g-serve'), $('#g-stop')].forEach((b) => withBridge(b));
        break;
      }
      case 'dpi': {
        $('#d-start').addEventListener('click', async () => {
          if (!withBridge($('#d-start'))) return toast(t('run_in_termux'), 'warn');
          try {
            const res = await bridgeCall('/api/dpi/start', {
              port: parseInt($('#d-port').value, 10) || 8081,
              chunks: parseInt($('#d-chunks').value, 10) || 3,
              fake: $('#d-fake').checked,
            });
            $('#dpi-result').innerHTML = `<div class="panel-inset">proxy running on
              <code>127.0.0.1:${res.port}</code> — use it as an HTTP or SOCKS5 upstream in your client.</div>`;
            toast('DPI proxy started', 'ok');
          } catch (e) {
            toast(e.message, 'err');
          }
        });
        $('#d-stop').addEventListener('click', async () => {
          if (!state.bridge) return;
          await bridgeCall('/api/dpi/stop', {}).catch(() => {});
          $('#dpi-result').innerHTML = '';
          toast('stopped', 'ok');
        });
        withBridge($('#d-start'));
        break;
      }
      case 'paas': {
        const sel = $('#p-preset');
        const presets = [
          ['vless-ws', 'VLESS + WebSocket + TLS'],
          ['vless-xhttp', 'VLESS + XHTTP (newest)'],
          ['trojan-ws', 'Trojan + WebSocket + TLS'],
          ['shadowsocks', 'Shadowsocks 2022 (UDP)'],
          ['hysteria2', 'Hysteria2 (QUIC, UDP)'],
          ['tuic', 'TUIC v5 (QUIC, UDP)'],
        ];
        sel.innerHTML = presets.map(([v, l]) => `<option value="${v}">${escapeHtml(l)}</option>`).join('');
        $('#p-render').addEventListener('click', async () => {
          if (!withBridge($('#p-render'))) return toast(t('run_in_termux'), 'warn');
          const repo = $('#p-repo').value.trim();
          if (!repo) return toast('repository is required (copy the paas/ folder into it)', 'err');
          setBusy(true, 'creating the service...');
          try {
            const res = await bridgeCall('/api/paas/render', { repo, preset: sel.value, name: 'openpath' });
            $('#paas-result').innerHTML = `<div class="panel-inset"><b>${escapeHtml(res.result.url || '')}</b>
              <pre class="code">${escapeHtml(JSON.stringify(res.result.settings, null, 2))}</pre></div>`;
            toast('service created', 'ok');
          } catch (e) {
            toast(e.message, 'err');
          } finally {
            setBusy(false);
          }
        });
        $('#p-codespace').addEventListener('click', async () => {
          if (!withBridge($('#p-codespace'))) return toast(t('run_in_termux'), 'warn');
          const repo = $('#p-repo').value.trim();
          if (!repo) return toast('repository is required', 'err');
          setBusy(true, 'starting a codespace (a few minutes)...');
          try {
            const res = await bridgeCall('/api/paas/codespace', { repo, preset: sel.value });
            $('#paas-result').innerHTML = `<div class="panel-inset"><b>${escapeHtml(res.result.tunnel_url || 'pending')}</b>
              <pre class="code">${escapeHtml(JSON.stringify(res.result.settings, null, 2))}</pre></div>`;
            toast('codespace requested', 'ok');
          } catch (e) {
            toast(e.message, 'err');
          } finally {
            setBusy(false);
          }
        });
        withBridge($('#p-render'));
        withBridge($('#p-codespace'));
        break;
      }
      case 'subs': {
        $('#s-fetch').addEventListener('click', async () => {
          if (!withBridge($('#s-fetch'))) return toast(t('run_in_termux'), 'warn');
          setBusy(true, 'fetching public lists...');
          try {
            const res = await bridgeCall('/api/sub/fetch', { limit: 40 });
            state.configs = Engine.mergeConfigs([state.configs, res.configs]);
            renderSubsList(res.configs, res.report);
            toast(res.count + ' configs', 'ok');
          } catch (e) {
            toast(e.message, 'err');
          } finally {
            setBusy(false);
          }
        });
        $('#s-import').addEventListener('click', () => {
          const parsed = Engine.parseAny($('#s-input').value);
          if (!parsed.length) return toast('nothing recognised', 'err');
          state.configs = Engine.mergeConfigs([state.configs, parsed]);
          renderSubsList(state.configs, []);
          toast(parsed.length + ' configs imported', 'ok');
        });
        $('#s-export').addEventListener('click', () => {
          if (!state.configs.length) return toast('no configs', 'err');
          const fmt = $('#s-format').value;
          const text = Engine.exportConfigs(state.configs, fmt, 'global');
          download('openpath-subscription.' + (fmt === 'clash' ? 'yaml' : fmt === 'b64' || fmt === 'text' ? 'txt' : 'json'), text);
          toast('exported', 'ok');
        });
        $('#s-qr').addEventListener('click', () => {
          if (!state.configs.length) return toast('no configs', 'err');
          const text = Engine.exportConfigs(state.configs, 'b64', 'global').trim();
          $('#subs-result').insertAdjacentHTML('afterbegin', `<div class="qr-box">${qrSvg(text, 4)}</div>`);
        });
        $('#s-serve').addEventListener('click', async () => {
          if (!withBridge($('#s-serve'))) return toast(t('run_in_termux'), 'warn');
          try {
            const res = await bridgeCall('/api/sub/serve', { configs: state.configs });
            $('#subs-result').insertAdjacentHTML(
              'afterbegin',
              `<div class="panel-inset">subscription: <code>${escapeHtml(res.local)}</code>
               ${res.lan ? `<br>LAN: <code>${escapeHtml(res.lan)}</code>` : ''}</div>`
            );
            toast('serving', 'ok');
          } catch (e) {
            toast(e.message, 'err');
          }
        });
        withBridge($('#s-fetch'));
        withBridge($('#s-serve'));
        if (state.configs.length) renderSubsList(state.configs, []);
        break;
      }
      case 'builder': {
        const proto = store.get('builder.proto', 'vless');
        $('#b-form').innerHTML = builderForm(proto);
        $$('#b-form [name=proto]').forEach((r) =>
          r.addEventListener('change', () => {
            store.set('builder.proto', r.value);
            $('#b-form').innerHTML = builderForm(r.value);
          })
        );
        $('#b-build').addEventListener('click', () => {
          const cfg = readBuilderForm();
          try {
            const uri = Engine.toUri(cfg);
            state.configs = Engine.mergeConfigs([state.configs, [cfg]]);
            $('#builder-result').innerHTML = `<div class="panel-inset">
              <code>${escapeHtml(uri)}</code>
              <div class="row"><button class="btn tiny" data-copy="${escapeHtml(uri)}">${escapeHtml(t('copy'))}</button>
              ${qrButton(uri, t('show_qr'))}</div>
              <pre class="code">${escapeHtml(JSON.stringify(Engine.singboxConfig([cfg]), null, 2))}</pre></div>`;
            wireCopyButtons();
            wireConfigList();
          } catch (e) {
            toast(e.message, 'err');
          }
        });
        break;
      }
      case 'test': {
        $('#t-run').addEventListener('click', async () => {
          if (!withBridge($('#t-run'))) return toast(t('run_in_termux'), 'warn');
          if (!state.configs.length) return toast('no configs', 'err');
          setBusy(true, 'testing reachability...');
          try {
            const res = await bridgeCall('/api/test', { configs: state.configs });
            const rows = res.results
              .map(
                (r) => `<tr><td>${escapeHtml(r.name || '')}</td><td>${escapeHtml(r.proto || '')}</td>
                  <td>${escapeHtml(r.server || '')}:${escapeHtml(String(r.port || ''))}</td>
                  <td class="${r.tcping ? 'ok' : 'bad'}">${r.tcping ? r.tcping + ' ms' : '—'}</td>
                  <td>${escapeHtml(r.tls || r.tls_error || '')}</td></tr>`
              )
              .join('');
            $('#test-result').innerHTML = `<table class="results"><thead><tr><th>node</th><th>proto</th><th>server</th><th>tcping</th><th>tls</th></tr></thead><tbody>${rows}</tbody></table>`;
            toast('done', 'ok');
          } catch (e) {
            toast(e.message, 'err');
          } finally {
            setBusy(false);
          }
        });
        withBridge($('#t-run'));
        break;
      }
      case 'settings': {
        $('#st-base').value = state.bridge ? state.bridge.base : '';
        $('#st-code').value = state.bridge ? state.bridge.code : '';
        $('#st-lang').addEventListener('click', () => {
          I18N.set(I18N.lang === 'en' ? 'fa' : 'en');
          render();
        });
        $('#st-connect').addEventListener('click', async () => {
          const base = $('#st-base').value.trim();
          const code = $('#st-code').value.trim();
          if (!base || !code) return toast('bridge URL and code are required', 'err');
          const prev = state.bridge;
          state.bridge = { base, code };
          try {
            const res = await bridgeCall('/api/hello', {});
            store.set('bridge', { base, code });
            $('#settings-result').innerHTML = `<div class="panel-inset">bridge OK — python ${escapeHtml(
              res.python || ''
            )}, termux: ${res.termux ? 'yes' : 'no'}</div>`;
            toast('connected', 'ok');
            renderStatus();
          } catch (e) {
            state.bridge = prev;
            toast('could not reach the bridge: ' + e.message, 'err');
          }
        });
        $('#st-selftest').addEventListener('click', async () => {
          const lines = [];
          const check = (name, fn) => {
            try {
              const r = fn();
              lines.push(`<div class="${r ? 'ok' : 'bad'}">${r ? 'PASS' : 'FAIL'} ${escapeHtml(name)}</div>`);
            } catch (e) {
              lines.push(`<div class="bad">FAIL ${escapeHtml(name)} — ${escapeHtml(e.message)}</div>`);
            }
          };
          check('uuid + vless link', () => Engine.toUri({ proto: 'vless', server: 'a.example.com', port: 443, uuid: Engine.newUUID() }).startsWith('vless://'));
          check('vless round-trip', () => {
            const u = Engine.toUri({ proto: 'vless', server: 'a.example.com', port: 443, uuid: Engine.newUUID(), network: 'ws', path: '/x' });
            return Engine.toUri(Engine.parseUri(u)) === u;
          });
          check('trojan round-trip', () => {
            const u = Engine.toUri({ proto: 'trojan', server: 'b.example.com', port: 443, password: 'pw', network: 'ws', path: '/y' });
            return Engine.toUri(Engine.parseUri(u)) === u;
          });
          check('vmess round-trip', () => {
            const u = Engine.toUri({ proto: 'vmess', server: 'c.example.com', port: 443, uuid: Engine.newUUID() });
            return Engine.parseUri(u).server === 'c.example.com';
          });
          check('ss round-trip', () => {
            const u = Engine.toUri({ proto: 'ss', server: 'd.example.com', port: 8388, password: 'pw', method: 'chacha20-ietf-poly1305' });
            const p = Engine.parseUri(u);
            return p.server === 'd.example.com' && p.password === 'pw';
          });
          check('hysteria2 round-trip', () => {
            const u = Engine.toUri({ proto: 'hysteria2', server: 'e.example.com', port: 8443, password: 'pw' });
            return Engine.parseUri(u).server === 'e.example.com';
          });
          check('tuic round-trip', () => {
            const u = Engine.toUri({ proto: 'tuic', server: 'f.example.com', port: 8443, uuid: Engine.newUUID(), password: 'pw' });
            return Engine.toUri(Engine.parseUri(u)) === u;
          });
          check('wireguard conf', () => Engine.wireguardConf({ proto: 'wireguard', server: 'g.example.com', port: 2408, wg_public_key: 'k' }).includes('[Peer]'));
          check('sing-box config', () => Engine.singboxConfig([{ proto: 'vless', server: 'h.example.com', port: 443, uuid: Engine.newUUID() }]).outbounds.length >= 4);
          check('clash config', () => Engine.clashConfig([{ proto: 'vless', server: 'i.example.com', port: 443, uuid: Engine.newUUID() }]).includes('proxies:'));
          check('xray fragment', () => Engine.xrayFragmentConfig().outbounds[0].settings.fragment.packets === 'tlshello');
          check('base64 subscription', () => Engine.parseAny(Engine.subBase64([{ proto: 'trojan', server: 'j.example.com', port: 443, password: 'p' }])).length === 1);
          $('#settings-result').innerHTML = `<div class="panel-inset">${lines.join('')}</div>`;
        });
        break;
      }
      default:
        break;
    }
  }

  function renderSubsList(cfgs, report) {
    const counts = (report || []).map((r) => `<span class="chip static">${escapeHtml(r.name)}: ${r.error ? 'error' : r.count}</span>`).join(' ');
    $('#subs-result').innerHTML = `<div class="row wrap">${counts}</div>
      <p class="muted">${state.configs.length} ${escapeHtml(t('subs_count'))}</p>
      ${renderConfigList(cfgs.slice(0, 60), 'subs-configs')}`;
    wireConfigList();
    wireCopyButtons();
  }

  function builderForm(proto) {
    const common = `
      <label>protocol
        <select class="in" name="proto">
          ${['vless', 'vmess', 'trojan', 'ss', 'hysteria2', 'tuic', 'wireguard']
            .map((p) => `<option value="${p}" ${p === proto ? 'selected' : ''}>${p}</option>`)
            .join('')}
        </select></label>
      <label>name<input class="in" name="name" value="OpenPath"></label>
      <label>server / host<input class="in" name="server" placeholder="your-worker.workers.dev"></label>
      <label>port<input class="in" name="port" type="number" value="443"></label>`;
    let extra = '';
    if (proto === 'vless' || proto === 'vmess' || proto === 'tuic') {
      extra += `<label>uuid<input class="in" name="uuid" placeholder="auto"></label>`;
    }
    if (['trojan', 'ss', 'hysteria2', 'tuic'].indexOf(proto) >= 0) {
      extra += `<label>password<input class="in" name="password" placeholder="auto"></label>`;
    }
    if (proto === 'ss') {
      extra += `<label>method<select class="in" name="method">
        <option>chacha20-ietf-poly1305</option><option>aes-256-gcm</option>
        <option>2022-blake3-chacha20-poly1305</option></select></label>`;
    }
    if (proto === 'wireguard') {
      extra += `<label>private key<input class="in" name="wg_private_key"></label>
        <label>peer public key<input class="in" name="wg_public_key"></label>
        <label>local address<input class="in" name="wg_local_address" value="172.16.0.2/32"></label>
        <label>reserved bytes<input class="in" name="wg_reserved" placeholder="0, 0, 0"></label>`;
    } else {
      extra += `<label>transport<select class="in" name="network">
        ${['ws', 'tcp', 'grpc', 'xhttp', 'httpupgrade']
          .map((n) => `<option value="${n}" ${n === 'ws' ? 'selected' : ''}>${n}</option>`)
          .join('')}</select></label>
        <label>security<select class="in" name="security">
          <option value="tls">tls</option><option value="none">none</option><option value="reality">reality</option>
        </select></label>
        <label>sni<input class="in" name="sni" placeholder="auto"></label>
        <label>host header<input class="in" name="host" placeholder="auto"></label>
        <label>path<input class="in" name="path" value="/openpath"></label>
        <label class="check"><input type="checkbox" name="fragment"> split the TLS handshake (anti-DPI)</label>`;
    }
    return common + extra;
  }

  function readBuilderForm() {
    const form = $('#b-form');
    const data = { proto: form.querySelector('[name=proto]').value };
    ['name', 'server', 'port', 'uuid', 'password', 'method', 'network', 'security', 'sni', 'host', 'path', 'wg_private_key', 'wg_public_key', 'wg_local_address', 'wg_reserved'].forEach(
      (field) => {
        const el = form.querySelector('[name=' + field + ']');
        if (el && el.value !== '') data[field] = field === 'port' ? parseInt(el.value, 10) : el.value;
      }
    );
    const frag = form.querySelector('[name=fragment]');
    if (frag && frag.checked) data.fragment = true;
    return Engine.normalize(data);
  }

  /* ------------------------------ boot ------------------------------ */
  function boot() {
    detectBridge();
    state.configs = store.get('configs', []).map(Engine.normalize);
    $('#lang-btn').addEventListener('click', () => {
      I18N.set(I18N.lang === 'en' ? 'fa' : 'en');
      render();
    });
    window.addEventListener('beforeunload', () => {
      store.set(
        'configs',
        state.configs.slice(0, 200).map((c) => Engine.normalize(c))
      );
    });
    render();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
