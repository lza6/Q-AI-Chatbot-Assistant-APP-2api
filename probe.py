import json, os, time, sys, threading, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor

from qai_upstream import BASE_URL as BASE, TOKEN
HDR = {"Content-Type": "application/json", "Authorization": "Bearer " + TOKEN, "User-Agent": "okhttp/4.12.0"}


def post(path, body, timeout=120, raw=False):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), headers=HDR, method="POST")
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read().decode("utf-8", "replace")
            return r.status, data, time.time() - t0
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), time.time() - t0
    except Exception as e:
        return -1, "%s: %s" % (type(e).__name__, e), time.time() - t0


def sse_text(data):
    out = []
    for line in data.splitlines():
        if line.startswith("data: "):
            p = line[6:].strip()
            if p == "[DONE]":
                continue
            try:
                j = json.loads(p)
                out.append(j["choices"][0].get("delta", {}).get("content") or "")
            except Exception:
                pass
    return "".join(out)


def one_chat(i, prompt="Reply with the single word: OK"):
    st, data, dt = post("/v1/chat/completions", {"messages": [{"role": "user", "content": prompt}], "stream": True})
    return {"i": i, "status": st, "t": round(dt, 2), "text": sse_text(data)[:60], "nbytes": len(data)}


def one_img(i):
    st, data, dt = post("/v1/images/text", {"prompt": "a blue cube, 3d render #%d" % i}, timeout=180)
    url = ""
    try:
        url = json.loads(data).get("image_url", "")
    except Exception:
        pass
    return {"i": i, "status": st, "t": round(dt, 2), "url": url, "raw": data[:80] if st != 200 else ""}


def run(fn, n, workers, label):
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        res = list(ex.map(fn, range(n)))
    wall = time.time() - t0
    ok = [r for r in res if r["status"] == 200]
    lat = sorted(r["t"] for r in ok)
    print("[%s] n=%d workers=%d ok=%d wall=%.1fs rps=%.2f" % (label, n, workers, len(ok), wall, n / wall))
    if lat:
        print("   latency min=%.2f p50=%.2f p95=%.2f max=%.2f" % (lat[0], lat[len(lat) // 2], lat[int(len(lat) * 0.95) - 1], lat[-1]))
    for r in res:
        if r["status"] != 200:
            print("   FAIL", r)
    return res


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "seq"
    if mode == "seq":
        for i in range(3):
            r = one_chat(i)
            print("seq chat", r)
        for i in range(3):
            print("seq img", one_img(i))
    elif mode == "conc":
        run(one_chat, 20, 10, "chat-20x10")
    elif mode == "burst":
        run(one_chat, 60, 30, "chat-60x30")
    elif mode == "img":
        run(one_img, 5, 5, "img-5x5")
