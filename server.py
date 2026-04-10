#!/usr/bin/env python3
"""
Simultane Tercüman — Sıfır Hata Versiyonu
- Çeviri: Google Translate (ücretsiz, overload yok)
- TTS: Google TTS (ücretsiz)
- WebSocket: otomatik yeniden bağlanma desteği
"""
import asyncio, json, os, random, string, urllib.request, urllib.error, urllib.parse
from aiohttp import web, WSMsgType

PORT          = int(os.environ.get("PORT", 5050))
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_KEY", "")  # yedek olarak tutuluyor

rooms = {}  # { "1234": [ {ws, lang, lang_name}, ... ] }

def make_code():
    for _ in range(200):
        code = ''.join(random.choices(string.digits, k=4))
        if code not in rooms:
            return code
    return ''.join(random.choices(string.digits, k=6))

# ── Google Translate (ücretsiz, API key gerektirmez) ──────────
GOOGLE_LANG = {
    "tr":"tr","en":"en","bg":"bg","es":"es","fr":"fr","it":"it",
    "ar":"ar","fa":"fa","he":"iw","ur":"ur","ku":"ku"
}

async def google_translate(text, src_lang, tgt_lang):
    """Google Translate API — ücretsiz, sınırsız"""
    sl = GOOGLE_LANG.get(src_lang, "auto")
    tl = GOOGLE_LANG.get(tgt_lang, "en")

    url = "https://translate.googleapis.com/translate_a/single?" + urllib.parse.urlencode({
        "client": "gtx",
        "sl": sl,
        "tl": tl,
        "dt": "t",
        "q": text
    })

    loop = asyncio.get_running_loop()
    def fetch():
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "*/*",
        })
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8"))
        # Google yanıtı: [[["çeviri","orijinal",...], ...], ...]
        parts = []
        for item in data[0]:
            if item[0]:
                parts.append(item[0])
        return "".join(parts).strip()

    return await loop.run_in_executor(None, fetch)

# ── Yedek: Anthropic (Google başarısız olursa) ────────────────
async def anthropic_translate(text, src_name, tgt_name):
    if not ANTHROPIC_KEY:
        raise Exception("Anthropic key yok")
    payload = {
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 500,
        "system": "Translate the given text. Output only the translation, nothing else.",
        "messages": [{"role": "user", "content": f"Translate from {src_name} to {tgt_name}:\n\n{text}"}]
    }
    loop = asyncio.get_running_loop()
    def fetch():
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=json.dumps(payload).encode(),
            headers={
                "Content-Type": "application/json",
                "x-api-key": ANTHROPIC_KEY,
                "anthropic-version": "2023-06-01",
            },
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    data = await loop.run_in_executor(None, fetch)
    return data["content"][0]["text"].strip()

# ── LibreTranslate (ücretsiz, açık kaynak yedek) ─────────────
LIBRE_LANG = {
    "tr":"tr","en":"en","bg":"bg","es":"es","fr":"fr","it":"it",
    "ar":"ar","fa":"fa","he":"he","ur":"ur","ku":"ku"
}

async def libre_translate(text, src_lang, tgt_lang):
    sl = LIBRE_LANG.get(src_lang, "en")
    tl = LIBRE_LANG.get(tgt_lang, "en")
    # Birkaç ücretsiz LibreTranslate sunucusu
    servers = [
        "https://libretranslate.com/translate",
        "https://translate.argosopentech.com/translate",
        "https://libretranslate.de/translate",
    ]
    payload = json.dumps({
        "q": text, "source": sl, "target": tl,
        "format": "text", "api_key": ""
    }).encode()
    loop = asyncio.get_running_loop()
    for server in servers:
        try:
            def fetch(url=server):
                req = urllib.request.Request(url,
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST"
                )
                with urllib.request.urlopen(req, timeout=10) as r:
                    return json.loads(r.read())
            data = await loop.run_in_executor(None, fetch)
            result = data.get("translatedText", "").strip()
            if result:
                return result
        except Exception as e:
            print(f"LibreTranslate {server} hata: {e}", flush=True)
    raise Exception("LibreTranslate tüm sunucular başarısız")

async def translate(text, src_lang, src_name, tgt_lang, tgt_name):
    """Katmanlı çeviri: Google → LibreTranslate → Anthropic"""

    # 1. Google Translate (en hızlı)
    for attempt in range(2):
        try:
            result = await google_translate(text, src_lang, tgt_lang)
            if result:
                print(f"Google OK: {src_name}→{tgt_name}", flush=True)
                return result
        except Exception as e:
            print(f"Google hata ({attempt+1}): {e}", flush=True)
            if attempt == 0:
                await asyncio.sleep(0.5)

    # 2. LibreTranslate (yedek 1)
    print("LibreTranslate deneniyor...", flush=True)
    try:
        result = await libre_translate(text, src_lang, tgt_lang)
        if result:
            print(f"LibreTranslate OK", flush=True)
            return result
    except Exception as e:
        print(f"LibreTranslate hata: {e}", flush=True)

    # 3. Anthropic (yedek 2)
    if ANTHROPIC_KEY:
        print("Anthropic deneniyor...", flush=True)
        try:
            result = await anthropic_translate(text, src_name, tgt_name)
            print("Anthropic OK", flush=True)
            return result
        except Exception as e:
            print(f"Anthropic hata: {e}", flush=True)

    raise Exception("Tüm çeviri servisleri başarısız. Lütfen tekrar deneyin.")

# ── Google TTS ────────────────────────────────────────────────
GOOGLE_TTS_LANG = {
    "tr":"tr","en":"en","bg":"bg","es":"es","fr":"fr","it":"it",
    "ar":"ar","fa":"fa","he":"iw","ur":"ur","ku":"tr"
}

async def handle_tts(request):
    try:
        body  = await request.json()
        text  = body.get("text", "")[:300]
        lang  = body.get("lang", "en")
        tl    = GOOGLE_TTS_LANG.get(lang, "en")

        url = "https://translate.google.com/translate_tts?" + urllib.parse.urlencode({
            "ie": "UTF-8", "q": text, "tl": tl,
            "client": "tw-ob", "ttsspeed": "1"
        })
        loop = asyncio.get_running_loop()
        def fetch():
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15"
            })
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.read()
        audio = await loop.run_in_executor(None, fetch)
        return web.Response(body=audio, content_type="audio/mpeg",
                           headers={"Cache-Control": "no-cache"})
    except Exception as e:
        print(f"TTS hata: {e}", flush=True)
        return web.Response(status=500, text=str(e))

# ── HTTP ──────────────────────────────────────────────────────
async def handle_index(request):
    try:
        with open("tercuman.html", "rb") as f:
            return web.Response(body=f.read(), content_type="text/html", charset="utf-8")
    except FileNotFoundError:
        return web.Response(text="tercuman.html bulunamadi", status=404)

async def handle_static(request):
    filename = request.match_info.get('filename', '')
    try:
        with open(filename, "rb") as f:
            return web.Response(body=f.read(), content_type="text/html", charset="utf-8")
    except FileNotFoundError:
        return web.Response(text="Dosya bulunamadi", status=404)

async def handle_health(request):
    return web.json_response({"status": "ok", "rooms": len(rooms)})

# ── WebSocket ─────────────────────────────────────────────────
async def handle_ws(request):
    ws = web.WebSocketResponse(heartbeat=25)
    await ws.prepare(request)

    my_room  = None
    my_entry = None

    async def safe_send(target, obj):
        try:
            if not target.closed:
                await target.send_json(obj)
        except Exception as e:
            print(f"send err: {e}", flush=True)

    try:
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            try:
                data = json.loads(msg.data)
            except:
                continue

            action = data.get("action", "")

            if action == "create":
                code     = make_code()
                my_room  = code
                my_entry = {
                    "ws": ws,
                    "lang": data["lang"],
                    "lang_name": data["lang_name"]
                }
                rooms[code] = [my_entry]
                await safe_send(ws, {"action": "created", "code": code})
                print(f"[{code}] oda acildi: {data['lang_name']}", flush=True)

            elif action == "join":
                code = data.get("code", "").strip()
                if code not in rooms:
                    await safe_send(ws, {"action": "error", "msg": "Oda bulunamadı. Kodu kontrol edin."})
                    continue
                if len(rooms[code]) >= 2:
                    await safe_send(ws, {"action": "error", "msg": "Bu oda dolu."})
                    continue

                my_room  = code
                my_entry = {
                    "ws": ws,
                    "lang": data["lang"],
                    "lang_name": data["lang_name"]
                }
                rooms[code].append(my_entry)
                partner = next(u for u in rooms[code] if u["ws"] is not ws)
                print(f"[{code}] baglandi: {partner['lang_name']} <-> {data['lang_name']}", flush=True)

                await safe_send(ws, {
                    "action": "ready",
                    "my_lang": data["lang"],
                    "my_lang_name": data["lang_name"],
                    "partner_lang": partner["lang"],
                    "partner_lang_name": partner["lang_name"],
                    "room": code,
                })
                await safe_send(partner["ws"], {
                    "action": "ready",
                    "my_lang": partner["lang"],
                    "my_lang_name": partner["lang_name"],
                    "partner_lang": data["lang"],
                    "partner_lang_name": data["lang_name"],
                    "room": code,
                })

            elif action == "speak":
                if not my_room or my_room not in rooms:
                    await safe_send(ws, {"action": "error", "msg": "Oda bağlantısı yok."})
                    continue

                text     = data.get("text", "").strip()
                src_lang = data.get("src_lang", "tr")
                src_name = data.get("src_lang_name", "")
                if not text:
                    continue

                others = [u for u in rooms[my_room] if u["ws"] is not ws]
                if not others:
                    await safe_send(ws, {"action": "error", "msg": "Karşı taraf bağlı değil."})
                    continue

                partner  = others[0]
                tgt_lang = partner["lang"]
                tgt_name = partner["lang_name"]

                print(f"[{my_room}] {src_name}→{tgt_name}: {text[:40]}", flush=True)

                if src_lang == tgt_lang:
                    translated = text
                else:
                    try:
                        translated = await translate(text, src_lang, src_name, tgt_lang, tgt_name)
                    except Exception as e:
                        print(f"[{my_room}] HATA: {e}", flush=True)
                        await safe_send(ws, {"action": "error", "msg": f"Çeviri yapılamadı: {e}"})
                        continue

                await safe_send(ws, {
                    "action": "sent",
                    "original": text,
                    "translated": translated,
                    "tgt_lang_name": tgt_name,
                })
                await safe_send(partner["ws"], {
                    "action": "message",
                    "original": text,
                    "translated": translated,
                    "from_lang_name": src_name,
                    "tgt_lang": tgt_lang,
                })
                print(f"[{my_room}] gonderildi OK", flush=True)

    except Exception as e:
        print(f"WS hata: {e}", flush=True)
    finally:
        if my_room and my_room in rooms:
            rooms[my_room] = [u for u in rooms[my_room] if u["ws"] is not ws]
            if not rooms[my_room]:
                del rooms[my_room]
                print(f"[{my_room}] oda silindi", flush=True)
            else:
                for u in rooms[my_room]:
                    await safe_send(u["ws"], {"action": "partner_left"})
    return ws

app = web.Application()
app.router.add_get("/",              handle_index)
app.router.add_get("/tercuman.html", handle_index)
app.router.add_get("/{filename}",    handle_static)
app.router.add_get("/health",        handle_health)
app.router.add_post("/tts",          handle_tts)
app.router.add_get("/ws",            handle_ws)

if __name__ == "__main__":
    print(f"Port: {PORT}", flush=True)
    print(f"Anthropic (yedek): {'OK' if ANTHROPIC_KEY else 'yok'}", flush=True)
    print(f"Google Translate: hazir (API key gerektirmez)", flush=True)
    web.run_app(app, host="0.0.0.0", port=PORT, access_log=None)
