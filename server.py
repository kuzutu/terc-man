#!/usr/bin/env python3
"""
Simultane Tercüman — WebSocket Sunucusu
Her oda 2 kişilik. A konuşur → B'nin diline çevrilir → B duyar. Ve tersi.
"""
import asyncio, json, os, random, string, urllib.request, urllib.error
from aiohttp import web, WSMsgType

PORT          = int(os.environ.get("PORT", 5050))
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_KEY", "")

# rooms: { "1234": [ {ws, lang, lang_name}, ... ] }
rooms = {}

def make_code():
    return ''.join(random.choices(string.digits, k=4))

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
    loop = asyncio.get_event_loop()
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

async def handle_ws(request):
    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)

    room_code = None
    user_info = None

    try:
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            try:
                data = json.loads(msg.data)
            except:
                continue

            action = data.get("action")

            # ── Oda oluştur ──────────────────────────────────────
            if action == "create":
                code = make_code()
                while code in rooms:
                    code = make_code()
                rooms[code] = []
                room_code = code
                user_info = {"ws": ws, "lang": data["lang"], "lang_name": data["lang_name"]}
                rooms[code].append(user_info)
                await ws.send_json({"action": "created", "code": code})
                print(f"Oda olusturuldu: {code} ({data['lang_name']})", flush=True)

            # ── Odaya katıl ───────────────────────────────────────
            elif action == "join":
                code = data.get("code", "").strip()
                if code not in rooms:
                    await ws.send_json({"action": "error", "msg": "Oda bulunamadı. Kodu kontrol edin."})
                    continue
                if len(rooms[code]) >= 2:
                    await ws.send_json({"action": "error", "msg": "Bu oda dolu."})
                    continue
                room_code = code
                user_info = {"ws": ws, "lang": data["lang"], "lang_name": data["lang_name"]}
                rooms[code].append(user_info)

                # Her iki kullanıcıya da "hazır" bildir
                partner = next(u for u in rooms[code] if u["ws"] != ws)
                await ws.send_json({
                    "action": "ready",
                    "partner_lang": partner["lang"],
                    "partner_lang_name": partner["lang_name"],
                    "my_lang": data["lang"],
                })
                await partner["ws"].send_json({
                    "action": "ready",
                    "partner_lang": data["lang"],
                    "partner_lang_name": data["lang_name"],
                    "my_lang": partner["lang"],
                })
                print(f"Oda hazir: {code} ({partner['lang_name']} ↔ {data['lang_name']})", flush=True)

            # ── Konuşma metni gönder ──────────────────────────────
            elif action == "speak":
                if not room_code or room_code not in rooms:
                    continue
                text     = data.get("text", "").strip()
                src_name = data.get("src_lang_name", "")
                if not text:
                    continue

                # Odadaki diğer kullanıcıyı bul
                others = [u for u in rooms[room_code] if u["ws"] != ws]
                if not others:
                    await ws.send_json({"action": "error", "msg": "Karşı taraf henüz bağlı değil."})
                    continue

                partner = others[0]
                tgt_name = partner["lang_name"]

                # Aynı dil ise çevirme
                if src_name == tgt_name:
                    translated = text
                else:
                    try:
                        translated = await translate(text, src_name, tgt_name)
                    except Exception as e:
                        await ws.send_json({"action": "error", "msg": f"Çeviri hatası: {e}"})
                        continue

                # Konuşmacıya orijinali göster
                await ws.send_json({
                    "action": "sent",
                    "original": text,
                    "translated": translated,
                    "tgt_lang_name": tgt_name,
                })

                # Karşı tarafa çeviriyi gönder (seslendir)
                await partner["ws"].send_json({
                    "action": "message",
                    "original": text,
                    "translated": translated,
                    "from_lang_name": src_name,
                    "tgt_lang": partner["lang"],
                })
                print(f"[{room_code}] {src_name}→{tgt_name}: {text[:40]}", flush=True)

    except Exception as e:
        print(f"WS hata: {e}", flush=True)
    finally:
        # Temizlik
        if room_code and room_code in rooms:
            rooms[room_code] = [u for u in rooms[room_code] if u["ws"] != ws]
            if not rooms[room_code]:
                del rooms[room_code]
                print(f"Oda silindi: {room_code}", flush=True)
            else:
                # Kalan kullanıcıya bildir
                for u in rooms[room_code]:
                    try:
                        await u["ws"].send_json({"action": "partner_left"})
                    except:
                        pass

    return ws

app = web.Application()
app.router.add_get("/",          handle_index)
app.router.add_get("/tercuman.html", handle_index)
app.router.add_get("/health",    handle_health)
app.router.add_get("/ws",        handle_ws)

if __name__ == "__main__":
    print(f"Port: {PORT}", flush=True)
    print(f"Anthropic: {'OK' if ANTHROPIC_KEY else 'EKSIK!'}", flush=True)
    web.run_app(app, host="0.0.0.0", port=PORT, access_log=None)
