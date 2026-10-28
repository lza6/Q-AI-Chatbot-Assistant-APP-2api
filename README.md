# Q-AI Chatbot Assistant v1.8.2 → OpenAI 兼容 2API

逆向对象：`Q-AI Chatbot Assistant v1.8.2 (Premium) (Mod by ElaMods).apk`
包名：`com.suponoholdings.grokchat`（Flutter / Dart AOT）｜上游：`https://grok.api.solidtechapps.com`（nginx + Express + MongoDB）

**一句话结论**：这个"Grok"外壳背后不是 Grok，而是一台自建 Ollama（`qwen2.5:7b` / `qwen2.5:1.5b` / `qwen2.5vl:7b` 视觉）外加两条文生图管线；鉴权是 APK 内置的单一静态 Bearer Token，没有用户身份、没有配额、也没有设备绑定——拿到 APK 的人都能直接用。

> 本仓库只做**协议还原 + 本地 OpenAI 兼容网关 + 真实测试**，不含 APK、不含任何绕过付费的实现，凭证已脱敏。

---

## 仓库结构

```
.
├── qai_upstream.py        上游协议客户端（纯标准库）：chat / Ollama 直通 / 双图生管线
├── demo_server.py         OpenAI 兼容网关 :8901（流式+非流式聚合、url/b64_json、OpenAI 错误体）
├── demo.html              可视化 demo 页（对话 / 文生图 / 协议说明）
├── test_demo.py           功能回归（7 项，含错误路径）
├── stress.py              压测（并发、p50/p90/p95、TTFT、失败明细）
├── browser_test.py        Playwright 真浏览器验证（截图落 shots/）
├── models_scan.py         模型枚举（44 个候选名实测）
├── vision_test.py         qwen2.5vl:7b 视觉验证（含不支持多模态的对照组）
├── probe.py  deep.py  deep2.py  charac.py  route_scan.py    上游摸底脚本
├── dump.py  scan.py       libapp.so 字符串提取工具
├── docs/
│   └── NEW-API-HANDOFF.md ★ new-api 对接交接文档（执行会话只需读这一份）
├── ANALYSIS.md            逆向分析报告（静态 + 动态 + 协议 + 基建指纹 + 踩坑表）
├── shots/                 浏览器验证截图
├── samples/               两条图管线实拍样图
└── .env.local.example     凭证模板（真实 token 不入库）
```

---

## 上游模型清单（实测，44 候选 → 3 存活）

| 模型 | 类型 | 能力 | 说明 |
|------|------|------|------|
| `qwen2.5:7b` | 文本 | 主通道 | hub 端点 `model` 字段被忽略，恒用此模型 |
| `qwen2.5:1.5b` | 文本 | 更快更弱 | 仅 Ollama 直通口可选 |
| `qwen2.5vl:7b` | **多模态** | **能读图** | 红/蓝图识别正确，成片描述准确；须用 `messages[].images`，且原图 <≈75 KB |

不存在（全部 `model not found`）：`qwen2.5:3b/0.5b/14b/32b`、`qwen2.5-coder:*`、`qwen3:*`、`llama3.x/4`、`gemma2/3`、`mistral/mixtral`、`phi3/3.5/4`、`deepseek-r1:*`、`llava`、`moondream`、`nomic-embed-text`、`grok-3/4`、`gpt-4o`。

文生图不暴露模型名：`/v1/images/text` → CloudFront、`/v1/images/generate` → Replicate，均 1024×1024，`size`/`n`/`aspect_ratio` 全部被忽略。

---

## 快速开始

```bash
cp .env.local.example .env.local     # 填入 QAI_TOKEN（APK 的 assets/flutter_assets/.env 里 TOKEN 的值）
python demo_server.py --port 8901
curl http://127.0.0.1:8901/health
# 浏览器打开 http://127.0.0.1:8901/ 即为 demo 页
```

OpenAI 兼容调用：

```bash
curl http://127.0.0.1:8901/v1/chat/completions -H 'Content-Type: application/json' \
  -d '{"model":"qai-qwen2.5-7b","messages":[{"role":"user","content":"你好"}],"stream":false}'

curl http://127.0.0.1:8901/v1/images/generations -H 'Content-Type: application/json' \
  -d '{"prompt":"a cyberpunk cat","response_format":"url"}'
```

环境变量 / `.env.local`：

| 键 | 必需 | 说明 |
|----|------|------|
| `QAI_TOKEN` | ✅ | 上游静态 Key（来自 APK），**不入库** |
| `QAI_BASE_URL` | — | 默认 `https://grok.api.solidtechapps.com` |
| `DEMO_API_KEY` | — | 给网关自己加入站鉴权（内网暴露时建议开） |

---

## 实测结果（2026-10-29）

| 项 | 结果 |
|----|------|
| 功能回归 | `test_demo.py` **7/7 通过**（非流式 2.38s、流式首字 2.43s、1.5b 直通、两条图管线、`b64_json` 1.74MB、400/404 错误路径） |
| 压测（网关） | 50 请求 @10 并发 → **50/50 成功、0 失败**，p50 15.8 s（瓶颈在上游排队）；流式 20/20；图 5/5 |
| 压测（上游直连） | c1→c10 吞吐 0.40→1.59 rps 饱和，**0 个 429/401**，并发越高延迟越差 → 算力受限而非限流 |
| 浏览器 | `browser_test.py` → **BROWSER_OK**：两轮对话上下文保持、图片 `naturalWidth=1024` 实加载、无 console error |
| 模型枚举 | `models_scan.py` → 44 候选只存活 3 个 |
| 视觉 | `vision_test.py` → 红/蓝图识别正确 + 猫图描述准确；对照组 `qwen2.5:7b` 明确报 `does not support multimodal` |
| 脱敏审计 | 干净 clone + `rg` 扫 TOKEN/SECRET/JWT/Firebase key → 无泄漏；无 `.env.local` 时启动明确报 `QAI_TOKEN is not set` |

---

## 文档索引

| 文档 | 读者 | 内容 |
|------|------|------|
| **[docs/NEW-API-HANDOFF.md](docs/NEW-API-HANDOFF.md)** | **要对接到 new-api 的执行会话** | 渠道字段、模型映射、计费、并发、验收清单、故障排查、可直接粘贴的提示词 |
| [ANALYSIS.md](ANALYSIS.md) | 想了解协议全貌的人 | 静态分析、`.env` 凭证面、6 个可用端点、上游行为坑、容量曲线、失效风险、踩坑表 |

> 旧的 `NEW-API-INTEGRATION.md` 已被 `docs/NEW-API-HANDOFF.md` 完全覆盖并合并，避免两份文档漂移。

---

## 免责与边界

- 凭证来自 APK 内第三方服务的静态密钥，**仅限研究与本地验证**，不得用于对外经营或规模转售。
- 上游是他人自建的推理资源，本仓库不提供绕过付费的实现，也不对上游可用性做任何承诺。
- 上游 token 一旦轮换，本方案立即失效——这是**预期内**的失效，不是 bug。
- APK 本体、`*.so`、`AndroidManifest.xml`、`strings.txt` 均不入库。

Licensed under the MIT License — see [LICENSE](LICENSE)。第三方 App 与其服务不在此许可范围内。
