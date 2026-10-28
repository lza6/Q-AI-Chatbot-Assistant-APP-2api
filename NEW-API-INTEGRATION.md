# 接入 new-api 的三种方案

上游已确认：`POST https://grok.api.solidtechapps.com/v1/chat/completions` + `Authorization: Bearer <静态TOKEN>`，
**永远返回 SSE、模型被固定为 `qwen2.5:7b`、无 usage 字段**。这是接入时所有坑的根源。

---

## 方案 A（推荐）：2API 中转让 new-api 当标准 OpenAI 渠道

```
客户端 → new-api（渠道类型：OpenAI）→ demo_server.py(:8901) → grok.api.solidtechapps.com
```

new-api 侧配置：

| 字段 | 值 |
|------|-----|
| 类型 | OpenAI |
| Base URL | `http://<你的中转机内网IP>:8901` |
| 密钥 | `DEMO_API_KEY` 的值（不设则随便填） |
| 模型 | `qai-qwen2.5-7b`（映射到你对外售卖名，如 `grok-2`/`qai-chat`） |
| 分组 | 按需 |
| 流式 | 开启（网关已支持 stream 与 true/false 双模式） |

优点：客户端拿到的就是标准 OpenAI 语义，`stream:false` 也能正确拿到 JSON；usage 已补齐（估算）；
错误统一成 OpenAI 错误体；图片走 `/v1/images/generations`。
缺点：多一跳进程需要自己保活（Windows 用 nssm/计划任务，Linux 用 systemd）。

**建议模型映射**：把 `qai-qwen2.5-7b` 映射成对外名（例如 `qai-chat`），不要直接叫 `grok-*`，否则用户预期与 7B 实际能力严重错配。

---

## 方案 B：直连（不加中转），仅在"全流式"时可用

new-api 里直接填 Base URL `https://grok.api.solidtechapps.com`，密钥填 APK 内 TOKEN。

- 可行前提：所有客户端都走 `stream:true`。因为上游无视 `stream:false` 一律返回 SSE，new-api 的非流式分支会解析失败。
- 不建议：一旦有非流式请求（很多 SDK 默认非流式）就会报 `unexpected content-type`。
- 且上游返回的 `model` 恒为 `qwen2.5:7b`，new-api 的模型一致性校验、计费按模型倍率都会对不上。

结论：只在临时验证时用，不作为生产渠道。

---

## 方案 C：原生 Go 渠道（type 自定义）

在 `relay/channel/` 下新增一个渠道实现，把上游当独立协议：

- `relay/channel/qai/adaptor.go`：构造 `{messages, stream:true}`，请求头写死 `Authorization: Bearer <token>`（从渠道 key 注入，**不要硬编码**）
- 响应侧强制按 SSE 解析，`stream=false` 时把 SSE 聚合后再吐 JSON（等价于 demo_server 里 `_chat` 的非流式分支）
- `usage`：上游不给，用 `len/4` 估算后在 `relayInfo` 里标注 `estimated`，计费按 token 倍率 × 估算值，或干脆按"次"计费（`PriceData` 里配固定价更稳）
- 模型名固定：渠道配置只允许一个上游模型 `qwen2.5:7b`，把 new-api 的请求模型映射进去，其它模型名直接 400

优点：少一个进程、可在 Go 侧做并发闸门（上游并发上限约 10）。
缺点：要写 Go 代码 + 过三数据库回归 + 发布流程（按项目 `Deployment Safety` 走 staging gate）。

---

## 计费与容量建议（三种方案通用）

1. **上游真实吞吐 ≈ 1.6 rps、p50 15 s @10 并发**。别按 rps 卖，按 token 卖且**限并发**：单渠道并发上限设 8–10，超了只会排队到超时（本机实测 30 并发时 p95 已 ≈4.8 s，长回答场景更糟）。
2. **倍率**：qwen2.5:7b 自建推理成本极低，但延迟高；建议倍率打到最低档、配合"低价慢速"定位，别对标 Grok。
3. **超时**：上游长回答可达 20 s+，网关与 new-api 的 `RELAY_TIMEOUT` 至少 180 s，客户端 SDK 默认 60 s 会先断。
4. **失败重试**：上游无 429，失败主要是超时/连接断；重试 1 次即可，别做指数退避长链（会把排队拖更久）。
5. **健康检查**：`GET http://<relay>:8901/health` 已含 uptime 与上游域名，可直接挂 new-api 的渠道测试。

## 上线前必做

- [ ] TOKEN 只放环境变量 / 渠道 key，**不要提交进仓库**（`qai_upstream.py` 里的默认值是逆向产物，推公开仓库前必须删）
- [ ] 中转进程开机自启 + 崩溃重启
- [ ] 打日志：上游状态码、首字延迟、总延迟、token 估算值，便于发现上游行为变化
- [ ] 准备"token 失效"预案：一旦全量 401，渠道立即禁用并提醒取新包
- [ ] 明确不做的事：不规模化转售、不给付费用户承诺 SLA
