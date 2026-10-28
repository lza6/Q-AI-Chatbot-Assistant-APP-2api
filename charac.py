"""Characterize upstream streaming granularity + concurrency saturation."""
import json, sys, time, urllib.request, statistics
from concurrent.futures import ThreadPoolExecutor

from qai_upstream import BASE_URL as BASE, TOKEN
H = {"Content-Type": "application/json", "Authorization": "Bearer " + TOKEN}


def stream_timing(prompt):
    body = json.dumps({"messages": [{"role": "user", "content": prompt}], "stream": True}).encode()
    req = urllib.request.Request(BASE + "/v1/chat/completions", data=body, headers=H, method="POST")
    t0 = time.time()
    times, chars = [], 0
    with urllib.request.urlopen(req, timeout=300) as r:
        for raw in r:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            p = line[5:].strip()
            if p == "[DONE]":
                break
            try:
                ev = json.loads(p)
            except Exception:
                continue
            d = ev["choices"][0]["delta"]
            if d.get("content"):
                times.append((time.time() - t0, len(d["content"])))
                chars += len(d["content"])
    total = time.time() - t0
    if not times:
        return None
    print("chars=%d total=%.2fs first_event=%.2fs last_event=%.2fs span=%.2fs events=%d"
          % (chars, total, times[0][0], times[-1][0], times[-1][0] - times[0][0], len(times)))
    print("   first 3 events:", [(round(t, 2), n) for t, n in times[:3]])
    print("   last  3 events:", [(round(t, 2), n) for t, n in times[-3:]])
    return total, chars


def one(prompt):
    body = json.dumps({"messages": [{"role": "user", "content": prompt}], "stream": True}).encode()
    req = urllib.request.Request(BASE + "/v1/chat/completions", data=body, headers=H, method="POST")
    t0 = time.time()
    chars = 0
    with urllib.request.urlopen(req, timeout=300) as r:
        for raw in r:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            p = line[5:].strip()
            if p == "[DONE]":
                break
            try:
                ev = json.loads(p)
            except Exception:
                continue
            chars += len((ev["choices"][0]["delta"].get("content") or ""))
    return time.time() - t0, chars


print("== A. streaming granularity (long answer) ==")
stream_timing("详细解释TCP三次握手，至少300字")

print()
print("== B. concurrency ladder, fixed prompt ==")
prompt = "用一句话概括什么是REST API"
for c in (1, 3, 5, 10):
    n = c * 2
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=c) as ex:
        res = list(ex.map(one, [prompt] * n))
    wall = time.time() - t0
    lat = sorted(r[0] for r in res)
    chars = sum(r[1] for r in res)
    print("c=%2d n=%2d wall=%6.2fs rps=%.2f  p50=%.2fs max=%.2fs  chars_total=%d  char/s=%.1f"
          % (c, n, wall, n / wall, lat[len(lat) // 2], lat[-1], chars, chars / wall))
