# -*- coding: utf-8 -*-
"""新式作业页（mooc-ans/work/doHomeWorkNew）选择器的回归测试。

fixture_newstyle.html 里的 DOM 是从真实页面 dump 出来的结构（.TiMu[data] + ul.Zy_ulTop > li
+ <input name="answer<qid>" type="radio" value="A"> + answertype 隐藏题型码），
只去掉了图片，避免离线测试时 8 秒取图超时。

覆盖：
  * questionContainers 命中 .TiMu[data]
  * detectType 读 answertype 得到 single（不再判 unknown）
  * optionRows 在 li 上取到 4 条选项，optionText 有真实文本
  * 回填时点 input[type=radio]，checked 变成对应字母（真实页面就是看 checked）

用法：先 python server.py，再 PYTHONIOENCODING=utf-8 python e2e_newstyle.py
"""
import json
import os
import pathlib
import sys
import time

from playwright.sync_api import sync_playwright

from e2e_dowork import STUB

HERE = pathlib.Path(__file__).resolve().parent
BRIDGE = os.environ.get("CX_BRIDGE", "http://127.0.0.1:8790")
DATA = pathlib.Path(os.environ.get("CXD_DATA_DIR") or HERE)
PENDING = DATA / "pending.json"
ANSWERS = DATA / "answers.json"
REPORT = DATA / "last-report.json"
US = (HERE / "cx-agent.user.js").read_text(encoding="utf-8").replace("http://127.0.0.1:8790", BRIDGE)
PAGE = HERE / "fixture_newstyle.html"
PENDING = DATA / "pending.json"
REPORT = DATA / "last-report.json"

# 安全闸：必须显式指定独立数据目录，避免测试覆盖真实 pending/answers
if not os.environ.get("CXD_DATA_DIR"):
    raise SystemExit("请先设置 CXD_DATA_DIR（并用同一目录启动 server.py），避免测试覆盖真实题目")

ANSWERS = DATA / "answers.json"

QIDS = ["215107224", "215107225"]
WANT = {"215107224": "A", "215107225": "C"}


def main():
    # 测试会触发脚本上报结构，必须保护真实页面留下的 last-report.json
    old = {p: (p.read_bytes() if p.exists() else None) for p in (PENDING, REPORT)}
    old_task = ""
    if old[PENDING]:
        try:
            old_task = json.loads(old[PENDING].decode("utf-8")).get("task_id", "")
        except Exception:
            pass
    if ANSWERS.exists():
        ANSWERS.unlink()
    fails = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.goto(PAGE.as_uri(), wait_until="domcontentloaded")
        page.wait_for_timeout(300)
        page.add_script_tag(content=STUB)
        page.add_script_tag(content=US)
        page.wait_for_selector("#cxb-all", timeout=10000)
        page.click("#cxb-all")

        pend = None
        deadline = time.time() + 40
        while time.time() < deadline:
            if PENDING.exists():
                try:
                    pend = json.loads(PENDING.read_text(encoding="utf-8"))
                    if pend.get("questions") and pend.get("task_id") != old_task:
                        break
                except Exception:
                    pass
            page.wait_for_timeout(400)
        if not pend or not pend.get("questions") or pend.get("task_id") == old_task:
            print("FAIL 没有生成新的 pending.json")
            browser.close()
            return 1

        qs = pend["questions"]
        print("提取到 %d 题：%s" % (len(qs), [q["type"] for q in qs]))
        if [q["id"] for q in qs] != QIDS:
            fails.append("题号应为 %s，实际 %s" % (QIDS, [q["id"] for q in qs]))
        if [q["type"] for q in qs] != ["single", "single"]:
            fails.append("题型应为 single/single（answertype=0），实际 %s" % [q["type"] for q in qs])
        for q in qs:
            opts = q.get("options") or []
            texts = [str(o.get("text") or "").strip() for o in opts]
            print("  %s options=%d %s" % (q["id"], len(opts), texts[:2]))
            if len(opts) != 4:
                fails.append("%s 选项数应为 4，实际 %d（optionRows 没吃到 li.Zy_ulTop）" % (q["id"], len(opts)))
            if any(not t for t in texts):
                fails.append("%s 有选项文本为空：%s" % (q["id"], texts))

        answers = {qid: {"ok": True, "answer": [WANT[qid]], "reason": "newstyle"} for qid in QIDS}
        ANSWERS.write_text(json.dumps({"task_id": pend["task_id"], "answers": answers}, ensure_ascii=False),
                           encoding="utf-8")

        try:
            page.wait_for_function(
                "() => /回填完成/.test(document.getElementById('cxb-log').textContent)", timeout=60000)
        except Exception:
            fails.append("等待「回填完成」超时")

        log = page.inner_text("#cxb-log")
        if "回填完成：2/2" not in log:
            fails.append("回填不是 2/2：" + log[-400:].replace("\n", " / "))

        for qid, want in WANT.items():
            got = page.evaluate(
                "(q) => { var i = document.querySelector('input[name=\"answer' + q + '\"]:checked');"
                " return i ? i.value : null; }", qid)
            print("  %s checked = %r（期望 %r）" % (qid, got, want))
            if got != want:
                fails.append("%s 勾选值应为 %r，实际 %r" % (qid, want, got))

        browser.close()

    for p, data in old.items():
        try:
            if data is None:
                if p.exists():
                    p.unlink()
            else:
                p.write_bytes(data)
        except Exception as e:
            print("!! 还原 %s 失败：%s" % (p.name, e))
    if fails:
        print("\nFAIL:")
        for f in fails:
            print("  - " + f)
        return 1
    print("PASS e2e_newstyle 2/2 OK (answertype->single, li 选项 4 条, radio 勾选)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
