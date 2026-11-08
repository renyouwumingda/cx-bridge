# 安装说明（给别人的版本）

这份文档只讲**从零装起来**。项目是干什么的见 [README.md](README.md)，改动历史见 [docs/DEVLOG.md](docs/DEVLOG.md)。

> 一句话：浏览器脚本负责「读页面 + 写页面」，本地 Python 服务负责「传题 + 传答案」，DSH 插件（MCP）负责「让 AI 拿到题」。三样缺一不可。

---

## 1. 你需要准备什么

| 项 | 要求 | 说明 |
|---|---|---|
| 系统 | **Windows 10 / 11 x64** | 已实测。Linux/macOS 理论上能跑 Python 与 Node 部分，但 `.vbs` 常驻、开机自启、路径写法都是 Windows 的，未测 |
| Python | **3.10+**，`python` 在 PATH | `server.py` 只用标准库，不需要 `pip install` 任何东西 |
| Node.js | **20+**（DSH 自带的 node 也行） | `cx-mcp.js` 零依赖 |
| DSH | 能正常启动的 DeepSeek Harness | 插件走它的 `plugin_manager` 安装 |
| 浏览器 | Chrome / Edge + **脚本猫 ScriptCat** 扩展 | Tampermonkey 也可以，但必须允许 `GM_xmlhttpRequest` 访问 `127.0.0.1` |
| 模型 | DSH 里能正常对话的任意模型 | 「作答」这一步由你的 AI 完成；不需要额外 key |
| （可选） | `OPENCODE_GO_API_KEY` 等 | 只有用面板上的「开始做题」（自动起 headless 会话）才需要，见 §5 |

磁盘占用：代码 < 1 MB，运行时只有几个 JSON 和一个日志。

---

## 2. 目录里都有什么

```
cx-bridge/
├── server.py               本地桥接服务（127.0.0.1:8790），题目/答案队列、起做题会话、日志
├── cx-mcp.js               MCP 服务（stdio，零依赖），4 个工具：cx_status / cx_take_questions / cx_submit_answers / cx_report
├── cx-agent.user.js        浏览器脚本（脚本猫），提取题目 + 回填答案 + 结构诊断
├── dsh-bundle/             DSH 插件包（package.json + cordis.patch.yml + locale + icon + index.js）
├── start-hidden.vbs        Windows 无窗口后台起服务
├── install-autostart.ps1   把服务加进开机启动
├── fixture*.html           离线测试页（不需要学习通账号）
├── e2e_*.py / test_server.py / sandbox_sim.py  测试（跑测试前必须设 CXD_DATA_DIR，见 §7）
└── README.md / INSTALL.md / docs/DEVLOG.md
```

数据文件（运行时生成，**不要提交/外发**）：`pending.json`、`answers.json`、`answers.prev.json`、`last-report.json`、`fill-report.json`、`agent-state.json`、`agent-solve.log`、`server.*.log`。

---

## 3. 安装：四步

### 3.1 拿代码

```bash
git clone https://github.com/renyouwumingda/cx-bridge
cd cx-bridge
```

或者从 Releases 下载 zip 解压（效果一样）。

### 3.2 起本地服务

```bash
python server.py
```

看到 `cx-bridge listening on http://127.0.0.1:8790` 即可。验证：

```bash
curl http://127.0.0.1:8790/ping
# {"ok": true, "engine": "agent", "model": "deepseek-flash", "key_loaded": false, "data_dir": "..."}
```

想让它常驻（推荐，否则关掉终端就断了）：

```powershell
# 无窗口后台运行
cscript //nologo start-hidden.vbs
# 加开机自启（可重复执行，不会重复加）
powershell -ExecutionPolicy Bypass -File install-autostart.ps1
```

### 3.3 装浏览器脚本

1. 先装脚本猫扩展；
2. 浏览器地址栏打开 `http://127.0.0.1:8790/cx-agent.user.js` —— 脚本猫会弹安装页，点「安装」；
3. 打开学习通作业作答页，右下角出现 `cx-bridge` 浮窗（显示版本号）就成功。

> 面板只注入作业页（`.../work/doHomeWorkNew`、`.../work/dowork` 等）和本地 `fixture*.html`。别的页面看不到是正常的。
> 如果不小心点了浮窗的 ×，刷新页面就回来了。

### 3.4 装 DSH 插件

**先改两处绝对路径**（换成你自己机器上的真实路径，`dsh-bundle/cordis.patch.yml`）：

```yaml
- insert:
    - id: dsh-cx-bridge
      name: 'dsh-cx-bridge'
    - id: mcp-cx-bridge
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: cx-bridge
        transport: stdio
        command: 'C:\你的路径\node.exe'            # ← 改成你的 node
        args:
          - 'C:\你的路径\cx-bridge\cx-mcp.js'      # ← 改成你的 cx-mcp.js
        toolCallTimeoutMs: 120000
```

然后在 DSH 里装（**不要**手写 profile 的 `cordis.patch.yml`）：

```
plugin_manager(action: "install_bundle", target: "C:\\你的路径\\cx-bridge\\dsh-bundle")
```

看到 `"enabled": true` 后**重启 DSH**（完全退出再打开）。

重启后验证三件事：

1. 设置 → 插件 → 已安装 → 搜「**学习通答题桥**」，有一张卡片，可以开关；
2. 任意会话的工具列表里有 `cx_status` / `cx_take_questions` / `cx_submit_answers` / `cx_report`；
3. 在会话里让我调一次 `cx_status`，返回 `{"pending": null, "answered": null}` 之类而不是报错。

> 旧方案：`python install_mcp.py` 会直接往 profile 里写 MCP 行。它现在只是兼容入口，装了**不会**在设置里显示成插件卡片，建议用上面的 bundle。

---

## 4. 用起来

**方式一（手动，最稳）**：作业页点「**提取**」→ 把面板上的题数/题型看一眼 → 在 DSH 会话里说「作答」→ AI 用 `cx_take_questions` 取题、`cx_submit_answers` 交答案 → 页面轮询到答案后自动回填 → 自己核对 → 自己点提交。

**方式二（一键）**：作业页点「**开始做题**」→ 脚本提取并登记 → 服务端起一个新的 DSH headless 会话做题 → 自动回填。需要 §5 的配置。

两种方式都**不会**替你交卷。

回填结果可以在服务端查：

```bash
curl http://127.0.0.1:8790/fill-report
cd cx-bridge && tail -20 agent-solve.log
```

---

## 5. 可选：「开始做题」的 headless 配置

`dsh --profile headless` 默认没有模型 provider、也没有 MCP。要让一键流程工作，在
`~/.dsh/profiles/headless/cordis.patch.yml` 里加（**换成你自己的 provider / key 环境变量**）：

```yaml
- id: llm-pi-ai
  config:
    providers:
      opencode-go:
        models:
          deepseek-v4.1-flash:
            contextWindow: 1000000
            maxTokens: 384000
            input: [text, image]
        apiKeyEnv: OPENCODE_GO_API_KEY

- id: agent-default-model
  config:
    provider: opencode-go
    model: deepseek-v4.1-flash
    reasoningEffort: low

- insert:
    - id: mcp-cx-bridge
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: cx-bridge
        transport: stdio
        command: 'C:\你的路径\node.exe'
        args:
          - 'C:\你的路径\cx-bridge\cx-mcp.js'
        toolCallTimeoutMs: 120000
```

验证：

```bash
dsh headless "调用 cx_status 看看有没有待答题目"
```

> 不想配也可以：跳过这一节，用 §4 的方式一手动做。
> server.py 里还可以用环境变量覆盖：`CX_DSH_CMD`（dsh 可执行文件）、`CX_DSH_PROFILE`（默认 headless）、`CX_DSH_CWD`（做题会话的工作目录）。

---

## 6. 常见问题

| 现象 | 原因 / 处理 |
|---|---|
| `curl 127.0.0.1:8790/ping` 连不上 | 服务没起。`python server.py` 或 `cscript //nologo start-hidden.vbs`；看 `server.err.log` |
| 端口被占 | `CX_PORT=8791 python server.py`，并让脚本指向新端口（脚本里 `BRIDGE` 常量） |
| 作业页右下角没有面板 | ① 不是作业作答页；② 脚本猫里确认「学习通 AI 助手（cx-bridge）」是启用状态且版本一致；③ 点过 × → 刷新 |
| 设置 → 插件里没有卡片 | ① 装完没重启；② `cordis.patch.yml` 的两处路径写错（插件仍在但启动失败）；③ 装到了别的 profile |
| 会话里没有 `cx_*` 工具 | 同上；重启后在工具列表里找 `mcp__cx-bridge__` 前缀 |
| 点「开始做题」提示「还没有题目」 | 先在作业页点「提取」，或直接用「开始做题」让它自己提取 |
| 面板一直「等答案」 | 做题会话可能退出了：看 `http://127.0.0.1:8790/logs` 和 `agent-solve.log`；也可以点「回填」用已有答案 |
| 回填 0 道 / 点击后未生效 | 页面类型不对（「作业详情/查看」页不能作答）；或页面结构改版，把那次的 `last-report.json` 发出来 |
| 填空显示「公式插件不可用，已按纯文本写入」 | 该页面没有公式编辑器；答案会以纯文本写入，可能判错 |
| 面板提示「页面用了字体加密」 | 只检测不解密（解密需要对方的外部映射表），这次答案别信 |
| 考试页（iframe + 滑块验证码） | 不支持，也不打算支持 |

---

## 7. 跑测试（可选）

测试会写 `pending.json` / `last-report.json`，**必须**用独立数据目录，避免覆盖真实题目：

```bash
export CXD_DATA_DIR=/tmp/cxb-test CX_PORT=8791   # Windows 用 set / $env:
python server.py &                                # 用同一套环境变量起服务
python test_server.py
python e2e_idempotent.py
python e2e_test.py
```

不设 `CXD_DATA_DIR` 时，这些脚本会直接拒绝运行（安全闸）。

---

## 8. 卸载

```text
plugin_manager(action: "remove_bundle", target: "dsh-cx-bridge")
```

然后：脚本猫里删脚本；删掉开机启动项（`shell:startup` 里的 `cx-bridge.lnk`）；删代码目录。
回退插件安装可以用仓库里的 `rollback-dsh-bundle.ps1`。

---

## 9. 安全与隐私

- 服务只监听 `127.0.0.1`，不对外网开放；不向任何第三方上传题目或答案；
- 不自动交卷、不自动签到、不改成绩；
- 运行时文件（`pending.json` / `answers.json` / `last-report.json` 等）含题目与答案，别提交、别外发；
- 本项目 MIT，仅用于学习辅助；因使用造成的后果由使用者自负。
