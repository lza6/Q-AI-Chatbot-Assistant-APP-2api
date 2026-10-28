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


def sse_text(d):
    out = []
    for line in d.splitlines():
        if line.startswith("data: "):
            p = line[6:].strip()
            if p == "[DONE]":
                continue
            try:
                j = json.loads(p)
                c = j["choices"][0].get("delta", {}).get("content")
                if c:
                    out.append(c)
            except Exception:
                pass
    return "".join(out)


print("== 1. multi-turn context ==")
st, d, t = post("/v1/chat/completions", {"messages": [
    {"role": "user", "content": "My name is Zorblax. Remember it."},
    {"role": "assistant", "content": "Understood, Zorblax."},
    {"role": "user", "content": "What is my name?"}]})
print(st, round(t, 2), repr(sse_text(d)[:120]))

print("== 2. system prompt ==")
st, d, t = post("/v1/chat/completions", {"messages": [
    {"role": "system", "content": "You only answer in French, one word."},
    {"role": "user", "content": "Hello, how are you?"}]})
print(st, round(t, 2), repr(sse_text(d)[:120]))

print("== 3. temperature/max_tokens ignored? ==")
st, d, t = post("/v1/chat/completions", {"model": "gpt-4", "temperature": 2.0, "max_tokens": 5,
                                         "messages": [{"role": "user", "content": "count 1 to 20"}]})
txt = sse_text(d)
print(st, round(t, 2), "len=%d" % len(txt), repr(txt[:100]))

print("== 4. image with extra params ==")
for body in [{"prompt": "a cat", "size": "1792x1024"}, {"prompt": "a cat", "n": 2},
             {"prompt": "a cat", "aspect_ratio": "16:9"}, {"prompt": ""}, {}]:
    st, d, t = post("/v1/images/text", body, timeout=120)
    print(st, round(t, 1), repr(d[:160]))

print("== 5. qwen/chat body shape ==")
for body in [{"model": "llama3", "messages": [{"role": "user", "content": "hi"}], "stream": False},
             {"prompt": "hi"}]:
    st, d, t = post("/v1/qwen/chat", body, timeout=60)
    print(st, round(t, 1), repr(d[:200]))

print("== 6. bad token / empty token ==")
for hdr in ["Bearer x", "", "bearer " + TOKEN]:
    h = dict(H)
    if hdr:
        h["Authorization"] = hdr
    else:
        h.pop("Authorization")
    req = urllib.request.Request(BASE + "/v1/chat/completions",
                                 data=json.dumps({"messages": [{"role": "user", "content": "hi"}]}).encode(),
                                 headers=h, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            print(repr(hdr), r.status, r.read(120).decode()[:100])
    except urllib.error.HTTPError as e:
        print(repr(hdr), e.code, e.read(140).decode("utf-8", "replace"))
