/**
 * OpenPath Google Apps Script relay
 * ---------------------------------------------------------------------------
 * A tiny HTTP relay that runs inside YOUR free Google account. During the
 * February / Esfand shutdowns in Iran, this was one of the very few things
 * that still connected, because the only thing your ISP sees is encrypted
 * traffic to script.google.com (a domain that is very hard for a censor to
 * block without breaking Google services).
 *
 * HOW TO DEPLOY (5 minutes, no server, no card)
 *   1. Open https://script.google.com  and sign in
 *   2. New project
 *   3. Delete the sample code, paste this whole file
 *   4. Change AUTH_KEY below to your own long random string
 *   5. Deploy -> New deployment -> (gear) Web app
 *        Execute as: Me
 *        Who has access: Anyone            <-- important
 *   6. Copy the "/exec" URL and give it to OpenPath:
 *        openpath gas url https://script.google.com/macros/s/XXXX/exec
 *        openpath gas serve
 *
 * LIMITS (Apps Script quotas)
 *   * ~60 seconds per execution, ~20 MB response -> big downloads are fetched
 *     in chunks with the Range header by the OpenPath client.
 *   * Google blocks Apps Script from fetching some Google-owned hosts
 *     (e.g. googlevideo.com), so YouTube *video* will not play through it.
 *   * Daily quotas apply (UrlFetchApp ~20k calls/day on a free account).
 *
 * The OpenPath client (openpath/core/gas.py) speaks the JSON protocol below:
 *   POST { "k": AUTH_KEY, "r": [ {m,u,h,b,f}, ... ] }
 *   <-   { "ok": true, "r": [ {s,h,b}, ... ] }     (b = base64 body)
 */

var CONFIG = {
  AUTH_KEY: '{{AUTH_KEY}}',
  MAX_RESPONSE_BYTES: 9 * 1024 * 1024, // keep below the Apps Script ceiling
  FETCH_TIMEOUT_MS: 28000,
  SHOW_USAGE_PAGE: true
};

/* ------------------------------------------------------------------ */
/* entry points                                                        */
/* ------------------------------------------------------------------ */
function doPost(e) {
  var started = new Date().getTime();
  try {
    if (!e || !e.postData || !e.postData.contents) {
      return json_({ ok: false, error: 'empty request' }, 400);
    }
    var payload;
    try {
      payload = JSON.parse(e.postData.contents);
    } catch (err) {
      return json_({ ok: false, error: 'bad json' }, 400);
    }
    if (!payload || payload.k !== CONFIG.AUTH_KEY) {
      return json_({ ok: false, error: 'forbidden' }, 403);
    }
    var requests = payload.r instanceof Array ? payload.r : [payload.r];
    var results = [];
    for (var i = 0; i < requests.length; i++) {
      results.push(handleOne_(requests[i]));
    }
    return json_({ ok: true, r: results, ms: new Date().getTime() - started }, 200);
  } catch (err) {
    return json_({ ok: false, error: String(err && err.message ? err.message : err) }, 500);
  }
}

function doGet(e) {
  if (!CONFIG.SHOW_USAGE_PAGE) return json_({ ok: true }, 200);
  var html =
    '<!DOCTYPE html><html><head><meta charset="utf-8"><title>OpenPath Relay</title>' +
    '<style>body{font-family:system-ui,sans-serif;background:#0f1115;color:#e6e6e6;padding:28px;line-height:1.6}' +
    'code{background:#1a1d24;color:#9fe870;padding:2px 6px;border-radius:5px}</style></head><body>' +
    '<h2>OpenPath relay is alive</h2>' +
    '<p>Paste this URL into OpenPath:</p>' +
    '<p><code>openpath gas url ' + scriptUrl_() + '</code></p>' +
    '<p>Then start the local proxy with <code>openpath gas serve</code>.</p>' +
    '<p><small>Keep this page private - anyone with the URL and your key can use the relay.</small></p>' +
    '</body></html>';
  return HtmlService.createHtmlOutput(html).setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}

function scriptUrl_() {
  try {
    return ScriptApp.getService().getUrl();
  } catch (err) {
    return '(deploy the script to get the /exec URL)';
  }
}

/* ------------------------------------------------------------------ */
/* one request                                                         */
/* ------------------------------------------------------------------ */
function handleOne_(req) {
  try {
    if (!req || !req.u) return { s: 400, h: {}, b: '', e: 'no url' };
    var method = String(req.m || 'GET').toUpperCase();
    if (['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'].indexOf(method) < 0) {
      return { s: 405, h: {}, b: '', e: 'method not allowed' };
    }

    var options = {
      method: method,
      headers: req.h || {},
      muteHttpExceptions: true,
      followRedirects: req.f === false ? false : true,
      validateHttpsCertificates: false
    };
    if (req.b) {
      try {
        options.payload = Utilities.base64Decode(req.b);
      } catch (err) {
        options.payload = Utilities.newBlob(req.b).getBytes();
      }
    }
    if (CONFIG.FETCH_TIMEOUT_MS) {
      // Apps Script does not expose a per-request timeout; keep requests small
      // and let the client split large downloads with Range.
      options.headers = options.headers || {};
    }

    var res = UrlFetchApp.fetch(req.u, options);
    var code = res.getResponseCode();
    var headers = {};
    try {
      headers = res.getHeaders() || {};
    } catch (err) {
      headers = {};
    }

    var bytes = [];
    try {
      bytes = res.getContent();
    } catch (err) {
      bytes = Utilities.newBlob('').getBytes();
    }

    if (bytes.length > CONFIG.MAX_RESPONSE_BYTES) {
      return {
        s: code,
        h: headers,
        b: '',
        e: 'response too large (' + bytes.length + ' bytes); retry with a Range header',
        truncated: true
      };
    }

    var b64 = '';
    try {
      b64 = Utilities.base64Encode(bytes);
    } catch (err) {
      b64 = Utilities.base64Encode(Utilities.newBlob('').getBytes());
    }
    return { s: code, h: headers, b: b64 };
  } catch (err) {
    return { s: 502, h: {}, b: '', e: String(err && err.message ? err.message : err) };
  }
}

function json_(obj, status) {
  var out = ContentService.createTextOutput(JSON.stringify(obj));
  out.setMimeType(ContentService.MimeType.JSON);
  return out;
}

/* ------------------------------------------------------------------ */
/* optional helpers (safe to delete)                                   */
/* ------------------------------------------------------------------ */
function openpathPing() {
  var res = handleOne_({ m: 'GET', u: 'https://www.gstatic.com/generate_204' });
  Logger.log('ping status: ' + res.s);
  return res.s;
}
