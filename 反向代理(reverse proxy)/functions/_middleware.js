// functions/_middleware.js

const VERSION = 'v1';   // 每次改数据或逻辑时 +1，强制刷新缓存

function toProxy(raw, origin) {
  if (!raw) return '';
  // 只有"已经是本域下代理过的链接"才跳过，其他一律拼接
  if (raw.startsWith('/proxy/')) return raw;
  if (raw.startsWith(origin + '/proxy/')) return raw;
  try {
    const u = new URL(raw);
    return `${origin}/proxy/${u.hostname}${u.pathname}${u.search}`;
  } catch {
    return raw;
  }
}

async function buildCfall(origin, env) {
  const res = await env.ASSETS.fetch(new URL('/all.json', origin));
  if (!res.ok) return null;
  let data;
  try { data = await res.json(); } catch { return null; }
  return (Array.isArray(data) ? data : []).map((it) => ({
    title: it.title || '',
    cover: toProxy(it.cover || '', origin),
    video_url: toProxy(it.video_url || '', origin),
  }));
}

function cacheKey(origin) {
  return new Request(`${origin}/cfall.json?${VERSION}`, { method: 'GET' });
}

async function preheat(origin, env) {
  const cache = caches.default;
  const key = cacheKey(origin);
  if (await cache.match(key)) return;
  const out = await buildCfall(origin, env);
  if (!out) return;
  const res = new Response(JSON.stringify(out), {
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      'Cache-Control': 'public, max-age=86400',
      'Access-Control-Allow-Origin': '*',
    },
  });
  await cache.put(key, res);
}

export async function onRequest(context) {
  const { request, next, env, waitUntil } = context;
  const url = new URL(request.url);
  const path = url.pathname;

  // /proxy/* 直接放过，交给 [[path]].js
  if (path.startsWith('/proxy/')) return next();

  // /cfall.json 直接响应
  if (path === '/cfall.json') {
    const cache = caches.default;
    const key = cacheKey(url.origin);
    const hit = await cache.match(key);
    if (hit) return hit;

    const out = await buildCfall(url.origin, env);
    if (!out) {
      return new Response(
        JSON.stringify({ error: 'all.json not found' }),
        {
          status: 404,
          headers: {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
          },
        }
      );
    }

    const res = new Response(JSON.stringify(out), {
      headers: {
        'Content-Type': 'application/json; charset=utf-8',
        'Cache-Control': 'public, max-age=86400',
        'Access-Control-Allow-Origin': '*',
      },
    });
    waitUntil(cache.put(key, res.clone()));
    return res;
  }

  // 其他任何路径：后台预热 + 正常走静态资源
  waitUntil(preheat(url.origin, env));
  return next();
}