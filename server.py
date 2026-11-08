# -*- coding: utf-8 -*-
"""学习通答题桥接服务（DSH 侧）

对脚本猫脚本提供的接口：
  GET  /ping                 -> 存活检查
  GET  /cx-agent.user.js     -> 直接安装脚本（拖不进浏览器时用这个 URL）
  GET  /answers              -> 取答案（按题目指纹校验，重复提取不会作废）
  GET  /agent-status         -> 做题会话状态（结构化 JSON，不带原始日志）
  GET  /logs                 -> 做题日志纯文本（排查用）
  POST /extract              -> 登记题目；题目指纹没变时直接复用已有答案
  POST /agent-solve          -> 起一个全新 DSH 会话去做题
  POST /report               -> 存页面结构快照（选择器校准用）
  POST /solve                -> 旧接口；默认走 agent，直连模型需 CXD_ALLOW_DIRECT=1

启动： python server.py        （数据目录默认本目录，可用 CXD_DATA_DIR 覆盖）
"""
import hashlib
import io
import json
import os
import re
import shutil
import ssl
import subprocess
import threading
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("CX_PORT", "8790"))
HERE = os.path.dirname(os.path.abspath(__file__))
USERSCRIPT = os.path.join(HERE, "cx-agent.user.js")
CRED = os.path.join(os.path.expanduser("~"), ".dsh", ".credentials.yaml")

MODEL = os.environ.get("CX_MODEL", "deepseek-flash")
MAX_WORKERS = 3

# 数据目录：测试用 CXD_DATA_DIR 指到临时目录，永远不碰线上数据
DATA_DIR = os.environ.get("CXD_DATA_DIR") or HERE
PENDING = os.path.join(DATA_DIR, "pending.json")
ANSWERS = os.path.join(DATA_DIR, "answers.json")
ANSWERS_PREV = os.path.join(DATA_DIR, "answers.prev.json")
REPORT = os.path.join(DATA_DIR, "last-report.json")
AGENT_LOG = os.path.join(DATA_DIR, "agent-solve.log")
AGENT_STATE = os.path.join(DATA_DIR, "agent-state.json")

# 谁来做题：
#   agent  = 默认。不调任何外部 API，把题目写进 pending.json，起一个全新 DSH 会话去做题。
#   direct = 旧行为，服务端直接打 DEEPSEEK_API_KEY（需 CXD_ALLOW_DIRECT=1 才可用）。
ENGINE = os.environ.get("CX_ENGINE", "agent")

# ---- 新会话做题（dsh headless）----
# dsh 可执行文件：默认从 PATH 找；没装全局命令时用 CX_DSH_CMD 指定绝对路径
DSH_CMD = os.environ.get("CX_DSH_CMD") or shutil.which("dsh") or "dsh"
DSH_HOME = os.environ.get("CX_DSH_HOME", os.path.join(os.path.expanduser("~"), ".dsh"))
DSH_PROFILE = os.environ.get("CX_DSH_PROFILE", "headless")
DSH_CWD = os.environ.get("CX_DSH_CWD") or os.path.join(HERE, ".work")

os.makedirs(DSH_CWD, exist_ok=True)

SOLVER_PROMPT = """你是做题助手。cx-bridge 里有一份待答题目，请按下面步骤做，不要问我任何问题：
1. 先调用 cx_status，看已经有多少条答案；再调用 cx_take_questions 取题（题目、选项、图片）。
2. 逐题作答：图片题看清图；计算题给出正确结果；不要输出长篇解释。已经有答案的题跳过。
3. 分批提交：每批最多 8 题，调用 cx_submit_answers 提交一批，直到把缺的题全部提交完。
   格式 answers = {"<题目id>": {"answer": ["答案"], "reason": "一句话依据"}}。
   这个工具是合并写入，不会覆盖之前批次；但每批别超过 8 题（太大客户端会把参数串化）。
4. 绝对不要自己直接写 answers.json 或其它文件，只用 cx_submit_answers。
5. 全部提交完只回复一句「已提交 N 题」。不要调用 cx_report，不要提交作业。
"""


# ---------------------------------------------------------------- 文件读写

def _load(path):
    try:
        with io.open(path, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _dump(path, data):
    tmp = path + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False, indent=1))
    os.replace(tmp, path)


def fingerprint(questions):
    """题目集合的指纹：只跟 id 有关，重复提取同一批题指纹不变。"""
    ids = sorted(str(q.get("id") or "") for q in questions if q.get("id") is not None)
    raw = ("|".join(ids)).encode("utf-8")
    return "fp-" + hashlib.sha1(raw).hexdigest()[:16]


def _answers_complete(ans, pend):
    answers = ans.get("answers") or {}
    qs = pend.get("questions") or []
    if not qs or not answers:
        return False
    return all(str(q.get("id")) in answers for q in qs)


# ---------------------------------------------------------------- 做题会话

def _pid_alive(pid):
    if not pid:
        return False
    if os.name != "nt":
        try:
            os.kill(int(pid), 0)
            return True
        except OSError:
            return False
    import ctypes
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    k32 = ctypes.windll.kernel32
    handle = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        if not k32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == STILL_ACTIVE
    finally:
        k32.CloseHandle(handle)


def _agent_state():
    st = _load(AGENT_STATE)
    pid = st.get("pid")
    st["running"] = bool(pid) and _pid_alive(pid)
    if not st["running"] and st.get("finished") is None and st.get("started"):
        st["finished"] = time.time()
        try:
            _dump(AGENT_STATE, st)
        except Exception:
            pass
    return st


def _log_tail(n=3, width=240):
    try:
        with io.open(AGENT_LOG, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()[-n:]
    except FileNotFoundError:
        return []
    out = []
    for line in lines:
        line = "".join(c for c in line if c in "\n\t" or ord(c) >= 32)
        out.append(line.strip()[:width])
    return out


def agent_status():
    """只返回结构化状态；原始日志走 /logs，避免 JSON 被日志内容弄坏。"""
    st = _agent_state()
    pend = _load(PENDING)
    ans = _load(ANSWERS)
    return {
        "running": st.get("running", False),
        "pid": st.get("pid"),
        "exit": (0 if st.get("finished") else None) if not st.get("running") else None,
        "task_id": pend.get("task_id"),
        "fingerprint": pend.get("fingerprint"),
        "count": len(pend.get("questions") or []),
        "answered": len(ans.get("answers") or {}),
        "log_file": os.path.basename(AGENT_LOG),
        "log_tail": _log_tail(),
    }


def _missing_ids():
    """还缺哪些题（没有 ok 答案的）。"""
    pend = _load(PENDING)
    ans = _load(ANSWERS)
    have = {k for k, v in (ans.get("answers") or {}).items() if v and v.get("ok")}
    return [str(q.get("id")) for q in (pend.get("questions") or []) if str(q.get("id")) not in have]


def _watch(proc, task_id, attempt):
    """这一轮做题会话退出后：还缺题就再起一轮，最多 3 轮。"""
    try:
        proc.wait()
    except Exception:
        pass
    miss = _missing_ids()
    st = _load(AGENT_STATE)
    st.update({"finished": time.time(), "running": False, "attempt": attempt, "missing": len(miss)})
    _dump(AGENT_STATE, st)
    with io.open(AGENT_LOG, "a", encoding="utf-8") as f:
        f.write("--- 第 %d 轮结束，缺 %d 题 ---%s" % (attempt, len(miss), chr(10)))
    if not miss or attempt >= 3:
        return
    if _load(PENDING).get("task_id") != task_id:
        return
    start_agent(attempt=attempt + 1)


def start_agent(attempt=1):
    st = _agent_state()
    if st.get("running"):
        return {"ok": True, "running": True, "pid": st.get("pid"),
                "hint": "上一轮还在做题（pid=%s）" % st.get("pid")}
    pend = _load(PENDING)
    task_id = pend.get("task_id")
    count = len(pend.get("questions") or [])
    if not task_id:
        return {"ok": False, "error": "还没有题目，先点「提取」"}
    miss = _missing_ids()
    if not miss:
        return {"ok": True, "running": False, "task_id": task_id, "count": count,
                "answered": count, "hint": "题目都答完了，不用再做"}
    env = dict(os.environ)
    env["DSH_HOME"] = DSH_HOME
    env.setdefault("PYTHONIOENCODING", "utf-8")
    flags = 0
    for name in ("DETACHED_PROCESS", "CREATE_NEW_PROCESS_GROUP", "CREATE_NO_WINDOW"):
        flags |= getattr(subprocess, name, 0)
    with io.open(AGENT_LOG, "a", encoding="utf-8") as f:
        f.write("=== %s task=%s count=%d miss=%d attempt=%d ===%s"
                % (time.strftime("%Y-%m-%d %H:%M:%S"), task_id, count, len(miss), attempt, chr(10)))
        f.flush()
        proc = subprocess.Popen(
            ["cmd", "/c", DSH_CMD, "--profile", DSH_PROFILE, SOLVER_PROMPT],
            cwd=DSH_CWD, env=env, stdout=f, stderr=subprocess.STDOUT,
            creationflags=flags, close_fds=True,
        )
    _dump(AGENT_STATE, {"pid": proc.pid, "task_id": task_id, "attempt": attempt,
                        "started": time.time(), "finished": None, "running": True})
    threading.Thread(target=_watch, args=(proc, task_id, attempt), daemon=True).start()
    return {"ok": True, "running": True, "task_id": task_id, "count": count,
            "missing": len(miss), "attempt": attempt, "pid": proc.pid,
            "hint": "新会话已启动（%s 思考 low），缺 %d 题，做完分批写入" % (DSH_PROFILE, len(miss))}


# ---------------------------------------------------------------- 登记 / 取答案

def enqueue(questions):
    """登记题目。同一批题（id 集合相同）重复登记时：不换 task、不清答案。"""
    fp = fingerprint(questions)
    pend = _load(PENDING)
    ans = _load(ANSWERS)
    same = bool(pend.get("questions")) and pend.get("fingerprint") == fp
    ans_same = (ans.get("fingerprint") == fp) or (
        ans.get("task_id") and ans.get("task_id") == pend.get("task_id"))
    if same and ans_same and (ans.get("answers") or {}):
        n = len(ans.get("answers") or {})
        ready = _answers_complete(ans, pend)
        return {"ok": True, "reused": True, "ready": ready,
                "task_id": pend.get("task_id"), "fingerprint": fp,
                "count": len(questions), "answered": n,
                "hint": "题目没变，复用已有 %d 条答案（不重新做题、不清空）" % n}

    # 时间戳只到秒，同一秒换题会撞车；拼上指纹尾号保证唯一、也方便肉眼对账
    task_id = "%s-%s" % (time.strftime("%Y%m%d-%H%M%S"), fp[3:7])
    if ans:
        # 题目变了：旧答案留档，不直接丢
        try:
            _dump(ANSWERS_PREV, ans)
            os.remove(ANSWERS)
        except Exception:
            pass
    payload = {"task_id": task_id, "fingerprint": fp, "created": time.time(),
               "count": len(questions), "questions": questions}
    _dump(PENDING, payload)
    return {"ok": True, "reused": False, "task_id": task_id, "fingerprint": fp,
            "count": len(questions),
            "hint": "题目已交到 DSH 这边，点「开始做题」就会起新会话"}


def read_answers():
    ans = _load(ANSWERS)
    if not ans.get("answers"):
        return {"ready": False, "reason": "还没有答案"}
    pend = _load(PENDING)
    fp_pend = pend.get("fingerprint")
    fp_ans = ans.get("fingerprint")
    if fp_pend and fp_ans and fp_ans != fp_pend:
        return {"ready": False, "reason": "答案属于上一轮题目（指纹不一致）",
                "fingerprint": fp_pend}
    if not fp_ans and pend.get("task_id") and ans.get("task_id") != pend.get("task_id"):
        return {"ready": False, "reason": "答案属于上一轮题目"}
    ans = dict(ans)
    ans["ready"] = True
    ans["count"] = len(ans.get("answers") or {})
    return ans


# ---------------------------------------------------------------- 直连引擎（默认关闭）

SYSTEM_PROMPT = """你是一个做题引擎。用户会给你一道题（可能是单选题、多选题、填空题、判断题），
题干里可能出现图片。请给出正确答案。

只输出一个严格 JSON 对象，不要 Markdown 代码块，不要解释：
{"answer": ["A"], "reason": "简短中文解析"}

规则：
- 单选题/判断题：answer 里只放一个选项字母，例如 ["B"]；判断题用 ["A"] 表示正确、["B"] 表示错误（以题目选项字母为准）。
- 多选题：answer 里放所有正确选项字母，例如 ["A","C"]。
- 填空题：answer 里按空的顺序放答案文本，例如 ["H2O"]；多个空就多个元素。
- 只使用题干给出的选项字母，不要自创。
- 不确定也要给出最可能的答案，不要返回空数组。
"""


def load_api_key():
    key = os.environ.get("DEEPSEEK_API_KEY")
    if key:
        return key
    try:
        with io.open(CRED, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
        m = re.search(r"DEEPSEEK_API_KEY[^\n]{0,80}?(sk-[A-Za-z0-9]{16,})", text)
        if m:
            return m.group(1)
    except Exception:
        pass
    return None


API_KEY = load_api_key()
_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE


def deepseek_chat(messages, timeout=120):
    body = json.dumps({
        "model": MODEL,
        "messages": messages,
        "max_tokens": 3000,
        "stream": False,
        "temperature": 0,
    }, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        "https://api.deepseek.com/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + (API_KEY or ""),
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_ctx) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return completion_text(payload)


def completion_text(payload):
    """取正文；deepseek-flash 先写思考再用正文回答，思考过长时 content 可能为空，
    这时从 reasoning_content 里捞 JSON 兜底，实在没有就报错（宁可失败也不要填空答案）。"""
    choices = (payload or {}).get("choices") or [{}]
    ch = choices[0] or {}
    msg = ch.get("message") or {}
    content = (msg.get("content") or "").strip()
    if content:
        return content
    reasoning = msg.get("reasoning_content") or ""
    m = re.search(r"\{[\s\S]*\}", reasoning)
    if m:
        return m.group(0)
    raise ValueError("模型返回空内容（finish=%s）" % ch.get("finish_reason"))


def build_messages(q):
    stem = q.get("stem") or ""
    opts = q.get("options") or []
    qtype = q.get("type") or "single"
    lines = ["题型：%s" % qtype, "题干：", stem]
    if opts:
        lines.append("选项：")
        for o in opts:
            lines.append("%s. %s" % (o.get("key", ""), o.get("text", "")))
    text = "\n".join(lines)
    parts = [{"type": "text", "text": text}]
    for img in (q.get("images") or [])[:4]:
        if isinstance(img, str) and img.startswith("data:image/"):
            parts.append({"type": "image_url", "image_url": {"url": img}})
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": parts if len(parts) > 1 else text},
    ]


def parse_answer(raw):
    raw = (raw or "").strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.M).strip()
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        raise ValueError("模型没有返回 JSON：" + raw[:120])
    obj = json.loads(m.group(0))
    ans = obj.get("answer")
    if isinstance(ans, str):
        ans = [ans]
    if not isinstance(ans, list) or not ans:
        raise ValueError("答案为空：" + raw[:120])
    cleaned = [str(a).strip() for a in ans if str(a).strip()]
    if not cleaned:
        raise ValueError("答案为空：" + raw[:120])
    return {"answer": cleaned, "reason": str(obj.get("reason") or "")[:300]}


def solve_one(q):
    last = None
    for attempt in range(2):
        try:
            raw = deepseek_chat(build_messages(q))
            out = parse_answer(raw)
            out["ok"] = True
            return out
        except Exception as e:
            last = e
            if attempt == 0:
                time.sleep(1.5)
    return {"ok": False, "error": str(last)[:200]}


# ---------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    server_version = "cxbridge/0.2"

    def log_message(self, fmt, *args):
        if sys.stdout is None:  # pythonw 下 stdout 为 None，别崩
            return
        try:
            sys.stdout.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), fmt % args))
            sys.stdout.flush()
        except Exception:
            pass

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/ping":
            return self._send(200, json.dumps({
                "ok": True, "engine": ENGINE, "model": MODEL, "key_loaded": bool(API_KEY),
                "data_dir": DATA_DIR,
            }, ensure_ascii=False))
        if path == "/agent-status":
            return self._send(200, json.dumps(agent_status(), ensure_ascii=True))
        if path == "/logs":
            try:
                with io.open(AGENT_LOG, "r", encoding="utf-8", errors="ignore") as f:
                    text = "".join(f.readlines()[-60:])
            except FileNotFoundError:
                text = "(还没有日志)"
            return self._send(200, text, "text/plain; charset=utf-8")
        if path == "/answers":
            return self._send(200, json.dumps(read_answers(), ensure_ascii=False))
        if path == "/fill-report":
            data = _load(os.path.join(DATA_DIR, "fill-report.json")) or {"ok": False, "reason": "还没有回填结果"}
            return self._send(200, json.dumps(data, ensure_ascii=False))
        if path in ("/cx-agent.user.js", "/cx-agent.js"):
            try:
                with io.open(USERSCRIPT, "r", encoding="utf-8") as f:
                    return self._send(200, f.read(), "text/javascript; charset=utf-8")
            except FileNotFoundError:
                return self._send(404, json.dumps({"ok": False, "error": "脚本文件不存在"}))
        if path in ("/fixture", "/fixture-real"):
            name = "fixture.html" if path == "/fixture" else "fixture_real.html"
            try:
                with io.open(os.path.join(HERE, name), "r", encoding="utf-8") as f:
                    return self._send(200, f.read(), "text/html; charset=utf-8")
            except FileNotFoundError:
                return self._send(404, json.dumps({"ok": False, "error": name + " 不存在"}))
        if path == "/":
            return self._send(200, "<h1>cx bridge</h1><p>POST /solve · "
                              "<a href=\"/fixture\">自检页</a> · "
                              "<a href=\"/fixture-real\">真实结构自检页</a> · "
                              "<a href=\"/cx-agent.user.js\">安装脚本</a></p>",
                              "text/html; charset=utf-8")
        return self._send(404, json.dumps({"ok": False, "error": "not found"}))

    def do_POST(self):
        if self.path.startswith("/fill-report"):
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                body = json.loads(raw.decode("utf-8"))
            except Exception:
                body = {}
            body["received"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            _dump(os.path.join(DATA_DIR, "fill-report.json"), body)
            return self._send(200, json.dumps({"ok": True}))

        path = self.path.split("?")[0]
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception as e:
            return self._send(400, json.dumps({"ok": False, "error": "bad json: " + str(e)}))

        if path == "/agent-solve":
            return self._send(200, json.dumps(start_agent(), ensure_ascii=False))

        if path == "/extract":
            questions = data.get("questions") or []
            if not questions:
                return self._send(400, json.dumps({"ok": False, "error": "questions 为空"}))
            return self._send(200, json.dumps(enqueue(questions), ensure_ascii=False))

        if path == "/solve":
            questions = data.get("questions") or []
            if not questions:
                return self._send(400, json.dumps({"ok": False, "error": "questions 为空"}))
            if ENGINE != "direct" or os.environ.get("CXD_ALLOW_DIRECT") != "1":
                return self._send(200, json.dumps(enqueue(questions), ensure_ascii=False))
            started = time.time()
            results = {}

            def work(q):
                return str(q.get("id") or ""), solve_one(q)

            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
                for qid, res in pool.map(work, questions):
                    results[qid] = res
            ok = sum(1 for v in results.values() if v.get("ok"))
            self._send(200, json.dumps({
                "ok": True, "model": MODEL, "total": len(questions),
                "solved": ok, "elapsed": round(time.time() - started, 1),
                "answers": results,
            }, ensure_ascii=False))
            return

        if path == "/report":
            _dump(REPORT, data)
            return self._send(200, json.dumps({"ok": True, "saved": REPORT}, ensure_ascii=False))

        return self._send(404, json.dumps({"ok": False, "error": "not found"}))


def main():
    if ENGINE == "direct" and not API_KEY:
        print("!! direct 模式没有找到 DeepSeek API Key（环境变量 DEEPSEEK_API_KEY 或 ~/.dsh/.credentials.yaml）")
    print("cx bridge listening on http://127.0.0.1:%d  engine=%s  model=%s" % (PORT, ENGINE, MODEL))
    print("   data dir: %s" % DATA_DIR)
    if ENGINE == "agent":
        print("   题目交给 DSH 侧作答：点「开始做题」起新会话，写完 answers.json 后脚本自动回填")
    print("安装脚本： http://127.0.0.1:%d/cx-agent.user.js" % PORT)
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
