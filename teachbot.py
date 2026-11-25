#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
教学bot 单文件服务器（纯标准库，无任何第三方依赖）
功能：
  1) 静态托管：首页 / 学生作答页 / 教师面板 / AI助教 / 12学科网站 / 传统练习系统
  2) API：题组发布、学生提交判分、实时学情报表、AI 出题、AI 助教聊天
运行：python3 teachbot.py   （需同目录 config.json：api_base / api_key / model / port）
"""
import json, os, re, time, uuid, urllib.request, urllib.error
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, unquote
from datetime import datetime
import threading

BASE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(BASE, "web")
DATA = os.path.join(BASE, "data")
os.makedirs(DATA, exist_ok=True)

CFG = json.load(open(os.path.join(BASE, "config.json"), encoding="utf-8"))
PORT = int(CFG.get("port", 8377))
SESSIONS_F = os.path.join(DATA, "sessions.json")
SUBS_F = os.path.join(DATA, "submissions.json")
LOCK = threading.Lock()


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return default


def save_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def sessions():
    return load_json(SESSIONS_F, {})


def submissions():
    return load_json(SUBS_F, [])


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def call_llm(messages, temperature=0.7, max_tokens=2000):
    url = CFG.get("api_base", "https://api.agnes-ai.cn/v1").rstrip("/") + "/chat/completions"
    req = urllib.request.Request(
        url,
        data=json.dumps({
            "model": CFG.get("model", "agnes-3.0-flash"),
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }).encode(),
        headers={"Authorization": "Bearer " + CFG.get("api_key", ""), "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        d = json.loads(r.read())
    return d["choices"][0]["message"]["content"]


# ---------------- 题目清洗 ----------------

def sanitize_questions(raw):
    """把 AI 返回的 JSON 文本清洗成标准题目数组；失败返回 None"""
    txt = raw.strip()
    m = re.search(r"```(?:json)?\s*(.+?)```", txt, re.S)
    if m:
        txt = m.group(1)
    m = re.search(r"(\[.*\]|\{.*\})", txt, re.S)
    if m:
        txt = m.group(1)
    try:
        data = json.loads(txt)
    except Exception:
        return None
    if isinstance(data, dict):
        for k in ("questions", "data", "list", "result"):
            if isinstance(data.get(k), list):
                data = data[k]
                break
    out = []
    for q in data if isinstance(data, list) else []:
        if not isinstance(q, dict) or not str(q.get("q", "")).strip():
            continue
        opts = [str(q.get("options", ["", "", "", ""]))[i:i + 4] for i in range(0, 4, 4)] if isinstance(q.get("options"), str) else list(q.get("options", ["", "", "", ""]))
        opts = [str(o).strip() for o in opts[:4]]
        while len(opts) < 4:
            opts.append("")
        ans = q.get("answer", q.get("a", 0))
        if isinstance(ans, str):
            ans = "ABCD".find(ans.strip().upper())
            if ans < 0:
                ans = 0
        ans = int(ans) % 4
        out.append({
            "q": str(q["q"]).strip(),
            "options": opts,
            "answer": ans,
            "explain": str(q.get("explain", q.get("analysis", ""))).strip(),
        })
    return out or None


# ---------------- HTTP Handler ----------------

class Handler(BaseHTTPRequestHandler):
    server_version = "TeachBot/1.0"

    def log_message(self, *a):  # 静默访问日志（保留错误打印）
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _err(self, msg, code=400):
        self._json({"error": msg}, code)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        try:
            return json.loads(raw.decode() or "{}")
        except Exception:
            return None

    def _static(self, path):
        # 路由映射（路径不带 query）
        p = unquote(path).split("?")[0].strip("/")
        if p in ("", "index"):
            p = "index.html"
        elif p in ("quiz", "report", "tutor"):
            p = p + ".html"
        f = os.path.normpath(os.path.join(WEB, p))
        if not f.startswith(WEB + os.sep) or not os.path.isfile(f):
            self._err("404", 404)
            return
        data = open(f, "rb").read()
        ct = "text/html; charset=utf-8" if f.endswith(".html") else \
             "text/css" if f.endswith(".css") else \
             "application/javascript" if f.endswith(".js") else "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        path = u.path
        if path.startswith("/api/"):
            return self.api_get(path)
        return self._static(path)

    def do_POST(self):
        u = urlparse(self.path)
        if u.path.startswith("/api/"):
            return self.api_post(u.path)
        self._err("方法不允许", 405)

    # ---------- API ----------

    def api_get(self, path):
        if path == "/api/health":
            return self._json({"ok": True, "ts": now()})
        m = re.match(r"^/api/session/([\w-]+)$", path)
        if m:
            code = m.group(1)
            with LOCK:
                s = sessions().get(code)
            if not s:
                return self._err("题组不存在", 404)
            # 学生端：不带答案和解析
            qs = [{"q": q["q"], "options": q["options"]} for q in s["questions"]]
            return self._json({"code": code, "meta": {k: s.get(k) for k in ("subject", "grade", "topic")}, "questions": qs, "n": len(qs)})
        m = re.match(r"^/api/report/([\w-]+)$", path)
        if m:
            code = m.group(1)
            with LOCK:
                s = sessions().get(code)
                subs = [x for x in submissions() if x.get("code") == code]
            if not s:
                return self._err("题组不存在", 404)
            nq = len(s["questions"])
            pq = []
            for i, q in enumerate(s["questions"]):
                hit = 0
                for x in subs:
                    a = x.get("answers", [])
                    if i < len(a) and a[i] == q["answer"]:
                        hit += 1
                pq.append({"i": i, "q": q["q"][:60], "answer": q["answer"], "n_correct": hit, "rate": round(hit / len(subs) * 100, 1) if subs else None, "n_sub": len(subs)})
            ranking = sorted(
                [{"name": x["name"], "score": x["score"], "total": x["total"], "ts": x["ts"], "answers": x.get("answers", [])} for x in subs],
                key=lambda r: (-r["score"], r["ts"]))
            return self._json({"code": code, "meta": {k: s.get(k) for k in ("subject", "grade", "topic", "created")}, "questions": s["questions"],
                               "subs": len(subs), "pq": pq, "ranking": ranking})
        if path == "/api/sessions":
            with LOCK:
                ss = list(sessions().values())
            return self._json([{"code": s["code"], "subject": s.get("subject"), "grade": s.get("grade"), "topic": s.get("topic"),
                                 "n": len(s["questions"]), "created": s.get("created"), "subs": sum(1 for x in submissions() if x.get("code") == s["code"])} for s in ss])
        self._err("未知接口", 404)

    def api_post(self, path):
        if path == "/api/session":
            b = self._body()
            if not b:
                return self._err("需要 JSON")
            qs = sanitize_questions(json.dumps(b.get("questions"), ensure_ascii=False)) if not isinstance(b.get("questions"), list) else None
            if qs is None and isinstance(b.get("questions"), list):
                qs = sanitize_questions(json.dumps(b["questions"], ensure_ascii=False))
            if not qs:
                return self._err("题目格式不对（需 q/options/answer）")
            code = str(b.get("code") or uuid.uuid4().hex[:6]).upper()[:8]
            with LOCK:
                ss = sessions()
                ss[code] = {"code": code, "subject": b.get("subject", ""), "grade": b.get("grade", ""), "topic": b.get("topic", ""),
                             "questions": qs, "created": now()}
                save_json(SESSIONS_F, ss)
            return self._json({"code": code, "n": len(qs)})
        if path == "/api/submit":
            b = self._body()
            if not b or not b.get("code") or not b.get("name"):
                return self._err("需要 code 和 name")
            with LOCK:
                s = sessions().get(str(b["code"]).upper()[:8])
            if not s:
                return self._err("题组不存在", 404)
            answers = [int(a) if str(a).strip() in "01234" or str(a).isdigit() else "ABCD".find(str(a).strip().upper()) for a in b.get("answers", [])]
            answers = [a if 0 <= a < 4 else -1 for a in answers]
            while len(answers) < len(s["questions"]):
                answers.append(-1)
            score = sum(1 for a, q in zip(answers, s["questions"]) if a == q["answer"])
            rec = {"code": s["code"], "name": str(b["name"]).strip()[:20], "answers": answers,
                   "score": score, "total": len(s["questions"]), "ts": now()}
            with LOCK:
                subs = submissions()
                subs.append(rec)
                save_json(SUBS_F, subs)
                n_sub = sum(1 for x in subs if x.get("code") == s["code"])
            details = []
            for i, (a, q) in enumerate(zip(answers, s["questions"])):
                ok = a == q["answer"]
                details.append({"i": i, "q": q["q"], "your": a, "correct": q["answer"], "ok": ok, "explain": q["explain"],
                                "options": q["options"]})
            return self._json({"score": score, "total": rec["total"], "rank": n_sub, "details": details})
        if path == "/api/ai/gen":
            b = self._body() or {}
            subject = str(b.get("subject", "信息科技"))
            grade = str(b.get("grade", "初中"))
            topic = str(b.get("topic", "通用知识"))
            n = max(1, min(int(b.get("n", 10)), 20))
            prompt = (f"请出 {n} 道单项选择题。学科：{subject}；年级：{grade}；知识点范围：{topic}。"
                      f"要求：选项互斥、有且只有一个正确答案、贴近教学实际、难度适中。"
                      f"只输出 JSON 数组，不要输出任何其他文字。每个元素格式："
                      '{"q":"题干","options":["A内容","B内容","C内容","D内容"],"answer":0,"explain":"解析"}，其中 answer 为正确选项下标(0=A,1=B,2=C,3=D)')
            try:
                raw = call_llm([{"role": "system", "content": "你是一名资深中学教研员，擅长出选择题。只输出合法 JSON。"},
                                 {"role": "user", "content": prompt}], temperature=0.8, max_tokens=3500)
            except urllib.error.HTTPError as e:
                return self._err(f"AI 接口 {e.code}：{e}", 502)
            except Exception as e:
                return self._err(f"AI 接口失败：{e}", 502)
            qs = sanitize_questions(raw)
            if qs is None:
                return self._err("AI 返回内容解析失败，请重试", 502)
            return self._json({"subject": subject, "grade": grade, "topic": topic, "questions": qs})
        if path == "/api/ai/chat":
            b = self._body() or {}
            subject = str(b.get("subject", "信息科技"))
            grade = str(b.get("grade", "初中"))
            msgs = b.get("messages") or []
            if not msgs:
                return self._err("需要 messages")
            sysp = (f"你是「{subject}」AI 助教，服务{grade}学生。要求：回答准确、分步讲解、语言亲切鼓励；"
                    f"出题时给出题目和答案解析；批改时先判对错再讲原因；回答控制在 400 字以内，除非学生要求详细。"
                    f"不回答与学习无关的问题。")
            history = [{"role": m.get("role", "user"), "content": str(m.get("content", ""))[:2000]} for m in msgs[-12:]]
            try:
                reply = call_llm([{"role": "system", "content": sysp}] + history, temperature=0.6, max_tokens=1200)
            except urllib.error.HTTPError as e:
                return self._err(f"AI 接口 {e.code}：{e}", 502)
            except Exception as e:
                return self._err(f"AI 接口失败：{e}", 502)
            return self._json({"reply": reply})
        self._err("未知接口", 404)


def main():
    print("=" * 50)
    print("教学bot 服务器启动  端口", PORT)
    print("  AI key:", "已配置" if CFG.get("api_key") else "未配置（AI出题/AI助教不可用；建 key.txt 后重跑 run.sh 启用）")
    print("  首页:    http://<本机局域网IP>:%d/" % PORT)
    print("  学生作答: .../quiz/    教师面板: .../report/    AI助教: .../tutor/")
    print("=" * 50)
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    srv.serve_forever()


if __name__ == "__main__":
    main()
