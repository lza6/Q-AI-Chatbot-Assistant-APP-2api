# new-api 对接交接文档（给执行会话）

> 本文件是**唯一需要读的对接说明**。读完即可直接动手，不需要再问上游协议细节。
> 上游协议事实见 `ANALYSIS.md`；网关源码见 `demo_server.py` / `qai_upstream.py`。
> 对接方：new-api（Go 网关）。本仓库只提供"上游 → OpenAI 兼容"的那一层。

---

## 0. TL;DR

```
客户端 → new-api（渠道类型: OpenAI）→ 本仓库 demo_server.py（中转，:8901）→ grok.api.solidtechapps.com（自建 Ollama）
```

- **只推荐方案 A（中转）**，理由见 §2：上游永远返回 SSE、模型名固定、无 usage，直连代理会踩死这两条。
- 你要交付的成果：new-api 里新增 1 个可用渠道 + 1~3 个对外模型 + 通过 §5.7 验收清单。
- 中转进程**必须常驻且开机自启**，它是唯一把 SSE 归一化成 OpenAI 语义的地方。

---

## 1. 必须先知道的上游事实（决定了所有配置）

| # | 事实 | 影响 |
|---|------|------|
| 1 | 鉴权只有 `Authorization: Bearer <静态TOKEN>`，**"Bearer " 大小写敏感** | 密钥字段只填 TOKEN 本体，new-api 会自动加 `Bearer ` |
| 2 | 上游 `POST /v1/chat/completions` **永远返回 SSE**，即使请求体写 `stream:false` | 直连时非流式请求必炸 → 必须中转 |
| 3 | 请求里的 `model` **被完全忽略**，响应恒为 `qwen2.5:7b` | 所有模型名必须映射到同一个上游模型，别开多模型倍率 |
| 4 | 响应**没有 `usage`** | 计费只能用估算值或按次（§5.5） |
| 5 | `temperature` / `max_tokens` / `top_p` **全部被忽略** | new-api 的"最大 token"限制对上游无效，限流只能靠 new-api 侧 |
| 6 | 上游是**单机 Ollama**，只装了 3 个模型：`qwen2.5:7b` / `qwen2.5:1.5b` / `qwen2.5vl:7b`(视觉) | 能力天花板 = 7B 级；宣传别对标 Grok |
| 7 | 吞吐 ≈ **1.6 rps 封顶**，10 并发时 p50 15 s、p95 20 s | 渠道并发上限设 8–10，超时 ≥180 s |
| 8 | 无 429、无设备指纹、无签名 → 目前不限流 | 但上游随时可加风控，需可快速摘除渠道 |
| 9 | Token 是 APK 内静态凭证，**轮换即全灭** | 必须有"全量 401 → 立即禁用渠道"的预案 |

---

## 2. 方案选择（结论：只做 A）

### 方案 A — 2API 中转让 new-api 当标准 OpenAI 渠道 ✅ 推荐

```
new-api(Base URL=http://<中转机>:8901) → demo_server.py → 上游
```

- 优点：客户端拿到的是**真·标准 OpenAI**（流式/非流式都正确、有 usage、错误体统一），零 Go 改动，当天可上。
- 缺点：多一个常驻进程。

### 方案 B — new-api 直连上游 ❌ 不可行

`Base URL = https://grok.api.solidtechapps.com` 看着能填，但因为事实 #2/#3/#4：
非流式请求会拿到 `text/event-stream` 解析失败；模型一致性校验缺失；计费无 usage。
**仅在"临时手工 curl 验证"时可用，不要建渠道。**

### 方案 C — 原生 Go 渠道（要写代码，本阶段不做）

适用条件：不接受多一跳进程，或需要在 Go 层做并发闸门。实现规格见 §6。

---

## 3. 方案 A：准备凭据

中转需要 `QAI_TOKEN`（上游静态 Key，来自 APK 的 `assets/flutter_assets/.env` 里 `TOKEN=` 的值）。

```bash
# 中转机上
cd <repo>/            # 本仓库
cp .env.local.example .env.local
# 编辑 .env.local，填 QAI_TOKEN='<APK .env 里的 TOKEN 值>'
```

- **绝不把 token 写进代码 / 提交 git / 贴进聊天**；`.env.local` 已在 `.gitignore` 里。
- 也可用环境变量 `QAI_TOKEN=...` 覆盖（优先级更高）。
- 可选 `DEMO_API_KEY=...`：给中转自身加一道入站鉴权（推荐开，避免内网裸奔）。

验证凭据正确：

```bash
python -c "import qai_upstream as u; print('token len', len(u.TOKEN))"
# 期望：token len 46
```

---

## 4. 方案 A：部署中转（二选一）

### 4.1 Linux（systemd，生产推荐）

```ini
# /etc/systemd/system/qai-2api.service
[Unit]
Description=QAI 2API relay
After=network-online.target

[Service]
WorkingDirectory=/opt/qai2api
Environment=QAI_TOKEN=<token>
Environment=DEMO_API_KEY=<自定义入站密钥>
ExecStart=/usr/bin/python3 demo_server.py --port 8901
Restart=always
RestartSec=3
User=qai

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now qai-2api
curl -s localhost:8901/health
```

### 4.2 Windows（本机自用，计划任务）

```powershell
# 放到 D:\apk-analysis\qai182\，先手动确认能跑
python demo_server.py --port 8901

# 开机自启（任务计划程序，崩溃自动重启）
schtasks /create /tn "qai-2api" /tr "python D:\apk-analysis\qai182\demo_server.py --port 8901" /sc onstart /ru SYSTEM /rl HIGHEST /f
```

> Windows 上同一端口只能有一个实例。重启前先 `netstat -ano | findstr :8901` 找到 PID 再 `taskkill /F /PID <pid>`（Windows 允许重复 bind，会出现两个进程抢同一端口）。

### 4.3 中转自检（必须全绿再配 new-api）

```bash
curl -s localhost:8901/health
# {"status":"ok","uptime_s":..,"upstream":"https://grok.api.solidtechapps.com","models":[...]}

curl -s -X POST localhost:8901/v1/chat/completions -H 'Content-Type: application/json' \
  -d '{"model":"qai-qwen2.5-7b","messages":[{"role":"user","content":"回复OK"}],"stream":false}'
# 期望：标准 chat.completion JSON，choices[0].message.content 非空，usage 带 "estimated": true

curl -s -N -X POST localhost:8901/v1/chat/completions -H 'Content-Type: application/json' \
  -d '{"model":"qai-qwen2.5-7b","messages":[{"role":"user","content":"数到5"}],"stream":true}'
# 期望：data: {...} 多帧 + 结尾 data: [DONE]
```

---

## 5. 方案 A：new-api 渠道配置（逐字段）

### 5.1 渠道字段

| 字段 | 值 | 说明 |
|------|-----|------|
| 类型 | **OpenAI** | 不要选"自定义"以外特殊类型 |
| 名称 | `QAI-Ollama-中转` | 自取 |
| Base URL | `http://<中转机内网IP>:8901` | 尾斜杠可有可无；用 `127.0.0.1` 时要求 new-api 与中转同机 |
| 密钥 | `DEMO_API_KEY` 的值（未设置则随便填 `sk-any`） | new-api 自动拼 `Authorization: Bearer ...` |
| 模型 | `qai-qwen2.5-7b` | 见 5.2，**只填中转真实存在的 id** |
| 模型映射 | 见 5.2 | 对外名 → 上游 id |
| 分组 | 按你的运营分组 | — |
| 权重 | 1 | 单点渠道，权重无所谓 |
| 渠道额外设置 | `{"force_stream": false}` 之类**不需要**；保持默认 | 中转已自处理流式 |
| 代理 | 留空 | 中转自己直连上游 |

> ⚠️ Base URL 填内网/明文 HTTP 时 new-api 前端会弹"私有地址 / 非 HTTPS"安全提示，**这是提醒不是拦截**（源码 `web/src/features/channels/lib/task-plugin-base-url.ts`：`flagged, never blocked`）。生产建议给中转发个 HTTPS 反代。

### 5.2 模型与映射

中转 `/v1/models` 暴露 3 个 id：

| 中转 id | 上游真实 | 能力 | 建议 |
|---------|----------|------|------|
| `qai-qwen2.5-7b` | hub 通道，固定 `qwen2.5:7b` | 文本（主通道） | 主推 |
| `qai-qwen2.5-1.5b` | Ollama 直通 `qwen2.5:1.5b` | 文本（更快更弱） | 可选，做低价档 |
| `qai-image` | 两条图生管线 | 文生图 | 只在需要出图时用（见 5.6） |

模型映射示例（把对外名映射到中转 id）：

```json
{
  "qai-chat": "qai-qwen2.5-7b",
  "qai-chat-fast": "qai-qwen2.5-1.5b"
}
```

> **别用 `grok-*` / `gpt-4o` 之类的名字对外**：上游是 7B 模型，名字骗人只会换来投诉。
> 也别开多个对外名指向同一个 `qai-qwen2.5-7b` 再配不同倍率——用户会发现"贵的那个和便宜的一模一样"，因为上游确实一模一样。

### 5.3 超时与并发

| 项 | 建议值 | 依据 |
|----|--------|------|
| 渠道/请求超时 | **≥ 180 s**（`RELAY_TIMEOUT`） | 上游长回答可达 20 s+，10 并发 p95 ≈20 s |
| 客户端 SDK 默认超时 | 提醒用户 ≥120 s | 默认 60 s 会先断 |
| 单渠道并发 | **8–10** | 上游吞吐 1.6 rps 封顶，再高只是排队 |
| 重试 | 1 次 | 上游无 429，失败多为超时；长退避只会加剧排队 |

### 5.4 中转侧可选参数

```bash
# 限制中转并发（默认不限，靠 new-api 侧控制即可）
# 若要硬限，用 ulimit / nginx limit_conn 或前面挂一层限流
```

### 5.5 计费建议（重要）

上游不返回 usage，`demo_server.py` 用 `len/4` 估算并标 `"estimated": true`。两种做法：

- **A. 按 token 卖（推荐，简单）**：在 `setting/billing_setting/builtin_billing.go` 给对外的 `qai-chat` 定义低价算式（真实成本≈自建电费，倍率打到最低档），usage 用估算值，允许 ±20% 误差。低于 7B 能力对应的价位才卖得动。
- **B. 按次卖**：把对外模型配成"固定价一次"，不依赖 usage。适合担心估偏。

**不要**照 OpenAI 价格体系定价——这是 7B 自建模型，且延迟远高于市面 API。

### 5.6 图片（可选，要用再接）

中转支持标准 OpenAI 图片接口：

```bash
curl -X POST localhost:8901/v1/images/generations -H 'Content-Type: application/json' \
  -d '{"prompt":"a cyberpunk cat","response_format":"url"}'
# {"created":...,"data":[{"url":"https://d2pjqnz3em56tc.cloudfront.net/qai/<ms>.png","revised_prompt":"..."}]}

# b64（会由中转去下载再转 base64，耗时 +2~5s，体积 ~1.7MB）
-d '{"prompt":"...","response_format":"b64_json"}'

# 另一条上游管线（Replicate）
-d '{"prompt":"...","pipeline":"replicate"}'
```

new-api 侧按 OpenAI 图片模型的常规接法即可（模型名配 `qai-image`）。

### 5.7 验收清单（逐条可执行，全绿才算完成）

- [ ] `curl localhost:8901/health` → `status: ok`
- [ ] 中转非流式 chat → 200 + 标准 JSON + `choices[0].message.content` 非空
- [ ] 中转流式 chat → 多帧 `data:` + `[DONE]`
- [ ] new-api 渠道"测试"按钮 → 通过（`GET /v1/models` 或测试消息）
- [ ] 经 new-api 非流式：`curl <new-api>/v1/chat/completions -H 'Authorization: Bearer <new-api令牌>' -d '{"model":"qai-chat",...}'` → 200 正常文本
- [ ] 经 new-api 流式：同上加 `"stream":true` → 逐字返回
- [ ] **失败路径**：故意填错 new-api 令牌 → 401；把中转停掉 → new-api 报渠道不可用（不是挂死）
- [ ] 日志里能看到上游状态码与首字延迟（new-api 侧请求日志 + 中转 stderr）
- [ ] 并发冒烟：`python stress.py --host http://<new-api> ...` 或直接 10 并发打中转 → 0 失败

---

## 6. 方案 C：原生 Go 渠道实现规格（本阶段不做，留档）

如果要写：`relay/channel/qai/adaptor.go`

1. 请求：`{messages, stream: true}`（**永远发 stream:true**，上游不认 false），header `Authorization: Bearer <渠道 key>`，key 从渠道配置注入，禁止硬编码。
2. 响应：按 SSE 逐行解析 `data: {...}`，取 `choices[0].delta.content`；
   - 客户端要流式 → 直接转成 new-api 的 SSE 帧；
   - 客户端要非流式 → 聚合完再一次吐 `chat.completion` JSON。
3. `usage`：估算 `len/4`，并标记估算来源（不得伪装成真实 usage 参与精确结算）。
4. 模型白名单：只允许 `qwen2.5:7b`，其它请求模型一律 400，避免与事实 #3 打架。
5. 错误映射：上游 401 → `authentication_error`；上游 413 → `invalid_request_error`；超时 → 504。
6. 并发闸门：semaphore 8~10，超出排队而不是无脑打上游。
7. 必过流程：`cd relaykit && GOWORK=off go build ./...`、三数据库回归、`scripts/staging.ps1 verify`、蓝绿发布（按项目 `AGENTS.md` 的 Deployment Safety）。

---

## 7. 视觉通道 `qwen2.5vl:7b`（**当前未接入中转**，要用再开）

上游确实支持读图（已验证：红/蓝图识别正确、成片描述准确）。但：

- 必须用 Ollama 原生格式 `messages[].images = [base64]`，**不是** OpenAI 的 `image_url`；
- Express body 上限 100 KB → base64 膨胀 4/3 → **原图必须 < ≈75 KB**，超了直接 `413 Payload Too Large`；
- 需要在中转里加：`content: [{type:"image_url",...}]` → 下载 → 缩放到 <75 KB → 转 base64 塞 `images`。

想上多模态档时，让做中转的会话按上面三条改 `demo_server.py`，并补一条"大图自动压缩"的验证用例。**没做这层之前不要在 new-api 里挂视觉模型。**

---

## 8. 故障排查表

| 现象 | 根因 | 处理 |
|------|------|------|
| new-api 渠道测试失败，中转日志无请求 | Base URL/端口错，或被防火墙拦 | `curl` 从 new-api 所在机直连中转 |
| 401 `Unauthorized: Invalid AUTHORIZATION header` | token 错 / 多了空格 / 用了 `bearer` 小写 | 检查 `.env.local`，`Bearer` 大小写敏感 |
| 非流式返回一堆 `data:` 文本 | 直连了上游（方案 B），没走中转 | 改 Base URL 指向中转 |
| 请求 20 s+ 才回 / 大量超时 | 并发超过 8–10，上游排队 | 降并发、提超时到 180 s |
| 回复内容为空 | 上游偶发空 chunk（1.5b 通道更常见） | 重试 1 次；持续则切回 7b |
| `413 Payload Too Large` | 图片/长上下文超 express body 限制 | 压图到 <75 KB / 缩短历史 |
| 全量 401（突然） | 上游把 token 轮换了 | 立刻禁用渠道，取新包重新提取 TOKEN |
| `model 'xxx' not found` | 用了不在 3 个白名单里的模型名 | 只填 `qai-qwen2.5-7b` / `qai-qwen2.5-1.5b` |

---

## 9. 红线

- 不提交、不硬编码 token；不把 token 贴进 issue/PR/聊天。
- 不在生产做压力测试（上游是别人的单机，压垮即全渠道挂）；压测打自己的中转，且 ≤10 并发。
- 不做规模化转售、不承诺 SLA；这条链路的稳定性上限就是一台 7B Ollama。
- 上游一旦加风控/换 key，本方所有路径失效——这是**预期内**的失效，不是 bug。

---

## 10. 给执行会话的提示词（直接粘贴）

```text
任务：把 Q-AI 2API 中转接进 new-api。

必读（按序）：
1. https://github.com/lza6/Q-AI-Chatbot-Assistant-APP-2api/blob/master/docs/NEW-API-HANDOFF.md
2. 同仓库 ANALYSIS.md 的 §1「必须先知道的上游事实」和 §2.4「模型清单」

事实（不要再自己探测上游，会浪费时间和上游额度）：
- 上游永远返回 SSE，请求里的 model 被忽略，响应恒为 qwen2.5:7b，没有 usage
- 上游只有 3 个模型：qwen2.5:7b / qwen2.5:1.5b / qwen2.5vl:7b(视觉，未接中转)
- 吞吐封顶约 1.6 rps，并发上限 8-10，超时须 ≥180s
- 凭据是静态 Bearer token，来自 APK 的 assets/flutter_assets/.env，用户已自行取到

要做的事（按 HANDOFF §4 → §5 执行）：
1. 在中转机部署 demo_server.py（systemd 或计划任务，开机自启+崩溃重启）
2. new-api 管理端新增渠道：类型 OpenAI，Base URL http://<中转机>:8901，
   密钥 = DEMO_API_KEY，模型 qai-qwen2.5-7b，模型映射 {"qai-chat":"qai-qwen2.5-7b"}
3. 配超时 ≥180s、单渠道并发 8-10、重试 1 次
4. 按 HANDOFF §5.5 定计费（建议按次或最低倍率；usage 是估算值，标记 estimated）
5. 全部通过 HANDOFF §5.7 验收清单后交付，逐条附实际命令与输出

禁止：
- 不要直连上游建渠道（方案 B 必炸，原因见 HANDOFF §2）
- 不要在代码里硬编码 token
- 不要对生产或上游做压测
- 对外模型名不要用 grok-*/gpt-* 之类误导名
```

---

**文档版本**：2026-10-29 ｜ 对应仓库 commit 见 `README.md` 的"交付状态"
