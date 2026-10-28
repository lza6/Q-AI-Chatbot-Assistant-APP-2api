import json, urllib.request, urllib.error, itertools, sys
from concurrent.futures import ThreadPoolExecutor

from qai_upstream import BASE_URL as BASE, TOKEN
H = {"Content-Type": "application/json", "Authorization": "Bearer " + TOKEN}

segs = ["chat", "completions", "images", "text", "qwen", "generate", "video", "audio",
        "transcriptions", "speech", "models", "users", "user", "auth", "login", "subscription",
        "subscriptions", "tasks", "history", "credits", "credit", "usage", "files", "upload",
        "embeddings", "ghibli", "replicate", "status", "health", "me", "chats", "messages",
        "prompt", "image", "edit", "vision", "youtube", "transcript", "doc", "assistant", "sora"]

cands = []
for s in segs:
    cands.append("v1/" + s)
    cands.append("api/v1/" + s)
for a, b in itertools.product(["v1", "api/v1"], segs):
    for c in ["chat", "images", "text", "generate", "user", "users", "task", "tasks", "credit"]:
        if b != c:
            cands.append(a + "/" + b + "/" + c)
cands += ["v1/images/text", "v1/qwen/chat", "v1/chat/completions", "v1/apple", "v1/google",
          "v1/payment", "v1/verify", "v1/revenuecat", "v1/notify", "v1/feedback", "v1/support"]
cands = list(dict.fromkeys(cands))


def probe(path):
    out = []
    body = json.dumps({"prompt": "hi", "messages": [{"role": "user", "content": "hi"}]}).encode()
    for m in ("POST", "GET"):
        try:
            req = urllib.request.Request(BASE + "/" + path, data=body if m == "POST" else None, headers=H, method=m)
            with urllib.request.urlopen(req, timeout=20) as r:
                out.append((m, r.status, r.read(120).decode("utf-8", "replace")))
        except urllib.error.HTTPError as e:
            txt = e.read(200).decode("utf-8", "replace")
            if e.code != 404:
                out.append((m, e.code, txt[:160]))
        except Exception as e:
            out.append((m, -1, str(e)[:60]))
    return path, out


if __name__ == "__main__":
    hits = []
    with ThreadPoolExecutor(max_workers=12) as ex:
        for path, res in ex.map(probe, cands):
            for m, st, txt in res:
                if st != 404:
                    hits.append((m, st, path, txt))
    print("probed %d paths, %d non-404" % (len(cands), len(hits)))
    for h in sorted(hits, key=lambda x: (x[2], x[0])):
        print(h[0], h[1], "/" + h[2], "|", h[3].replace("\n", " ")[:140])
