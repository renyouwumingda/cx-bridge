"""在真实学习通作业页快照上验证提取器（离线，不联网、不调模型）。

快照来源：ceilf6/ChaoXingPaste 的「作业作答.html」（333KB，mooc2/work/dowork 页面，Ctrl+S 保存）。
运行：cd cx-bridge && PYTHONIOENCODING=utf-8 python probe_real_page.py
"""
import pathlib
import sys

from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).parent
DEFAULT = HERE / "research" / "real-page" / "doWork-367k.html"
US = (HERE / "cx-agent.user.js").read_text(encoding="utf-8")

STRUCT = """() => {
  const q = s => document.querySelectorAll(s).length;
  return {
    'fanyaMarking_left': q('.fanyaMarking_left'),
    '.fanyaMarking_left .questionLi.singleQuesId': q('.fanyaMarking_left .questionLi.singleQuesId'),
    '.questionLi': q('.questionLi'),
    '.questionLi.singleQuesId': q('.questionLi.singleQuesId'),
    '.TiMu': q('.TiMu'),
    '.stem_answer': q('.stem_answer'),
    '.answerBg': q('.answerBg'),
    '.num_option': q('.num_option'),
    '.num_option_dx': q('.num_option_dx'),
    '.Zy_TItle': q('.Zy_TItle'),
    '.Zy_TItle .fontLabel': q('.Zy_TItle .fontLabel'),
    '.mark_name': q('.mark_name'),
    '[id^=question]': q('[id^=question]'),
    'img': q('img'),
    'iframes': q('iframe'),
    'textarea[answerEditor]': q('textarea[name^=answerEditor]'),
  };
}"""


def main():
    page_path = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    if not page_path.is_absolute():
        page_path = (HERE / page_path).resolve()
    print("快照：", page_path.name)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        url = page_path.as_uri()
        if "--generic" in sys.argv:
            url += "?cxb_generic=1"
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(1500)

        print("== 页面结构计数 ==")
        for k, v in page.evaluate(STRUCT).items():
            print("  %-46s %s" % (k, v))

        page.add_script_tag(content="window.GM_xmlhttpRequest = window.GM_xmlhttpRequest || function(){};")
        page.add_script_tag(content=US)
        page.wait_for_selector("#cxb-extract", timeout=5000)

        page.click("#cxb-extract")
        page.wait_for_function(
            "document.getElementById('cxb-log').textContent.includes('共')", timeout=30000)
        print("\n== 提取日志 ==")
        print(page.inner_text("#cxb-log"))

        data = page.evaluate("() => { const s = window.__cxb_state && window.__cxb_state(); return s ? s.questions : null; }")
        if data:
            print("\n== 逐题 ==")
            for it in data:
                opts = " | ".join("%s.%s" % (o["key"], o["text"][:14]) for o in it["options"])
                print("  [%s] %-8s %s" % (it["id"], it["type"], it["stem"][:60].replace("\n", " ")))
                print("       %s" % opts)
        else:
            print("\n[WARN] __cxb_state 不可用")

        browser.close()


if __name__ == "__main__":
    main()
