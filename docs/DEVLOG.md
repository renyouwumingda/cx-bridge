## v0.6.6（2026-11-08）视频卡住看门狗

- `handleTask` 里给每个 video 记 `{cur, at, warned}`：25s 内 `currentTime` 不动 → 日志「视频卡住 Ns（时间不动），重试播放」，再点一次播放按钮/调 `play()`；90s 仍不动 → 「视频一直不动，跳过这个任务点」直接返回，后续任务点/下一章继续。
- 两个阈值可用 `window.__CXB_STALL_WARN_MS` / `__CXB_STALL_SKIP_MS` 覆盖（测试用，生产不设）。
- fixture 增加 `?stall=1`（video 时间永远为 0）；e2e_chapter 增加阶段 C 断言，13 项全 PASS。
- 全量回归（隔离 8796）：test_server 19、e2e_test、e2e_real、e2e_dowork 6/6、e2e_newstyle 2/2、sandbox_sim、e2e_idempotent 7 项全 PASS。

## v0.6.5（2026-11-08）诊断加同源 iframe / 继续上次 / 上次上报

- `chapterDiag()` 增加 `docs`（同源文档数）、`videosInDocs`（含 iframe 内的 video）、`nextBtn`、`tasks`，上报内容能直接看出「任务点在不在 iframe 里」。
- `GET /report`：服务端返回最近一次结构上报的摘要（url/at/kind/count/diag/fontEncrypted/formula），没有则 `{"ok":false,"reason":"还没有结构上报"}`。
- 概览页新增「上次上报」一行；章节页新增「继续上次」按钮（读 GM 里的进度直接续跑，不要求上次仍在运行）。
- 回归（隔离 8795 + 生产 8790 重启）：e2e_chapter 12 项、e2e_test、e2e_real、e2e_dowork 6/6、e2e_newstyle 2/2、sandbox_sim、e2e_idempotent 7 项、test_server 19 项全 PASS；`GET /report` 实测 before/after 正常。

## v0.6.4（2026-11-08）刷章节只刷视频/文档，播放器兜底

- 任务点名字命中 `测验|作业|考试|讨论|投票|问卷|互评|章节检测|签到` 时直接跳过并记日志——这类任务点只点开不交也会产生「已开始」记录，宁可不动。
- 视频 `play()` 后仍 `paused` 时，按 `.vjs-big-play-button / .xgplayer-start / .prism-big-play-btn / [class*="bigPlay"] / [class*="play-btn"]` 补点播放按钮，再试一次 `play()`（各学校播放器 DOM 不同）。
- fixture 增加一个「2.2 章节测验（10 题）」任务点；e2e_chapter 增加「跳过测验类任务点」断言，12 项全 PASS。
- 全量回归（隔离 8794）：test_server 19、e2e_test、e2e_real、e2e_dowork 6/6、e2e_newstyle 2/2、sandbox_sim、e2e_idempotent 7 项全 PASS。

## v0.6.3（2026-11-08）刷章节兼容新版页面 + 自动上报结构

- 章节列表：`.chapter_item` 找不到时退回 `h3`，并按九九助手的判据用 `outerHTML`（含 `data-cid="chapterId=…"` 或 `onclick` 带 `toOld`）过滤；同一章用 chapterId 去重。
- 打开章节：先 `el.click()`，再点它内部的 `a`（老版 `.chapter_item` 的链接常挂在里面）。
- 概览页新增「刷章节」一行：列表页显示 已完成 N/M，学习页显示 任务点 N/M，运行时注明第几章。
- 进课程页/学习页 1.5s 后自动 `reportChapter()`（每 URL 每标签页一次，`sessionStorage` 去重），`last-report.json` 的 `kind` 为 `chapter`。
- fixture 增加 `?mode=course&v=new`（h3 + chapterId 结构）；e2e_chapter 增加该用例，11 项全 PASS。
- 全量回归（隔离 8793）：test_server 19、e2e_test、e2e_real、e2e_dowork 6/6、e2e_newstyle 2/2、sandbox_sim、e2e_idempotent 7 项全 PASS。

## v0.6.2（2026-11-08）刷章节跨页续跑

- 学习页刷完本章、且没有「下一节」按钮时：记下章节列表地址，`chapterIdx += 1`，跳回列表继续。
- 新增 `chapKeepGoing`：点「下一节」或回列表前不再在 `finally` 里把 `running` 清成 false——修「跳到下一页就不自动继续」。
- 自动续跑从只认「学习页」扩到「学习页 + 章节列表页」。
- e2e_chapter 改成两阶段：A 只断言 URL 循环（列表 → 第2章 → 列表 → 第3章）与进度，B 单独预置「无 listUrl 的进行中状态」断言 自动继续/任务点/2×/播完，避开页面跳转时的日志竞态；10 项全过。
- 全量回归（隔离 8791）：test_server 19、e2e_test、e2e_real、e2e_dowork 6/6、e2e_newstyle 2/2、sandbox_sim、e2e_idempotent 7 项全 PASS。


## v0.6.1（2026-11-08）刷章节按真实结构加固

- 任务点选择器扩到 7 套（九九助手里 `.posCatalog_select`/`.menulist-menu-title`/id 含 `cur` 的写法都收进来）。
- 视频查找改成递归扫同源 iframe（depth 2），`#iframe_content` 里再嵌播放器也能找到。
- 新增「诊断结构」按钮：把选择器命中数 + 候选节点 HTML 上报到 `last-report.json`（kind=chapter），页面打开时也会在日志里打印一次命中数。
- 下一节按钮兼容 `#prevNextFocusNext` 与文本「下一节/下一个/下一章」。
- e2e_chapter 改用「任务点 → iframe → video」的真实嵌套结构，8 项断言仍全过；其余回归同 v0.6.0。

## v0.6.0（2026-11-08）刷章节 + 控制台改版

- 面板拆成「答题 / 刷章节 / 概览」三页签；日志加了复制/清空；概览显示桥接状态、数据目录、task_id、题数/已答数。
- 新增刷章节：章节列表跳过已完成 → 打开未完成章节 → 任务点逐个处理（视频静音 2×、文档停留计时）→ 自动下一节；进度存 GM，跳页后自动继续；随时可停。
- 做题会话工作目录从「桌面」改为 `cx-bridge/.work`（`DSH_CWD` 默认值），桌面原先的 `cx_imgs/`、`cx_work/` 已移进 `.work/`。
- 新增 `fixture_chapter.html` + `e2e_chapter.py`：章节列表 → 跳转 → 自动继续 → 视频播完，8 项断言全过。
- 回归：test_server 19 OK；e2e_test / e2e_real / e2e_dowork 6/6 / e2e_newstyle 2/2 / sandbox_sim / e2e_idempotent 7 项全 PASS。
# 开发日志（cx-bridge）

> 这份文档是从仓库早期的 README 原样搬过来的：逐版记录做了什么、踩了哪些坑、实测数据与页面结构笔记。
> 面向使用者的说明请看根目录 [README.md](../README.md)。

# cx-bridge — 学习通 AI 答题（浏览器脚本 + 本地桥接服务）

> 为什么重写：现成的 `chaoxing-ai-assistant`（zhu-hailin）在 mooc2 作业页上有**两道硬门禁**——
> 必须 40/40 全部分析完成、且不能是「暂存恢复的只读结果」才允许预填。
> 学习通作业页的自动存草稿会周期性改动 DOM，脚本的快照校验因此中断分析，
> 40 道永远凑不满 ⇒ 永远不填。这个门禁是它的产品设计，不是配置错误，改不动就只能换实现。

本项目的做法：**把「读页面 / 点选项」留在浏览器脚本里，「做题」交给本地服务**，
两边用 HTTP 通信。我没有装任何扩展、没有占用你的浏览器，也不依赖脚本自己的任何门禁。

---

## 1. 架构

```
┌──────────────────────────── 浏览器（脚本猫 · 用户脚本） ────────────────────────────┐
│  cx-agent.user.js                                                                  │
│                                                                                    │
│  ① 提取      遍历 .questionLi，取题干/选项字母/选项文字，题干图片转 base64         │
│  ② 请求      POST http://127.0.0.1:8790/extract  {questions:[...]}                   │
│  ③ 回填      按题干字母点 span.num_option（页面原生 addChoice）                    │
│              填空题写 input / textarea / UEditor iframe                           │
│  ④ 人审      永不自动提交；面板上显示每题答案与解析                                │
└───────────────────────────────────┬────────────────────────────────────────────────┘
                                    │ JSON over HTTP（仅 127.0.0.1，不联网外传）
┌───────────────────────────────────▼────────────────────────────────────────────────┐
│  server.py（Python 标准库，无第三方依赖）                                          │
│                                                                                    │
│  POST /extract  题目落盘 pending.json，不调任何模型                               │
│  GET  /answers  把 answers.json 交给脚本（校验 task_id，不给上一轮的旧答案）      │
│  POST /report  保存脚本抓到的原始结构，便于校准选择器                              │
│  GET  /ping    存活检查                                                            │
│  GET  /cx-agent.user.js   直接从这个地址安装脚本                                   │
└────────────────────────────────────────────────────────────────────────────────────┘
```

### 谁来做题：`agent`（默认）vs `direct`

| 引擎 | 谁在答 | 花不花额外 API 额度 |
|---|---|---|
| `agent`（默认） | **DSH 的模型，也就是会话里的助手**。脚本把题目写进 `pending.json`，助手读完作答、写 `answers.json`，脚本轮询取走 | 不花：服务端不持有任何 API Key、不发任何外部模型请求 |
| `direct`（旧行为） | 服务端自己用 `DEEPSEEK_API_KEY` 打 `api.deepseek.com` | 花：每次作答都是真 token |

换成 `agent` 的原因：用户配的模型在 DSH 里，做题就该用**同一个模型**，而不是服务端偷偷直连一个自己从凭据文件里挖出来的 key。

完整流程（`一键做完` 的 `作答` 阶段）：

1. 脚本 `POST /extract` 把题目落盘 → 面板显示「等 DSH 作答…」
2. 你（或脚本面板）跟我说一句「作答」
3. 我读 `pending.json`，用当前会话模型逐题作答，写 `answers.json`
4. 脚本 2 秒一轮询 `GET /answers`，拿到就自动继续回填

### 为什么这样切分

| 决策 | 理由 |
|---|---|
| 做题交给 DSH 侧模型 | 用用户自己配的模型，服务端不存 key、不直连第三方；换模型只在 DSH 里换 |
| 脚本只做 DOM 读写 | 页面结构变化时只改脚本；换模型/换提示词不动脚本 |
| 逐题请求而不是整页打包 | 单题失败不连坐；40 题互不影响（原脚本正是"一处致命错就取消剩下全部"） |
| 不自动提交 | 交卷不可逆，必须人看一眼 |
| 回填用「点 span.num_option」 | 参考 HanKuCha 实测：`div.answerBg` 的坐标点击容易落在文字上不触发，点内层 span 最稳 |

---

## 2. 从同类项目吸收的做法（代码级）

调研对象与结论，原始文件在 `cx-bridge/research/`：

### zhu-hailin/chaoxing-ai-assistant（120★，MIT）— 解析选择器与预填守门
- **mooc2 作业页专属容器**：`.fanyaMarking_left .questionLi.singleQuesId`
  （源码 line 5127 `collect`，`isMooc2HomeworkDocument(doc)` 为真时只认这一套；
  `cx-agent.user.js` 的 `questionContainers()` 就按这个优先级做，先 scoped 再退化到 `.questionLi`、`.TiMu`）。
- **题干选择器**（源码 line 4616）：
  `STEM_SELECTOR = '.Zy_TItle .fontLabel,.Zy_TItle,.question-stem,.question-title,.mark_name,.stem,[data-question-text]'`
  → 取第一个匹配到的元素，`.fontLabel` 优先是因为它只含题干正文、不含题型标签。
- 选项行 `.stem_answer .answerBg`，且必须满足 `row.closest('.questionLi.singleQuesId') === node`
  （line 4741）—— 这条过滤不能省，否则会抓到同页别的题的选项。
- 字母 `.num_option` / 多选 `.num_option_dx`，选项文字 `.answer_p`，`qtype` 在行属性上。
- 它的失败点即本项目要绕开的点：`analysisComplete===false` 时预填按钮直接 disable
  （line 15583 `records.every(r => ['success','skipped'].includes(r.status))`）；
  `restoredReadOnly` 时先 `verifyRestoredAnalysis()` 重验快照，不一致就退出（line 15904）。
- 熔断：`analysisFatalError()` 命中 401/402/403/CFG 类错误 → `stop()` → 剩下队列全部标 `cancelled`（line 3375/3414/3478）。
- **字体加密**：学习通部分文本用自定义字体替换成私用区码位，脚本需要 woff 解密才能读。
  本项目不做解密，改为**检测**：`looksGarbled()` 统计 U+E000–U+F8FF 占比，≥5% 判为乱码，
  提取时在面板告警并在题目上打 `_garbled` 标记 —— 宁可报错也不给错答案。

### HanKuCha/chaoxing-exam-automation（DSH 技能）— 选中态判定与点击目标
- 选中态 = `span.num_option` 的 class 含 `check_answer`；**选项是 toggle**，点已选中项会取消。
- 判断题 `data` = `true|false`；单选/多选 `data` = `A|B|C|D`。
- 直接点 `span.num_option[qid][data]` 最稳；按 `#sigleQuestionDiv_<qid>` 定位题目。

### Trashwbin/MultiAI-Answer-cx（72★，MIT）— 回填节奏与填空处理
- 回填节奏：`scrollIntoView` → 等 500ms → 随机 1000–3000ms → 再填下一题。
  拟人节奏不仅是为了规避风控，也避免连续 DOM 操作触发页面重渲染。
- 填空题：优先 `input`，其次 `textarea[name^="answerEditor"]`，
  最后 UEditor。**v0.3.1 已升级**：不再只改 iframe body / 隐藏 textarea，而是拿到真正的编辑器实例
  `UE.getEditor(<textarea.id 或 name>).setContent('<p>…</p>')` 再 `sync()` —— 学习通只在 `sync()`
  时把内容写回落库字段，光改 textarea 刷新就丢。

---

## 3. 接口约定

### POST /solve

```json
{
  "questions": [
    {
      "id": "57393283_1",
      "type": "single",            // single | multiple | judge | blank
      "stem": "在磁感应强度为B的均匀磁场中…",
      "options": [{"key": "A", "text": "πr²B"}, {"key": "B", "text": "2πr²B"}],
      "images": ["data:image/png;base64,..."]
    }
  ]
}
```

返回：

```json
{
  "ok": true, "model": "deepseek-flash", "total": 40, "solved": 39, "elapsed": 82.4,
  "answers": {
    "57393283_1": {"ok": true, "answer": ["D"], "reason": "磁通量 Φ=B·S·cosα…"}
  }
}
```

- `answer`：选择题返回选项字母数组；填空题按空顺序返回文本数组。
- 单题失败只影响该题（`ok:false` + `error`），不中断整批。

---

## 4. 执行计划与状态

| 步骤 | 内容 | 状态 |
|---|---|---|
| 1 | 调研 3 个同类项目并抽出可复用做法 | ✅ 完成（见第 2 节与 `research/`） |
| 2 | 本地桥接服务 `server.py`（/solve、/report、/ping、脚本分发） | ✅ 完成，已用真实 DeepSeek 请求验证 |
| 3 | 浏览器脚本 `cx-agent.user.js`（提取 / 作答 / 回填 / 面板） | ✅ 完成 |
| 4 | 模拟页（`/fixture`）跑通全链路：提取 → 作答 → 回填 | ✅ 完成，`e2e_test.py` PASS，修掉 4 个真 bug |
| 5 | 真实页面验证：在别人保存的真实作业页快照上跑「提取」 | ✅ 完成（20/20、147/147 全中），修掉第 5 个 bug（`mark_letter` 选项结构） |
| 6 | 加页面结构兜底（换皮/考试页/定制版也能抓） | ✅ 完成，兜底路径与主路径在 3 个真实快照上结果完全一致 |
| 7 | 在**登录状态**的真实作业页跑一次完整回填，按实测校准 | ⏳ 待你的真实页面：v0.3.1 起每次「提取」都会自动存 `last-report.json`，点一次我就能定位「40 题只抓到 5 题」 |
| 8 | 在**脚本猫沙箱**里跑一遍（用户实测报错后补） | ✅ 完成，`sandbox_sim.py` PASS，修掉第 6 个 bug（沙箱 `window` 构造 MouseEvent 抛异常） |

### v0.3.1（2026-11-08）改了什么 —— 借鉴其他刷题脚本后

| 改动 | 为什么（对应的问题） |
|---|---|
| `questionContainers()` 改成**多选择器并集 + 去重 + 去嵌套 + 同源 iframe** | 旧逻辑「某个 scoped 选择器命中 >0 就直接 return」正是「页面 40 题只提取到 5 题」的根源：它只挂了 5 个 `.singleQuesId` 就当成全部 |
| `QID_ID_RE = /^(?:question\|sigleQuestionDiv_)(\d+)$/` 只认数字后缀 id | 避免把 `#questionList` 这类容器误当题目 |
| 题型优先读容器 `typename` 属性 → `input[name^=typeName]` → `.mark_name` 文本 | 考试页/换皮页没有 `Zy_TItle` 时不再把「三、填空题（每题 2 分）」当题干 |
| 选项行补 `.stem_answer .hoverDiv`（复合题小题）；字母识别补 `span[class*=num_option]` | 复合题与 `num_option_dx` 一律认得出 |
| 填空/简答改用 **UEditor 实例** `UE.getEditor(id).setContent('<p>…</p>') + sync()`，selectors 用 `textarea[name^=answerEditor]` | 只改 textarea 不进编辑器 → 刷新即丢，这是「填了没保存」的主因 |
| `fillAll()` 改成**按 qid 对齐**（`byId.get(qid)`），不再按下标配对 | 提取后页面若有增减，按下标会把 A 题答案填进 B 题 |
| 题干图片并行取 + 单图 8s 超时 | 一张坏图不再拖死整次提取（旧版在缺 jQuery 的页面会永久挂住） |
| 新增结构自检：每次提取打印「结构诊断：…」并自动 `POST /report` | 不用你再手动点「导出结构」，真实页面一点就有 `last-report.json` |
| `/solve` 的直连引擎加闸：必须 `CXD_ENGINE=direct` **且** `CXD_ALLOW_DIRECT=1` | 服务端不会在默认配置下悄悄花你的 API 额度 |

自测：`test_server.py` 19 项 OK；`e2e_test.py` / `e2e_real.py` / `sandbox_sim.py` 全 PASS；
新增真实标记 fixture `fixture_dowork.html`（`padBom50 questionLi typename` + `answerBg/num_option` + UEditor + `#answer<qid>`）
全链路 5 题 → 作答 → 回填 **5/5**，隐藏字段读到 `A` / `A` / `true`。
4 份真实页面快照提取：20 / 20 / 147 / 1 题全中（其中「查看详情2」旧版会挂死，现已通过）。

### v0.3.2（2026-11-08）填空里的「公式」

你发的那张截图（工具栏里有 Ω、TEX、U，编辑器里渲染着 `B = μ₀I/(6R) + μ₀I/(4πR)(2−√3)`）说明
你学校的填空题编辑器带 **TEX/公式插件**。这种空写纯文本不行——`\frac{\mu_0 I}{6R}` 会被当成一串字符串判错。

| 改动 | 说明 |
|---|---|
| 答案里带 `$...$` 或 `\frac` `\sqrt` `\mu` 这类 LaTeX 命令 → 走**公式插入** | `insertFormula()` 依次试 `insertformula` / `insertFormula` / `kityformula` / `formula`（`{latex}` 与裸字符串两种参数），再退 `insertHtml` 插 `<img class="kfformula" data-latex="…">`；插完读 `getContent()`，确认内容里出现 `kfformula` / `data-latex` / `katex` 才算真插进去 |
| 插件不可用就退化纯文本，并在回填日志里注明 | 不会一声不响地把 LaTeX 源码当答案填进去，让你误以为填好了 |
| 每次「提取」把 `formulaProbe()` 一起上报 | `last-report.json.formula` 里有 `toolbar`（如 `edui-for-tex`）、`plugins`、`commands`、`hasUE`；真页面确认命令名后再收紧 `insertFormula` |

自测：`fixture_dowork.html` 增加第 6 题（`typename="填空题"` + 支持公式命令的假 UEditor），
`e2e_dowork.py` 全链路 **6/6**，断言落库字段为 `[formula:B=\frac{\mu_0 I}{6R}+…]`。

### v0.3.3（2026-11-08）又扫了几份别的刷题脚本

按「你可以借鉴其他刷题脚本」把剩下的几份也翻了：Khihl-lucky 的单体脚本（547KB）、Chrome 扩展 Fk-Chaoxing 的模块入口、
2018 年的 erya-user.js，以及 Trashwbin 文档里之前没读到第 7/8/11 节。

| 来源 | 借鉴的东西 | 解决什么 |
|---|---|---|
| Khihl-lucky/ChaoXing-AutoAnswer | `tidyQuestion` 清洗规则；`findAnswerTextareas` 三级选择器；判断题文本兜底；`.font-cxsecret` 加密识别 | 题干带「【章节】」「（2.5分）」「(单选题)」会带偏模型；老版页面编辑器不叫 `answerEditor`；部分学校把字换成自定义字体，抓到的字是错的 |
| Fk-Chaoxing（Chrome 扩展） | URL 判页面类型（`work/dowork`、`work/view`、`exam-ans`、`reVersionTestStartNew`）；顶层 frame 提取、子 frame 只做桥 | 在查看/批改页白填一遍、在考试页误操作 |
| Trashwbin（补读 §7/§8/§11） | 填空/简答写完必须点题内「保存」；双层验证（先回读 hidden 字段，再等 10s 强刷读服务端渲染值）；症状→根因表 | 「填了刷新就没」的另一半原因：不是没写进编辑器，是**没点保存** |
| erya-user.js | 考试页题干在 `.TiMu .Cy_TItle`；题干尾部「（X分）」要剥掉 | 考试页/换皮页题干抓不到 |

具体改动：

- 题干清洗 `tidyStem()`（去前置【…】、去「(单选题)」前缀、去尾部「（X分）」），`.Cy_TItle` 加进题干探测；
- 填空编辑器选择器补齐 `.subEditor textarea / .Answer .divText textarea / .stem_answer textarea / .edui-editor textarea`；
- 填空/简答写完后**自动点题内「保存」**（文本含「保存」且不含「提交/交卷」），等 800ms，日志写明「（已点保存）」；
- 页面级字体加密检测 `pageFontEncrypted()`：疑似加密时提取完直接警告「这次答案别信」；
- 页面类型 `pageKind()`：`view` 页提示「没有作答入口，回到作答页」；`exam` 页提示「只提取不提交，保存要你手动点」；
- `last-report.json` 里图片改为体积占位（之前会把整张 base64 塞进去，文件能到几 MB），并新增 `kind` / `fontEncrypted` 字段。

**没抄 / 抄不动的（明确说明）**

- `.font-cxsecret` 的**解密**：Khihl 依赖外部 `Table` 资源 + Typr 字体解析 + `md5(glyphPath)` 映射，
  那张映射表是别人整理的第三方数据。我只做到「检测到就告警」，没做解密（要做等于引入 Typr + 一张外部表）。
- 考试页的保存入口（`saveSingleSelect` / `clickSaveMultiSelect` / `saveBTypeSelect`）与整卷预览提取：
  不在你给的要求里，没做。
- 自动提交/交卷、选词填空拖拽槽、连线/排序题：没做——要么你没要求，要么需要你的真实页面样本才能校准。

自测：`test_server.py` 19 项 OK；`e2e_test.py` / `e2e_real.py` / `sandbox_sim.py` 全 PASS；
`e2e_dowork.py` 6/6（新增「保存按钮确实被点」断言，`window.__cxbSaved` = 1）。

### 文件

| 文件 | 作用 |
|---|---|
| `server.py` | 桥接服务（8790）：`/solve` `/report` `/ping` `/fixture` `/cx-agent.user.js` |
| `cx-agent.user.js` | 浏览器脚本（脚本猫 / 油猴），面板四按钮，永不提交 |
| `fixture.html` | 模拟 mooc2 作业页结构，3 道题，用于自检 |
| `fixture_dowork.html` | **真实作答页标记**的自检页（`padBom50 questionLi` + `typename` + `answerBg/num_option` + UEditor + `#answer<qid>`），5 题，专门用来验回填 |
| `last-report.json` | 每次「提取」自动落盘的页面结构诊断（选择器命中数 + 题目快照），排查漏题就看它 |
| `e2e_test.py` | headless Chromium 端到端测试（注入脚本 → 点按钮 → 断言 DOM） |
| `e2e_real.py` | 同上，跑真实 `mark_letter` 结构的自检页（含隐藏字段兜底） |
| `sandbox_sim.py` | 模拟**脚本猫沙箱**（`window` 不是真 Window）跑全链路，专抓只有用户脚本管理器里才暴露的问题 |
| `test_server.py` | 服务端单测 19 项，不联网 |
| `probe_real_page.py` | 在真实页面快照上离线跑「提取」，验证选择器 |
| `probe_snapshots.py` | 对比多个快照的结构计数，挑合适的样本 |
| `research/` | 三个同类项目的原始代码/文档快照 + `real-page/` 真实作业页 HTML |


### 已实测（2026-11-07）

| 用例 | 输入 | 结果 | 耗时 |
|---|---|---|---|
| 单选题（用户作业第 1 题原题） | 半球面磁通量四选项 | `A`（πr²B）✓，附解析 | 10.6s（串行，单题） |
| 填空题 | 水的化学式 | `H2O` ✓ | — |
| **图片题** | 560×180 PNG（题干+选项全在图里） | `B`（左手定则）✓ | **1.6s** |
| 混合 6 题（单选/判断/填空/**多选**/**简答**/**图片**） | 自检页 | **6/6 全对、6/6 回填成功**，并发 3 | **5.7s** |

→ 40 题的预期耗时：**40 秒左右**（并发 3，每题约 3s，含思考 token）。


### 自测（不联网，可随时重跑）

```bash
cd <repo>
PYTHONIOENCODING=utf-8 python test_server.py   # 19 项，全绿
```

覆盖：答案 JSON 解析（裸 JSON / ```json 围栏 / 前后夹话 / 字符串答案 / 数字答案 / 空答案 / 非 JSON 报错 /
reason 截断 300 字）、消息构造（纯文本 / 带图变 parts / 图片上限 4 张 / 非 data URL 忽略）、
`solve_one` 重试（首次失败二次成功、两次都失败给出 error）。

脚本侧：`node --check cx-agent.user.js` 通过。

链路自检（不需要真作业页、不需要模型）：打开 `http://127.0.0.1:8790/fixture`，
`curl -s -o /dev/null -w "%{http_code}"` 应为 200，页面里应有 3 个 `.questionLi.singleQuesId`。

### 真实页面快照验证（不需要登录、不联网）

从 GitHub 上找到别人 Ctrl+S 保存下来的**真实学习通作业页**（`mooc2/work/dowork`、`作业详情`），
存到 `research/real-page/`，用 Playwright 离线加载、注入脚本、只跑「提取」：

```bash
cd <repo>
PYTHONIOENCODING=utf-8 python probe_real_page.py "research/real-page/123qwe55aa_analytic-chemistry__作业详情.html"
```

| 快照 | 页面类型 | 提取结果 |
|---|---|---|
| `doWork-367k.html` | 真实 dowork（论述题，367KB） | 1 道 essay，题干干净 |
| `123qwe55aa_…作业详情.html` | 真实作业详情，20 题 | **20/20 抓到**：single 11、multiple 3、blank 3、judge 3 |
| `2443045255_shool__作业详情.html` | 真实作业详情，147 题 | **147/147 抓到**：single 89、blank 28、judge 29、essay 1 |

这一步逼出并修掉了第 5 个 bug（也是**最要命的一个**）：

| bug | 表现 | 修法 |
|---|---|---|
| 选项标签写死成 mooc2 结构 | 真页面的选项是 `<ul class="mark_letter"><li>A. xxx</li>`，既没有 `.answerBg` 也没有 `.num_option` → 一道题的选项都抓不到 | `optionRows()` 增加 `ul.mark_letter > li` 兜底；新增 `keyOf()`（从标记或行文本 `A.` 前缀取字母）、`optionText()`（剥掉 `A.` 前缀）；`isSelected()` 也认行上的 `active/selected/cur/checked` 类 |

还顺带把题干清洗加强：剥掉 `1.` 序号和 `（单选题）`/`(多选题)` 这类题型前缀（真页面的题干就长这样：
`1. <span class="colorShallow">(单选题)</span>下列离子在酸中稳定的是: ( )`。

`probe_real_page.py` 接受任意快照路径，`probe_snapshots.py` 一次对比目录下所有快照的结构计数。

### 第 6 个 bug：脚本猫沙箱里 `new MouseEvent({view: window})` 直接抛异常

用户装上脚本、在浏览器里点「一键做完」时，提取和作答都正常，一到回填就报：

```
错误：Failed to construct 'MouseEvent': Failed to read the 'view' property from
'UIEventInit': Failed to convert value to 'Window'.
```

原因是**用户脚本管理器的沙箱**：脚本猫/油猴会让脚本跑在一个隔离环境里，脚本里的 `window`
是沙箱包装对象，不是页面的 `Window` 实例。`new MouseEvent('click', {view: window})`
初始化时要把 `view` 转成 `Window`，转不过去就直接抛异常——**整个回填被这一个
`dispatchEvent` 卡死**。

Playwright e2e 测不出来的原因：它把脚本直接注入页面，`window` 是真 Window。
所以专门补了 `sandbox_sim.py`，用 `new Function('window', …)` 把 `window` 换成一个
普通对象再跑全链路，复现沙箱条件。

| bug | 表现 | 修法 |
|---|---|---|
| 沙箱里构造 MouseEvent 抛异常 | 回填第一步就报 `Failed to convert value to 'Window'` | `clickEl()` 不再传 `view`（默认 `null` 即可，事件照样冒泡到页面上的 `onclick`），并加 `composed: true`；构造失败时退回 `el.click()` |

验证：`sandbox_sim.py` 对修复后的脚本 **PASS**（4 个隐藏字段全部写入），对把
`view: window` 改回去的副本**稳定复现用户看到的报错**——同一个脚本、同一套断言，
一个过、一个报错，说明这个测试确实盯住了沙箱差异。

### 页面结构兜底（学习通换皮 / 考试页 / 别的学校定制版）

提取题目时按四级顺序找容器，前一级有结果就不往下走：

| 级别 | 依据 | 覆盖 |
|---|---|---|
| 1 | `.fanyaMarking_left .questionLi.singleQuesId` | mooc2 作业页（最标准） |
| 2 | `.questionLi` | 学习通作业页通用 |
| 3 | `.TiMu` / `.question-item[data-question-id]` | 旧版、部分定制版 |
| 4 | **万能兜底**：先按 `.mark_name` / `.Zy_TItle` 标题反推题目块，找不到再按「一串 `A. B. C. D.` 开头的 li」反推选项组 | 完全不认识的页面 |

选项同理：`.stem_answer .answerBg` → `.answerBg` → `ul.mark_letter > li` → 任何 `A.` 开头的 `li`。
题干兜底：整块文本里剔掉选项行和「一、单选题（每题 2 分）」式标签行。

在真实快照上对比过（同一批页面，强制走第 4 级 vs 走第 1 级）：

| 快照 | 已知选择器 | 强制兜底（`?cxb_generic=1`） |
|---|---|---|
| 作业详情 20 题 | 20/20（single 11、multiple 3、blank 3、judge 3） | **20/20，题型分布完全一致** |
| 作业详情 147 题 | 147/147（single 89、blank 28、judge 29、essay 1） | **147/147，完全一致** |
| doWork 论述题 | 1/1 | 1/1 |

也就是说：学习通哪天换皮了，最差也能走兜底路径把题抓全。调试时在地址栏加 `?cxb_generic=1`
可以强制走兜底，用来判断"抓不到题"到底是选择器问题还是页面问题。

### 从真实页面 JS 里挖到的作答机制（这才是回填的底层协议）

那个 367KB 的真 `doWork` 快照里带着学习通自己的内联 JS，`addChoice(obj)` 写得很清楚：

```js
if ($(obj).find(".num_option").hasClass("check_answer")) {   // 单选：再点一次是取消
    $(obj).find(".num_option").removeClass("check_answer");
    $(obj).attr("aria-checked","false");
} else {
    $(".choice" + qid).removeClass("check_answer");          // 单选：先清同组
    $(obj).find(".num_option").addClass("check_answer");
    $(obj).attr("aria-checked","true");                      // aria 写在选项容器上
}
$(".choice" + qid).each(function(){ if ($(this).hasClass("check_answer"))
    choiceContent += $(this).attr("data"); });               // 把 data 串起来
$("#answer" + qid).val(choiceContent);                       // ← 存进隐藏字段
answerContentChange();                                       // 标脏
```

多选走的是 `.num_option_dx` + `check_answer_dx`，判断题的 `data` 是 `true`/`false`。

据此改了三处：

1. `isSelected()` 认 `check_answer`、**`check_answer_dx`**、`checked`、`selected`，也认容器上的 `aria-checked` / `aria-pressed`。
2. **按隐藏字段判真**：`#answer{qid}` 才是学习通真正保存的东西。点完之后读它，字母排序一致才算成功；
   不一致就以字段为准，不再自欺欺人地报 ✓。
3. **点击失效时写字段兜底**：如果点了没反应（页面换了写法 / 选项被遮罩 / 事件没绑），
   直接写 `#answer{qid}` 并补上 `check_answer(_dx)` + `aria-*`，让"保存/提交"拿到的就是对的答案。
   日志会写明 `✓（点击未生效，已写入隐藏答案字段）`，不会假装是点成功的。

自检页 `/fixture-real` 现在有 **5 道题**，第 5 题的选项**故意不绑任何点击事件**，专门验证这条兜底路径：
`e2e_real.py` 跑出来是 `5/5 提取、5/5 作答、5/5 回填`，第 5 题走的就是隐藏字段兜底。

### 端到端自检（headless Chromium，真跑一次 /solve）



```bash
cd <repo>
PYTHONIOENCODING=utf-8 python e2e_test.py    # 约 15 秒
```

用 Playwright 打开 `/fixture` → 注入脚本 → 依次点 **提取 / 作答 / 回填** → 直接断言 DOM：

```
[ok] 提取： 共 6 道：single 2，judge 1，blank 1，multiple 1，essay 1 / 带图片的题：1 道
[ok] 作答： 完成：6/6，用时 5.7s
[check] single   ['A']
[check] judge    ['true']
[check] blank    'H2O'
[check] multiple ['A', 'B', 'D']
[check] essay    '<p>安培环路定理：…</p>'          ← 写进 UEditor iframe + 隐藏 textarea
[check] image    ['B']                            ← 题干是图片，读出 B=0.5T、S=2m²，算出 1 Wb
回填完成：6/6
E2E: PASS
```

这一步抓出并修掉了 4 个真 bug（都只有在真浏览器的 DOM 里跑才会暴露）：

| bug | 表现 | 修法 |
|---|---|---|
| 题干抓错 | 只抓到「三、填空题（每题 2 分）」，模型回「题干未提供内容」 | `stemOf()` 改成**有序探测**：先 `.Zy_TItle`（克隆后删掉内部 `.mark_name`），再退到 `.question-stem` 等，最后才用整块文本；并剥掉「一、单选题（每题 2 分）」前缀 |
| 判断题填不进 | 模型回 `true`/`A`，脚本却只认 `A`–`Z` 字母 → 直接跳过 | 新增 `judgeValue()`（true/false、对/错、正确/错误、T/F、A/B 归一到 `true`/`false`）+ `pickJudge()` 按 `data` 找行 |
| 空答案也填 | 模型答不出时回 `[""]`，脚本照样填一个空串并报 ✓ | 服务端 `parse_answer` 丢弃空串、全空即报错；脚本 `fillBlanks` 遇到空答案直接判失败 |
| 多选判成单选 | 多选页面的选项标记是 `.num_option_dx`，只看 `role` 会误判 | `detectType()` 先看 `.num_option_dx` → `multiple`（比 role 属性可靠） |

另外修了一个只在长思考时偶发的问题：deepseek-flash 先写思考再写正文，
思考过长（实测 852 token）时 `content` 可能为空 → 现在会从 `reasoning_content` 捞 JSON 兜底，
并把 `max_tokens` 提到 3000、超时提到 120s。




### 使用

```bash
cd <repo>
python server.py
# 浏览器打开  http://127.0.0.1:8790/cx-agent.user.js  安装脚本
```

打开学习通作业页 → 右下角面板：
1. **一键做完** → 提取 + 作答 + 回填，一条龙（最省事）
2. **提取** → 状态栏显示抓到的题目数与题型分布
3. **作答** → 调本地服务，逐题出答案（显示每题答案 + 解析）
4. **回填** → 按答案点选 / 填文本框
5. 人工核对 → 自己点提交（脚本**不会**点提交）

> `server.py` 每次请求都从磁盘读 `cx-agent.user.js` 再返回，所以**改脚本不用重启服务**，
> 浏览器里点一下脚本猫的「更新」即可拿到新版本。

### 自检页（先验证链路，不碰真作业）

```
http://127.0.0.1:8790/fixture        # mooc2 结构，6 题，含图片题
http://127.0.0.1:8790/fixture-real   # 真实页面结构（ul.mark_letter > li），4 题，可交互
```

- `/fixture`：按 mooc2 结构造 6 道题（单选 2 / 判断 1 / 填空 1 / 多选 1 / 简答 1，第 6 题题干是图片），
  带 `check_answer` toggle、UEditor 富文本 iframe、底部实时「选择结果」→ `e2e_test.py` 断言（6/6 全绿）。
- `/fixture-real`：按**真实作业页**的结构造 4 道题（`<h3 class="mark_name">1. (单选题)…</h3>` +
  `<ul class="mark_letter"><li>A. xxx</li></ul>`），点 li 切换 `check_answer` → `e2e_real.py` 断言
  （4/4 提取、4/4 作答、4/4 回填，**并且「一键做完」按钮也跑通**）。

装好脚本后打开这两个页面 → 点「一键做完」→ 看题是否被自动勾上 / 写入。
自检过了再上真作业页；真作业页若抓不到题，点「导出结构」生成 `last-report.json` 给我校准。


### 已知限制

- 只覆盖 `mooc-ans` 系作业页（`mooc2/work/dowork`、`work/doHomeWorkNew`）；考试页结构不同，未适配。
- 多选题的答案会随模型有波动（同一道题两次跑可能一个选 2 项、一个选 1 项），提交前请自己核一遍。
- 题干图片走 `GM_xmlhttpRequest` 取字节（跨域），若图片域被拦则退化为纯文本作答并在面板告警。
- 连线题、选项本身是图片的题，只作答不回填（回填风险太高）。
- 本地服务只监听 127.0.0.1，脚本不向外网发送任何内容。

## 5. DSH 接入（MCP 工具）

目标：让助手在 DSH 会话里**直接用工具调用**读题、交答案，而不是靠用户点按钮再把结果贴回来。

- 服务：`cx-mcp.js`（零依赖，手写 MCP over stdio：换行分隔 JSON-RPC，支持 initialize / tools/list / tools/call / ping）。
- 四个工具：
  | 工具 | 作用 |
  | --- | --- |
  | `cx_status` | 有没有待答题、上一轮答案还在不在 |
  | `cx_take_questions` | 取走页面交上来的题目（题干/选项/图片） |
  | `cx_submit_answers` | 交回答案（校验 task_id），脚本轮询到就回填 |
  | `cx_report` | 最近一次「导出结构」，用来校准选择器 |
- 注册：`python install_mcp.py` —— 往 `~/.dsh\profiles\{desktop,web}\cordis.patch.yml` 追加 `mcp-cx-bridge` 条目（先备份、写完用 PyYAML 校验，幂等）。
- **生效需要重启 DSH**（MCP 客户端在插件加载时连一次，不热重载）。重启后工具列表里应出现 `cx_status` 等 4 个工具。
- 额度：作答走的是 **DSH 会话自己的模型**，不额外调用外部 API，不产生额外费用。

数据流（agent 引擎）：

```
学习通页 ──(脚本 /extract)──> pending.json ──(cx_take_questions)──> 助手
助手 ──(cx_submit_answers)──> answers.json ──(脚本轮询 /answers)──> 回填页面
```

## 6. 开始做题（手动点一次，起一个全新会话）

用户要求：**开始做题必须手动点**；点完之后由一个新会话去做题，不要占用当前对话。

- 面板按钮：`开始做题`（v0.4.2 起）。点它做的事：
  1. 提取题目 → `POST /extract` 写 `pending.json`（task_id）；
  2. `POST /agent-solve` → server 用 `dsh --profile headless` 起一个**全新 DSH 会话**；
  3. 新会话按固定提示词工作：`cx_take_questions` 取题 → 逐题作答 → **每批最多 8 题** `cx_submit_answers`（合并写入）→ 退出；缺题会自动续跑（最多 3 轮）；
  4. 页面只负责轮询 `/answers`，拿到后自动回填（仍然不会提交作业）。
- 新会话的模型/思考强度在 `~/.dsh/profiles/headless/cordis.patch.yml`：
  `provider: opencode-go / model: deepseek-v4.1-flash / reasoningEffort: low`，并注册了 `mcp-cx-bridge`。
- 默认**不再自动跑**；想让作业页自己开跑，加 `?cxb_auto=1`。
- 运行日志：`cx-bridge/agent-solve.log`（每次开头有一行 `=== 时间 task=… count=… ===`）。
- 状态接口：`GET /agent-status` → 结构化字段 `{running, pid, exit, task_id, fingerprint, count, answered, log_file, log_tail}`；原始日志走 `GET /logs`（text/plain，末 60 行），不再把日志塞进 JSON。
- 一次没做完/要重做：再点一次「开始做题」会重新提取并起新会话；上一轮进程还在跑时接口返回 `running:true` 不重复起。

### v0.5.0（2026-11-08）把「头痛医头」的坑一次修掉

上一轮实测暴露的 6 个坑，逐条落到代码里：

| 坑 | 现在的做法 |
| --- | --- |
| 重复点「作答」→ 新 task_id、清空 answers，前功尽弃 | `pending.json` 带题目**指纹**（`fp-` + 排序后 qid 的 sha1 前 16 位）。同批题再点，`enqueue()` 直接返回 `reused:true, ready:…, answered:N`，**不新 task、不清空** |
| 答案和时间戳绑定，一提取就作废 | 答案也带指纹；`read_answers()` 先比指纹、再退回 task_id（兼容旧数据）；指纹不符明确返回「答案属于上一轮题目」 |
| 做题会话随起服务的工具会话一起死 | `start_agent()` 用 `DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW` 起子进程；状态写 `agent-state.json`，用 `OpenProcess`+`GetExitCodeProcess` 判断是否还活着 |
| 面板固定「等待超时」，不看答案是否在写 | 改成事件化：`/answers` 一 ready 就回填；60 分钟只提示一次、不终止；做题进程退出且 0 条答案时才放弃 |
| 测试覆盖真实题目/结构 | 所有数据文件走 `CXD_DATA_DIR`；五个 e2e 脚本开头有安全闸，**不显式设置就拒绝运行**；`e2e_idempotent.py` 专门验「连点两次不丢答案」 |
| `/agent-status` 解析崩 | 只返回结构化字段 + 转义后的 `log_tail`（去控制字符、每行截 240 字） |

服务常驻：

- 双击 `start-hidden.vbs` → 无窗口后台起 8790（日志 `server.out.log` / `server.err.log`）。
- `powershell -ExecutionPolicy Bypass -File install-autostart.ps1` → 在「启动」目录放 `cx-bridge.lnk`，登录自动起；已启动时不会重复起。
- 数据目录默认就是 `cx-bridge/`，可用 `CXD_DATA_DIR` 改（测试务必改）。

回归（隔离环境 `CXD_DATA_DIR=<临时目录>` + `CX_PORT=8791`）：`test_server.py` 19 项、`e2e_idempotent.py` 10 项、`e2e_test.py`、`e2e_real.py`、`e2e_dowork.py` 6/6、`e2e_newstyle.py` 2/2、`sandbox_sim.py` 全 PASS。


### v0.5.1（2026-11-08）大 payload 提交修复 + 缺题续跑 + 回填结果上报

这一版解决的是「明明做出来了，却没有答案」这一类看不见的问题：

| 问题 | 现在的做法 |
| --- | --- |
| `cx_submit_answers` 传大对象（40 题）返回 `written: 0` | `cx-mcp.js` 入口 `asObject()`：参数是 JSON 字符串先 `JSON.parse`；写入改为**合并**（同 task / 同指纹保留已有答案再叠加），返回 `acceptedThisCall` 表示本次新增几条 |
| 做题会话退出，面板只说「没写答案」，没法查 | 新增 `POST /fill-report`（页面回填完上报 `{url, task_id, ok, total, fails[]}`）与 `GET /fill-report`；另有 `GET /logs` 看模型原始日志 |
| 一轮没做完就得整体重来 | `SOLVER_PROMPT` 要求**每批最多 8 题**提交；`start_agent()` 先算 `_missing_ids()`，`_watch()` 在子进程退出后若仍缺题且 task 未变，自动再起一轮（最多 3 轮），只做缺的题 |
| 「开始做题」直接 500 | `start_agent()` 里 `proc = subprocess.Popen(...)` 曾被改丢（`NameError: proc`）——真机 E2E 才暴露，已补回 |
| 隔离测试写进真实答案 | `cx-mcp.js` 的 `HERE` 也读 `CXD_DATA_DIR`，测试不会再碰生产数据 |

真机端到端证据（隔离目录 + 独立端口，不碰真实作业）：

- 10 道题 → `answered: 10`，日志 `--- 第 1 轮结束，缺 0 题 ---`，答案全对；
- 手动删掉最后 2 条 → 再点「开始做题」→ 只补那 2 题（`t8=19, t9=21`），其余 8 条**没有被覆盖**（合并写入生效）。

真实作业回填（2026-11-08 14:07:33）：`/fill-report` → `{"ok": 40, "total": 40, "fails": []}`。

## 7. 项目结构

```
cx-bridge/
├─ cx-agent.user.js        # 浏览器脚本（脚本猫）：提取题目 / 点选项 / 写 UEditor / 回填 / 上报
├─ server.py               # 本地桥接服务（127.0.0.1:8790）：题目队列、答案队列、起做题会话、日志
├─ cx-mcp.js               # DSH MCP 服务端（stdio，4 个工具）
│
├─ start.bat               # 前台起服务（看日志用）
├─ start-hidden.vbs        # 无窗口后台起服务
├─ install-autostart.ps1   # 把快捷方式放进「启动」目录（登录自启）
├─ install_mcp.py          # 把 mcp-cx-bridge 写进 DSH 的 desktop/web profile（幂等、先备份）
│
├─ test_server.py          # 服务端单元测试（19 项）
├─ e2e_test.py             # 模拟页端到端（选择/判断/填空/多选/简答/图片）
├─ e2e_real.py             # 学习通旧版真实标记（mark_letter）端到端
├─ e2e_dowork.py           # 新版作答页标记（questionLi + UEditor + 保存按钮 + 公式）
├─ e2e_newstyle.py         # 新版选项结构（ul.Zy_ulTop + input[name=answer*] + answertype）
├─ e2e_idempotent.py       # 纯 HTTP 幂等回归（连点两次不丢答案、换题不冒充旧答案）
├─ sandbox_sim.py          # 脚本猫沙箱（GM_* 隔离）下的端到端
├─ probe_real_page.py      # 在离线 HTML 快照上跑提取（不用登录）
├─ probe_snapshots.py / probe_markup.py   # 快照统计 / 结构片段导出
│
├─ fixture*.html           # 测试页（模拟学习通各种页面结构）
├─ README.md / 快速开始.md
└─ research/               # 同类项目调研与真实页面快照（第三方材料，不进 git）
```

数据文件（不进 git）：`pending.json`（题目队列）、`answers.json`（答案队列）、`answers.prev.json`（上一轮归档）、`last-report.json`（页面结构诊断）、`fill-report.json`（回填结果）、`agent-state.json`（做题进程状态）、`*.log`。

## 8. 测试清单怎么跑

所有 e2e 都会**写入** `pending.json` / `answers.json` / `last-report.json`，所以必须用隔离目录 + 独立端口：

```bash
# 1) 用临时数据目录、另一个端口起一份服务
CXD_DATA_DIR=/tmp/cxb-test CX_PORT=8791 python server.py &

# 2) 同一组环境变量跑测试（脚本里也有安全闸，不设 CXD_DATA_DIR 会直接拒绝）
export CXD_DATA_DIR=/tmp/cxb-test CX_PORT=8791 CX_BRIDGE=http://127.0.0.1:8791
python test_server.py
python e2e_idempotent.py
python e2e_test.py
python e2e_real.py
python e2e_dowork.py
python e2e_newstyle.py
python sandbox_sim.py
```

浏览器脚本相关测试用 Playwright（headless Chromium）；`probe_*.py` 只用本地 HTML 快照，不用登录。

## 9. 第三方材料与许可

- `research/` 里是调研时抓的同类项目代码/文档副本与学习通页面快照，**只作本地参考，不随仓库分发**（已在 `.gitignore` 里排除），避免把别人的代码混进本仓库的许可范围。
- 借鉴来源（做法层面，非复制）：zhu-hailin/chaoxing-ai-assistant（MIT）、Trashwbin/MultiAI-Answer-cx（MIT）、Khihl-lucky/ChaoXing-AutoAnswer、Fk-Chaoxing、HanKuCha、九九助手、GAOQI-GQ/xuexitong-deepseek-console、Samueli924/chaoxing、aquamarine5/ChaoxingSignFaker、cxOrz/chaoxing-signin。
- 本仓库目前**未附开源许可证**（默认保留所有权利）。若要公开发布，先选一个 License（建议 MIT）再推。
- 使用范围：仅限自己有权限访问的课程作业；脚本不自动提交，提交前请自行核对。

## 2026-11-08 真实作业连续通过（记录）

- 27 题作业（single 12 / blank 15，含 18 张题干图）：`ok 27 / total 27, fails 0`，回填耗时约 5 分钟（含做题）。
- 40 题作业（single 21 / blank 19，含 25 张题干图）：`ok 40 / total 40, fails 0`。
- 期间定位并修掉的问题：
  - 做题会话大对象提交 `written: 0` → MCP 参数 `asObject()` + 合并写入；
  - 重复点「开始做题」清空答案 → 题目指纹复用；
  - 一轮没做完 → 缺题续跑（最多 3 轮）；
  - 会话退出时答案尚未落盘 → 面板误报「没写答案」，改为退出后再查 5 轮；
  - 「回填」只认页面内存答案 → 改为先从服务端 `GET /answers` 取。

## 2026-11-08 v0.6.7 刷章节：换课程进度隔离

- 现象：脚本猫里那份进度是全局的，A 课刷到第 3 章、换 B 课打开时会从「第 3 章」开始，跳过 B 课的前两章。
- 改法：`chapterRun()` 里比较 `state.course` 与当前 `chapCourseKey()`（`courseId/clazzId`），不一致就把 `chapterIdx/taskIdx/done` 清零并提示「换了课程（旧 → 新），进度从头开始」，再写回新 key。
- 测试：fixture 加 `&alldone=1`（所有章节标记已完成，流程停在列表页、日志可读）；`e2e_chapter.py` 加 `run_phase_d`，预置一份别的课程的旧进度，断言重置提示 + `chapterIdx` 归零；e2e 共 15 项 PASS。
