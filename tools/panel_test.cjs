// Drives the panel in a real DOM (jsdom) and checks that every tab renders and
// really works - in bridge mode (the python helper running) and in standalone
// mode (what GitHub Pages serves, where there is no helper at all).
//
//   npm install jsdom            # only dependency
//   node tools/panel_test.cjs
//
// It starts its own bridge on a free port and stops it afterwards, so it needs
// nothing running. Two bugs that no syntax check could see were found by this
// test: an async call used without await (the download contained
// "[object Promise]") and template URLs that did not exist once the panel was
// published as a site.

const { spawn } = require('node:child_process');
const fs = require('node:fs');
const net = require('node:net');
const path = require('node:path');

const ROOT = path.dirname(__dirname);

let JSDOM;
try {
  ({ JSDOM } = require('jsdom'));
} catch (e) {
  console.log('skipped: jsdom is not installed (npm install jsdom)');
  process.exit(0);
}

const SCRIPTS = [
  'vendor/qrcode.js',
  'assets/js/i18n.js',
  'assets/js/engine.js',
  'assets/js/methods.js',
  'assets/js/app.js',
];

const results = [];
const check = (name, cond, extra = '') =>
  results.push(((cond ? 'PASS  ' : 'FAIL  ') + name + (cond ? '' : '   ' + String(extra).slice(0, 160))));
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

function freePort() {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.on('error', reject);
    srv.listen(0, '127.0.0.1', () => {
      const { port } = srv.address();
      srv.close(() => resolve(port));
    });
  });
}

async function waitForServer(url, timeoutMs = 40000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(url);
      if (res.ok) return true;
    } catch (e) {
      /* not up yet */
    }
    await wait(300);
  }
  return false;
}

// Builds a DOM for the panel. `offline` = pretend there is no helper: /api/*
// answers 404, everything static still comes from the real server.
async function makePanel(base, html, offline) {
  const dom = new JSDOM(html, { runScripts: 'outside-only', url: base + '/' });
  const w = dom.window;
  const blobs = [];
  w.URL.createObjectURL = (b) => {
    blobs.push(b);
    return 'blob:test';
  };
  w.URL.revokeObjectURL = () => {};
  // a real browser runs the <script> the bridge injects into index.html; with
  // runScripts:"outside-only" jsdom does not, so apply it by hand
  if (!offline) {
    const code = html.match(/OPENPATH_CODE="([A-Z0-9]+)"/);
    const bridge = html.match(/OPENPATH_BRIDGE="([^"]*)"/);
    if (code) w.OPENPATH_CODE = code[1];
    if (bridge) w.OPENPATH_BRIDGE = bridge[1];
  }
  w.fetch = (url) => {
    const u = String(url);
    if (offline && u.includes('/api/')) {
      return Promise.resolve({ ok: false, status: 404, json: () => Promise.reject(new Error('404')) });
    }
    return fetch(base + '/' + u.replace(/^\.?\/*/, ''));
  };
  for (const f of SCRIPTS) w.eval(fs.readFileSync(path.join(ROOT, 'panel', f), 'utf8'));
  if (!w.document.querySelector('#tabs').children.length) {
    w.document.dispatchEvent(new w.Event('DOMContentLoaded', { bubbles: true }));
  }
  await wait(500);
  return { w, blobs, $: (s) => w.document.querySelector(s), $$: (s) => Array.from(w.document.querySelectorAll(s)) };
}

async function runSuite(label, offline, base, html) {
  const { w, blobs, $, $$ } = await makePanel(base, html, offline);
  const click = (el) => {
    if (!el) throw new Error('missing element');
    el.dispatchEvent(new w.Event('click', { bubbles: true }));
  };
  const tab = (n) => $$('#tabs .tab').find((b) => b.dataset.tab === n);

  check(`${label}: tabs rendered`, $$('#tabs .tab').length >= 10, $$('#tabs .tab').length);
  check(`${label}: methods rendered`, $$('#methods-list .method').length >= 15, $$('#methods-list .method').length);
  const online = $('#bridge-status').className.includes('online');
  check(`${label}: bridge status correct`, online === !offline, $('#bridge-status').textContent.trim());
  if (offline) {
    check(`${label}: standalone hint shown`, !!$('#standalone-hint'), 'no hint');
  }

  // every tab must render something
  for (const t of $$('#tabs .tab').map((b) => b.dataset.tab)) {
    let ok = true;
    let err = '';
    try {
      click($$('#tabs .tab').find((b) => b.dataset.tab === t));
      ok = $('#view').innerHTML.length > 100;
      err = 'len=' + $('#view').innerHTML.length;
    } catch (e) {
      ok = false;
      err = e.message;
    }
    check(`${label}: tab ${t} renders`, ok, err);
  }

  // worker tab: a real, filled-in worker must come out
  click(tab('worker'));
  if (offline) {
    check(`${label}: bridge-only buttons marked`, $('#w-deploy').className.includes('needs-bridge'), $('#w-deploy').className);
  }
  const uuidBefore = $('#w-uuid').value;
  click($('#w-uuid-new'));
  check(`${label}: uuid generator`, /^[0-9a-f-]{36}$/.test($('#w-uuid').value), $('#w-uuid').value);
  const before = blobs.length;
  click($('#w-generate'));
  await wait(1200);
  const code = blobs.length > before ? await blobs[blobs.length - 1].text() : '';
  check(`${label}: worker download produced`, code.length > 5000, code.length + ' bytes: ' + code.slice(0, 60));
  check(`${label}: worker has no unfilled slot`, !code.includes('{{'), (code.match(/\{\{[A-Z_]+\}\}/g) || []).slice(0, 3).join(','));
  check(`${label}: worker carries its uuid`, code.includes($('#w-uuid').value), $('#w-uuid').value);

  // subscriptions: import -> export -> qr
  click(tab('subs'));
  $('#s-input').value = [
    'vless://b4b7d3d1-2f0f-4a64-9ddc-1a4b2c3d4e5f@demo.workers.dev:443?encryption=none&security=tls&type=ws&host=demo.workers.dev&path=%2Fx#Test1',
    'trojan://p@ss@demo.workers.dev:443?security=tls&type=ws&path=%2Fy#Test2',
  ].join('\n');
  click($('#s-import'));
  check(`${label}: import parsed configs`, $('#subs-result').innerHTML.includes('Test1'), $('#subs-result').innerHTML.slice(0, 100));
  const beforeExport = blobs.length;
  click($('#s-export'));
  check(`${label}: export downloads a file`, blobs.length > beforeExport, 'no download');
  click($('#s-qr'));
  check(`${label}: qr renders`, $('#subs-result').innerHTML.includes('<svg'), $('#subs-result').innerHTML.slice(0, 80));

  // builder
  click(tab('builder'));
  const serverField = $('#b-form [name=server]') || $('#b-form input');
  if (serverField) serverField.value = 'builder.example.com';
  click($('#b-build'));
  check(`${label}: builder produces a link`, $('#builder-result').innerHTML.includes('vless://'), $('#builder-result').innerHTML.slice(0, 90));

  // relay template in standalone mode
  if (offline) {
    click(tab('gas'));
    const beforeGs = blobs.length;
    click($('#g-create'));
    await wait(900);
    const gs = blobs.length > beforeGs ? await blobs[blobs.length - 1].text() : '';
    check(`${label}: relay template produced`, gs.length > 1000, gs.length + ' bytes');
    check(`${label}: relay key filled in`, !gs.includes('{{AUTH_KEY}}') && $('#g-key').value.length > 0, $('#g-key').value);
  }

  // settings: in-browser self test + language switch
  click(tab('settings'));
  click($('#st-selftest'));
  const st = $('#settings-result').innerHTML;
  check(`${label}: in-browser self test`, (st.match(/PASS/g) || []).length >= 10 && !st.includes('FAIL'), 'fails=' + (st.match(/FAIL/g) || []).length);
  click($('#st-lang'));
  check(`${label}: persian switches to rtl`, w.document.documentElement.dir === 'rtl', w.document.documentElement.dir);
  check(`${label}: persian labels render`, $('#tabs').textContent.includes('روش‌ها'), $('#tabs').textContent.slice(0, 50));
  click(tab('methods'));
  check(`${label}: persian methods render`, $('#methods-list').textContent.length > 500, $('#methods-list').textContent.length);
  click($('#lang-btn'));
  void uuidBefore;
  return results;
}

async function main() {
  const port = await freePort();
  const base = `http://127.0.0.1:${port}`;
  console.log(`starting the bridge on ${base} ...`);
  const proc = spawn('python3', [path.join(ROOT, 'openpath.py'), 'panel', '--port', String(port), '--host', '127.0.0.1', '--no-open'], {
    stdio: 'ignore',
    detached: true,
  });
  let up = false;
  try {
    up = await waitForServer(base + '/api/hello');
    if (!up) {
      console.log('FAIL  the bridge did not start');
      process.exit(1);
    }
    const html = await (await fetch(base + '/')).text();
    check('bridge injects its code into the panel', /OPENPATH_CODE="[A-Z0-9]{6}"/.test(html), html.slice(0, 120));
    await runSuite('bridge', false, base, html);
    await runSuite('standalone', true, base, html);
  } finally {
    try {
      process.kill(-proc.pid);
    } catch (e) {
      proc.kill();
    }
  }
  console.log(results.join('\n'));
  const failed = results.filter((r) => r.startsWith('FAIL')).length;
  console.log(`\n${results.length - failed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
}

main().catch((e) => {
  console.log('HARNESS ERROR ' + e.stack.slice(0, 600));
  process.exit(1);
});
