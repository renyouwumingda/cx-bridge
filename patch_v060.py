# -*- coding: utf-8 -*-
import pathlib, re
p = pathlib.Path(r"C:\Users\10183\Desktop\ds\cx-bridge\cx-agent.user.js")
s = p.read_text(encoding="utf-8")

# ---------- 1. 头部：版本 / @match / @grant ----------
s = s.replace("// @version      0.5.3", "// @version      0.6.0", 1)
s = s.replace("const VERSION = '0.5.3';", "const VERSION = '0.6.0';", 1)
anchor_match = "// @match        http://127.0.0.1:8790/fixture*\n"
new_matches = anchor_match + """// @match        *://mooc1.chaoxing.com/mooc-ans/mycourse/*
// @match        *://mooc1.chaoxing.com/mycourse/*
// @match        *://mooc1.chaoxing.com/mooc2-ans/mycourse/*
// @match        *://mooc1.chaoxing.com/knowledge/cards*
// @match        *://mooc1.chaoxing.com/mooc-ans/course/*
// @match        *://mooc1.chaoxing.com/ananas/modules/*
"""
assert anchor_match in s
s = s.replace(anchor_match, new_matches, 1)
anchor_grant = "// @grant        GM_xmlhttpRequest\n"
assert anchor_grant in s
s = s.replace(anchor_grant, anchor_grant + "// @grant        GM_getValue\n// @grant        GM_setValue\n// @grant        GM_deleteValue\n", 1)

# ---------- 2. 插入刷章节模块（放在面板之前） ----------
CHAPTER = r'''
  /* ---------------- 刷章节 ---------------- */

  // 目标：在课程章节列表页点进未完成章节，在章节学习页里依次点任务点，
  // 视频静音 2 倍速播完、文档/PPT 停留计时，然后自动下一节。不交测验、不交作业。
  const CH_KEY = 'cxb_chapter_state';
  let chapRunning = false;
  let chapSkip = false;

  const qsa = (sel, root) => Array.from((root || document).querySelectorAll(sel));
  const norm = el => (el ? (el.textContent || '').replace(/\s+/g, ' ').trim() : '');

  function chapKind() {
    const u = location.pathname + location.search;
    if (/studentstudy|knowledge\/cards/.test(u)) return 'study';
    if (/studentcourse|mycourse\/stu\b/.test(u)) return 'course';
    return 'other';
  }
  function chapLoad() { try { return JSON.parse(GM_getValue(CH_KEY, '{}')) || {}; } catch (e) { return {}; } }
  function chapSave(o) { try { GM_setValue(CH_KEY, JSON.stringify(o)); } catch (e) {} }
  function chapLog(m) { log('[章节] ' + m); }
  function chapStatus(m, pct) {
    const el = $('cxb-chap-state'); if (el) el.textContent = m;
    const bar = $('cxb-chap-bar');
    if (bar && typeof pct === 'number') bar.style.width = Math.max(0, Math.min(100, pct)) + '%';
  }
  function chapCourseKey() {
    const p = new URLSearchParams(location.search);
    return [p.get('courseId') || '', p.get('clazzid') || p.get('classid') || ''].join('/') || location.pathname;
  }

  // 章节列表页：挑出章节链接（旧版 .chapter_item，新版 h3/单元）
  function chapterItems() {
    let list = qsa('div.chapter_item, .chapter_item');
    if (!list.length) list = qsa('.chapter_unit a, h3 a, #mainid a');
    const seen = new Set(), out = [];
    list.forEach(el => {
      const a = el.tagName === 'A' ? el : (el.querySelector('a') || el);
      if (!a) return;
      const onclick = a.getAttribute('onclick') || a.getAttribute('href') || '';
      if (!/chapterId|toOld|getTeacherAjax|studentstudy/.test(onclick)) return;
      const key = onclick.replace(/\d+/g, '#') + '|' + norm(el).slice(0, 40);
      if (seen.has(key)) return;
      seen.add(key);
      const t = norm(el);
      const done = /已完成|100%/.test(t) || !!el.querySelector('[class*="finish"], [class*="complete"], i.icon.blue');
      out.push({ el: a, name: t.slice(0, 40) || '章节', done });
    });
    return out;
  }

  // 章节学习页：任务点
  function taskItems() {
    let list = qsa('.posCatalog_select, .posCatalog_name, #prevNextFocusList a, .catalog_points li');
    if (!list.length) list = qsa('a[onclick*="getTeacherAjax"], a[onclick*="toOld"], a[onclick*="changeDisplayContent"]');
    const seen = new Set(), out = [];
    list.forEach(el => {
      const t = norm(el);
      if (!t) return;
      const key = t + '|' + (el.getAttribute('onclick') || '');
      if (seen.has(key)) return; seen.add(key);
      out.push({ el, name: t.slice(0, 40) });
    });
    return out.slice(0, 200);
  }

  function sameOriginDocs() {
    const docs = [document];
    qsa('iframe').forEach(f => {
      try { const d = f.contentDocument; if (d && d.body) docs.push(d); } catch (e) {}
    });
    return docs;
  }
  function findVideos() {
    const out = [];
    sameOriginDocs().forEach(d => {
      try { qsa('video', d).forEach(v => out.push({ v, d })); } catch (e) {}
    });
    return out;
  }
  function anyVideoPlaying() {
    return findVideos().some(({ v }) => !v.paused && !v.ended);
  }

  // 处理当前任务点：视频播完 / 文档停留
  async function handleTask(item, idx) {
    chapLog('任务点 ' + (idx + 1) + '：' + item.name);
    try { item.el.click(); } catch (e) { chapLog('点不动这个任务点：' + (e.message || e)); }
    await sleep(2500);

    const end = Date.now() + 45 * 60 * 1000;
    let lastLog = 0;
    while (chapRunning && Date.now() < end) {
      const vids = findVideos().filter(({ v }) => !v.ended && isFinite(v.duration) && v.duration > 0);
      if (!vids.length) {
        // 文档 / PPT / 音频之外的页面：停留 20–40 秒算过
        const wait = rnd(20000, 40000);
        chapLog('没有视频，按文档处理，停留 ' + Math.round(wait / 1000) + ' 秒');
        const t0 = Date.now();
        while (chapRunning && Date.now() - t0 < wait) await sleep(1000);
        return true;
      }
      let allDone = true;
      for (const { v } of vids) {
        try {
          v.muted = true;
          if (v.playbackRate < 2) v.playbackRate = 2;
          if (v.paused && !v.ended) await v.play().catch(() => {});
        } catch (e) {}
        const cur = v.currentTime || 0, dur = v.duration || 0;
        if (dur && cur >= dur - 2) continue;
        allDone = false;
        if (Date.now() - lastLog > 5000) {
          lastLog = Date.now();
          const pct = dur ? Math.round(cur / dur * 100) : 0;
          chapLog('播放中 ' + pct + '%（' + Math.round(cur) + '/' + Math.round(dur) + 's，' + v.playbackRate + '×）');
        }
      }
      if (allDone) { chapLog('本任务点视频已播完'); return true; }
      await sleep(1200);
    }
    return chapRunning;
  }

  async function runChapterTaskLoop(state) {
    const tasks = taskItems();
    if (!tasks.length) { chapLog('这个章节页没找到任务点，跳过'); return false; }
    if (!state.done) state.done = {};
    const doneKey = (state.chapterId || 'ch') + '#';
    let i = state.taskIdx || 0;
    for (; i < tasks.length; i++) {
      if (!chapRunning) return false;
      if (state.done[doneKey + i]) continue;
      const ok = await handleTask(tasks[i], i);
      if (ok && chapRunning) {
        state.done[doneKey + i] = 1;
        state.taskIdx = i + 1;
        chapSave(state);
        chapStatus('已完成任务点 ' + (i + 1) + '/' + tasks.length, ((i + 1) / tasks.length) * 100);
      }
      if (chapSkip) { chapSkip = false; state.taskIdx = i + 1; chapSave(state); }
    }
    return true;
  }

  async function goNextChapter(state) {
    const items = chapterItems();
    if (!items.length) { chapLog('不在章节列表页，先回章节列表'); return false; }
    let idx = state.chapterIdx || 0;
    for (; idx < items.length; idx++) {
      if (!chapRunning) return false;
      if (items[idx].done) continue;
      chapLog('打开章节 ' + (idx + 1) + '/' + items.length + '：' + items[idx].name);
      state.chapterIdx = idx; state.taskIdx = 0; state.chapterId = String(idx);
      chapSave(state);
      items[idx].el.click();
      await sleep(4000);
      return true;
    }
    chapLog('所有章节都完成了');
    return false;
  }

  async function chapterRun() {
    chapRunning = true;
    const kind = chapKind();
    let state = chapLoad();
    state.course = chapCourseKey();
    state.running = true;
    state.done = state.done || {};
    chapSave(state);
    chapLog('开始：' + (kind === 'course' ? '章节列表页' : kind === 'study' ? '章节学习页' : '未知页面'));
    try {
      if (kind === 'course') {
        const ok = await goNextChapter(state);
        if (!ok) chapStatus('没有可刷的章节', 100);
      } else if (kind === 'study') {
        const ok = await runChapterTaskLoop(state);
        // 本页任务点跑完 → 尝试点下一节
        const nxt = qsa('#prevNextFocusNext, a[onclick*="getTeacherAjax"]').find(e => /下一?节|下一个/.test(norm(e)));
        if (ok && chapRunning && nxt) { chapLog('点下一节'); nxt.click(); }
        else if (ok && chapRunning) chapStatus('本章节任务点已跑完，回章节列表继续', 100);
      } else {
        chapLog('当前页面不是课程章节页，请先打开「课程 → 章节」');
      }
    } finally {
      chapRunning = false;
      state.running = false;
      chapSave(state);
      chapStatus('已停止');
    }
  }

  function chapterDiag() {
    const kinds = {
      'div.chapter_item': qsa('div.chapter_item').length,
      '.chapter_unit a': qsa('.chapter_unit a').length,
      'h3 a': qsa('h3 a').length,
      '.posCatalog_select': qsa('.posCatalog_select').length,
      '.posCatalog_name': qsa('.posCatalog_name').length,
      '#prevNextFocusList a': qsa('#prevNextFocusList a').length,
      'video': findVideos().length,
      'iframe': qsa('iframe').length,
    };
    return kinds;
  }
'''

anchor_panel = "  /* ---------------- 面板 ---------------- */"
assert anchor_panel in s
s = s.replace(anchor_panel, CHAPTER + "\n" + anchor_panel, 1)

# ---------- 3. 面板 HTML 重写 ----------
start = s.index("  panel.innerHTML = `")
end = s.index("\n  `;", start) + len("\n  `;")
NEW_PANEL = r'''  panel.innerHTML = `
    <div style="display:flex;align-items:center;gap:8px;padding:9px 12px;border-bottom:1px solid #eef1f4">
      <strong style="font-size:13px">cx-bridge</strong>
      <span style="color:#8b5cf6;font-size:11px">v${VERSION}</span>
      <span id="cxb-state" style="color:#8a9199;font-size:12px">未连接</span>
      <button id="cxb-hide" title="收起" style="margin-left:auto;border:0;background:none;cursor:pointer;font-size:15px;color:#8a9199">×</button>
    </div>
    <div id="cxb-tabs" style="display:flex;gap:4px;padding:8px 10px 0">
      <button data-tab="quiz" class="tab on">答题</button>
      <button data-tab="chapter" class="tab">刷章节</button>
      <button data-tab="info" class="tab">概览</button>
    </div>
    <div id="cxb-tab-quiz" class="pane">
      <div class="row">
        <button id="cxb-agent" class="primary">开始做题</button>
        <button id="cxb-all">一键做完</button>
        <button id="cxb-extract">提取</button>
        <button id="cxb-solve">作答</button>
        <button id="cxb-fill">回填</button>
        <button id="cxb-report">导出结构</button>
      </div>
      <div id="cxb-quiz-stats" class="hint">还没有提取题目</div>
    </div>
    <div id="cxb-tab-chapter" class="pane" hidden>
      <div class="row">
        <button id="cxb-chap-start" class="primary">开始刷章节</button>
        <button id="cxb-chap-stop">停止</button>
        <button id="cxb-chap-skip">跳过当前</button>
      </div>
      <div id="cxb-chap-state" class="hint">在课程章节列表页或章节学习页点「开始刷章节」；只播视频、翻文档，不交测验/作业。</div>
      <div class="bar"><i id="cxb-chap-bar"></i></div>
    </div>
    <div id="cxb-tab-info" class="pane" hidden>
      <div class="kv"><span>服务</span><b id="cxb-i-engine">-</b></div>
      <div class="kv"><span>模型</span><b id="cxb-i-model">-</b></div>
      <div class="kv"><span>数据目录</span><b id="cxb-i-data">-</b></div>
      <div class="kv"><span>本次任务</span><b id="cxb-i-task">-</b></div>
      <div class="kv"><span>题目/已答</span><b id="cxb-i-count">-</b></div>
      <div class="row"><button id="cxb-info-refresh">刷新状态</button><button id="cxb-open-logs">服务日志</button></div>
    </div>
    <div id="cxb-log-wrap">
      <div style="display:flex;align-items:center;gap:8px;padding:6px 12px 0;color:#8a9199;font-size:11px">
        <span>日志</span>
        <button id="cxb-log-copy" class="mini">复制</button>
        <button id="cxb-log-clear" class="mini">清空</button>
      </div>
      <div id="cxb-log" style="padding:4px 12px 12px;font-size:12px;color:#4b5563;white-space:pre-wrap;word-break:break-all;max-height:34vh;overflow:auto"></div>
    </div>
  `;'''
s = s[:start] + NEW_PANEL + s[end:]

# ---------- 4. 样式重写 ----------
start = s.index("  style.textContent = `")
end = s.index("\n  document.head.appendChild(style);", start)
NEW_CSS = r'''  style.textContent = `#cxb-panel button{border:1px solid #d7dbe0;background:#f7f8fa;border-radius:6px;padding:5px 10px;font-size:12px;cursor:pointer}
  #cxb-panel button:disabled{opacity:.5;cursor:not-allowed}
  #cxb-panel button.primary{background:#3569d4;border-color:#3569d4;color:#fff}
  #cxb-panel button.tab{background:#f1f3f5;border-bottom-color:transparent}
  #cxb-panel button.tab.on{background:#fff;font-weight:600}
  #cxb-panel .row{display:flex;gap:6px;flex-wrap:wrap;padding:10px 12px 0}
  #cxb-panel .hint{padding:8px 12px 0;color:#8a9199;font-size:11.5px;line-height:1.5}
  #cxb-panel .kv{display:flex;justify-content:space-between;gap:8px;padding:3px 12px;font-size:12px}
  #cxb-panel .kv b{font-weight:600;max-width:64%;text-align:right;word-break:break-all}
  #cxb-panel button.mini{padding:1px 6px;font-size:11px}
  #cxb-panel .bar{height:6px;margin:8px 12px 0;background:#eef1f4;border-radius:3px;overflow:hidden}
  #cxb-panel .bar i{display:block;height:100%;width:0;background:#3569d4;transition:width .3s}`;'''
s = s[:start] + NEW_CSS + s[end:]

# ---------- 5. 页签 / 概览 / 日志按钮 ----------
anchor_logel = "  const logEl = $('cxb-log');"
assert anchor_logel in s
TABS = anchor_logel + r'''

  // ---- 页签 ----
  const tabBtns = qsa('#cxb-tabs button');
  function showTab(name) {
    tabBtns.forEach(b => b.classList.toggle('on', b.dataset.tab === name));
    ['quiz', 'chapter', 'info'].forEach(n => { const el = $('cxb-tab-' + n); if (el) el.hidden = (n !== name); });
  }
  tabBtns.forEach(b => { b.onclick = () => showTab(b.dataset.tab); });
  showTab((chapKind() === 'course' || chapKind() === 'study') ? 'chapter' : 'quiz');

  const infoVals = {
    engine: $('cxb-i-engine'), model: $('cxb-i-model'), data: $('cxb-i-data'),
    task: $('cxb-i-task'), count: $('cxb-i-count'),
  };
  function setInfo(k, v) { const el = infoVals[k]; if (el) el.textContent = v == null || v === '' ? '-' : String(v); }
  async function refreshInfo() {
    try {
      const p = await getJSON('/ping');
      setInfo('engine', p.engine); setInfo('model', p.model); setInfo('data', p.data_dir);
    } catch (e) { setInfo('engine', '离线'); }
    try {
      const a = await getJSON('/answers');
      setInfo('count', (a.count || Object.keys(a.answers || {}).length || 0) + ' 题 / 已答 ' + (a.ready ? '是' : '否'));
      setInfo('task', a.task_id || LAST_TASK || '-');
    } catch (e) {}
    try {
      const st = await getJSON('/agent-status');
      if (st && st.answered != null) setInfo('count', (st.count || '?') + ' 题 / 已答 ' + st.answered);
      if (st && st.task_id) setInfo('task', st.task_id);
    } catch (e) {}
    refreshQuizStats();
  }
  function refreshQuizStats() {
    const el = $('cxb-quiz-stats'); if (!el) return;
    if (!questions.length) { el.textContent = '还没有提取题目'; return; }
    const t = {}; questions.forEach(q => { t[q.type] = (t[q.type] || 0) + 1; });
    el.textContent = '共 ' + questions.length + ' 题（' + Object.entries(t).map(([k, n]) => k + ' ' + n).join('，') + '）'
      + '，答案 ' + Object.keys(answers || {}).length + ' 条';
  }

  $('cxb-info-refresh').onclick = () => withBusy(refreshInfo);
  $('cxb-open-logs').onclick = () => { try { window.open(BRIDGE + '/logs', '_blank'); } catch (e) {} };
  $('cxb-log-clear').onclick = () => { logEl.textContent = ''; };
  $('cxb-log-copy').onclick = async () => {
    try { await navigator.clipboard.writeText(logEl.textContent); log('日志已复制'); }
    catch (e) { log('复制失败：' + (e.message || e)); }
  };
'''
s = s.replace(anchor_logel, TABS, 1)

# ---------- 6. setBusy 增加章节按钮 ----------
old_busy = "['cxb-agent', 'cxb-all', 'cxb-extract', 'cxb-solve', 'cxb-fill', 'cxb-report'].forEach(id => { $(id).disabled = b; });"
new_busy = "['cxb-agent', 'cxb-all', 'cxb-extract', 'cxb-solve', 'cxb-fill', 'cxb-report'].forEach(id => { const el = $(id); if (el) el.disabled = b; });"
assert old_busy in s
s = s.replace(old_busy, new_busy, 1)

# ---------- 7. 底部按钮接线 ----------
anchor_fill = "  $('cxb-fill').onclick = () => withBusy(() => doFill());"
assert anchor_fill in s
WIRE = anchor_fill + r'''
  $('cxb-chap-start').onclick = () => withBusy(chapterRun);
  $('cxb-chap-stop').onclick = () => { chapRunning = false; chapLog('你点了停止'); chapStatus('已停止'); };
  $('cxb-chap-skip').onclick = () => { chapSkip = true; chapLog('跳过当前任务点'); };
'''
s = s.replace(anchor_fill, WIRE, 1)

# ---------- 8. 提取/作答后刷新统计与概览 ----------
s = s.replace("  window.__cxb_state = () => ({ questions, answers });",
              "  window.__cxb_state = () => ({ questions, answers, chapter: chapLoad(), diag: chapterDiag() });", 1)

p.write_text(s, encoding="utf-8")
print("patched, length =", len(s))
