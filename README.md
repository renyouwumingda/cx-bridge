# cx-bridge

> 把「学习通作业」的读题与回填交给浏览器脚本，把「做题」交给你自己的 AI（DSH / 任意 MCP 客户端）。
> 本机桥接、不自动提交、不收集任何数据。

一个三段式的小工具：

- **浏览器脚本**（脚本猫 / 篡改猴）：识别作业页结构、提取题目（含题干图片）、按答案点选项 / 填 UEditor、回填后上报结果；
- **本地桥接服务**（`127.0.0.1:8790`，Python 标准库，无第三方依赖）：题目队列、答案队列、起做题会话、日志；
- **MCP 服务**（`cx-mcp.js`，stdio，零依赖）：让你在 AI 客户端里用 4 个工具直接取题、交答案。

做题由**你自己的模型**完成（默认：DSH 的 `dsh --profile headless` 起一个新会话），服务端不持有任何 API Key、不联网。

## 为什么这么切

浏览器里拿不到你的登录态与题型上下文给模型；模型又够不到 DOM。中间加一层本地 HTTP + MCP，就能做到：

```
学习通页面（已登录）
   │  脚本提取题目（题干 / 选项 / 图片）
   ▼
127.0.0.1:8790  桥接服务  ── pending.json
   │                        answers.json
   │  MCP (stdio)
   ▼
你的 AI（DSH 会话）── 取题 → 作答 → 交答案
   │
   ▼
脚本轮询 → 回填页面 → 上报 /fill-report
```

不自动交卷；脚本只做「提取 + 填写」。

## 快速开始

### 1. 起服务

```bash
python server.py
# 看到 cx-bridge listening on http://127.0.0.1:8790 即可
```

Windows 想后台常驻：双击 `start-hidden.vbs`（无窗口，日志写 `server.out.log`），或
`powershell -ExecutionPolicy Bypass -File install-autostart.ps1` 加开机自启。

### 2. 装脚本

浏览器打开 `http://127.0.0.1:8790/cx-agent.user.js`，脚本猫会弹安装页，点「安装」。
装完打开作业页，右下角出现 `cx-bridge` 面板即成功。

### 3. 用

作业作答页（`.../work/doHomeWorkNew` 一类）→ 面板点 **「开始做题」**：

1. 提取题目 → 报名到服务端；
2. 服务端起一个新的 DSH 会话做题（默认 `deepseek-v4.1-flash`，思考 `low`）；
3. 页面轮询到答案后**自动回填**（选项、判断、填空、简答、公式都覆盖）；
4. 回填完把结果上报 `GET /fill-report`。

也可以不用「开始做题」：点「提取」→ 在 AI 会话里说一句「作答」→ 你自己/助手通过 MCP 交答案 → 页面自动回填。

## MCP 工具

在 DSH（或其他 MCP 客户端）里注册 `cx-mcp.js` 后可用：

| 工具 | 作用 |
| --- | --- |
| `cx_status` | 服务是否在线、有没有待答题目、已有几条答案 |
| `cx_take_questions` | 取走当前待答题目（题干、选项、图片 dataURL） |
| `cx_submit_answers` | 写入答案（**合并写入**，可分批；页面轮询到即回填） |
| `cx_report` | 最近一次页面结构诊断（选择器校准用） |

注册示例（DSH profile 的 `cordis.patch.yml`）：

```yaml
- insert:
    - id: mcp-cx-bridge
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: cx-bridge
        transport: stdio
        command: '/absolute/path/to/node'
        args: ['/absolute/path/to/cx-mcp.js']
        toolCallTimeoutMs: 120000
```

仓库里的 `install_mcp.py` 会自动写进 `~/.dsh/profiles/{desktop,web}/cordis.patch.yml`（先备份、再 YAML 校验、幂等）。

## 关键设计

- **题目指纹**：对题目 id 集合算 `sha1`，写进队列。同一批题重复点「开始做题」**不会**新开 task、不会清空已有答案。
- **合并写入**：`cx_submit_answers` 读旧答案再叠加，分批提交（模型一次交 8 题）不会互相覆盖；答案与题目按指纹绑定，换页才会作废。
- **缺题续跑**：一轮结束仍缺题时自动再起一轮（最多 3 轮），只做缺的。
- **事件化等待**：页面每 2s 轮询 `/answers`，答案一落盘就回填，不用等固定超时。
- **结构诊断**：每次提取把页面结构写 `last-report.json`（含前 40 个题块的 DOM 片段、题型命中数、公式插件探测），页面换皮时拿它改选择器。
- **测试隔离**：所有数据文件走 `CXD_DATA_DIR`；测试脚本不设这个变量会直接拒绝运行，避免覆盖真实作业。

## 配置

| 环境变量 | 默认 | 说明 |
| --- | --- | --- |
| `CX_PORT` | `8790` | 服务端口 |
| `CXD_DATA_DIR` | 本目录 | 数据目录（题目/答案/日志）；测试必改 |
| `CX_DSH_CMD` | PATH 里的 `dsh` | 做题会话用的 DSH 命令 |
| `CX_DSH_PROFILE` | `headless` | 做题会话的 profile |
| `CX_DSH_CWD` | 本目录的上级 | 做题会话的工作目录 |
| `CX_MODEL` | `deepseek-flash` | 展示/旧直连引擎用的模型名 |
| `CXD_ALLOW_DIRECT` | 未设 | 设为 `1` 才允许旧的直连模型引擎（防误烧额度） |

做题会话的模型与思考强度写在 DSH 的 `profiles/headless/cordis.patch.yml`：

```yaml
- id: agent-default-model
  config: { provider: opencode-go, model: deepseek-v4.1-flash, reasoningEffort: low }
```

## 兼容性与已知限制

已适配：

- 旧版作业页：`.questionLi` + `.stem_answer .answerBg` + `span.num_option`；
- 新版作业页：`.TiMu[data]` + `ul.Zy_ulTop > li` + `input[name="answer<qid>"]`（radio/checkbox），题型读 `answertype` 隐藏字段；
- 填空 / 简答：UEditor `setContent + sync`，写完自动点「保存」；公式用 `$...$` 包 LaTeX，通过 TEX 插件插入，插件不可用时降级纯文本并在日志说明；
- 题干图片：随题目上传 dataURL（默认 8s 超时，不拖死整次提取）。

未适配：

- **考试页**（题目在 iframe 内、有滑块验证码）；
- **连线题 / 拖拽题**；
- **选项本身是图片**的题；
- 字体加密页面只能检测（`fontEncrypted: true`），不能解密；
- 提交动作永远留给人工。

## 测试

```bash
# 用隔离目录 + 独立端口跑一份服务
CXD_DATA_DIR=/tmp/cxb-test CX_PORT=8791 python server.py &
export CXD_DATA_DIR=/tmp/cxb-test CX_PORT=8791 CX_BRIDGE=http://127.0.0.1:8791

python test_server.py        # 服务端单元测试（19 项）
python e2e_idempotent.py     # 幂等：连点两次不丢答案、换题不冒充旧答案
python e2e_test.py           # 模拟页端到端（选择/判断/填空/多选/简答/图片）
python e2e_real.py           # 旧版真实标记端到端
python e2e_dowork.py         # 新版作答页标记（UEditor + 保存 + 公式）
python e2e_newstyle.py       # 新版选项结构（Zy_ulTop + input[name=answer*]）
python sandbox_sim.py        # 脚本猫沙箱下的端到端
```

浏览器相关测试用 Playwright（headless Chromium）。`probe_*.py` 只需要本地 HTML 快照，不用登录。

## 目录

```
cx-agent.user.js   浏览器脚本（提取 / 回填 / 上报）
server.py          本地桥接服务
cx-mcp.js          MCP 服务（stdio）
install_mcp.py     注册进 DSH profile
start.bat / start-hidden.vbs / install-autostart.ps1   启动与自启
test_server.py / e2e_*.py / sandbox_sim.py / probe_*.py 测试与探针
fixture*.html      各种页面结构的测试页
快速开始.md        3 步上手
docs/DEVLOG.md     开发日志（逐版做了什么、踩了哪些坑、实测数据）
```

数据文件（`pending.json` / `answers.json` / `last-report.json` / `fill-report.json` / `*.log`）都在 `.gitignore` 里，不会进仓库。

## 安全与免责

- 服务只监听 `127.0.0.1`，不联网、不上传任何题目或答案；除「开始做题」会调用本机 `dsh` 外，不做外部请求。
- 不自动提交作业；提交前请自己核对答案（做题模型可能算错，尤其是带图的方向/符号判断）。
- 仅用于**你有权限访问**的课程作业；请遵守学校与平台的使用规则。
- 仅供学习交流，使用风险自负。

## 许可

MIT（见 `LICENSE`）。第三方项目只借鉴了做法，未复制其代码；调研材料不随仓库分发。

## 作为 DSH 插件安装

`dsh-bundle/` 是一个标准的 DSH bundle（`package.json` + `cordis.patch.yml` + `locale/` + `icon.svg`），
它把本项目的 MCP 服务接进 Harness，装完会出现在「已安装的插件」里，可开关。

用 `plugin_manager` 安装（不要手写 profile 的 `cordis.patch.yml`）：

```
plugin_manager(action: "install_bundle", target: "<仓库>/dsh-bundle")
```

装完需要重启 DSH 生效。重启后在「设置 → 插件 → 已安装」里能看到一张卡片：

- 显示名取自 `dsh-bundle/locale/zh.json` 的 `meta.title`（**学习通答题桥**），搜索 `cx` 或 `学习通` 都能找到；
- 卡片上的开关控制的是 bundle 里的 `dsh-cx-bridge` 这一行（一个不注册服务的空入口），
  MCP 连接本身是同一 bundle 的第二行 `mcp-cx-bridge`，关掉整个 bundle 两者一起失效；
- 真正的功能证据是会话工具列表里的 `cx_status` / `cx_take_questions` / `cx_submit_answers` / `cx_report`。

> 为什么要有那个「空入口」：如果 bundle 里只有一条 MCP 连接行，它装得上、工具也能用，
> 但设置界面不会把它渲染成插件卡片（实测），所以补了一行 `index.js`（`export const name` + 空的 `apply`，整段 try/catch）。

换机器时改 `dsh-bundle/cordis.patch.yml` 里的两处绝对路径
（`command` 指向 node，`args[0]` 指向 `cx-mcp.js`）。
