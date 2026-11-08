# 把 cx-bridge 的 MCP 服务注册进 DSH（desktop + web 两个 profile），幂等，先备份再校验。
import io
import os
import shutil
import sys
import time

import yaml

ROOT = r"C:\Users\10183\.dsh\profiles"
BLOCK = """# === cx-bridge MCP BEGIN ===
- insert:
    - id: mcp-cx-bridge
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: cx-bridge
        transport: stdio
        command: 'C:\\node-v24.14.0-win-x64\\node.exe'
        args:
          - 'C:\\Users\\10183\\Desktop\\ds\\cx-bridge\\cx-mcp.js'
        toolCallTimeoutMs: 120000
# === cx-bridge MCP END ===
"""


def has_entry(doc):
    for item in doc or []:
        for key in ("insert", "append"):
            for e in item.get(key) or [] if isinstance(item, dict) else []:
                if isinstance(e, dict) and e.get("id") == "mcp-cx-bridge":
                    return True
        if isinstance(item, dict) and item.get("id") == "mcp-cx-bridge":
            return True
    return False


ok = True
for profile in ("desktop", "web"):
    path = os.path.join(ROOT, profile, "cordis.patch.yml")
    text = io.open(path, encoding="utf-8").read()
    doc = yaml.safe_load(text)
    if has_entry(doc):
        print(f"{profile}: 已注册，跳过")
        continue
    stamp = time.strftime("%Y%m%d-%H%M%S")
    bak = f"{path}.bak-cxbridge-{stamp}"
    shutil.copy2(path, bak)
    new = text
    if not new.endswith("\n"):
        new += "\n"
    new += "\n" + BLOCK
    parsed = yaml.safe_load(new)
    if not has_entry(parsed):
        print(f"{profile}: 写入后校验失败，已回滚")
        shutil.copy2(bak, path)
        ok = False
        continue
    io.open(path, "w", encoding="utf-8", newline="\n").write(new)
    print(f"{profile}: 已追加 mcp-cx-bridge 条目（备份 {os.path.basename(bak)}），YAML 校验通过")
    print(f"  条目总数 {len(parsed)}")
sys.exit(0 if ok else 1)
