import json, sys, time, urllib.request, urllib.error

BASE = "http://127.0.0.1:8901"
H = {"Content-Type": "application/json"}


def post(path, body, timeout=180):
    req = urllib.request.Request(BASE + path, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                                 headers=H, method="POST")
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8"), time.time() - t0
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), time.time() - t0


print("== 1. 中文非流式 ==")
st, d, t = post("/v1/chat/completions", {"model": "qai-qwen2.5-7b",
                                        "messages": [{"role": "user", "content": "用一句中文自我介绍，并说明你是哪个模型"}],
                                        "stream": False})
j = json.loads(d)
print(st, round(t, 2), j["choices"][0]["message"]["content"][:120])

print("== 2. 流式 ==")
req = urllib.request.Request(BASE + "/v1/chat/completions",
                             data=json.dumps({"model": "qai-qwen2.5-7b", "stream": True,
                                              "messages": [{"role": "user", "content": "从1数到10，只输出数字，逗号分隔"}]}).encode(),
                             headers=H, method="POST")
t0 = time.time()
first = None
acc = []
with urllib.request.urlopen(req, timeout=180) as r:
    print("status", r.status, "ctype", r.headers.get("Content-Type"))
    for raw in r:
        line = raw.decode("utf-8", "replace").strip()
        if not line.startswith("data:"):
            continue
        p = line[5:].strip()
        if p == "[DONE]":
            break
        ev = json.loads(p)
        dl = ev["choices"][0]["delta"]
        if dl.get("content"):
            if first is None:
                first = time.time() - t0
            acc.append(dl["content"])
print("first_token=%.2fs total=%.2fs text=%r" % (first or -1, time.time() - t0, "".join(acc)[:80]))

print("== 3. qwen1.5b (ollama 直通) ==")
st, d, t = post("/v1/chat/completions", {"model": "qai-qwen2.5-1.5b",
                                        "messages": [{"role": "user", "content": "说三个水果名字"}], "stream": False})
print(st, round(t, 2), json.loads(d)["choices"][0]["message"]["content"][:80])

print("== 4. 图片 text 管线 ==")
st, d, t = post("/v1/images/generations", {"prompt": "a cyberpunk cat wearing sunglasses, neon city"})
print(st, round(t, 2), d[:200])

print("== 5. 图片 replicate 管线 ==")
st, d, t = post("/v1/images/generations", {"prompt": "a cyberpunk cat wearing sunglasses, neon city", "pipeline": "replicate"})
print(st, round(t, 2), d[:200])

print("== 6. b64_json ==")
st, d, t = post("/v1/images/generations", {"prompt": "a single red apple", "response_format": "b64_json"})
if st == 200:
    j = json.loads(d)
    print(st, round(t, 2), "b64 len", len(j["data"][0]["b64_json"]))
else:
    print(st, d[:200])

print("== 7. 错误路径 ==")
print("空 messages:", post("/v1/chat/completions", {"messages": []})[0:2])
print("缺 prompt:  ", post("/v1/images/generations", {})[0:2])
print("未知路由:  ", end=" ")
try:
    urllib.request.urlopen(urllib.request.Request(BASE + "/v1/nope", data=b"{}", headers=H, method="POST"))
except urllib.error.HTTPError as e:
    print(e.code, e.read().decode()[:100])
