"""Q-AI / solidtechapps upstream client (stdlib only).

Verified protocol (2026-10-28):
  POST {BASE}/v1/chat/completions   Bearer <TOKEN>  -> OpenAI-style SSE (ALWAYS stream, model pinned qwen2.5:7b)
  POST {BASE}/v1/qwen/chat          Bearer <TOKEN>  -> Ollama /api/chat SSE passthrough (model selectable)
  POST {BASE}/v1/qwen/generate      Bearer <TOKEN>  -> Ollama /api/generate SSE passthrough
  POST {BASE}/v1/images/text        Bearer <TOKEN>  -> {"image_url": cloudfront 1024x1024}
  POST {BASE}/v1/images/generate    Bearer <TOKEN>  -> [{"url": replicate.delivery 1024x1024}]
  POST {BASE}/v1/feedback           Bearer <TOKEN>  -> 201 stored
"""

import json
import os
import time
import urllib.error
import urllib.request

BASE_URL = os.environ.get("QAI_BASE_URL", "https://grok.api.solidtechapps.com").rstrip("/")


def _read_local_env(key):
    """Read one key from an optional git-ignored .env.local next to this file."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env.local")
    if not os.path.isfile(path):
        return ""
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line.startswith("QAI_TOKEN=") and key == "QAI_TOKEN":
                    return line.split("=", 1)[1].strip().strip("'\"")
                if line.startswith("QAI_BASE_URL=") and key == "QAI_BASE_URL":
                    return line.split("=", 1)[1].strip().strip("'\"")
    except OSError:
        pass
    return ""


# The credential is a static key baked into the APK's assets/flutter_assets/.env.
# It is NOT committed here: export QAI_TOKEN or drop it into .env.local.
TOKEN = os.environ.get("QAI_TOKEN", "").strip() or _read_local_env("QAI_TOKEN")
if not TOKEN:
    raise SystemExit("QAI_TOKEN is not set. Export it, or create .env.local with QAI_TOKEN=<key> "
                     "(see .env.local.example). The key is the TOKEN value in the APK's .env asset.")

HUB_MODEL = "qwen2.5:7b"
OLLAMA_MODELS = ("qwen2.5:7b", "qwen2.5:1.5b")


class UpstreamError(Exception):
    def __init__(self, status, message, body=""):
        super().__init__(message)
        self.status = status
        self.message = message
        self.body = body


def _headers():
    # Case matters: upstream/Express expects exactly "Bearer " + token.
    return {
        "Content-Type": "application/json",
        "Authorization": "Bearer " + TOKEN,
        "Accept": "text/event-stream",
        "User-Agent": "okhttp/4.12.0",
    }


def post_json(path, payload, timeout=120):
    req = urllib.request.Request(BASE_URL + path, data=json.dumps(payload).encode("utf-8"),
                                 headers=_headers(), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        raise UpstreamError(exc.code, _error_message(raw), raw) from None
    except urllib.error.URLError as exc:
        raise UpstreamError(502, "upstream unreachable: %s" % exc.reason) from None


def open_stream(path, payload, timeout=180):
    """Open an SSE stream, return the raw response object for line iteration."""
    req = urllib.request.Request(BASE_URL + path, data=json.dumps(payload).encode("utf-8"),
                                 headers=_headers(), method="POST")
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        raise UpstreamError(exc.code, _error_message(raw), raw) from None
    except urllib.error.URLError as exc:
        raise UpstreamError(502, "upstream unreachable: %s" % exc.reason) from None


def _error_message(raw):
    try:
        data = json.loads(raw)
    except Exception:
        return raw[:200] or "upstream error"
    err = data.get("error")
    if isinstance(err, str):
        return err
    if isinstance(err, dict):
        return err.get("description") or err.get("message") or json.dumps(err)[:200]
    return raw[:200]


def iter_sse_data(resp):
    """Yield the payload string of every `data:` line, skipping [DONE]."""
    for raw in resp:
        line = raw.decode("utf-8", "replace").strip()
        if not line or not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload and payload != "[DONE]":
            yield payload


def hub_chat(messages, timeout=180):
    """Stream chat deltas from the hub endpoint. Yields text chunks."""
    resp = open_stream("/v1/chat/completions", {"messages": messages, "stream": True}, timeout)
    try:
        for payload in iter_sse_data(resp):
            try:
                event = json.loads(payload)
            except Exception:
                continue
            for choice in event.get("choices") or []:
                text = (choice.get("delta") or {}).get("content")
                if text:
                    yield text
    finally:
        resp.close()


def ollama_chat(model, messages, timeout=180):
    """Stream chat deltas from the Ollama passthrough endpoint. Yields text chunks."""
    resp = open_stream("/v1/qwen/chat", {"model": model, "messages": messages, "stream": True}, timeout)
    try:
        for payload in iter_sse_data(resp):
            try:
                event = json.loads(payload)
            except Exception:
                continue
            message = event.get("message")
            # Upstream proxies upstream failures as {"status":..,"message":"<string>",..}.
            if event.get("error") or not isinstance(message, dict):
                if isinstance(message, str):
                    raise UpstreamError(int(event.get("status") or 502), message)
                continue
            text = message.get("content")
            if text:
                yield text
    finally:
        resp.close()


def image_text(prompt, timeout=180):
    status, raw = post_json("/v1/images/text", {"prompt": prompt}, timeout)
    data = json.loads(raw)
    if not data.get("image_url"):
        raise UpstreamError(502, "upstream returned no image_url", raw[:200])
    return data["image_url"]


def image_generate(prompt, timeout=200):
    status, raw = post_json("/v1/images/generate", {"prompt": prompt}, timeout)
    data = json.loads(raw)
    if not isinstance(data, list) or not data or not data[0].get("url"):
        raise UpstreamError(502, "upstream returned no image url", raw[:200])
    return data[0]["url"]


def estimate_tokens(text):
    """Rough token estimate; upstream never returns usage."""
    return max(1, len(text or "") // 4)


def now():
    return int(time.time())
