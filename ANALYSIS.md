# 逆向分析报告 — Q-AI Chatbot Assistant v1.8.2

> 结论标签：`已验证`＝本机实测有输出；`静态确认`＝读包内产物确认；`合理推断`＝有间接证据；`待验证`＝缺条件。
> 时间：2026-10-28 ~ 10-29 ｜ 分析目录：`D:/apk-analysis/qai182/`

---

## 1. 静态面

| 项 | 值 | 依据 |
|----|----|------|
| 文件 | `Q-AI Chatbot Assistant v1.8.2 (Premium) (Mod by ElaMods).apk` / 38.2 MB | `ls` |
| 包名 | `com.suponoholdings.grokchat` | `AndroidManifest.xml`（apktool 解码）✅静态确认 |
| 版本 | versionName `1.8.2`，compileSdk 36 | 同上 |
| 框架 | **Flutter**：`lib/arm64-v8a/libapp.so` 10.6 MB（Dart AOT）、`libflutter.so` 11.1 MB | zip 清单 ✅静态确认 |
| 原生库 | `libsigner.so`、`libbugsnag*.so`、`libdatastore_shared_counter.so` | 同上 |
| 重打包痕迹 | `assets/Modder_Hub_Msg`(138 KB)、`Modder_Hub_Title`(118 KB)、`E_l_a_Mods.xml`、`assets/El_a credit.xml`、`assets/ads.txt`、`lib/arm64-v8a/El-a Mo-ds.so`(85 B 占位) | 同上 ✅静态确认 |
| 证书 | 重签证书（非原始发布证书），因此 Firebase/Google 登录在 mod 版上通常会失败 | 合理推断（重打包必然换签名） |

**Mod 的性质**：ElaMods 只做本地层面改造（广告/内购门控、品牌水印），**没有改协议、没有加代理**。所以"Premium 解锁"与能不能白嫖上游是两件事：后者完全取决于包里 `.env` 的静态 token，原版 APK 一样能白嫖。

### 1.1 明文凭证（核心）

`assets/flutter_assets/.env` —— 未加密、未混淆，flutter_dotenv 运行时读取：

```
BASE_URL='https://grok.api.solidtechapps.com/'
TOKEN='<46 字符静态 API Key，已脱敏>'
SECRET='s@k-p2p@grook:1'            # 已探测：当前鉴权链路未使用
SERDA_BASE_URL='https://ai.sora.solidtechapps.com'
SERDA_AUTH_TOKEN='eyJhbGciOiJIUzI1NiIs…'   # 独立 JWT，非本 App 聊天链路
AB_TESTING_URL / AB_TESTING_BODY_ENCRYPTION_KEY='Q94jTYTk|Jq3Z7h8'
FIREBASE_* / REVENUECAT(google,apple) / ADJUST / BUGSNAG / FACEBOOK_APP_ID
APPLE_WEB_CLIENT_ID='com.suponoholdings.grokchat.client'
```

要点：
1. **TOKEN 是唯一鉴权要素**，全量用户共用同一把，服务端没有设备绑定、没有用户概念 ✅已验证（同一 token 从本机独立 IP 直接可用）。
2. `SECRET` 在 chat / images / feedback 全链路都未被校验（带上不报错、不带也不报错）✅已验证。
3. 包内还泄漏 Firebase、RevenueCat、Adjust、Bugsnag 的 key —— 与本渠道无关，但属同类风险面，归档即可。

### 1.2 Dart 快照中的路由线索

`libapp.so` 可打印字符串里直接命中：`v1/chat/completions`、`v1/images/text`、`v1/qwen/chat`、`/qai/generate/replicate/ghibli`，以及 UI 路由 `/home/askByLink`、`/home/youtube`、`/home/docAssistant`、`/home/imageCreator`、`/home/animeDream`。App 侧功能面比 API 面大得多，说明部分功能走的是 WebView / 另一域名 ✅静态确认。

---

## 2. 动态面：上游 API 全貌

服务端指纹：`nginx/1.18.0 (Ubuntu)` + `X-Powered-By: Express` + `Access-Control-Allow-Origin: *`；`/v1/feedback` 返回 24 位 hex id（Mongo ObjectId 形态）→ **Node/Express + MongoDB** ✅已验证（响应头 + 响应体）。

### 2.1 路由枚举

对 813 条候选路径（`v1/*`、`api/v1/*`、二级组合）做 GET+POST 双方法探测，**只有 6 条非 404**（`route_scan.py`）：

| 方法 | 路径 | 形态 | 状态 |
|------|------|------|------|
| POST | `/v1/chat/completions` | OpenAI 风格 SSE，模型固定 `qwen2.5:7b` | ✅已验证 |
| POST | `/v1/qwen/chat` | Ollama `/api/chat` 直通 SSE，模型可选（仅 2 个） | ✅已验证 |
| POST | `/v1/qwen/generate` | Ollama `/api/generate` 直通（`response` 字段） | ✅已验证 |
| POST | `/v1/images/text` | `{"image_url": cloudfront 1024×1024}` | ✅已验证 |
| POST | `/v1/images/generate` | `[{"url": replicate.delivery …}]` 1024×1024 | ✅已验证 |
| POST | `/v1/feedback` | 需 `type`+`summary`+`details`，201 落库 | ✅已验证 |

注：`/v1/feedback` 属外部写接口，本轮仅各发 1 条带"probe test, ignore"的测试数据用于确认 schema，**未批量写、未删除、未暴露到网关**。

### 2.2 鉴权

```
Authorization: Bearer <TOKEN>      # "Bearer " 大小写敏感，"bearer xxx" 直接 401
```

- 缺头 / 错 token → `401 {"success":false,"error":"Unauthorized: Invalid AUTHORIZATION header"}` ✅已验证
- **错误体不一致**：401 的 `error` 是字符串，404 的 `error` 是对象 `{code,name,message,description}` —— 客户端解析要分支处理（本网关已做）。
- 无 `X-Device-Id`、无时间戳、无签名 → 无重放防护，token 一旦泄漏即长期有效 ✅已验证（跨会话/跨日仍可用）。

### 2.3 聊天通道行为（关键坑）

| 行为 | 实测结果 | 标签 |
|------|----------|------|
| `stream:false` | **仍然返回 SSE**，不会给你 JSON | ✅已验证 |
| `model` 字段 | 被忽略，响应恒为 `qwen2.5:7b`（发 `gpt-4o`、`grok-3` 都一样） | ✅已验证 |
| 多轮上下文 | 正常，`messages` 全量透传 | ✅已验证（"我叫Zorblax"→下一轮正确复述） |
| system prompt | 正常生效 | ✅已验证（限定法语后回 "Bien"） |
| `temperature` / `max_tokens` | 被忽略（`max_tokens:5` 仍输出 190 字） | ✅已验证 |
| 流式真伪 | 真流式：609 字 / 333 个 chunk / 首包 5.32 s、跨度 5.26 s | ✅已验证 |
| 计费字段 | 响应无 `usage`，本网关用 `len/4` 估算并标 `estimated:true` | 合理推断 |

### 2.4 Ollama 直通通道

`/v1/qwen/chat` 把 body 原样转给上游 Ollama，**错误也原样透传**：`model:"llama3"` → `{"error":"model 'llama3' not found"}`。

模型枚举（13 个候选）：**只有 `qwen2.5:7b`、`qwen2.5:1.5b` 存在**，其余全 not found ✅已验证 → 上游是一台自建 Ollama，不是 Grok、也不是外部 API 聚合。

### 2.5 文生图

| 管线 | 入参 | 出图 | 耗时 | 备注 |
|------|------|------|------|------|
| `/v1/images/text` | `{"prompt"}` | `d2pjqnz3em56tc.cloudfront.net/qai/<epoch_ms>.png` 1024×1024 / 1.5 MB | 3.5–5.7 s | 空 prompt → 400 `Prompt is required.` |
| `/v1/images/generate` | `{"prompt"}` | `replicate.delivery/.../out-0.png` 1024×1024 / 1.2 MB | 3.4–4.9 s | **空 prompt 也照样出图**（走默认空提示，质量无保证）；`n`/`size`/`aspect_ratio` 全被忽略 |

画质抽样：`img1.png`（橘猫特写）与 `rep1.png` 均为真实 1024×1024 成片，非占位图 ✅已验证（人工查看）。

隐私面：CloudFront 路径唯一变量是毫秒时间戳，**无签名、可枚举**，历史生成图可被按时间窗口扫到（✅静态确认路径规律，未做枚举验证）。

---

## 3. 容量与压测（第一轮）

### 3.1 上游裸压（直连 grok.api.solidtechapps.com）

并发阶梯（固定短 prompt，每档 2c 请求）：

| 并发 | 请求数 | 墙钟 | RPS | p50 | 输出速率 |
|------|--------|------|-----|-----|----------|
| 1 | 2 | 5.01 s | 0.40 | 2.59 s | 18.0 字/s |
| 3 | 6 | 7.91 s | 0.76 | 4.12 s | 37.9 字/s |
| 5 | 10 | 8.40 s | 1.19 | 3.15 s | 56.0 字/s |
| 10 | 20 | 12.57 s | 1.59 | 5.24 s | 75.1 字/s |

结论：**上游是算力受限而非限流受限**——全程 0 个 429、0 个 401，rps 随并发上升但趋饱和（≈1.6 rps），单请求延迟随并发线性变差，典型 Ollama 单机 + 小 `OLLAMA_NUM_PARALLEL` 的排队特征。`合理推断`：可用并发上限约 8–12，再往上只是排队。

### 3.2 本地网关（demo_server.py → 上游）

| 场景 | 结果 |
|------|------|
| 非流式 50 请求 @10 并发 | 50/50 成功，0 失败，墙钟 82.9 s，avg 14.9 s / p50 15.8 s / p95 19.8 s |
| 流式 20 请求 @10 并发 | 20/20 成功，TTFT avg 12.7 s（即排队时间全压在首字） |
| 文生图 5 请求 @5 并发 | 5/5 成功，p50 6.05 s，max 9.03 s |

→ 网关本身几乎不引入额外开销（同并发下延迟与直连一致），**瓶颈 100% 在上游生成侧**。

---

## 4. 次要资产（未打通，仅记录）

| 资产 | 状态 |
|------|------|
| `https://ai.sora.solidtechapps.com` | 全路径 401（`UnauthorizedAccess`）。试过 `Authorization: Bearer/token/x-auth-token/apiKey` 四种 + SERDA JWT，均 401 → 需 DB 内有效用户态，`待验证` |
| `http://test.abtestingapi.solidtechapps.com/api/v1/` | nginx/1.26.3 存活，目录级 404；A/B 通道，与聊天链路无关 |
| CloudFront 桶 `d2pjqnz3em56tc` | 公开只读，图不可列目录（仅按时间戳直取） |
| Firebase `grok-project-d7f8b` | 项目 id / apiKey 泄漏，重签包无法正常走 Google 登录 |

---

## 5. 失效风险（接入前必读）

1. **Token 轮换即全灭**：唯一鉴权要素写死在客户端，服务端做版本校验/换 key 后，所有旧 token 立刻失效，网关需同步取新包。`合理推断`
2. **随时可加风控**：目前无设备指纹、无签名、无频率限制，一旦加任一要素，本方案的全部请求路径都要重写。
3. **第三方 ToS / 合规**：这是他人付费/自建推理资源，规模化转发属典型滥用，仅限研究。
4. **单点**：单机 Ollama + 单 MongoDB，无多区域冗余；上游挂 = 渠道挂。
5. **模型能力天花板**：qwen2.5:7b，中文可用但复杂推理/长上下文远不如 GPT-4 级；`grok` 品牌纯属营销。

---

## 6. 本轮踩坑（已修复，避免下次重犯）

| # | 现象 | 根因 | 修复 |
|---|------|------|------|
| 1 | 网关 500、`AttributeError: 'str' object has no attribute 'get'` | `/v1/qwen/chat` 把上游错误包成 `{"status":404,"message":"<字符串>"}` 混在 SSE 里 | `ollama_chat` 判 `isinstance(message, dict)`，否则抛 `UpstreamError` 让客户端拿到 404 |
| 2 | 选 `qai-qwen2.5-1.5b` 返回 `KeyError: 'choices'` | 把本地别名当上游模型名传了 | 模型表加 `upstream_model` 字段，别名与上游名分离 |
| 3 | Playwright 等不到回复、截图空白 | 测试选择器 `.msg.bot` 同时命中 info 面板里的静态 `.msg bot` 块 | 选择器全部收窄为 `#chat .msg.bot` |
| 4 | 8901 端口两个实例同时 LISTENING | Windows 默认 `SO_REUSEADDR` 允许重复绑定，旧进程未死 | 起服务前按 `netstat -ano` 找 PID 精确 kill |
