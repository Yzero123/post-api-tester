# 通用 POST 接口测试工具

一个零依赖的本地 POST 接口调试工具。双击启动，浏览器打开一个页面，填 URL / Headers / 请求 JSON 就能发请求，直接看状态码、耗时、响应头、格式化 JSON 和提取出的响应文本。

不绑定任何模型或厂商，URL、Headers、请求体全部由你自己填。

## 快速开始

### 方式一：下载打包版（推荐）

1. 到 [Releases](../../releases) 下载 `post-api-tester-v1.0.0.zip`
2. 解压到任意目录
3. **macOS**：双击 `启动测试工具.command`
   首次可能提示"未验证的开发者"，在 `系统设置 → 隐私与安全性` 里点"仍要打开"即可
4. **Windows / Linux**：在解压目录里执行 `python3 server.py`
5. 浏览器会自动打开 `http://127.0.0.1:17831/`

### 方式二：从源码运行

```bash
git clone https://github.com/Yzero123/post-api-tester.git
cd post-api-tester
python3 server.py
```

**环境要求**：Python 3.9+，无需 pip 安装任何东西（只用标准库）。

## 使用

| 字段 | 说明 |
| --- | --- |
| 请求 URL | 完整地址，含 `https://`。留空会提示，不会发请求 |
| 认证方式 | `不发送` / `x-api-key` / `Authorization: Bearer`，默认不发送 |
| API Key | 仅保存在页面内存，**不写盘、不写配置文件、不回显** |
| 自定义 Headers | JSON 对象格式，如 `{"X-Trace-Id": "abc"}`。留空合法 |
| 请求 JSON | 留空合法（会发送 0 字节请求体）；非空则必须是合法 JSON |

发送后右侧会显示：

- **响应文本**：常驻面板，自动从响应里提取可读文本
  提取顺序为 顶层 `text` → `content[].text` → `choices[0].message.content`，都没有则显示"响应中未找到可提取文本"
- **状态码 / 耗时**：非 2xx 也会完整展示，不会被当成异常吞掉
- **响应头 / 格式化 JSON / cURL**：cURL 里的密钥用环境变量 `$POST_TEST_API_KEY` 引用，不落明文

## 为什么不用 Postman / curl

- 不用装客户端，不用注册账号，不上传任何东西到云端
- 请求由本机 Python 服务转发，**绕过浏览器 CORS 限制**，能直接打任意 HTTP 接口
- 密钥只经过你自己的机器，不进第三方日志

## 安全边界

- 服务只监听 `127.0.0.1`，局域网和公网都访问不到
- API Key 只存在于页面内存，刷新即清空；服务端不落盘、不写配置文件
- 服务端日志只记录方法和路径，**不记录请求体、Headers、查询参数和密钥**
- cURL 预览用环境变量引用密钥，避免截图或粘贴时泄露
- 转发时会剥掉 `host` / `content-length` / `connection` / `transfer-encoding` 等由客户端自行接管的请求头

## 参数

```bash
python3 server.py --port 17831     # 指定端口，默认 17831
python3 server.py --no-browser     # 不自动打开浏览器
```

端口被占用时会自动往后找可用端口，并在终端打印实际地址。

## 限制

- 请求体上限 2 MB，响应体上限 20 MB，超出会明确报错
- 超时范围 1–300 秒，默认 30 秒
- 只支持 POST（如需 GET / PUT / DELETE，自行改 `server.py` 的转发逻辑）
- 字体从 Google Fonts 异步加载，网络不通时自动回退系统字体，不影响使用

## 文件说明

| 文件 | 作用 |
| --- | --- |
| `server.py` | 本地服务：静态页面 + `/api/proxy` 转发 |
| `index.html` | 单页界面，全部逻辑内联，无构建步骤 |
| `启动测试工具.command` | macOS 双击启动脚本 |

## 接口

本地服务暴露三个端点：

| 端点 | 方法 | 说明 |
| --- | --- | --- |
| `/` | GET | 返回页面 |
| `/health` | GET | 健康检查，返回 `{"ok":true,"service":"post-tester"}` |
| `/api/proxy` | POST | 转发请求，body 字段见下 |

`/api/proxy` 请求体字段：

```json
{
  "url": "https://example.com/api",
  "apiKey": "",
  "authMode": "none",
  "headers": {},
  "body": "",
  "timeoutSeconds": 30,
  "verifyTls": true
}
```

`authMode` 取值：`x-api-key` / `bearer` / `none`。

## License

MIT
