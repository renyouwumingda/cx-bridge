"""对 research/real-page 下的真实页面快照做结构计数，挑出有选项的那种页。"""
import pathlib

from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).parent / "research" / "real-page"

STRUCT = """() => {
  const q = s => document.querySelectorAll(s).length;
  return {
    '.questionLi': q('.questionLi'),
    '.questionLi.singleQuesId': q('.questionLi.singleQuesId'),
    '.TiMu': q('.TiMu'),
    '.Zy_TItle': q('.Zy_TItle'),
    '.mark_name': q('.mark_name'),
    '.stem_answer': q('.stem_answer'),
    '.answerBg': q('.answerBg'),
    '.num_option': q('.num_option'),
    '.num_option_dx': q('.num_option_dx'),
    'li[onclick]': q('li[onclick]'),
    'input[type=radio]': q('input[type=radio]'),
    'input[type=checkbox]': q('input[type=checkbox]'),
    'textarea': q('textarea'),
    'iframe': q('iframe'),
  };
}"""

with sync_playwright() as p:
    b = p.chromium.launch()
    for f in sorted(HERE.glob("*.html")):
        pg = b.new_page()
        try:
            pg.goto(f.as_uri(), wait_until="domcontentloaded")
            pg.wait_for_timeout(800)
            counts = pg.evaluate(STRUCT)
            print("==", f.name)
            print("   " + "  ".join("%s=%s" % (k, v) for k, v in counts.items() if v))
        except Exception as e:
            print("==", f.name, "ERROR", e)
        finally:
            pg.close()
    b.close()
