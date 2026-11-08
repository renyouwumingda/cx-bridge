"""端到端自检：headless Chromium 打开 /fixture → 注入 cx-agent → 提取/作答/回填 → 校验 DOM。

不依赖脚本猫，也不需要真作业页，不调任何外部模型（agent 模式下答案由本脚本模拟写出）。
运行：cd cx-bridge && PYTHONIOENCODING=utf-8 python e2e_test.py
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
URL = BRIDGE + "/fixture"


def auto_answer(answers_map, timeout=90):
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

        # 脚本所有请求都走 GM_xmlhttpRequest；用 fetch 实现一个等价壳子（fixture 与桥接服务同源）
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
        print("[ok] 面板已注入")

        page.click("#cxb-extract")
        try:
            page.wait_for_function(
                "document.getElementById('cxb-log').textContent.includes('共 6 道')", timeout=20000)
        except Exception:
            print("[FAIL] 提取没识别到 6 题，日志：")
            print(page.inner_text("#cxb-log"))
            browser.close()
            return 1
        log = page.inner_text("#cxb-log")
        print("[ok] 提取：", " / ".join(log.splitlines()[1:3]))
        for want in ("single 2", "judge 1", "blank 1", "multiple 1", "essay 1", "带图片的题：1 道"):
            if want not in log:
                print("[FAIL] 提取结果缺少：", want)
                ok = False

        page.click("#cxb-solve")
        # agent 模式：脚本只把题目交上去，答案由「助手」写 answers.json（这里模拟）
        auto_answer({
            "1001": {"ok": True, "answer": ["A"], "reason": "测试"},
            "1002": {"ok": True, "answer": ["true"], "reason": "测试"},
            "1003": {"ok": True, "answer": ["H2O"], "reason": "测试"},
            "1004": {"ok": True, "answer": ["A", "B", "D"], "reason": "测试"},
            "1005": {"ok": True, "answer": ["测试简答内容"], "reason": "测试"},
            "1006": {"ok": True, "answer": ["B"], "reason": "测试"},
        })
        try:
            page.wait_for_function(
                "document.getElementById('cxb-log').textContent.includes('已作答')", timeout=60000)
        except Exception:
            print("[FAIL] 作答超时/失败，日志：")
            print(page.inner_text("#cxb-log")[-800:])
            browser.close()
            return 1
        print("[ok] 作答：", [l for l in page.inner_text("#cxb-log").splitlines() if "已作答" in l][-1])

        page.click("#cxb-fill")
        try:
            page.wait_for_function(
                "document.getElementById('cxb-log').textContent.includes('回填完成')", timeout=60000)
        except Exception:
            print("[FAIL] 回填超时，日志：")
            print(page.inner_text("#cxb-log")[-800:])
            browser.close()
            return 1

        q = {
            "single": page.eval_on_selector_all(
                "#question1001 .num_option.check_answer", "els => els.map(e => e.getAttribute('data'))"),
            "judge": page.eval_on_selector_all(
                "#question1002 .num_option.check_answer", "els => els.map(e => e.getAttribute('data'))"),
            "blank": page.eval_on_selector("#question1003 input", "el => el.value"),
            "multiple": page.eval_on_selector_all(
                "#question1004 .num_option_dx.check_answer", "els => els.map(e => e.getAttribute('data'))"),
            "essay": page.eval_on_selector("#question1005 textarea", "el => el.value"),
            "image": page.eval_on_selector_all(
                "#question1006 .num_option.check_answer", "els => els.map(e => e.getAttribute('data'))"),
        }
        for k, v in q.items():
            print("[check] %-8s %r" % (k, v))

        checks = [
            ("单选", q["single"]),
            ("判断", q["judge"]),
            ("填空", q["blank"].strip()),
            ("多选", len(q["multiple"]) >= 1),
            ("简答", q["essay"].strip()),
            ("图片题", q["image"]),
        ]
        for name, val in checks:
            if not val:
                print("[FAIL] %s没有回填成功" % name)
                ok = False

        print("\n---- 回填日志 ----")
        print(page.inner_text("#cxb-log"))
        browser.close()

    print("\nE2E:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
