import json, pathlib, sys, urllib.request
from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
FIX = (HERE / "fixture_exam.html").as_uri()
US = (HERE / "cx-agent.user.js").read_text(encoding="utf-8")
BRIDGE = "http://127.0.0.1:8790"
STUB = r"""window.GM_getValue = (k, d) => { try { const v = localStorage.getItem('gm:' + k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } };
window.GM_setValue = (k, v) => { try { localStorage.setItem('gm:' + k, JSON.stringify(v)); } catch (e) {} };
window.GM_deleteValue = (k) => { try { localStorage.removeItem('gm:' + k); } catch (e) {} };
window.GM_xmlhttpRequest = (opt) => {
  const x = new XMLHttpRequest();
  x.open(opt.method || 'GET', opt.url, true);
  if (opt.headers) Object.keys(opt.headers).forEach(h => x.setRequestHeader(h, opt.headers[h]));
  x.onload = () => { opt.onload && opt.onload({ status: x.status, responseText: x.responseText }); };
  x.onerror = () => { opt.onerror && opt.onerror({ status: 0 }); };
  x.send(opt.data || null);
  return { abort() { try { x.abort(); } catch (e) {} } };
};"""

def ok_list(ok, name, cond):
    ok.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name)

def main():
    ok = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.goto(FIX)
        pg.add_script_tag(content=STUB)
        pg.add_script_tag(content=US)
        pg.wait_for_selector("#cxb-panel")
        pg.evaluate("document.querySelector('#cxb-panel').classList.remove('hidden')")

        qs = pg.evaluate("() => window.__cxb_extract ? window.__cxb_extract() : null")
        # 走面板按钮更真实
        pg.click('[data-tab=quiz]')
        pg.click('#cxb-extract')
        pg.wait_for_timeout(800)
        stats = pg.inner_text("#cxb-log")
        ok_list(ok, "考试页提取到 2 题", "共 2 道" in stats)
        ok_list(ok, "题型识别 single/judge", "single 1" in stats and "judge 1" in stats)
        cases = pg.evaluate("() => window.__cxb_lastExtract || []")
        ok_list(ok, "选项字母 A-D", cases and [o["key"] for o in cases[0]["options"]] == ["A", "B", "C", "D"])
        ok_list(ok, "判断题选项 正确/错误", cases and cases[1]["options"][0]["text"].startswith("正确"))

        # 回填：单选选 C，判断题选 true
        pg.evaluate("() => window.__cxb_injectAnswers({ '9001': {ok:true, answer:['C'], reason:'fixture'}, '9002': {ok:true, answer:['true'], reason:'fixture'} })")
        res = pg.evaluate("() => window.__cxb_fillAll()")
        pg.wait_for_timeout(300)
        sel = pg.evaluate("""() => {
          const single = [...document.querySelectorAll('.choice9001')].map(x => x.className.includes('check_answer'));
          const judge = [...document.querySelectorAll('.choice9002')].map(x => x.className.includes('check_answer'));
          return { single, judge };
        }""")
        ok_list(ok, "单选 C 被点中", sel["single"] == [False, False, True, False])
        ok_list(ok, "判断题 true 被点中", sel["judge"] == [True, False])
        ok_list(ok, "回填报告 2/2", (res or {}).get("okCount") == 2)
        b.close()
    print(("PASS e2e_exam " if all(v for _, v in ok) else "FAILED: ") + f"{sum(1 for _, v in ok if v)}/{len(ok)}")
    return 0 if all(v for _, v in ok) else 1

if __name__ == "__main__":
    sys.exit(main())
