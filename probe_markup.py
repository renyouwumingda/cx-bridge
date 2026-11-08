"""打印真实快照里第一道题的 HTML 片段，看选项到底用什么标签。"""
import pathlib
import re

from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).parent / "research" / "real-page"

with sync_playwright() as p:
    b = p.chromium.launch()
    for name in ["123qwe55aa_analytic-chemistry__作业详情.html",
                 "2443045255_shool__作业详情.html"]:
        pg = b.new_page()
        pg.goto((HERE / name).as_uri(), wait_until="domcontentloaded")
        pg.wait_for_timeout(600)
        html = pg.evaluate("""() => {
            const q = document.querySelector('.questionLi');
            return q ? q.outerHTML : '(未找到 .questionLi)';
        }""")
        html = re.sub(r"\s+", " ", html)
        print("=====", name, "len=", len(html))
        print(html[:1800])
        print()
        pg.close()
    b.close()
