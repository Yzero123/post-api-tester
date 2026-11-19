// 通用 POST 接口测试工具 · 浏览器跨域代理（Cloudflare Worker）
//
// 用途：让网页版能调用「不返回 CORS 头」的接口（例如 Kling）。
// 原理：浏览器 -> 你的 Worker（补上 CORS 头）-> 目标接口。
//
// 部署后把 Worker 网址填进工具的「高级 -> 代理前缀」即可，例如：
//   https://你的名字.workers.dev/?url=
//
// 安全：默认只转发白名单里的域名，不会变成谁都能白嫖的公开代理。

// ── 1. 允许转发的目标域名（要用别的接口就往这里加）────────────────────────
const ALLOWED_HOSTS = [
  "api-beijing.klingai.com",
  "api.klingai.com",
];

// ── 2. 代理密钥（强烈建议填一个随机串，防止别人盗用你的 Worker）──────────
// 填了之后，工具里的代理前缀要写成：
//   https://你的名字.workers.dev/?k=这里填的密钥&url=
// 留空字符串 "" 表示不校验。
const SHARED_SECRET = "";

// ── 3. 是否允许转发 GET（Kling 轮询任务状态需要 GET）──────────────────────
const ALLOW_GET = true;

const HOP_BY_HOP = [
  "host", "origin", "referer", "connection", "keep-alive",
  "proxy-authenticate", "proxy-authorization", "te", "trailer",
  "transfer-encoding", "upgrade", "content-length", "content-encoding",
  "cf-connecting-ip", "cf-ipcountry", "cf-ray", "cf-visitor", "x-forwarded-proto",
  "x-real-ip", "x-proxy-key",
];

export default {
  async fetch(request) {
    const url = new URL(request.url);

    // 预检请求：直接放行，不打扰上游
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: corsHeaders(request) });
    }

    const target = url.searchParams.get("url");
    if (!target) {
      return json({ error: "缺少 url 参数。用法：?url=" + encodeURIComponent("https://目标接口") }, 400, request);
    }

    let targetUrl;
    try {
      targetUrl = new URL(target);
    } catch (error) {
      return json({ error: "url 参数不是合法地址：" + target }, 400, request);
    }

    if (targetUrl.protocol !== "https:" && targetUrl.protocol !== "http:") {
      return json({ error: "只支持 http/https" }, 400, request);
    }
    if (!ALLOWED_HOSTS.includes(targetUrl.hostname)) {
      return json({
        error: "目标域名不在白名单里：" + targetUrl.hostname,
        hint: "在 Worker 的 ALLOWED_HOSTS 里加上这个域名后重新部署",
      }, 403, request);
    }

    if (SHARED_SECRET) {
      const provided = url.searchParams.get("k") || request.headers.get("x-proxy-key");
      if (provided !== SHARED_SECRET) {
        return json({ error: "代理密钥不正确" }, 401, request);
      }
    }

    if (request.method === "GET" && !ALLOW_GET) {
      return json({ error: "该代理未开启 GET 转发" }, 405, request);
    }

    // 转发：剥掉由浏览器/Worker 自己接管的头，其余原样带过去（含 Authorization）
    const headers = new Headers();
    for (const [key, value] of request.headers) {
      if (!HOP_BY_HOP.includes(key.toLowerCase())) headers.set(key, value);
    }

    const hasBody = !["GET", "HEAD"].includes(request.method);
    let upstream;
    try {
      upstream = await fetch(targetUrl.toString(), {
        method: request.method,
        headers,
        body: hasBody ? await request.arrayBuffer() : undefined,
        redirect: "follow",
      });
    } catch (error) {
      return json({ error: "转发到目标接口失败：" + (error && error.message ? error.message : String(error)) }, 502, request);
    }

    // 回程：保留上游响应头，再覆盖成允许浏览器读取的 CORS 头
    const out = new Headers();
    for (const [key, value] of upstream.headers) {
      const lower = key.toLowerCase();
      if (lower === "content-encoding" || lower === "content-length") continue;
      if (lower.startsWith("access-control-")) continue;
      out.set(key, value);
    }
    for (const [key, value] of Object.entries(corsHeaders(request))) out.set(key, value);

    return new Response(upstream.body, {
      status: upstream.status,
      statusText: upstream.statusText,
      headers: out,
    });
  },
};

function corsHeaders(request) {
  const origin = request.headers.get("Origin");
  return {
    // 有 Origin 就原样回显（兼容带凭证的请求），没有就用 *
    "Access-Control-Allow-Origin": origin || "*",
    "Access-Control-Allow-Methods": "GET,POST,PUT,PATCH,DELETE,OPTIONS",
    "Access-Control-Allow-Headers": request.headers.get("Access-Control-Request-Headers") || "*",
    "Access-Control-Expose-Headers": "*",
    "Access-Control-Max-Age": "86400",
    "Vary": "Origin",
  };
}

function json(payload, status, request) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      ...corsHeaders(request),
    },
  });
}
