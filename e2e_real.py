"""真实结构自检页的端到端测试（ul.mark_letter > li 结构）。

运行：cd cx-bridge && PYTHONIOENCODING=utf-8 python e2e_real.py
"""
import json
import os
import pathlib
import sys
import threading
import time

from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
BRIDGE = os.environ.get("CX_BRIDGE", "http://127.0.0.1:8790")
DATA = pathlib.Path(os.environ.get("CXD_DATA_DIR") or HERE)
PENDING = DATA / "pending.json"
ANSWERS = DATA / "answers.json"
REPORT = DATA / "last-report.json"

# 安全闸：必须显式指定独立数据目录，避免测试覆盖真实 pending/answers
if not os.environ.get("CXD_DATA_DIR"):
    raise SystemExit("请先设置 CXD_DATA_DIR（并用同一目录启动 server.py），避免测试覆盖真实题目")

US = (HERE / "cx-agent.user.js").read_text(encoding="utf-8").replace("http://127.0.0.1:8790", BRIDGE)
URL = BRIDGE + "/fixture-real"

ANS = {
    "213998352": {"ok": True, "answer": ["A"], "reason": "测试"},
    "213998360": {"ok": True, "answer": ["A", "B"], "reason": "测试"},
    "213998370": {"ok": True, "answer": ["true"], "reason": "测试"},
    "213998380": {"ok": True, "answer": ["测试简答内容"], "reason": "测试"},
    "213998390": {"ok": True, "answer": ["B"], "reason": "测试"},
}


def auto_answer(answers_map, timeout=180):
    """模拟「助手作答」：盯着 pending.json，一出现新的 task 就写 answers.json。"""
    def run():
        seen = None
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                pend = json.loads(PENDING.read_text(encoding="utf-8"))
            except Exception:
                time.sleep(0.2)
                continue
            tid = pend.get("task_id")
            if tid and tid != seen:
                seen = tid
                ans = {}
                for q in pend.get("questions") or []:
                    qid = str(q.get("id"))
                    ans[qid] = answers_map.get(qid) or {"ok": False, "error": "测试未给答案"}
                ANSWERS.write_text(
                    json.dumps({"task_id": tid, "answers": ans}, ensure_ascii=False), encoding="utf-8")
            time.sleep(0.2)
    th = threading.Thread(target=run, daemon=True)
    th.start()
    return th


def main():
    ok = True
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(URL, wait_until="load")

        page.add_script_tag(content="""
          window.GM_xmlhttpRequest = function (opts) {
            var init = { method: opts.method || 'GET', headers: opts.headers || {} };
            if (opts.data) init.body = opts.data;
            fetch(opts.url, init)
              .then(function (r) { return r.text().then(function (t) {
                opts.onload && opts.onload({ status: r.status, responseText: t, response: t });
              }); })
              .catch(function (e) { opts.onerror && opts.onerror({ error: String(e) }); });
          };
        """)
        page.add_script_tag(content=US)
        page.wait_for_selector("#cxb-extract", timeout=5000)

        page.click("#cxb-extract")
        try:
            page.wait_for_function(
                "document.getElementById('cxb-log').textContent.includes('共 5 道')", timeout=20000)
        except Exception:
            print("[FAIL] 提取失败：")
            print(page.inner_text("#cxb-log"))
            browser.close()
            return 1
        log = page.inner_text("#cxb-log")
        print("[ok] 提取：", " / ".join(log.splitlines()[1:3]))
        for want in ("single 2", "multiple 1", "judge 1", "essay 1"):
            if want not in log:
                print("[FAIL] 题型缺少：", want)
                ok = False

        page.click("#cxb-solve")
        auto_answer(ANS)
        try:
            page.wait_for_function(
                "document.getElementById('cxb-log').textContent.includes('已作答')", timeout=90000)
        except Exception:
            print("[FAIL] 作答失败：")
            print(page.inner_text("#cxb-log")[-600:])
            browser.close()
            return 1
        print("[ok] 作答：", [l for l in page.inner_text("#cxb-log").splitlines() if "已作答" in l][-1])

        page.click("#cxb-fill")
        try:
            page.wait_for_function(
                "document.getElementById('cxb-log').textContent.includes('回填完成')", timeout=60000)
        except Exception:
            print("[FAIL] 回填失败：")
            print(page.inner_text("#cxb-log")[-600:])
            browser.close()
            return 1

        state = page.evaluate("""() => {
          const get = id => [...document.querySelectorAll('#' + id + ' li.check_answer')]
            .map(li => li.getAttribute('data') || li.textContent.trim().slice(0, 1));
          return {
            q1: get('question213998352'),
            f1: (document.getElementById('answer213998352') || {}).value || '',
            f2: (document.getElementById('answer213998360') || {}).value || '',
            f5: (document.getElementById('answer213998390') || {}).value || '',
            q2: get('question213998360'),
            q3: get('question213998370'),
            essay: document.querySelector('#question213998380 textarea').value,
            result: document.getElementById('result').textContent,
          };
        }""")
        for k, v in state.items():
            print("[check] %-6s %r" % (k, v[:60] if isinstance(v, str) else v))

        if not state["q1"]:
            print("[FAIL] 单选没勾上")
            ok = False
        if not state["q3"]:
            print("[FAIL] 判断没勾上")
            ok = False
        if not (state["essay"] or "").strip():
            print("[FAIL] 简答没写进编辑器")
            ok = False
        if not state["f1"]:
            print("[FAIL] 隐藏字段 q1 为空")
            ok = False
        if not state["f5"]:
            print("[FAIL] 点了没反应的题没走隐藏字段兜底")
            ok = False
        if state["result"].count("—"):
            print("[warn] 仍有一道题没填：", state["result"])

        print("\n---- 回填日志 ----")
        print(page.inner_text("#cxb-log"))

        # 第二遍：只点「一键做完」
        print("\n==== 一键做完 ====")
        page.reload(wait_until="load")
        page.add_script_tag(content="""
          window.GM_xmlhttpRequest = function (opts) {
            var init = { method: opts.method || 'GET', headers: opts.headers || {} };
            if (opts.data) init.body = opts.data;
            fetch(opts.url, init)
              .then(function (r) { return r.text().then(function (t) {
                opts.onload && opts.onload({ status: r.status, responseText: t, response: t });
              }); })
              .catch(function (e) { opts.onerror && opts.onerror({ error: String(e) }); });
          };
        """)
        page.add_script_tag(content=US)
        page.wait_for_selector("#cxb-all", timeout=5000)
        auto_answer(ANS)
        page.click("#cxb-all")
        try:
            page.wait_for_function(
                "document.getElementById('cxb-log').textContent.includes('一键完成')", timeout=200000)
        except Exception:
            print("[FAIL] 一键做完超时：")
            print(page.inner_text("#cxb-log")[-600:])
            ok = False
        one = page.evaluate("""() => ({
          q1: [...document.querySelectorAll('#question213998352 li.check_answer')].length,
          q3: [...document.querySelectorAll('#question213998370 li.check_answer')].length,
          essay: (document.querySelector('#question213998380 textarea') || {}).value || '',
          full: document.getElementById('cxb-log').textContent.includes('回填完成：5/5'),
        })""")
        print("[check] 一键结果：", one)
        if not (one["q1"] and one["q3"] and one["essay"].strip() and one["full"]):
            print("[FAIL] 一键做完没填全")
            ok = False

        browser.close()

    print("\nE2E-REAL:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
