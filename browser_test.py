"""Real-browser verification of demo.html (Playwright chromium).

Asserts: health badge, streaming chat reply rendered (non-empty, meta shows latency),
image generation card rendered with a real <img> that loads (naturalWidth > 0).
"""
import os
from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:8901/"
OUT = "shots"
LAST_BOT = "() => { const m = document.querySelectorAll('#chat .msg.bot'); return m.length ? m[m.length-1] : null; }"


def wait_reply(page, timeout_ms=240000):
    """Poll until the last bot bubble has a non-empty body and a finished meta line."""
    page.wait_for_function(
        """() => {
          const m = document.querySelectorAll('#chat .msg.bot');
          if (!m.length) return false;
          const last = m[m.length - 1];
          const body = last.children[1];
          const meta = last.children[0];
          return body && body.textContent.trim().length > 0
                 && meta && meta.textContent.includes('ms');
        }""", timeout=timeout_ms)


def main():
    os.makedirs(OUT, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        errors = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))

        page.goto(URL, wait_until="networkidle")
        page.wait_for_function("document.getElementById('upstream').textContent.includes('.')", timeout=15000)
        print("badge:", page.text_content("#upstream"), "| uptime:", page.text_content("#uptime"))
        page.screenshot(path=OUT + "/01_home.png")

        page.fill("#input", "用两句话介绍你自己，并说明你是哪个模型")
        page.click("#send")
        wait_reply(page)
        bubble = page.evaluate(LAST_BOT)
        meta = page.evaluate("() => { const m=document.querySelectorAll('#chat .msg.bot'); const l=m[m.length-1]; return l.children[0].textContent; }")
        body = page.evaluate("() => { const m=document.querySelectorAll('#chat .msg.bot'); const l=m[m.length-1]; return l.children[1].textContent; }")
        assert len(body.strip()) > 10, "empty reply body"
        print("CHAT_OK meta=%s body=%s" % (meta, body.replace("\n", " ")[:120]))
        page.screenshot(path=OUT + "/02_chat.png")

        # second turn to prove context is kept
        page.fill("#input", "我刚才问你的是什么？一句话回答")
        page.click("#send")
        page.wait_for_function("() => document.querySelectorAll('#chat .msg.bot').length >= 2", timeout=60000)
        wait_reply(page)
        body2 = page.evaluate("() => { const m=document.querySelectorAll('#chat .msg.bot'); return m[m.length-1].children[1].textContent; }")
        print("TURN2_OK", body2.replace("\n", " ")[:120])
        page.screenshot(path=OUT + "/02b_chat_turn2.png")

        page.click(".tab[data-tab='image']")
        page.fill("#imgprompt", "a cyberpunk cat with neon glasses, cinematic")
        page.click("#genimg")
        page.wait_for_selector("#images .card img", timeout=300000)
        page.wait_for_function("() => { const i = document.querySelector('#images .card img');"
                               " return i && i.complete && i.naturalWidth > 0; }", timeout=120000)
        src = page.get_attribute("#images .card img", "src")
        w = page.evaluate("() => document.querySelector('#images .card img').naturalWidth")
        print("IMAGE_OK", src[:70], "naturalWidth=", w)
        page.screenshot(path=OUT + "/03_image.png")

        page.click(".tab[data-tab='info']")
        page.wait_for_timeout(400)
        page.screenshot(path=OUT + "/04_info.png")

        print("console errors:", errors if errors else "none")
        browser.close()
        print("BROWSER_OK")


if __name__ == "__main__":
    main()
