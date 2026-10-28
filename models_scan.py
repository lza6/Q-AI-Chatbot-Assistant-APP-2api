"""Enumerate the models actually served upstream.

Two probes:
  A) hub channel /v1/chat/completions  -> response.model reveals which model really answered
  B) ollama passthrough /v1/qwen/chat  -> 404 'model not found' means the name does not exist
"""
import json
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from qai_upstream import BASE_URL, TOKEN

H = {"Content-Type": "application/json", "Authorization": "Bearer " + TOKEN}

CANDIDATES = [
    # confirmed winners + family variants
    "qwen2.5:7b", "qwen2.5:1.5b", "qwen2.5:3b", "qwen2.5:0.5b", "qwen2.5:14b", "qwen2.5:32b",
    "qwen2.5:7b-instruct", "qwen2.5-coder:7b", "qwen2.5-coder:1.5b", "qwen2.5vl:7b",
    "qwen3:8b", "qwen3:4b", "qwen3:1.7b", "qwen3:0.6b",
    # common ollama library names
    "llama3.2", "llama3.2:3b", "llama3.1:8b", "llama3:8b", "llama4", "codellama:7b",
    "gemma2:9b", "gemma2:2b", "gemma3:4b", "gemma3:12b",
    "mistral", "mistral:7b", "mistral-small", "mixtral:8x7b",
    "phi3", "phi3.5", "phi4", "deepseek-r1:7b", "deepseek-r1:1.5b", "deepseek-coder-v2",
    "llava:7b", "llava:13b", "moondream", "nomic-embed-text", "tinyllama",
    # the app's marketing names
    "grok", "grok-3", "grok-4", "gpt-4o", "gpt-3.5-turbo",
]


def probe(model):
    payload = {"model": model, "messages": [{"role": "user", "content": "hi"}], "stream": True}
    req = urllib.request.Request(BASE_URL + "/v1/qwen/chat", data=json.dumps(payload).encode(),
                                 headers=H, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            for raw in r:
                line = raw.decode("utf-8", "replace").strip()
                if "not found" in line:
                    return model, "MISS"
                if '"message"' in line and '"content"' in line:
                    return model, "OK"
            return model, "EMPTY"
    except Exception as exc:
        return model, "ERR:%s" % type(exc).__name__


def hub_model(requested):
    payload = {"model": requested, "messages": [{"role": "user", "content": "hi"}], "stream": True}
    req = urllib.request.Request(BASE_URL + "/v1/chat/completions", data=json.dumps(payload).encode(),
                                 headers=H, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        for raw in r:
            line = raw.decode("utf-8", "replace").strip()
            if line.startswith("data:") and '"model"' in line:
                return json.loads(line[5:].strip())["model"]
    return "?"


if __name__ == "__main__":
    with ThreadPoolExecutor(max_workers=5) as ex:
        results = list(ex.map(probe, CANDIDATES))
    ok = [m for m, s in results if s == "OK"]
    print("=== /v1/qwen/chat 实测存活模型 (%d/%d) ===" % (len(ok), len(results)))
    for m in ok:
        print("  OK  ", m)
    miss = [(m, s) for m, s in results if s != "OK"]
    print("=== 不存在 / 异常 (%d) ===" % len(miss))
    for m, s in miss:
        print("  %-22s %s" % (m, s))

    print()
    print("=== hub 通道 /v1/chat/completions 的 model 透传行为 ===")
    for m in ["qwen2.5:1.5b", "qai-qwen2.5-1.5b", "gpt-4o", "grok-4", "qwen3:8b"]:
        try:
            print("  请求 model=%-20s -> 响应 model=%s" % (m, hub_model(m)))
        except Exception as exc:
            print("  请求 model=%-20s -> %s" % (m, exc))
