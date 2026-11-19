# 自己搭一个跨域代理

网页版受浏览器同源策略限制，只能调用**明确返回 `Access-Control-Allow-Origin`** 的接口。
minimax、OpenAI 等支持，可以直连；Kling 等不支持，必须经过一个代理。

这个目录里的 `cloudflare-worker.js` 就是一个可直接部署的代理。

## 为什么是 Cloudflare Worker

| 方案 | 费用 | 耗时 | 需要什么 |
| --- | --- | --- | --- |
| **Cloudflare Worker** | 免费额度足够个人用 | 约 2 分钟 | 一个 Cloudflare 账号 |
| Deno Deploy | 免费额度够用 | 约 3 分钟 | 一个 GitHub 账号 |
| 自己的服务器 / VPS | 按月付费 | 10 分钟起 | 一台公网服务器 + 域名 + HTTPS |
| 公共 CORS 代理 | 免费 | 0 分钟 | **不要用**：你的 API Key 会经过陌生人的服务器 |

## 部署步骤（Cloudflare Worker）

1. 打开 <https://dash.cloudflare.com> 注册并登录（免费，不需要绑卡）
2. 左侧菜单进入 **Workers & Pages** → **Create** → **Start with Hello World!** → **Deploy**
3. 部署完成后点 **Edit code**，把 `cloudflare-worker.js` 的全部内容粘进去，替换掉原来的代码
4. 点右上角 **Deploy**
5. 记下你的 Worker 网址，形如 `https://你的名字.workers.dev`

## 填进工具

打开网页版 → 展开「高级：跨域代理」→ 在「代理前缀」里填：

```
https://你的名字.workers.dev/?url=
```

然后正常填目标 URL 发送即可。

## 强烈建议：加一个代理密钥

不加密钥的话，任何人拿到你的 Worker 网址都能借你的账号转发流量（虽然有域名白名单，但仍建议加）。

1. 在 Worker 代码里把 `SHARED_SECRET` 改成一段随机字符串：

```js
const SHARED_SECRET = "k3j9x2m7q4p8";
```

2. 重新 **Deploy**
3. 工具里的代理前缀改成：

```
https://你的名字.workers.dev/?k=k3j9x2m7q4p8&url=
```

## 加新的接口域名

Worker 默认只转发 Kling 的两个域名。要用别的接口，在代码顶部的 `ALLOWED_HOSTS` 里加：

```js
const ALLOWED_HOSTS = [
  "api-beijing.klingai.com",
  "api.klingai.com",
  "api.example.com",   // 新增
];
```

改完重新 Deploy。

## 安全边界

- 代理只转发白名单里的域名，不会变成公开代理
- 代理会**原样转发 `Authorization` 头**，所以你的 API Key 会经过 Cloudflare 的服务器
- 代理不记录请求体、不记录请求头、不写日志
- 目标接口的响应会原样返回，只额外补上 CORS 头

## 验证是否生效

部署后在工具里发一次请求：

- 出现 **401 / 403 等具体状态码和错误正文** → 代理生效了（跨域已绕过）
- 仍然显示「浏览器没能完成这个请求 / Failed to fetch」→ 代理没生效，检查前缀是否写对、Worker 是否部署成功

## Kling 的两个额外提醒

1. **请求体格式**：Kling 公开文档的图片生成是 `{"model_name":"kling-v1","prompt":"...","n":1,"aspect_ratio":"16:9"}`，不是 `contents[]` 结构。
2. **异步任务**：创建任务只返回 `task_id`，需要再发 `GET /v1/images/generations/{task_id}` 轮询才能拿到图片 URL。Worker 已开启 GET 转发，但工具界面目前只发 POST，轮询要另想办法。
