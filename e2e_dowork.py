# -*- coding: utf-8 -*-
"""真实作答页标记的全链路自检：fixture_dowork.html → 提取 → /extract → 写 answers → 回填 → 读隐藏字段。

不需要登录、不联网（只连本机 8790）。跑之前先 `python server.py`。
覆盖：padBom50 questionLi + typename 题型、answerBg/num_option 选项、判断题 true/false、
      UEditor 填空/简答、#answer<qid> 隐藏落库字段、按 qid 对齐回填。

用法：
    PYTHONIOENCODING=utf-8 python e2e_dowork.py
"""
import json
import os
import pathlib
import sys
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
PAGE = HERE / "fixture_dowork.html"

# 把 GM_xmlhttpRequest 换成真 XHR（脚本在真浏览器里靠它连本机桥接服务）
STUB = """
window.GM_xmlhttpRequest = function (o) {
  var x = new XMLHttpRequest();
  x.open(o.method || 'GET', o.url, true);
  if (o.headers) Object.keys(o.headers).forEach(function (k) { x.setRequestHeader(k, o.headers[k]); });
  x.responseType = o.responseType === 'blob' ? 'blob' : 'text';
  x.onload = function () {
    o.onload && o.onload({ status: x.status, responseText: o.responseType === 'blob' ? '' : x.response, response: x.response });
  };
  x.onerror = function () { o.onerror && o.onerror({ error: 'net' }); };
  x.send(o.data || null);
};
"""

EXPECT = {
    "406012500": ("single", ["A"], "answer406012500", "A"),
    "406012501": ("multiple", ["A", "C"], "answer406012501", "AC"),
    "406012502": ("judge", ["true"], "answer406012502", "true"),
}


def _restore_report(old_report):
    """跑测试时脚本会 POST /report，把真实页面的结构快照覆盖掉；跑完必须还回去。"""
    try:
        if old_report is None:
            if REPORT.exists():
                REPORT.unlink()
        else:
            REPORT.write_bytes(old_report)
    except Exception as e:
        print("!! 还原 last-report.json 失败：%s" % e)


def _restore(old_pending):
    """把跑测试前就存在的 pending.json 原样写回（没有就删掉测试产物）。"""
    try:
        if old_pending is None:
            if PENDING.exists():
                PENDING.unlink()
        else:
            PENDING.write_bytes(old_pending)
    except Exception as e:
        print("!! 还原 pending.json 失败：%s" % e)


def main():
    # 保护用户/其他测试已经存在的 pending.json：跑完原样还回去
    old_pending = PENDING.read_bytes() if PENDING.exists() else None
    # 提取时会 POST /report，会覆盖真实页面留下的结构快照 —— 跑完必须还回去
    old_report = REPORT.read_bytes() if REPORT.exists() else None
    old_task = ""
    if old_pending:
        try:
            old_task = json.loads(old_pending.decode("utf-8")).get("task_id", "")
        except Exception:
            pass
    if ANSWERS.exists():
        ANSWERS.unlink()
    fails = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.goto(PAGE.as_uri(), wait_until="domcontentloaded")
        page.wait_for_timeout(500)
        page.add_script_tag(content=STUB)
        page.add_script_tag(content=US)
        page.wait_for_selector("#cxb-all", timeout=10000)

        page.click("#cxb-all")  # 提取 → 交 DSH 侧 → 轮询 /answers
        deadline = time.time() + 40
        pend = None
        while time.time() < deadline:
            if PENDING.exists():
                try:
                    pend = json.loads(PENDING.read_text(encoding="utf-8"))
                    # 必须等到本次提取写进来的（task_id 变化），否则会读到旧 pending
                    if pend.get("questions") and pend.get("task_id") != old_task:
                        break
                except Exception:
                    pass
            page.wait_for_timeout(400)
        if not pend or not pend.get("questions") or pend.get("task_id") == old_task:
            print("FAIL 没有生成新的 pending.json")
            browser.close()
            _restore(old_pending)
            _restore_report(old_report)
            return 1

        qs = pend["questions"]
        types = [q["type"] for q in qs]
        print("提取到 %d 题：%s" % (len(qs), ", ".join(types)))
        if len(qs) != 6:
            fails.append("题数应为 6，实际 %d" % len(qs))
        if types != ["single", "multiple", "judge", "blank", "essay", "blank"]:
            fails.append("题型顺序不对：%s" % types)

        answers = {}
        for q in qs:
            qid = str(q["id"])
            if qid in EXPECT:
                answers[qid] = {"ok": True, "answer": list(EXPECT[qid][1]), "reason": "fixture"}
            elif qid == "406012505":  # 公式填空：答案用 $...$ 包住 LaTeX
                answers[qid] = {"ok": True,
                                "answer": ["$B=\\frac{\\mu_0 I}{6R}+\\frac{\\mu_0 I}{4\\pi R}(2-\\sqrt{3})$"],
                                "reason": "fixture-formula"}
            else:  # 填空 / 简答
                vals = ["氧", "H2O"] if q["type"] == "blank" else ["一切物体在不受外力时保持静止或匀速直线运动。"]
                answers[qid] = {"ok": True, "answer": vals, "reason": "fixture"}
        ANSWERS.write_text(json.dumps({"task_id": pend["task_id"], "answers": answers}, ensure_ascii=False),
                           encoding="utf-8")

        try:
            page.wait_for_function(
                "() => /回填完成/.test(document.getElementById('cxb-log').textContent)", timeout=90000)
        except Exception:
            fails.append("等待「回填完成」超时")

        log = page.inner_text("#cxb-log")
        if "回填完成：6/6" not in log:
            fails.append("回填不是 6/6：" + log[-300:].replace("\n", " / "))

        # 填空/简答写完应点题内「保存」（不点的话刷新就没）
        saved = page.evaluate("() => window.__cxbSaved || 0")
        print("  保存按钮点击次数 = %r" % saved)
        if saved < 1:
            fails.append("填空题没有点题内「保存」按钮")
        if "已点保存" not in log:
            fails.append("日志里没有「已点保存」")

        # 选择题 / 判断题：隐藏落库字段必须等于答案
        for qid, (_t, _vals, field, want) in EXPECT.items():
            got = page.evaluate("(id) => { var e = document.getElementById(id); return e ? e.value : null; }", field)
            print("  %s %s = %r（期望 %r）" % (qid, field, got, want))
            if got != want:
                fails.append("%s 隐藏字段应为 %r，实际 %r" % (field, want, got))

        # 填空 / 简答：UEditor 的 setContent 应已写回对应 textarea
        for qid, want in (("406012503", ["氧", "H2O"]), ("406012504", ["一切物体"]),
                          ("406012505", ["formula:", chr(92) + "frac", "sqrt{3}"])):
            vals = page.evaluate(
                "(qid) => Array.from(document.querySelectorAll('textarea[name^=\"answerEditor' + qid + '\"]')).map(t => t.value)",
                qid)
            print("  %s UEditor 落库 textarea = %r" % (qid, vals))
            if not any(vals):
                fails.append("%s 填空/简答没有写进 textarea" % qid)
            else:
                joined = " ".join(vals)
                for w in want:
                    if w not in joined:
                        fails.append("%s 期望含 %r，实际 %r" % (qid, w, vals))

        browser.close()

    _restore(old_pending)
    _restore_report(old_report)
    if fails:
        print("\nFAIL:")
        for f in fails:
            print("  - " + f)
        return 1
    print("PASS e2e_dowork 6/6 OK (extract, types, options, judge, UEditor, formula, hidden fields, qid align)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
