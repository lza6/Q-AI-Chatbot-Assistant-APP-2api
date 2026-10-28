# Q-AI Chatbot Assistant v1.8.2 → OpenAI 兼容 2API

逆向对象：`Q-AI Chatbot Assistant v1.8.2 (Premium) (Mod by ElaMods).apk`
包名：`com.suponoholdings.grokchat`（Flutter / Dart AOT）
上游：`https://grok.api.solidtechapps.com`（nginx + Express + MongoDB）

一句话结论：**这个"Grok"外壳背后不是 Grok，而是自建 Ollama（qwen2.5:7b / 1.5b）+ Replicate/自研图生管线；鉴权是 APK 内置的单一静态 Bearer Token，无用户身份、无配额，任何拿到 APK 的人都能直接白嫖。**

---

## 目录

| 文件 | 作用 |
|------|------|
| `qai_upstream.py` | 上游协议客户端（纯标准库）。聊天 / Ollama 直通 / 两条文生图管线 |
| `demo_server.py` | OpenAI 兼容网关（:8901），把上游转成 `/v1/chat/completions`、`/v1/images/generations` |
| `demo.html` | 可视化 demo 页（对话 + 文生图 + 协议说明），由网关直接托管 |
| `stress.py` | 本地压测工具（并发、p50/p95、TTFT、错误收集） |
| `test_demo.py` | 功能回归（非流式 / 流式 / 1.5b / 两条图片管线 / b64_json / 错误路径） |
| `browser_test.py` | Playwright 真实浏览器验证（截图落 `shots/`） |
| `probe.py` `deep.py` `deep2.py` `charac.py` `route_scan.py` | 上游摸底脚本（限速探测、参数行为、路由爆破、并发饱和曲线） |
| `models_scan.py` | 模型枚举：44 个候选名实测，确认上游只有 3 个模型 |
| `vision_test.py` | `qwen2.5vl:7b` 视觉能力验证（含不支持多模态的对照实验） |
| `ANALYSIS.md` | 逆向分析报告（静态 + 动态 + 协议 + 基建指纹） |
| `NEW-API-INTEGRATION.md` | 接入 new-api 的三种方案与计费建议 |

## 快速开始

```bash
python demo_server.py --port 8901
curl http://127.0.0.1:8901/health
# 浏览器打开 http://127.0.0.1:8901/ 即为 demo 页
```

OpenAI 兼容调用：

```bash
curl http://127.0.0.1:8901/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"qai-qwen2.5-7b","messages":[{"role":"user","content":"你好"}],"stream":false}'

curl http://127.0.0.1:8901/v1/images/generations \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"a cyberpunk cat","response_format":"url"}'
```

环境变量 / `.env.local`：

```
QAI_TOKEN='<APK assets/flutter_assets/.env 里的 TOKEN 值>'   # 必需，未提交到仓库
QAI_BASE_URL=...      # 可选，默认 grok.api.solidtechapps.com
DEMO_API_KEY=...      # 可选，本网关自己的入站鉴权
```

```bash
cp .env.local.example .env.local   # 填入 TOKEN 后再启动
```

> 凭证**不入库**：`qai_upstream.py` 只从环境变量或 git-ignored 的 `.env.local` 读取。

## 已验证状态（2026-10-28/29，本机实测）

- 功能：`test_demo.py` 7/7 通过（含流式首字 2.4s、b64_json 1.7MB）
- 模型：`models_scan.py` 44 候选 → 存活 `qwen2.5:7b` / `qwen2.5:1.5b` / `qwen2.5vl:7b`（其余全 not found）
- 视觉：`vision_test.py` → 红/蓝图识别正确 + 图片描述准确，文本模型同图报 `does not support multimodal`
- 压测：`stress.py` 50 请求 @10 并发 → 50/50 成功、0 失败、p50 15.8s（上游排队）；20 流式 @10 并发 → 20/20；5 图 @5 并发 → 5/5
- 浏览器：`browser_test.py` → `BROWSER_OK`，两轮对话上下文保持、图片 `naturalWidth=1024`、无 console error
- 截图：`shots/01_home.png` `02_chat.png` `02b_chat_turn2.png` `03_image.png` `04_info.png`

## 免责与边界

- 凭证来自 APK 内 `assets/flutter_assets/.env` 的第三方服务静态密钥，**仅用于研究与本地验证**，不得用于对外经营或规模转售。
- 本仓库不含 APK 本体、不代理鉴权绕过、不提供绕过付费的实现；`/v1/feedback` 等写接口未暴露到网关。
- 上游 token 一旦轮换，本网关立即失效（见 `ANALYSIS.md` 的失效风险章节）。
