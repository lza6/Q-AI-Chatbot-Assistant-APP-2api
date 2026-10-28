"""Verify qwen2.5vl:7b vision capability through the /v1/qwen/chat passthrough."""
import base64
import json
import struct
import urllib.request
import zlib

from qai_upstream import BASE_URL, TOKEN

H = {"Content-Type": "application/json", "Authorization": "Bearer " + TOKEN}


def solid_png(rgb, size=64):
    raw = b"".join(b"\x00" + bytes(rgb) * size for _ in range(size))

    def chunk(tag, data):
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def ask(model, text, images=None):
    msg = {"role": "user", "content": text}
    if images:
        msg["images"] = images
    payload = {"model": model, "messages": [msg], "stream": True}
    req = urllib.request.Request(BASE_URL + "/v1/qwen/chat", data=json.dumps(payload).encode(),
                                 headers=H, method="POST")
    out = []
    with urllib.request.urlopen(req, timeout=120) as r:
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
            m = ev.get("message")
            if isinstance(m, dict) and m.get("content"):
                out.append(m["content"])
            elif isinstance(m, str):
                out.append("[ERR] " + str(ev))
    return "".join(out)


red = base64.b64encode(solid_png((220, 30, 30))).decode()
blue = base64.b64encode(solid_png((30, 60, 220))).decode()
cat = base64.b64encode(open("shots/03_image.png", "rb").read()).decode()

print("== 纯红图 ==")
print(ask("qwen2.5vl:7b", "这张图主要是什么颜色？只回答颜色词。", [red])[:200])
print("== 纯蓝图 ==")
print(ask("qwen2.5vl:7b", "这张图主要是什么颜色？只回答颜色词。", [blue])[:200])
print("== 赛博朋克猫截图 ==")
print(ask("qwen2.5vl:7b", "用一句话描述这张图里的主体。", [cat])[:300])
print("== 对照: 不支持视觉的 qwen2.5:7b ==")
print(ask("qwen2.5:7b", "这张图主要是什么颜色？只回答颜色词。", [red])[:200])
