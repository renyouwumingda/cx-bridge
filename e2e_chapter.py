# -*- coding: utf-8 -*-
"""
刷章节 e2e（离线 fixture，不需要联网/真账号）
阶段 A：章节列表 -> 第2章学习页 -> 自动回列表 -> 自动进第3章（只断言 URL 与 state，避免日志竞态）
阶段 B：单独开 context，预置「没有 listUrl 的进行中状态」，断言学习页内部流程（自动继续/任务点/2倍速/播完）
"""
import json
import pathlib
import sys
import time

from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
US = (HERE / "cx-agent.user.js").read_text(encoding="utf-8")
FIX = (HERE / "fixture_chapter.html").as_uri()

STUB = r"""
(() => {
  const s = window.localStorage;
  window.GM_getValue = (k, d) => { const v = s.getItem('gm:' + k); return v === null ? d : JSON.parse(v); };
  window.GM_setValue = (k, v) => { s.setItem('gm:' + k, JSON.stringify(v)); };
  window.GM_deleteValue = (k) => { s.removeItem('gm:' + k); };
  window.unsafeWindow = window;
  window.GM_xmlhttpRequest = (o) => {
    const x = new XMLHttpRequest();
    x.open(o.method || 'GET', o.url, true);
    x.onload = () => o.onload && o.onload({ status: x.status, responseText: x.responseText });
    x.onerror = () => o.onerror && o.onerror({});
    x.send(o.data || null);
  };
})();
"""

def inject(page):
    page.add_script_tag(content=STUB)
    page.add_script_tag(content=US)
    page.wait_for_selector("#cxb-panel", timeout=15000)
    page.wait_for_timeout(300)

def chapter_tab(page):
    page.click('#cxb-tabs button[data-tab="chapter"]')
    page.wait_for_timeout(150)

def state_of(page):
    raw = page.evaluate("() => localStorage.getItem('gm:cxb_chapter_state')")
    if not raw:
        return {}
    v = json.loads(raw)
    return json.loads(v) if isinstance(v, str) else v

def run_phase_a(browser, ok):
    ctx = browser.new_context()
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(FIX + "?mode=course")
    inject(page)
    ok.append(("面板有三个页签", len(page.query_selector_all("#cxb-tabs button")) == 3))
    chapter_tab(page)
    page.click("#cxb-chap-start")
    page.wait_for_url("**mode=study**", timeout=20000)
    ok.append(("从列表进入未完成章节", "mode=study" in page.url))
    st = state_of(page)
    ok.append(("running 已存到 GM", st.get("running") is True))
    inject(page)
    page.wait_for_url("**mode=course**", timeout=25000)
    ok.append(("本章完成自动回列表", "mode=course" in page.url))
    inject(page)
    page.wait_for_url("**mode=study&ch=2**", timeout=25000)
    ok.append(("列表页自动续跑进第 3 章", "ch=2" in page.url))
    ok.append(("第 3 章进度已记录", state_of(page).get("chapterIdx") == 2))
    if errors:
        print("PAGEERRORS:", errors[:3])
    ctx.close()

def run_phase_a2(browser, ok):
    """新版页面：章节是 h3 + onclick 里带 chapterId，没有 .chapter_item"""
    ctx = browser.new_context()
    page = ctx.new_page()
    page.goto(FIX + "?mode=course&v=new")
    inject(page)
    chapter_tab(page)
    page.click("#cxb-chap-start")
    try:
        page.wait_for_url("**mode=study**", timeout=20000)
        ok.append(("新版 h3 章节也能点进去", "mode=study" in page.url))
    except Exception:
        log = page.evaluate("() => { const e = document.querySelector('#cxb-log'); return e ? e.textContent : ''; }")
        print("----- 新版页面日志 -----")
        print((log or "<empty>")[-500:])
        ok.append(("新版 h3 章节也能点进去", False))
    ctx.close()

def run_phase_d(browser, ok):
    """换了课程：旧进度作废（用「全部已完成」的列表页，流程不跳转，日志可读）"""
    ctx = browser.new_context()
    page = ctx.new_page()
    page.goto(FIX + "?mode=course&courseId=222&alldone=1")
    old_state = {"course": "111/0", "running": True, "done": {"ch0": 1}, "chapterIdx": 2, "taskIdx": 0}
    page.evaluate("s => localStorage.setItem('gm:cxb_chapter_state', JSON.stringify(s))", json.dumps(old_state))
    inject(page)
    log, deadline = "", time.time() + 20
    while time.time() < deadline:
        cur = page.evaluate("() => { const e = document.querySelector('#cxb-log'); return e ? e.textContent : ''; }")
        if cur:
            log = cur
        if "换了课程" in log:
            break
        page.wait_for_timeout(200)
    print("----- 换课程日志 -----")
    print((log or "<empty>")[-400:])
    ok.append(("换课程会重置进度", "换了课程" in log))
    st = state_of(page)
    ok.append(("换课程后进度归零", st.get("chapterIdx") == 0))
    ctx.close()

def run_phase_e(browser, ok):
    """音频任务点：应被当成媒体播放（2 倍速、播完），而不是干等 20–40 秒"""
    ctx = browser.new_context()
    page = ctx.new_page()
    page.goto(FIX + "?mode=study&ch=1&audio=1")
    page.evaluate("() => localStorage.setItem('gm:cxb_chapter_state', JSON.stringify(JSON.stringify({running:true, chapterIdx:1, taskIdx:0, done:{}})))")
    inject(page)
    log, deadline = "", time.time() + 25
    while time.time() < deadline:
        cur = page.evaluate("() => { const e = document.querySelector('#cxb-log'); return e ? e.textContent : ''; }")
        if cur:
            log = cur
        if "播完" in log or "按文档处理" in log:
            break
        page.wait_for_timeout(200)
    info = page.evaluate("() => { const a = document.querySelector('#a1'); return a ? {rate: a.playbackRate, muted: a.muted, ended: a.ended} : null; }")
    print("----- 音频任务点 -----", info)
    ok.append(("音频按媒体播放（走进度）", bool(info) and "播完" in log and "按文档处理" not in log))
    ok.append(("音频 2 倍速且静音", bool(info) and info.get("rate") == 2 and info.get("muted") is True))
    ctx.close()

def run_phase_c(browser, ok):
    """视频 currentTime 不动：看门狗重试后跳过，不把流程卡死"""
    ctx = browser.new_context()
    page = ctx.new_page()
    page.add_init_script("window.__CXB_STALL_WARN_MS = 1200; window.__CXB_STALL_SKIP_MS = 2600;")
    page.goto(FIX + "?mode=study&ch=1&stall=1")
    st = {"course": "/fixture_chapter.html", "running": True, "done": {}, "chapterIdx": 1, "taskIdx": 0}
    page.evaluate("s => localStorage.setItem('gm:cxb_chapter_state', JSON.stringify(s))", json.dumps(st))
    inject(page)
    log, deadline = "", time.time() + 25
    while time.time() < deadline:
        try:
            cur = page.evaluate("() => { const e = document.querySelector('#cxb-log'); return e ? e.textContent : ''; }")
        except Exception:
            break
        if cur:
            log = cur
        if "跳过这个任务点" in log:
            break
        page.wait_for_timeout(200)
    print("----- 卡住看门狗日志 -----")
    print((log or "<empty>")[-500:])
    ok.append(("视频卡住会自动跳过", "跳过这个任务点" in log))
    ctx.close()

def run_phase_b(browser, ok):
    ctx = browser.new_context()
    page = ctx.new_page()
    page.goto(FIX + "?mode=study&ch=1")
    # 预置进行中状态，故意不带 listUrl：跑完本章后停在原地，方便读日志
    st = {"course": "/fixture_chapter.html", "running": True, "done": {}, "chapterIdx": 1, "taskIdx": 0}
    page.evaluate(
        "s => localStorage.setItem('gm:cxb_chapter_state', JSON.stringify(s))",
        json.dumps(st),
    )
    inject(page)
    log = ""
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            cur = page.evaluate(
                "() => { const e = document.querySelector('#cxb-log'); return e ? e.textContent : ''; }"
            )
        except Exception:
            break
        if cur:
            log = cur
        if "播完" in log or "没记住" in log:
            break
        page.wait_for_timeout(200)
    print("----- 学习页日志 -----")
    print((log or "<empty>")[-800:])
    ok.append(("自动继续上次进度", "自动继续" in log))
    ok.append(("识别任务点并点击", "任务点 1" in log))
    ok.append(("视频按 2 倍速播放", "2×" in log or "2x" in log))
    ok.append(("视频播完", "播完" in log))
    ok.append(("跳过测验类任务点", "跳过非视频任务点" in log))
    ctx.close()

def main():
    ok = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        run_phase_a(browser, ok)
        run_phase_a2(browser, ok)
        run_phase_c(browser, ok)
        run_phase_e(browser, ok)
        run_phase_d(browser, ok)
        run_phase_b(browser, ok)
        browser.close()

    failed = [n for n, v in ok if not v]
    for n, v in ok:
        print(("PASS " if v else "FAIL ") + n)
    if failed:
        print("\nFAILED:", failed)
        sys.exit(1)
    print("\nPASS 刷章节 e2e %d 项" % len(ok))

if __name__ == "__main__":
    main()
