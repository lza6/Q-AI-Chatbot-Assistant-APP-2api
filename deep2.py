import json, time, urllib.request, urllib.error

from qai_upstream import BASE_URL as BASE, TOKEN
H = {"Content-Type": "application/json", "Authorization": "Bearer " + TOKEN}


def post(path, body, timeout=180):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), headers=H, method="POST")
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace"), time.time() - t0
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), time.time() - t0
    except Exception as e:
        return -1, "%s: %s" % (type(e).__name__, e), time.time() - t0


print("== images/generate variants ==")
for body in [{"prompt": "a red apple"}, {"prompt": "a red apple", "num_outputs": 2},
             {"prompt": "a red apple", "aspect_ratio": "16:9"}, {"prompt": "a red apple", "model": "flux"},
             {"prompt": "a red apple", "images": ["https://d2pjqnz3em56tc.cloudfront.net/qai/1793219550137.png"]}]:
    st, d, t = post("/v1/images/generate", body, timeout=200)
    print(st, round(t, 1), repr(d[:220]))

print("== images/generate without prompt ==")
print(post("/v1/images/generate", {})[0:2])

print("== feedback ==")
print(post("/v1/feedback", {"type": "bug", "summary": "test", "details": "probe test, ignore"})[0:2])

print("== ollama model enumeration via qwen/chat ==")
for m in ["qwen2.5:7b", "qwen2.5:1.5b", "qwen2.5:3b", "llama3.2", "llama3.1:8b", "llama3:8b",
          "gemma2:9b", "mistral", "phi3", "deepseek-r1:7b", "qwen3:8b", "grok"]:
    st, d, t = post("/v1/qwen/chat", {"model": m, "messages": [{"role": "user", "content": "say OK"}], "stream": False}, timeout=60)
    ok = '"error"' not in d[:200] and "not found" not in d
    print(("OK  " if ok else "MISS"), m, "|", d.replace("\n", " ")[:110])
