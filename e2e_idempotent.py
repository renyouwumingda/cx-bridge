# -*- coding: utf-8 -*-
"""幂等回归：重复点「提取/开始做题」不能把上一轮答案弄丢。

覆盖：
  1. 同一批题登记两次 → 第二次不换 task、不清答案；
  2. 有了答案后再登记同一批题 → reused=True / ready=True，answers.json 原样保留；
  3. 换了一批题（指纹变化）→ 旧答案归档到 answers.prev.json，不再冒充新答案。

用法（服务端要和测试用同一个数据目录）：
    CXD_DATA_DIR=$(mktemp -d) CX_PORT=8791 python server.py  &
    CXD_DATA_DIR=同上 CX_BRIDGE=http://127.0.0.1:8791 python e2e_idempotent.py
"""
import json
import os
import pathlib
import sys
import time
import urllib.request

BRIDGE = os.environ.get("CX_BRIDGE", "http://127.0.0.1:8790")
DATA = pathlib.Path(os.environ["CXD_DATA_DIR"]) if os.environ.get("CXD_DATA_DIR") else pathlib.Path(__file__).parent
PENDING = DATA / "pending.json"
ANSWERS = DATA / "answers.json"
PREV = DATA / "answers.prev.json"


def get(path):
    with urllib.request.urlopen(BRIDGE + path, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def post(path, body):
    req = urllib.request.Request(BRIDGE + path, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def check(cond, msg):
    if not cond:
        print("FAIL " + msg)
        sys.exit(1)
    print("ok   " + msg)


def main():
    QS = [{"id": "9001", "stem": "1+1", "type": "single"},
          {"id": "9002", "stem": "水的化学式", "type": "blank"}]

    for p in (PENDING, ANSWERS, PREV):
        if p.exists():
            p.unlink()

    r1 = post("/extract", {"questions": QS})
    check(r1["ok"] and not r1.get("reused"), "首次登记：新 task %s" % r1["task_id"])
    task1 = r1["task_id"]
    check(bool(r1.get("fingerprint")), "登记带指纹 %s" % r1.get("fingerprint"))

    r2 = post("/extract", {"questions": QS})
    check(r2["task_id"] == task1, "同批题再登记：task 不变")

    pend = json.loads(PENDING.read_text(encoding="utf-8"))
    ANSWERS.write_text(json.dumps({
        "task_id": pend["task_id"], "fingerprint": pend["fingerprint"],
        "answers": {"9001": {"ok": True, "answer": ["B"]},
                    "9002": {"ok": True, "answer": ["H2O"]}},
    }, ensure_ascii=False), encoding="utf-8")

    a1 = get("/answers")
    check(a1.get("ready") and a1.get("count") == 2, "/answers ready 且 2 条")

    r3 = post("/extract", {"questions": QS})
    check(r3.get("reused") and r3.get("ready"), "有答案后再登记：复用且 ready")
    check(r3.get("answered") == 2, "复用答案数 2")
    a2 = get("/answers")
    check(a2.get("ready") and set(a2["answers"]) == {"9001", "9002"}, "答案没被清空")

    r4 = post("/extract", {"questions": QS + [{"id": "9003", "stem": "新题"}]})
    check(not r4.get("reused") and r4["task_id"] != task1, "换题后：新 task")
    check(PREV.exists(), "旧答案归档到 answers.prev.json")
    a3 = get("/answers")
    check(not a3.get("ready"), "换题后旧答案不冒充新答案")

    print("\nPASS 幂等回归 7 项")
    return 0


if __name__ == "__main__":
    sys.exit(main())
