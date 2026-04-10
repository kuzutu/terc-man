#!/usr/bin/env python3
import http.server, json, urllib.request, urllib.error, os, sys

PORT          = int(os.environ.get("PORT", 5050))
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_KEY", "")
OPENAI_KEY    = os.environ.get("OPENAI_KEY", "")

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, f, *a): pass
    def send_cors(self):
        self.send_header("Access-Control-Allow-Origin","*")
        self.send_header("Access-Control-Allow-Methods","GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers","Content-Type")
    def do_OPTIONS(self):
        self.send_response(204); self.send_cors(); self.end_headers()
    def do_GET(self):
        if self.path in ("/","/tercuman.html"):
            try:
                with open("tercuman.html","rb") as f: content=f.read()
                self.send_response(200)
                self.send_header("Content-Type","text/html; charset=utf-8")
                self.send_cors(); self.end_headers(); self.wfile.write(content)
            except: self.send_response(404); self.end_headers()
        elif self.path=="/health":
            self.send_response(200); self.send_header("Content-Type","application/json")
            self.send_cors(); self.end_headers(); self.wfile.write(b'{"status":"ok"}')
        else: self.send_response(404); self.end_headers()
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length",0)))
        try: payload=json.loads(body)
        except: self.send_response(400); self.end_headers(); return
        if self.path=="/translate": self._translate(payload)
        elif self.path=="/speak": self._speak(payload)
        else: self.send_response(404); self.end_headers()
    def _translate(self, payload):
        if not ANTHROPIC_KEY: self._err(401,"ANTHROPIC_KEY eksik"); return
        payload.pop("api_key",None)
        req=urllib.request.Request("https://api.anthropic.com/v1/messages",
            data=json.dumps(payload).encode(),
            headers={"Content-Type":"application/json","x-api-key":ANTHROPIC_KEY,"anthropic-version":"2023-06-01"},
            method="POST")
        self._proxy(req,"application/json")
    def _speak(self, payload):
        if not OPENAI_KEY: self._err(401,"OPENAI_KEY eksik"); return
        payload.pop("openai_key",None)
        tts={"model":"tts-1","input":payload.get("text",""),"voice":payload.get("voice","nova"),"speed":payload.get("speed",1.0),"response_format":"mp3"}
        req=urllib.request.Request("https://api.openai.com/v1/audio/speech",
            data=json.dumps(tts).encode(),
            headers={"Content-Type":"application/json","Authorization":f"Bearer {OPENAI_KEY}"},
            method="POST")
        self._proxy(req,"audio/mpeg")
    def _proxy(self, req, ct):
        try:
            with urllib.request.urlopen(req,timeout=30) as r: data=r.read()
            self.send_response(200); self.send_header("Content-Type",ct)
            self.send_cors(); self.end_headers(); self.wfile.write(data)
        except urllib.error.HTTPError as e:
            body=e.read(); self.send_response(e.code)
            self.send_header("Content-Type","application/json")
            self.send_cors(); self.end_headers(); self.wfile.write(body)
        except Exception as e: self._err(500,str(e))
    def _err(self, code, msg):
        self.send_response(code); self.send_header("Content-Type","application/json")
        self.send_cors(); self.end_headers()
        self.wfile.write(json.dumps({"error":msg}).encode())

if __name__=="__main__":
    print(f"Port: {PORT} | Anthropic: {'OK' if ANTHROPIC_KEY else 'EKSIK'} | OpenAI: {'OK' if OPENAI_KEY else 'EKSIK'}",flush=True)
    http.server.HTTPServer(("0.0.0.0",PORT),Handler).serve_forever()
