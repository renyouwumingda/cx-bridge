# -*- coding: utf-8 -*-
"""刷章节链路 e2e：章节列表 → 打开未完成章节 → 学习页自动继续 → 视频播完。

跑法（必须先起隔离服务的可选，本测试离线也能跑，脚本 ping 失败会自己忽略）：
    python e2e_chapter.py
"""
import json, pathlib, sys, time
from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
US = (HERE / "cx-agent.user.js").read_text(encoding="utf-8")
FIX = (HERE / "fixture_chapter.html").as_uri()

STUB = r"""
(() => {
  const store = window.localStorage;
  window.GM_getValue = (k, d) => { const v = store.getItem('gm:' + k); return v === null ? d : JSON.parse(v); };
  window.GM_setValue = (k, v) => { store.setItem('gm:' + k, JSON.stringify(v)); };
  window.GM_deleteValue = (k) => { store.removeItem('gm:' + k); };
  window.unsafeWindow = window;
  window.GM_xmlhttpRequest = (o) => {
    const x = new XMLHttpRequest();
    x.open(o.method || 'GET', o.url, true);
    if (o.responseType === 'blob') x.responseType = 'blob';
    x.onload = () => o.onload && o.onload({ status: x.status, responseText: x.responseText, response: x.response });
    x.onerror = () => o.onerror && o.onerror({ error: 'xhr failed' });
    x.send(o.data || null);
  };
})();
"""


def inject(page):
    page.add_script_tag(content=STUB)
    page.add_script_tag(content=US)
    page.wait_for_selector('#cxb-panel', timeout=15000)


def main():
    ok = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        # --- 1. 章节列表页 ---
        page.goto(FIX + "?mode=course")
        inject(page)
        ok.append(("面板有三个页签", page.locator('#cxb-tabs button').count() == 3))
        page.click('#cxb-tabs button[data-tab="chapter"]')
        page.click('#cxb-chap-start')
        page.wait_for_url("**mode=study**", timeout=20000)
        ok.append(("点进未完成章节", "mode=study" in page.url))
        # 记录跳转前的日志（跳转后页面重载，日志会丢，用 storage 判断状态）
        raw = page.evaluate("() => localStorage.getItem('gm:cxb_chapter_state')")
        st = json.loads(json.loads(raw)) if raw else {}
        ok.append(("状态已存 GM 且 running", st.get("running") is True))
        ok.append(("跳过已完成章节，选中第 2 章", st.get("chapterIdx") == 1))

        # --- 2. 章节学习页：脚本重载后自动继续 ---
        page.wait_for_timeout(300)
        inject(page)
        page.click('#cxb-tabs button[data-tab="chapter"]')
        deadline = time.time() + 40
        log = ""
        while time.time() < deadline:
            log = page.inner_text('#cxb-log')
            if "本任务点视频已播完" in log:
                break
            page.wait_for_timeout(500)
        ok.append(("自动继续上次进度", "自动继续" in log))
        ok.append(("识别任务点并点击", "任务点 1" in log))
        ok.append(("视频按 2 倍速播放", "播放中" in log))
        ok.append(("视频播完", "本任务点视频已播完" in log))
        print("----- 学习页日志 -----")
        print(log[-1500:])
        browser.close()

    for name, good in ok:
        print(("PASS " if good else "FAIL ") + name)
    if not all(g for _, g in ok):
        sys.exit(1)
    print("PASS 刷章节 e2e %d 项" % len(ok))


if __name__ == "__main__":
    main()
