#!/usr/bin/env python3
import asyncio, json, os, random, string, urllib.request, urllib.error
from aiohttp import web, WSMsgType

PORT          = int(os.environ.get("PORT", 5050))
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_KEY", "")

# rooms: { "1234": [ {ws, lang, lang_name}, ... ] }
rooms = {}

def make_code():
    code = ''.join(random.choices(string.digits, k=4))
    return code if code not in rooms else make_code()

async def translate(text, src_name, tgt_name):
    payload = {
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 1000,
        "system": "Sen profesyonel bir çevirmensın. Verilen metni belirtilen dile çevir. Sadece çeviriyi yaz, açıklama ekleme.",
        "messages": [{"role":"user","content":f"{src_name} dilinden {tgt_name} diline çevir:\n\n{text}"}]
    }
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(payload).encode(),
        headers={"Content-Type":"application/json","x-api-key":ANTHROPIC_KEY,"anthropic-version":"2023-06-01"},
        method="POST"
    )
    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(None, lambda: json.loads(urllib.request.urlopen(req, timeout=30).read()))
    return data["content"][0]["text"].strip()

async def handle_index(request):
    try:
        with open("tercuman.html","rb") as f:
            return web.Response(body=f.read(), content_type="text/html", charset="utf-8")
    except FileNotFoundError:
        return web.Response(text="tercuman.html bulunamadi", status=404)

async def handle_health(request):
    return web.json_response({"status":"ok","rooms":len(rooms)})

async def handle_ws(request):
    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)

    room_code = None
    my_lang = None
    my_lang_name = None

    try:
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            try:
                data = json.loads(msg.data)
            except:
                continue

            action = data.get("action")

            if action == "create":
                room_code    = make_code()
                my_lang      = data["lang"]
                my_lang_name = data["lang_name"]
                rooms[room_code] = [{"ws":ws,"lang":my_lang,"lang_name":my_lang_name}]
                await ws.send_json({"action":"created","code":room_code})
                print(f"[{room_code}] Oda olusturuldu: {my_lang_name}", flush=True)

            elif action == "join":
                code = data.get("code","").strip()
                if code not in rooms:
                    await ws.send_json({"action":"error","msg":"Oda bulunamadı."})
                    continue
                if len(rooms[code]) >= 2:
                    await ws.send_json({"action":"error","msg":"Oda dolu."})
                    continue

                room_code    = code
                my_lang      = data["lang"]
                my_lang_name = data["lang_name"]
                rooms[code].append({"ws":ws,"lang":my_lang,"lang_name":my_lang_name})

                creator = rooms[code][0]
                joiner  = rooms[code][1]

                # İkisine de "ready" gönder
                await joiner["ws"].send_json({
                    "action":"ready",
                    "my_lang":joiner["lang"],
                    "my_lang_name":joiner["lang_name"],
                    "partner_lang":creator["lang"],
                    "partner_lang_name":creator["lang_name"],
                })
                await creator["ws"].send_json({
                    "action":"ready",
                    "my_lang":creator["lang"],
                    "my_lang_name":creator["lang_name"],
                    "partner_lang":joiner["lang"],
                    "partner_lang_name":joiner["lang_name"],
                })
                print(f"[{code}] Hazir: {creator['lang_name']} <-> {joiner['lang_name']}", flush=True)

            elif action == "speak":
                if not room_code or room_code not in rooms:
                    await ws.send_json({"action":"error","msg":"Oda bulunamadı."})
                    continue

                text     = data.get("text","").strip()
                src_name = data.get("src_lang_name","")
                if not text:
                    continue

                # Odadaki diğer kişiyi bul
                others = [u for u in rooms[room_code] if u["ws"] is not ws]
                if not others:
                    await ws.send_json({"action":"error","msg":"Karşı taraf bağlı değil."})
                    continue

                partner  = others[0]
                tgt_name = partner["lang_name"]

                print(f"[{room_code}] Çeviri: '{text[:30]}' {src_name} -> {tgt_name}", flush=True)

                try:
                    translated = await translate(text, src_name, tgt_name)
                except Exception as e:
                    await ws.send_json({"action":"error","msg":f"Çeviri hatası: {e}"})
                    continue

                # Konuşmacıya: ne söylediği + çevirisi
                await ws.send_json({
                    "action":"sent",
                    "original":text,
                    "translated":translated,
                    "tgt_lang_name":tgt_name,
                })

                # Karşı tarafa: çeviriyi gönder (seslendir)
                await partner["ws"].send_json({
                    "action":"message",
                    "original":text,
                    "translated":translated,
                    "from_lang_name":src_name,
                    "tgt_lang":partner["lang"],
                })
                print(f"[{room_code}] Gönderildi: '{translated[:30]}'", flush=True)

    except Exception as e:
        print(f"WS hata: {e}", flush=True)
    finally:
        if room_code and room_code in rooms:
            rooms[room_code] = [u for u in rooms[room_code] if u["ws"] is not ws]
            if not rooms[room_code]:
                del rooms[room_code]
                print(f"[{room_code}] Oda silindi", flush=True)
            else:
                for u in rooms[room_code]:
                    try:
                        await u["ws"].send_json({"action":"partner_left"})
                    except:
                        pass
    return ws

app = web.Application()
app.router.add_get("/",             handle_index)
app.router.add_get("/tercuman.html",handle_index)
app.router.add_get("/health",       handle_health)
app.router.add_get("/ws",           handle_ws)

if __name__ == "__main__":
    print(f"Port:{PORT} Anthropic:{'OK' if ANTHROPIC_KEY else 'EKSIK!'}", flush=True)
    web.run_app(app, host="0.0.0.0", port=PORT, access_log=None)
