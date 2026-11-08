"""模拟脚本猫沙箱跑一遍「提取 → 作答 → 回填」。

脚本猫（ScriptCat）等用户脚本管理器跑脚本时，脚本里的 window 是沙箱包装对象，
不是页面真正的 Window。所以 new MouseEvent('click', {view: window}) 会抛
  Failed to construct 'MouseEvent': ... Failed to convert value to 'Window'
而 Playwright 直接把脚本注入页面时 window 就是真 Window，测不出这个问题。

这里把脚本用 new Function 包起来，把 window 参数换成普通对象，复现沙箱条件。

运行：cd cx-bridge && PYTHONIOENCODING=utf-8 python sandbox_sim.py [脚本路径]
不传脚本路径时测 cx-agent.user.js；传别（比如临时改回旧写法的副本）应能复现报错。
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

URL = BRIDGE + "/fixture-real"

ANS = {
    "213998352": {"ok": True, "answer": ["A"], "reason": "测试"},
    "213998360": {"ok": True, "answer": ["A", "B"], "reason": "测试"},
    "213998370": {"ok": True, "answer": ["true"], "reason": "测试"},
    "213998380": {"ok": True, "answer": ["测试简答内容"], "reason": "测试"},
    "213998390": {"ok": True, "answer": ["B"], "reason": "测试"},
}


def auto_answer(answers_map, timeout=180):
    """模拟「助手作答」：等 pending.json 出现新 task 就写 answers.json。"""
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
                ans = {str(q.get("id")): answers_map.get(str(q.get("id"))) or {"ok": False, "error": "未给答案"}
                       for q in pend.get("questions") or []}
                ANSWERS.write_text(
                    json.dumps({"task_id": tid, "answers": ans}, ensure_ascii=False), encoding="utf-8")
            time.sleep(0.2)
    th = threading.Thread(target=run, daemon=True)
    th.start()
    return th

GM_SHELL = """
window.GM_xmlhttpRequest = function (opts) {
  var init = { method: opts.method || 'GET', headers: opts.headers || {} };
  if (opts.data) init.body = opts.data;
  fetch(opts.url, init)
    .then(function (r) { return r.text().then(function (t) {
      opts.onload && opts.onload({ status: r.status, responseText: t, response: t });
    }); })
    .catch(function (e) { opts.onerror && opts.onerror({ error: String(e) }); });
};
"""

# 沙箱里的 window：不是 Window 实例，但保留脚本可能用到的几个属性
SANDBOX_WRAP = """
(src) => {
  const W = {
    __fakeSandboxWindow: true,
    addEventListener() {}, removeEventListener() {},
    setTimeout, clearTimeout, setInterval, clearInterval,
    location, document,
    getComputedStyle: (el) => getComputedStyle(el),
    innerWidth: window.innerWidth, innerHeight: window.innerHeight,
  };
  new Function(
    'window', 'GM_xmlhttpRequest', 'GM_getValue', 'GM_setValue',
    'GM_registerMenuCommand', 'GM_addStyle',
    src
  )(W, window.GM_xmlhttpRequest, () => '', () => {}, () => {}, () => {});
}
"""


def main():
    script = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "cx-agent.user.js"
    src = script.read_text(encoding="utf-8").replace("http://127.0.0.1:8790", BRIDGE)
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(URL, wait_until="load")
        page.add_script_tag(content=GM_SHELL)
        page.evaluate(SANDBOX_WRAP, src)
        try:
            page.wait_for_selector("#cxb-all", timeout=5000)
        except Exception:
            print("[FAIL] 面板没出来，注入失败：")
            print("\n".join(errors[:5]))
            browser.close()
            return 1

        auto_answer(ANS)
        page.click("#cxb-all")
        try:
            page.wait_for_function(
                "(() => { const t = document.getElementById('cxb-log').textContent;"
                " return t.includes('回填完成') || t.includes('一键完成'); })()", timeout=180000)
        except Exception:
            try:
                log = page.inner_text("#cxb-log")
            except Exception:
                log = "<page closed>"
            print("[FAIL] 没走到回填完成：")
            print(log[-800:])
            if errors:
                print("[pageerror]", errors[0][:300])
            browser.close()
            return 1

        fields = page.evaluate("""() => {
          const out = {};
          document.querySelectorAll('input[type=hidden][id^=answer]').forEach(f => out[f.id] = f.value);
          const picked = [...document.querySelectorAll('li.check_answer')]
            .map(li => (li.getAttribute('data') || li.textContent.trim().slice(0, 1)));
          return { fields: out, picked };
        }""")
        browser.close()

    print("[ok] 回填完成，字段：", fields["fields"])
    print("[ok] 点中：", fields["picked"])
    bad = [k for k, v in fields["fields"].items() if not v]
    if bad:
        print("[FAIL] 这些隐藏字段还是空：", bad)
        return 1
    print("SANDBOX-SIM: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
