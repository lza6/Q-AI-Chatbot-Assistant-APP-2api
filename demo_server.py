"""Q-AI Chatbot Assistant -> OpenAI-compatible demo gateway.

Run:  python demo_server.py [--port 8901]
Test: curl http://127.0.0.1:8901/health

Routes
  GET  /health
  GET  /v1/models
  POST /v1/chat/completions     (stream=true | false)
  POST /v1/images/generations   (response_format=url | b64_json)
  GET  /                        demo.html
"""

import argparse
import base64
import json
import os
import sys
import time
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import qai_upstream as up

DEMO_API_KEY = os.environ.get("DEMO_API_KEY", "")
DEFAULT_MODEL = "qai-qwen2.5-7b"
SERVER_START = time.time()

MODELS = [
    {"id": "qai-qwen2.5-7b", "upstream": "hub", "upstream_model": "qwen2.5:7b",
     "note": "upstream pins qwen2.5:7b"},
    {"id": "qai-qwen2.5-1.5b", "upstream": "ollama", "upstream_model": "qwen2.5:1.5b",
     "note": "faster, weaker"},
    {"id": "qai-image", "upstream": "image", "upstream_model": "", "note": "1024x1024 text-to-image"},
]
MODEL_BY_ID = {m["id"]: m for m in MODELS}


def usage_block(prompt_text, completion_text):
    return {
        "prompt_tokens": up.estimate_tokens(prompt_text),
        "completion_tokens": up.estimate_tokens(completion_text),
        "total_tokens": up.estimate_tokens(prompt_text) + up.estimate_tokens(completion_text),
        "estimated": True,
    }


def flatten_messages(messages):
    parts = []
    for msg in messages or []:
        content = msg.get("content")
        if isinstance(content, list):
            content = " ".join(c.get("text", "") for c in content if isinstance(c, dict))
        parts.append("%s: %s" % (msg.get("role", "user"), content or ""))
    return "\n".join(parts)


def resolve_model(model):
    if model in MODEL_BY_ID:
        return MODEL_BY_ID[model]
    if model in up.OLLAMA_MODELS:
        return {"id": model, "upstream": "ollama", "upstream_model": model}
    return MODEL_BY_ID[DEFAULT_MODEL]


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "qai-2api/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), fmt % args))

    # ---------- helpers ----------
    def _json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status, message, err_type="upstream_error", code=None):
        self._json(status, {"error": {"message": message, "type": err_type,
                                      "code": code if code is not None else status}})

    def _read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8", "replace"))
        except Exception:
            return None

    def _auth_ok(self):
        if not DEMO_API_KEY:
            return True
        header = self.headers.get("Authorization", "")
        return header in ("Bearer " + DEMO_API_KEY, "bearer " + DEMO_API_KEY)

    # ---------- routes ----------
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/health":
            self._json(200, {"status": "ok", "uptime_s": round(time.time() - SERVER_START, 1),
                             "upstream": up.BASE_URL, "models": [m["id"] for m in MODELS]})
            return
        if path == "/v1/models":
            self._json(200, {"object": "list", "data": [
                {"id": m["id"], "object": "model", "created": SERVER_START, "owned_by": "qai-2api"}
                for m in MODELS]})
            return
        if path in ("/", "/index.html"):
            return self._serve_file("demo.html", "text/html; charset=utf-8")
        self._error(404, "not found", "invalid_request_error")

    def _serve_file(self, name, ctype):
        base = os.path.dirname(os.path.abspath(__file__))
        full = os.path.join(base, name)
        if not os.path.isfile(full):
            self._error(404, "%s missing" % name, "invalid_request_error")
            return
        with open(full, "rb") as fh:
            body = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        path = self.path.split("?")[0]
        if not self._auth_ok():
            self._error(401, "invalid api key", "authentication_error")
            return
        body = self._read_json()
        if body is None:
            self._error(400, "invalid JSON body", "invalid_request_error")
            return
        if path == "/v1/chat/completions":
            self._chat(body)
        elif path == "/v1/images/generations":
            self._images(body)
        else:
            self._error(404, "not found", "invalid_request_error")

    # ---------- chat ----------
    def _chat(self, body):
        messages = body.get("messages") or []
        if not messages:
            self._error(400, "messages is required", "invalid_request_error")
            return
        model_meta = resolve_model(body.get("model") or DEFAULT_MODEL)
        stream = bool(body.get("stream"))
        request_id = "chatcmpl-qai-%d" % int(time.time() * 1000)
        client_model = body.get("model") or model_meta["id"]
        prompt_text = flatten_messages(messages)

        if model_meta["upstream"] == "ollama":
            chunks = lambda: up.ollama_chat(model_meta["upstream_model"], messages)
        else:
            chunks = lambda: up.hub_chat(messages)

        if stream:
            self._stream_chat(request_id, client_model, chunks, prompt_text)
            return

        text = []
        try:
            for piece in chunks():
                text.append(piece)
        except up.UpstreamError as exc:
            self._error(exc.status if exc.status >= 400 else 502, exc.message)
            return
        content = "".join(text)
        self._json(200, {
            "id": request_id,
            "object": "chat.completion",
            "created": up.now(),
            "model": client_model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content},
                         "finish_reason": "stop"}],
            "usage": usage_block(prompt_text, content),
        })

    def _stream_chat(self, request_id, model, chunks, prompt_text):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.close_connection = True

        created = up.now()

        def emit(obj):
            self.wfile.write(("data: " + json.dumps(obj, ensure_ascii=False) + "\n\n").encode("utf-8"))
            self.wfile.flush()

        emit({"id": request_id, "object": "chat.completion.chunk", "created": created, "model": model,
              "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]})
        collected = []
        try:
            for piece in chunks():
                collected.append(piece)
                emit({"id": request_id, "object": "chat.completion.chunk", "created": created, "model": model,
                      "choices": [{"index": 0, "delta": {"content": piece}, "finish_reason": None}]})
        except up.UpstreamError as exc:
            emit({"error": {"message": exc.message, "type": "upstream_error", "code": exc.status}})
        except (BrokenPipeError, ConnectionResetError):
            return
        emit({"id": request_id, "object": "chat.completion.chunk", "created": created, "model": model,
              "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
              "usage": usage_block(prompt_text, "".join(collected))})
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    # ---------- images ----------
    def _images(self, body):
        prompt = (body.get("prompt") or "").strip()
        if not prompt:
            self._error(400, "prompt is required", "invalid_request_error")
            return
        response_format = body.get("response_format") or "url"
        pipeline = "text" if body.get("pipeline") != "replicate" else "generate"
        try:
            url = up.image_text(prompt) if pipeline == "text" else up.image_generate(prompt)
        except up.UpstreamError as exc:
            self._error(exc.status if exc.status >= 400 else 502, exc.message)
            return
        item = {"revised_prompt": prompt}
        if response_format == "b64_json":
            try:
                with urllib.request.urlopen(url, timeout=90) as resp:
                    item["b64_json"] = base64.b64encode(resp.read()).decode("ascii")
            except Exception as exc:
                self._error(502, "image download failed: %s" % exc)
                return
        else:
            item["url"] = url
        self._json(200, {"created": up.now(), "data": [item],
                         "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8901)))
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.daemon_threads = True
    print("qai-2api demo listening on http://%s:%d  (upstream %s)" % (args.host, args.port, up.BASE_URL))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
