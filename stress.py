"""Load test for the qai-2api demo gateway.

python stress.py --host http://127.0.0.1:8901 --path chat --n 100 --c 20 [--stream]
python stress.py --path image --n 5 --c 5
"""

import argparse
import json
import statistics
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

PROMPTS = [
    "用一个句子解释什么是 HTTP 状态码。",
    "写一个 Python 单行函数，判断字符串是否回文。",
    "把这句话翻译成英文：今天的天气很适合写代码。",
    "列出三种常见的排序算法并用一句话说明各自特点。",
    "用 JSON 描述一个包含 name 和 age 的用户对象。",
]


def one_chat(host, idx, stream):
    body = json.dumps({"model": "qai-qwen2.5-7b", "stream": stream,
                       "messages": [{"role": "user", "content": PROMPTS[idx % len(PROMPTS)]}]}).encode()
    req = urllib.request.Request(host + "/v1/chat/completions", data=body,
                                 headers={"Content-Type": "application/json"}, method="POST")
    t0 = time.time()
    first = None
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            if stream:
                text = []
                for raw in resp:
                    line = raw.decode("utf-8", "replace").strip()
                    if not line.startswith("data:"):
                        continue
                    p = line[5:].strip()
                    if p == "[DONE]":
                        break
                    ev = json.loads(p)
                    if ev.get("error"):
                        raise RuntimeError(ev["error"]["message"])
                    d = ev["choices"][0]["delta"]
                    if d.get("content"):
                        if first is None:
                            first = time.time() - t0
                        text.append(d["content"])
                content = "".join(text)
            else:
                data = json.loads(resp.read().decode("utf-8"))
                if resp.status != 200:
                    raise RuntimeError(json.dumps(data)[:120])
                content = data["choices"][0]["message"]["content"]
        return {"ok": True, "t": time.time() - t0, "ttft": first, "chars": len(content)}
    except Exception as exc:
        return {"ok": False, "t": time.time() - t0, "err": "%s: %s" % (type(exc).__name__, exc)}


def one_image(host, idx, _stream=None):
    body = json.dumps({"prompt": "a minimal vector icon of a %s" % ["rocket", "cat", "tree", "guitar", "clock"][idx % 5]}).encode()
    req = urllib.request.Request(host + "/v1/images/generations", data=body,
                                 headers={"Content-Type": "application/json"}, method="POST")
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return {"ok": bool(data["data"][0].get("url")), "t": time.time() - t0, "chars": len(data["data"][0]["url"])}
    except Exception as exc:
        return {"ok": False, "t": time.time() - t0, "err": "%s: %s" % (type(exc).__name__, exc)}


def pct(values, p):
    if not values:
        return 0.0
    values = sorted(values)
    k = max(0, min(len(values) - 1, int(round((p / 100.0) * len(values) + 0.5)) - 1))
    return values[k]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="http://127.0.0.1:8901")
    ap.add_argument("--path", choices=["chat", "image"], default="chat")
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--c", type=int, default=10)
    ap.add_argument("--stream", action="store_true")
    args = ap.parse_args()

    fn = (lambda i: one_chat(args.host, i, args.stream)) if args.path == "chat" else (lambda i: one_image(args.host, i))
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.c) as ex:
        results = list(ex.map(fn, range(args.n)))
    wall = time.time() - t0

    ok = [r for r in results if r["ok"]]
    bad = [r for r in results if not r["ok"]]
    lat = [r["t"] for r in ok]
    print("=" * 62)
    print("path=%s n=%d concurrency=%d stream=%s" % (args.path, args.n, args.c, args.stream))
    print("wall=%.2fs  success=%d  fail=%d  rps=%.2f" % (wall, len(ok), len(bad), len(ok) / wall if wall else 0))
    if lat:
        print("latency  avg=%.2fs  p50=%.2fs  p90=%.2fs  p95=%.2fs  max=%.2fs" % (
            statistics.mean(lat), pct(lat, 50), pct(lat, 90), pct(lat, 95), max(lat)))
    ttfts = [r["ttft"] for r in ok if r.get("ttft")]
    if ttfts:
        print("ttft     avg=%.2fs  p95=%.2fs" % (statistics.mean(ttfts), pct(ttfts, 95)))
    for r in bad[:10]:
        print("FAIL", r.get("err"))
    print("=" * 62)


if __name__ == "__main__":
    main()
