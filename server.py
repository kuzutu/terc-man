#!/usr/bin/env python3
import asyncio, json, os, random, string, urllib.request, urllib.error, urllib.parse
from aiohttp import web, WSMsgType

PORT          = int(os.environ.get("PORT", 5050))
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_KEY", "")

rooms = {}

def make_code():
    for _ in range(100):
        code = ''.join(random.choices(string.digits, k=4))
        if code not in rooms:
            return code
    return ''.join(random.choices(string.digits, k=6))

async def translate(text, src_name, tgt_name):
    payload = {
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 1000,
        "system": "Sen profesyonel bir çevirmensın. Verilen metni belirtilen dile çevir. Sadece çeviriyi yaz, açıklama ekleme.",
        "messages": [{"role": "user", "content": f"{src_name} dilinden {tgt_name} diline çevir:\n\n{text}"}]
    }
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
    loop = asyncio.get_running_loop()
    def do_req():
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    data = await loop.run_in_executor(None, do_req)
    return data["content"][0]["text"].strip()

async def handle_index(request):
    try:
        with open("tercuman.html", "rb") as f:
            return web.Response(body=f.read(), content_type="text/html", charset="utf-8")
    except FileNotFoundError:
        return web.Response(text="tercuman.html bulunamadi", status=404)

async def handle_health(request):
    return web.json_response({"status": "ok"})

# Google Translate TTS proxy — ücretsiz, API key gerektirmez
async def handle_tts(request):
    try:
        body   = await request.json()
        text   = body.get("text", "")[:300]
        lang   = body.get("lang", "en")

        lang_map = {"tr":"tr","en":"en","bg":"bg","es":"es","fr":"fr","ar":"ar","fa":"fa","he":"iw","ur":"ur","ku":"tr"}
        tl = lang_map.get(lang, "en")

        url = "https://translate.google.com/translate_tts?" + urllib.parse.urlencode({
            "ie": "UTF-8",
            "q": text,
            "tl": tl,
            "client": "tw-ob",
            "ttsspeed": "1"
        })

        loop = asyncio.get_running_loop()
        def fetch():
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15"
            })
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.read()

        audio_data = await loop.run_in_executor(None, fetch)
        return web.Response(
            body=audio_data,
            content_type="audio/mpeg",
            headers={"Cache-Control": "no-cache"}
        )
    except Exception as e:
        print(f"TTS hata: {e}", flush=True)
        return web.Response(status=500, text=str(e))

async def handle_ws(request):
    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)

    my_room  = None
    my_entry = None

    async def safe_send(target_ws, obj):
        try:
            if not target_ws.closed:
                await target_ws.send_json(obj)
        except Exception as e:
            print(f"send error: {e}", flush=True)

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
                my_entry = {"ws": ws, "lang": data["lang"], "lang_name": data["lang_name"]}
                rooms[code] = [my_entry]
                await safe_send(ws, {"action": "created", "code": code})
                print(f"[{code}] olusturuldu: {data['lang_name']}", flush=True)

            elif action == "join":
                code = data.get("code", "").strip()
                if code not in rooms:
                    await safe_send(ws, {"action": "error", "msg": "Oda bulunamadı."})
                    continue
                if len(rooms[code]) >= 2:
                    await safe_send(ws, {"action": "error", "msg": "Bu oda dolu."})
                    continue

                my_room  = code
                my_entry = {"ws": ws, "lang": data["lang"], "lang_name": data["lang_name"]}
                rooms[code].append(my_entry)

                partner = next(u for u in rooms[code] if u["ws"] is not ws)
                print(f"[{code}] {partner['lang_name']} <-> {data['lang_name']}", flush=True)

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
                src_name = data.get("src_lang_name", "")
                if not text:
                    continue

                others = [u for u in rooms[my_room] if u["ws"] is not ws]
                if not others:
                    await safe_send(ws, {"action": "error", "msg": "Karşı taraf bağlı değil."})
                    continue

                partner  = others[0]
                tgt_name = partner["lang_name"]

                if src_name == tgt_name:
                    translated = text
                else:
                    try:
                        translated = await translate(text, src_name, tgt_name)
                    except Exception as e:
                        await safe_send(ws, {"action": "error", "msg": f"Çeviri hatası: {e}"})
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
                    "tgt_lang": partner["lang"],
                })
                print(f"[{my_room}] {src_name}→{tgt_name}: {text[:40]}", flush=True)

    except Exception as e:
        print(f"WS genel hata: {e}", flush=True)
    finally:
        if my_room and my_room in rooms:
            rooms[my_room] = [u for u in rooms[my_room] if u["ws"] is not ws]
            if not rooms[my_room]:
                del rooms[my_room]
            else:
                for u in rooms[my_room]:
                    await safe_send(u["ws"], {"action": "partner_left"})

    return ws

app = web.Application()
app.router.add_get("/",              handle_index)
app.router.add_get("/tercuman.html", handle_index)
app.router.add_get("/health",        handle_health)
app.router.add_post("/tts",          handle_tts)
app.router.add_get("/ws",            handle_ws)

if __name__ == "__main__":
    print(f"Port: {PORT} | Anthropic: {'OK' if ANTHROPIC_KEY else 'EKSIK!'}", flush=True)
    web.run_app(app, host="0.0.0.0", port=PORT, access_log=None)
