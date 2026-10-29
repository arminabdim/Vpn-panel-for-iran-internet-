// Runs the generated Cloudflare Worker in node and checks that it really
// serves configs. The worker is a Workers script (it imports cloudflare:sockets
// and exports a fetch handler), so we render it, swap that one import for a
// small stub, and then call fetch() the way Cloudflare would.
//
//   node tools/worker_runtime_test.mjs            # renders via openpath cf code
//   node tools/worker_runtime_test.mjs file.mjs   # check an existing file

import { execFileSync } from 'node:child_process';
import { mkdtempSync, readFileSync, writeFileSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.dirname(HERE);

const STUB = `// stand-in for cloudflare:sockets (only the Workers runtime has it)
export function connect() { throw new Error('connect() needs the Cloudflare runtime'); }
`;

async function loadWorker() {
  const dir = mkdtempSync(path.join(tmpdir(), 'openpath-worker-'));
  let file = process.argv[2];
  if (!file) {
    file = path.join(dir, 'worker.mjs');
    execFileSync('python3', [path.join(ROOT, 'openpath.py'), 'cf', 'code', '--out', file], { stdio: 'inherit' });
  }
  if (!existsSync(file)) {
    console.error('worker file not found:', file);
    process.exit(1);
  }
  const stub = path.join(dir, 'cloudflare-sockets.mjs');
  writeFileSync(stub, STUB);
  const src = readFileSync(file, 'utf8')
    .replace(/from\s+"cloudflare:sockets"/g, `from ${JSON.stringify(stub)}`)
    .replace(/from\s+'cloudflare:sockets'/g, `from ${JSON.stringify(stub)}`);
  const shimmed = path.join(dir, 'worker-shimmed.mjs');
  writeFileSync(shimmed, src);
  const mod = await import(shimmed);
  if (!mod.default || typeof mod.default.fetch !== 'function') {
    console.error('the worker must export default { fetch }');
    process.exit(1);
  }
  // the subscription path is randomised per deployment, so read it back out of
  // the rendered script instead of assuming a fixed one
  const subPath = (src.match(/subPath:\s*'([^']+)'/) || [null, 'sub'])[1];
  const wsPath = (src.match(/wsPath:\s*'([^']+)'/) || [null, '/'])[1];
  return { worker: mod.default, subPath, wsPath };
}

const results = [];
const check = (name, cond, extra = '') =>
  results.push(((cond ? 'PASS  ' : 'FAIL  ') + name + (cond ? '' : '   ' + String(extra).slice(0, 160))));

const { worker, subPath, wsPath } = await loadWorker();
const call = (url, headers = {}) => worker.fetch(new Request(url, { headers }), {}, {});

// ---------------------------------------------------------------- health --
let res = await call('https://demo.workers.dev/health');
let body = await res.text();
check('/health -> 200', res.status === 200, 'status=' + res.status);
check('/health says it is alive', /ok|alive|health/i.test(body), body.slice(0, 60));

// -------------------------------------------------------- subscription ----
const decode = (text) => {
  try {
    return Buffer.from(text.trim(), 'base64').toString('utf8');
  } catch (e) {
    return text;
  }
};

res = await call(`https://demo.workers.dev/${subPath}`, { 'User-Agent': 'v2rayNG/1.9.0' });
let sub = await res.text();
check(`/${subPath} -> 200`, res.status === 200, 'status=' + res.status);
let links = decode(sub);
check('subscription (base64) has a vless link', /vless:\/\/[0-9a-f-]{36}@/.test(links), links.slice(0, 120));
check('subscription (base64) has a trojan link', /trojan:\/\/.+@/.test(links), links.slice(0, 120));
check('subscription links carry the worker host', links.includes('demo.workers.dev'), '');

res = await call(`https://demo.workers.dev/${subPath}?format=singbox`, { 'User-Agent': 'HiddifyNext/2.0' });
let sb = await res.text();
let ok = false;
try {
  const j = JSON.parse(sb);
  ok = Array.isArray(j.outbounds) && j.outbounds.some((o) => o.type === 'vless');
} catch (e) {
  ok = false;
}
check('?format=singbox -> sing-box JSON with a vless outbound', ok, sb.slice(0, 120));

res = await call(`https://demo.workers.dev/${subPath}?format=clash`);
let cl = await res.text();
check('?format=clash -> YAML proxies list', cl.includes('proxies:') && /type:\s*"?vless"?/.test(cl), cl.slice(0, 120));
check('?format=clash -> port is a number, not a string', /\n\s+port:\s*\d+\s*\n/.test(cl), (cl.match(/port:[^\n]*/) || [''])[0]);

res = await call(`https://demo.workers.dev/${subPath}?format=xray`);
let xr = await res.text();
ok = false;
try {
  const j = JSON.parse(xr);
  ok = Array.isArray(j.outbounds) && j.outbounds.some((o) => o.protocol === 'vless');
} catch (e) {
  ok = false;
}
check('?format=xray -> Xray JSON with a vless outbound', ok, xr.slice(0, 120));

// ------------------------------------------------------------ other paths --
res = await call(`https://demo.workers.dev${wsPath}`);
check(`websocket path ${wsPath} without an Upgrade header does not crash`, res.status >= 100, 'status=' + res.status);

res = await call('https://demo.workers.dev/');
check('/ shows the landing page', res.status === 200 && (await res.text()).length > 200, 'status=' + res.status);

console.log(results.join('\n'));
const failed = results.filter((r) => r.startsWith('FAIL')).length;
console.log(`\n${results.length - failed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
