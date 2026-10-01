// functions/proxy/[[path]].js
// X/Twitter 媒体资源边缘反向代理

const ALLOWED_HOSTS = [
  'video.twimg.com',
  'pbs.twimg.com',
  'abs.twimg.com',
  'ton.twimg.com',
  'cdn.syndication.twimg.com',
];

const STRIP_REQ_HEADERS = new Set([
  'host',
  'cf-connecting-ip',
  'cf-ipcountry',
  'cf-ray',
  'cf-visitor',
  'cf-worker',
  'x-forwarded-proto',
  'x-forwarded-for',
  'x-real-ip',
]);

const STRIP_RES_HEADERS = new Set([
  'content-security-policy',
  'content-security-policy-report-only',
  'x-frame-options',
  'set-cookie',
  'strict-transport-security',
  'alt-svc',
]);

const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, HEAD, OPTIONS',
  'Access-Control-Allow-Headers': 'Range, Content-Type, Accept, Origin',
  'Access-Control-Expose-Headers':
    'Content-Length, Content-Range, Accept-Ranges, Content-Type',
};

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { 'Content-Type': 'application/json; charset=utf-8', ...CORS },
  });
}

function rewriteM3u8(text, proxyBase, host, filePath) {
  const basePath = filePath.substring(0, filePath.lastIndexOf('/') + 1);

  const rewrite = (u) => {
    if (!u) return u;
    if (/^https?:\/\//i.test(u)) {
      try {
        const p = new URL(u);
        return `${proxyBase}/${p.host}${p.pathname}${p.search}`;
      } catch { return u; }
    }
    if (u.startsWith('/')) return `${proxyBase}/${host}${u}`;
    return `${proxyBase}/${host}${basePath}${u}`;
  };

  return text.split('\n').map((line) => {
    const t = line.trim();
    if (!t) return line;
    if (t.startsWith('#')) {
      return line.replace(/URI="([^"]+)"/g, (_, u) => `URI="${rewrite(u)}"`);
    }
    return rewrite(t);
  }).join('\n');
}

export async function onRequest(context) {
  const { request, params } = context;
  const method = request.method.toUpperCase();

  if (method === 'OPTIONS') return new Response(null, { status: 204, headers: CORS });
  if (method !== 'GET' && method !== 'HEAD') return json({ error: 'method not allowed' }, 405);

  const pathArr = Array.isArray(params.path) ? params.path : [];
  if (pathArr.length < 2) {
    return json({ ok: true, usage: '/proxy/<host>/<path>', allowed_hosts: ALLOWED_HOSTS });
  }

  const host = pathArr[0];
  const rest = pathArr.slice(1).join('/');

  const allowed = ALLOWED_HOSTS.some((h) => host === h || host.endsWith('.' + h));
  if (!allowed) return json({ error: 'host not allowed', host }, 403);

  const incoming = new URL(request.url);
  const target = `https://${host}/${rest}${incoming.search}`;

  const fwdHeaders = new Headers();
  for (const [k, v] of request.headers) {
    if (!STRIP_REQ_HEADERS.has(k.toLowerCase())) fwdHeaders.set(k, v);
  }
  fwdHeaders.set('Referer', 'https://x.com/');
  fwdHeaders.set('Origin', 'https://x.com');
  if (!fwdHeaders.has('user-agent')) {
    fwdHeaders.set('User-Agent',
      'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ' +
      '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36');
  }
  if (!fwdHeaders.has('accept')) fwdHeaders.set('Accept', '*/*');

  let upstream;
  try {
    upstream = await fetch(target, { method, headers: fwdHeaders, redirect: 'follow' });
  } catch (e) {
    return json({ error: 'upstream fetch failed', detail: String(e) }, 502);
  }

  const resHeaders = new Headers();
  for (const [k, v] of upstream.headers) {
    if (!STRIP_RES_HEADERS.has(k.toLowerCase())) resHeaders.set(k, v);
  }
  for (const [k, v] of Object.entries(CORS)) resHeaders.set(k, v);
  if (!resHeaders.has('cache-control')) {
    resHeaders.set('Cache-Control', 'public, max-age=86400, immutable');
  }

  const ct = (upstream.headers.get('content-type') || '').toLowerCase();
  const isM3u8 = rest.endsWith('.m3u8') || ct.includes('mpegurl') || ct.includes('x-mpegurl');

  if (isM3u8 && method === 'GET') {
    const text = await upstream.text();
    const proxyBase = `${incoming.origin}/proxy`;
    const rewritten = rewriteM3u8(text, proxyBase, host, '/' + rest);
    resHeaders.set('Content-Type', 'application/vnd.apple.mpegurl');
    resHeaders.delete('content-length');
    return new Response(rewritten, { status: upstream.status, headers: resHeaders });
  }

  return new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: resHeaders,
  });
}