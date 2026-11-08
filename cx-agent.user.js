// ==UserScript==
// @name         学习通 AI 助手（cx-bridge）
// @namespace    local.dsh.cxbridge
// @version      0.7.0
// @description  提取学习通作业题目 -> 本地 cx-bridge 服务做题 -> 回填选项。不自动提交。
// @author       local
// @updateURL    http://127.0.0.1:8790/cx-agent.user.js
// @downloadURL  http://127.0.0.1:8790/cx-agent.user.js
// @match        *://mooc1.chaoxing.com/mooc-ans/mooc2/work/dowork*
// @match        *://mooc1.chaoxing.com/mooc-ans/work/doHomeWorkNew*
// @match        *://mooc1.chaoxing.com/mooc-ans/work/*
// @match        http://127.0.0.1:8790/fixture*
// @match        *://mooc1.chaoxing.com/mooc-ans/mycourse/*
// @match        *://mooc1.chaoxing.com/mycourse/*
// @match        *://mooc1.chaoxing.com/mooc2-ans/mycourse/*
// @match        *://mooc1.chaoxing.com/knowledge/cards*
// @match        *://mooc1.chaoxing.com/mooc-ans/course/*
// @match        *://mooc1.chaoxing.com/ananas/modules/*
// @connect      127.0.0.1
// @connect      localhost
// @connect      p.ananas.chaoxing.com
// @connect      *.chaoxing.com
// @grant        GM_xmlhttpRequest
// @grant        GM_getValue
// @grant        GM_setValue
// @grant        GM_deleteValue
// @run-at       document-idle
// ==/UserScript==

(function () {
  'use strict';

  const VERSION = '0.7.0'; // 与文件头 @version 保持一致（面板上会显示，方便确认装的是哪版）

  const BRIDGE = 'http://127.0.0.1:8790';
  const SCROLL_WAIT = 400;
  const Q_WAIT_MIN = 350;
  const Q_WAIT_MAX = 900;

  let questions = [];   // 提取结果
  let answers = {};     // qid -> {ok, answer, reason}
  let LAST_TASK = null; // 最近一次 /extract 的 task_id（回填结果上报用）
  let busy = false;
  // 调试用：地址栏加 ?cxb_generic=1 可跳过已知选择器，强制走"万能兜底"提取
  const FORCE_GENERIC = /[?&]cxb_generic=1/.test(location.search);

  /* ---------------- 基础工具 ---------------- */

  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const rnd = (a, b) => Math.floor(Math.random() * (b - a + 1)) + a;

  function gmFetch(opts) {
    return new Promise((resolve, reject) => {
      GM_xmlhttpRequest({
        timeout: 30000,
        ...opts,
        onload: r => resolve(r),
        onerror: e => reject(new Error('网络错误: ' + (e && e.error) || 'unknown')),
        ontimeout: () => reject(new Error('请求超时')),
      });
    });
  }

  async function postJSON(path, body) {
    const r = await gmFetch({
      method: 'POST',
      url: BRIDGE + path,
      headers: { 'Content-Type': 'application/json' },
      data: JSON.stringify(body),
    });
    if (r.status !== 200) throw new Error('服务返回 ' + r.status + ' ' + (r.responseText || '').slice(0, 200));
    return JSON.parse(r.responseText);
  }

  async function ping() {
    const r = await gmFetch({ method: 'GET', url: BRIDGE + '/ping' });
    if (r.status !== 200) throw new Error('桥接服务未响应');
    return JSON.parse(r.responseText);
  }

  async function getJSON(path) {
    const r = await gmFetch({ method: 'GET', url: BRIDGE + path });
    if (r.status !== 200) throw new Error('HTTP ' + r.status);
    try {
      return JSON.parse(r.responseText);
    } catch (e) {
      // 服务端返回了非 JSON（重启中/代理错误页）时不要炸整个流程
      throw new Error('返回不是 JSON: ' + String(r.responseText || '').slice(0, 120));
    }
  }

  /* ---------------- 图片转 base64 ---------------- */

  const imgCache = new Map();

  function toDataURL(blob) {
    return new Promise((resolve, reject) => {
      const fr = new FileReader();
      fr.onload = () => resolve(String(fr.result));
      fr.onerror = () => reject(new Error('读取图片失败'));
      fr.readAsDataURL(blob);
    });
  }

  const IMG_WAIT = 8000; // 单张图最多等 8s，不能让一张挂了 CDN 的图把整次提取卡死

  async function imageToDataURL(src) {
    if (!src || src.startsWith('data:')) return src || null;
    if (imgCache.has(src)) return imgCache.get(src);
    try {
      const abs = new URL(src, location.href).href;
      const r = await Promise.race([
        gmFetch({ method: 'GET', url: abs, responseType: 'blob' }),
        sleep(IMG_WAIT).then(() => { throw new Error('取图超时'); }),
      ]);
      if (r.status !== 200) throw new Error('HTTP ' + r.status);
      const dataUrl = await toDataURL(r.response);
      imgCache.set(src, dataUrl);
      return dataUrl;
    } catch (e) {
      imgCache.set(src, null);
      return null;
    }
  }

  /* ---------------- 提取题目 ---------------- */

  // 选择器对齐 zhu-hailin/chaoxing-ai-assistant 在 mooc2 作业页上的实测结构：
  // 容器 .fanyaMarking_left .questionLi.singleQuesId，题干 .Zy_TItle .fontLabel
  const STEM_SELECTOR = '.Zy_TItle .fontLabel,.Zy_TItle,.question-stem,.question-title,.mark_name,.stem,[data-question-text]';

  // 兜底：完全不认识页面结构时，靠「一串以 A. B. C. D. 开头的选项」反推题目容器。
  // 学习通换皮 / 考试页 / 别的学校定制版都可能走到这条路上。
  function genericContainers() {
    const isOptionLine = li => /^[A-D]\s*[.、．:：]/.test(((li.innerText || '').trim()));
    const groups = [...document.querySelectorAll('ul,ol,dl')].filter(g => {
      const kids = [...g.children].filter(isOptionLine);
      return kids.length >= 2 && g.clientHeight > 0;
    });
    const out = [];
    for (const g of groups) {
      let box = g.parentElement;
      // 往上找 2 层，直到这个盒子里的文字比选项组明显更长（含题干）
      for (let i = 0; i < 3 && box && box.parentElement; i++) {
        const text = (box.innerText || '').trim();
        if (text.length > (g.innerText || '').trim().length + 8) break;
        box = box.parentElement;
      }
      if (box && !out.includes(box)) out.push(box);
    }
    return out;
  }

  // 兜底 2：页面里有 .mark_name / .Zy_TItle 标题，就按"标题所在题目块"反推
  function headingContainers(root) {
    root = root || document;
    const out = [];
    for (const h of root.querySelectorAll('.mark_name, .Zy_TItle')) {
      const box = h.closest('.questionLi,.marBom60,.TiMu,.question-item,li') || h.parentElement;
      if (box && !out.includes(box)) out.push(box);
    }
    return out;
  }

  // 页面结构诊断：每条选择器命中多少，随 /report 一起交给 cx-bridge，
  // 页面一改版就能看出是哪条掉了，不用再猜（「页面 40 题只抓到 5 题」这一类问题）。
  let lastDiag = {};

  // 不同学习通版本给题目容器挂的 class 不一样：作业作答页是 .questionLi[data]，
  // 章节测验是 .singleQuesId[data] .TiMu[data]，考试预览是 #sigleQuestionDiv_<qid>。
  // 只认其中一条就会漏题，所以取并集，再按包含关系去重。
  const CONTAINER_SELECTORS = [
    '.questionLi',
    '.singleQuesId[data] .TiMu[data]',
    '.TiMu[data]',
    '.question-item[data-question-id]',
    '[data-questionid]',
  ];
  // 靠 id 兜底时只认「question<数字>」「sigleQuestionDiv_<数字>」，
  // 否则会抓到 #questionList 这类外层壳，把 40 题算成 1 题
  const QID_ID_RE = /^(?:question|sigleQuestionDiv_)(\d+)$/;

  // 题目可能在同源 iframe 里（考试预览页 / 部分学校定制版）；跨域读不到就跳过
  function scanRoots() {
    const roots = [document];
    const seen = new Set();
    (function walk(doc, depth) {
      if (!doc || depth > 2) return;
      let frames = [];
      try { frames = [...doc.querySelectorAll('iframe')]; } catch (e) { return; }
      for (const f of frames) {
        let d = null;
        try { d = f.contentDocument; } catch (e) { d = null; } // 跨域会抛
        if (!d || seen.has(d)) continue;
        seen.add(d);
        try {
          if (d.querySelector('.questionLi, .TiMu[data], [id^=question]')) roots.push(d);
          walk(d, depth + 1);
        } catch (e) { /* ignore */ }
      }
    })(document, 0);
    return roots;
  }

  function questionContainers() {
    if (FORCE_GENERIC) return genericContainers();
    const diag = {};
    let out = [];
    for (const root of scanRoots()) {
      let list = [];
      const add = (sel, hits) => {
        diag[sel] = (diag[sel] || 0) + hits.length;
        for (const h of hits) if (!list.includes(h)) list.push(h);
      };
      for (const sel of CONTAINER_SELECTORS) {
        let hits = [];
        try { hits = [...root.querySelectorAll(sel)]; } catch (e) { hits = []; }
        add(sel, hits);
      }
      let byId = [];
      try { byId = [...root.querySelectorAll('[id^=question], [id^=sigleQuestionDiv_]')]; } catch (e) { byId = []; }
      add('[id=question<qid>]', byId.filter(el => QID_ID_RE.test(el.id || '')));
      // 只留最外层：.TiMu 常常嵌在 .questionLi 里，不去重会一题算两遍
      list = list.filter(el => !list.some(other => other !== el && other.contains(el)));
      // 一条候选都没有的页面才退回标题反推 / 万能把戏
      if (!list.length) list = headingContainers(root);
      out = out.concat(list);
      if (out.length) break; // 主子文档已经抓到就不用再拼 iframe 里的
    }
    if (!out.length) out = headingContainers(document);
    if (!out.length) out = genericContainers();
    lastDiag = diag;
    return out;
  }

  function qidOf(el, index) {
    const id = el.getAttribute('id') || '';
    const m = /question(\d+)/.exec(id);
    if (m) return m[1];
    const data = el.getAttribute('data-question-id') || el.getAttribute('data-questionid') || el.getAttribute('data');
    if (data && /^\d+$/.test(data)) return data;
    return 'idx' + (index + 1);
  }

  function cleanText(t) {
    return (t || '')
      .replace(/\s+\n\s+/g, '\n')
      .replace(/[ \t]{2,}/g, ' ')
      .replace(/\n{3,}/g, '\n\n')
      .replace(/^[一二三四五六七八九十]+、\s*[^\n]{0,14}?（[^）]{0,20}）\s*/, '')
      .replace(/^\d+\s*[.、．]\s*/, '')
      .replace(/^[（(【\[]\s*(单选题?|多选题?|判断题?|填空题?|简答题?|论述题?|名词解释题?)\s*[）)】\]]\s*/, '')
      .trim();
  }

  // 题干：优先 .Zy_TItle（剥掉里面的题型标签），再退到其他候选，最后才是整块文本。
  // 不能直接把 .mark_name 放前面——它往往在 DOM 里排在题干预备之前，会只抓到「三、填空题（每题 2 分）」。
  // 题干清洗：学习通的题干常带「【章节】」「（2.5分）」「(单选题)」这类噪音，
  // 抄自 Khihl-lucky 的 tidyQuestion —— 噪音进了模型提示词会带偏答案。
  function tidyStem(s) {
    return String(s || '')
      .replace(/^【[^】]{0,24}】\s*/, '')
      .replace(/^[（(]\s*(?:单选|多选|判断|填空|简答|论述|名词解释|计算|分析)题?\s*[)）]\s*/, '')
      .replace(/[（(]\s*\d+(?:\.\d+)?\s*分\s*[)）]\s*$/, '')
      .replace(/\s+/g, ' ')
      .trim();
  }

  function stemOf(el) {
    const title = el.querySelector('.Zy_TItle, .Cy_TItle');
    if (title) {
      const clone = title.cloneNode(true);
      clone.querySelectorAll('.mark_name').forEach(n => n.remove());
      const t = tidyStem(cleanText(clone.innerText));
      if (t.length > 4) return t.slice(0, 4000);
    }
    for (const sel of ['.question-stem', '.question-title', '.stem', '[data-question-text]', '.mark_name', '.Cy_TItle']) {
      const n = el.querySelector(sel);
      if (n) {
        const t = tidyStem(cleanText(n.innerText));
        if (t.length > 4) return t.slice(0, 4000);
      }
    }
    // 完全认不出的页面：整块文本里去掉选项行和题型标签行，剩下的当题干
    const lines = (el.innerText || '').split('\n')
      .map(s => s.trim())
      .filter(s => s && !/^[A-D]\s*[.、．:：]/.test(s) && !/^[一二三四五六七八九十]+、\s*\S{0,14}?（/.test(s));
    return cleanText(lines.join('\n')).slice(0, 4000);
  }

  // 题型优先从标签文字判断（比看 role 属性稳），标签在 .mark_name / .Zy_TItle 里
  function typeFromLabel(el) {
    // 作业作答页把题型写在容器属性上（typename="单选题"），最可靠；
    // 考试预览页没有属性，退到隐藏字段 input[name=typeName<qid>]，再退到标题文字
    const attr = (el.getAttribute && el.getAttribute('typename')) || '';
    const hid = el.querySelector && el.querySelector('input[name^="typeName"]');
    const head = attr || (hid && hid.value) || ((el.querySelector('.mark_name') || el.querySelector('.Zy_TItle') || {}).innerText) || '';
    const label = String(head).slice(0, 40);
    if (/多选/.test(label)) return 'multiple';
    if (/判断/.test(label)) return 'judge';
    if (/填空/.test(label)) return 'blank';
    if (/(简答|论述|名词解释|计算|分析|问答)/.test(label)) return 'essay';
    if (/单选/.test(label)) return 'single';
    return '';
  }

  // 学习通用自定义字体加密部分文字；出现私用区字符说明文本不可信
  function looksGarbled(text) {
    if (!text) return false;
    const pua = (text.match(/[\uE000-\uF8FF]/g) || []).length;
    const cjk = (text.match(/[\u4e00-\u9fa5]/g) || []).length;
    return pua > 0 && pua >= Math.max(2, cjk * 0.05);
  }

  // 页面级字体加密检测：部分学校把文字换成自定义字体（.font-cxsecret + 内联 @font-face），
  // 文本层看着正常、渲染出来是另一个字。这种页面抓到的题干/选项不可信，必须明确告警。
  function pageFontEncrypted() {
    try {
      if (document.querySelector('.font-cxsecret')) return true;
      return [...document.querySelectorAll('style')].some(s => /font-cxsecret/.test(s.textContent || ''));
    } catch (e) { return false; }
  }

  // 页面类型：作业作答页能填；查看/批改页没有作答入口；考试页只提取不提交。
  function pageKind() {
    const u = location.href;
    if (/exam-ans|\/exam\/|reVersionTestStartNew/.test(u)) return 'exam';
    if (/\/work\/dowork|\/work\/doHomeWorkNew|\/mooc2\/work\/dowork|\/work\/mooc\//.test(u)) return 'work';
    if (/\/work\/view/.test(u)) return 'view';
    return 'other';
  }

  // 填空/简答写完要按题目自带的「保存」才算落库（Trashwbin 实测：只 setContent 不点保存，刷新就没了）
  function clickSave(el) {
    const nod = [...el.querySelectorAll('a, button, div[onclick], span[onclick], .saveBtn, [class*="save"]')]
      .find(n => /保存/.test((n.innerText || '').trim()) && !/提交|交卷/.test(n.innerText || ''));
    if (!nod) return false;
    try { nod.click(); return true; } catch (e) { return false; }
  }

  function optionRows(el) {
    // 新式作业页（mooc-ans/work/doHomeWorkNew）的真实结构：选项是 ul.Zy_ulTop > li，里面
    // <input name="answer<qid>" type="radio|checkbox" value="A|B|…"> + <a class="after">选项文本</a>。
    // 之前只认 .answerBg / .hoverDiv / ul.mark_letter，这类题的选项一个都抓不到 → 整题被判 unknown。
    // 九九助手的做法更通用：TiMu 里所有 li，只要里面带 radio/checkbox 就是选项行。
    const zy = [...el.querySelectorAll('li')]
      .filter(r => r.querySelector && r.querySelector('input[name^="answer"]'));
    if (zy.length) return zy;
    const anyRadio = [...el.querySelectorAll('li')]
      .filter(r => r.querySelector && r.querySelector('input[type="radio"], input[type="checkbox"]'));
    if (anyRadio.length) return anyRadio;
    const rows = [...el.querySelectorAll('.stem_answer .answerBg, .stem_answer .hoverDiv')];
    if (rows.length) return rows;
    const bg = [...el.querySelectorAll('.answerBg, .hoverDiv')].filter(r => el.contains(r));
    if (bg.length) return bg;
    // 作业详情 / 考试页的真实结构：<ul class="mark_letter"><li>A. xxx</li></ul>
    const lettered = [...el.querySelectorAll('ul.mark_letter > li, .mark_letter > li')].filter(r => el.contains(r));
    if (lettered.length) return lettered;
    // 最后兜底：任何以 A. B. C. D. 开头的 li
    return [...el.querySelectorAll('li')]
      .filter(r => el.contains(r) && /^[A-D]\s*[.、．:：]/.test((r.innerText || '').trim()));
  }

  function markerOf(row) {
    // 新式作业页：选项字母/debug 值直接挂在 <input name="answer<qid>" value="A"> 上
    const inp = row.querySelector && row.querySelector('input[name^="answer"][value]');
    if (inp) return inp;
    // span 的 class 里可能同时带 num_option / num_option_dx，用 *= 一次覆盖两种
    return row.querySelector('span[class*="num_option"]') || row.querySelector('.num_option_dx') ||
      row.querySelector('.num_option') || row.querySelector('[data]') || null;
  }

  // 选项字母：优先看标记元素，其次看行文本开头的 "A." / "A、"
  function keyOf(row) {
    const mk = markerOf(row);
    if (mk) {
      const t = (mk.textContent || '').trim();
      const m = t.match(/^([A-Za-z])/);
      if (m) return m[1].toUpperCase();
      const v = (mk.value || mk.getAttribute('value') || '').trim();
      if (/^(true|false)$/i.test(v)) return v.toLowerCase();
      if (/^[A-Za-z]$/.test(v)) return v.toUpperCase();
      const d = (mk.getAttribute('data') || '').trim();
      if (/^[A-Za-z]$/.test(d)) return d.toUpperCase();
    }
    const m2 = (row.innerText || '').trim().match(/^([A-Za-z])\s*[.、．:：]/);
    return m2 ? m2[1].toUpperCase() : '';
  }

  function optionText(row) {
    const node = row.querySelector('.answer_p') || row.querySelector('.after');
    let text = ((node || row).innerText || '').trim();
    // 去掉 "A. " / "A、" 前缀
    text = text.replace(/^[A-Za-z]\s*[.、．:：]\s*/, '');
    return text.slice(0, 300);
  }

  function detectType(el, rows) {
    // 权威来源：页面自己写的 <input type="hidden" name="answertype<qid>" value="0|1|2|3">
    // 0=单选 1=多选 2=填空 3=判断（九九助手同款映射），比任何 DOM 猜测都可靠。
    const at = el.querySelector('input[name^="answertype"]');
    if (at) {
      const v = String(at.value || '').trim();
      if (v === '0') return 'single';
      if (v === '1') return 'multiple';
      if (v === '2') return 'blank';
      if (v === '3') return 'judge';
    }
    const label = typeFromLabel(el);
    if (['blank', 'essay', 'multiple', 'judge', 'single'].includes(label)) return label;
    // 新式作业页：单选/多选/判断全在 input[name="answer<qid>"] 上（radio/checkbox、value=true/false）
    const ins = [...el.querySelectorAll('input[name^="answer"]')].filter(i => i.type === 'radio' || i.type === 'checkbox');
    if (ins.length) {
      if (ins.some(i => /^(true|false)$/i.test(i.value || ''))) return 'judge';
      if (ins.some(i => i.type === 'checkbox')) return 'multiple';
      return 'single';
    }
    // 多选在 mooc2 里用 .num_option_dx（不是 .num_option），这比 role 属性可靠
    if (el.querySelector('.num_option_dx')) return 'multiple';
    const hasBlank = el.querySelector('.blankItemDiv input, .stem_answer input[type="text"], textarea[name^="answerEditor"]');
    if (hasBlank) return 'blank';
    // 作答页的「计算题/简答题」只给编辑器：要么 answerEditor 多空，要么整块一个 UEditor，
    // 甚至只有 .edui-editor / iframe，没有任何 textarea 名字约定 —— 这些都按文本题处理，
    // 否则会被当成选择题去找 A/B/C/D，回填必然失败。
    const editorSel = 'textarea[name^="answerEditor"], textarea[id^="answer"], textarea[name^="answer"], .edui-editor, iframe[id^="ueditor"], iframe[class*="edui"]';
    if (el.querySelector(editorSel)) {
      const n = el.querySelectorAll('textarea[name^="answerEditor"], textarea[id^="answer"], textarea[name^="answer"]').length;
      return n > 1 ? 'blank' : (label === 'essay' ? 'essay' : 'blank');
    }
    if (!rows.length) return 'unknown';
    const roles = new Set(rows.map(r => (r.getAttribute('role') || '').toLowerCase()));
    const datas = rows.map(r => (markerOf(r) || r).getAttribute('data') || '').filter(Boolean);
    if (datas.length && datas.every(d => d === 'true' || d === 'false')) return 'judge';
    if (roles.has('checkbox') || rows.some(r => (r.getAttribute('qtype') || '') === '1')) return 'multiple';
    return 'single';
  }

  async function extractAll() {
    const containers = questionContainers();
    const out = [];
    for (let i = 0; i < containers.length; i++) {
      const el = containers[i];
      const qid = qidOf(el, i);
      const rows = optionRows(el);
      const type = detectType(el, rows);
      const options = rows.map(row => {
        const mk = markerOf(row);
        const key = keyOf(row);
        const val = (mk && mk.getAttribute('data')) || key;
        return {
          key,
          text: optionText(row),
          dataValue: val || '',
        };
      }).filter(o => o.key);

      // 题干图片
      const stems = el.querySelector('.Zy_TItle') || el;
      const imgs = [...stems.querySelectorAll('img')]
        .map(img => img.getAttribute('src') || '')
        .filter(s => s && !/^data:image\/svg/i.test(s))
        .slice(0, 3);
      // 题干图片：并行取，单张超时 8s，不让一张坏图拖住整题
      const images = (await Promise.all(imgs.map(imageToDataURL))).filter(Boolean);

      out.push({
        id: qid,
        type,
        stem: stemOf(el),
        options: options.map(o => ({ key: o.key, text: o.text })),
        images,
        _dataValues: options.map(o => o.dataValue),
        _garbled: looksGarbled(stemOf(el)),
      });
    }
    return out;
  }

  /* ---------------- 回填 ---------------- */

  // 学习通真实逻辑（取自 doWork 页内联 JS 的 addChoice）：
  //   单选 .num_option += check_answer；多选 .num_option_dx += check_answer_dx；
  //   同时把 aria-checked / aria-pressed 写在选项容器上。
  const SELECTED_CLASSES = ['check_answer', 'check_answer_dx', 'checked', 'selected'];

  function isSelected(node) {
    if (!node) return false;
    if (node.checked === true) return true;
    if (node.querySelector && node.querySelector('input[type="radio"]:checked, input[type="checkbox"]:checked')) return true;
    if (node.getAttribute && (node.getAttribute('aria-checked') === 'true' || node.getAttribute('aria-pressed') === 'true')) return true;
    const own = ((node.className || '') + '').split(/\s+/);
    if (SELECTED_CLASSES.some(c => own.includes(c))) return true;
    if (node.querySelector) {
      for (const c of SELECTED_CLASSES) {
        if (node.querySelector('.' + c)) return true;
      }
      if (node.querySelector('[aria-checked="true"],[aria-pressed="true"]')) return true;
    }
    return false;
  }

  function clickEl(el) {
    // 注意：不能传 view: window —— 脚本跑在脚本猫沙箱里，这里的 window 是沙箱包装对象，
    // 不是页面 Window，MouseEvent 初始化时把 view 转成 Window 会直接抛
    // "Failed to construct 'MouseEvent': ... Failed to convert value to 'Window'"。
    // 不传 view（默认 null）就够了，事件照样冒泡到页面上的 onclick。
    try {
      el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, composed: true, button: 0 }));
      return;
    } catch (e) { /* 构造失败（老浏览器/异常沙箱）时退回原生 click */ }
    try { el.click(); } catch (e) { /* ignore */ }
  }

  function activate(target) {
    if (isSelected(target)) return { ok: true, why: '已选中' };
    const mk = markerOf(target);
    const inp = target.querySelector
      ? target.querySelector('input[name^="answer"][type="radio"], input[name^="answer"][type="checkbox"]')
      : null;
    // 新式作业页：真正被识别的是原生 radio/checkbox，先直接点 input（九九助手就这么做）
    if (inp && !inp.checked) {
      clickEl(inp);
      if (inp.checked) return { ok: true, why: '已勾选 ' + (inp.value || '') };
    }
    // 依次尝试：内层标记 -> 选项行 -> 原生 onclick
    if (mk) clickEl(mk);
    if (!isSelected(target)) clickEl(target);
    if (!isSelected(target) && typeof target.onclick === 'function') {
      try { target.onclick.call(target); } catch (e) { /* ignore */ }
    }
    // 新式作业页：真正被识别的是原生 radio/checkbox 的 checked 状态
    if (!isSelected(target) && inp) {
      if (!inp.checked) clickEl(inp);
      if (!inp.checked) {
        try { inp.checked = true; inp.dispatchEvent(new Event('change', { bubbles: true })); } catch (e) { /* ignore */ }
      }
      if (inp.checked) return { ok: true, why: '已勾选 ' + (inp.value || '') };
    }
    return { ok: isSelected(target), why: isSelected(target) ? '已点选' : '点击后未生效' };
  }

  function pickOption(el, q, letter) {
    const rows = optionRows(el);
    const target = rows.find(row => {
      if (keyOf(row) === letter) return true;
      const mk = markerOf(row);
      const val = (mk ? (mk.getAttribute('data') || '') : '').toUpperCase();
      if (val === letter) return true;
      return q.type === 'judge' &&
        ((letter === 'A' && val === 'TRUE') || (letter === 'B' && val === 'FALSE'));
    });
    if (!target) return { ok: false, why: '找不到选项 ' + letter };
    return activate(target);
  }

  // 判断题：模型可能回 true/false、对/错、正确/错误、T/F，也可能仍是 A/B
  function judgeValue(values) {
    for (const raw of values) {
      const v = String(raw).trim().toLowerCase();
      if (['true', 't', '对', '正确', '是', '√', 'yes', 'y', 'a'].includes(v)) return 'true';
      if (['false', 'f', '错', '错误', '否', '×', 'no', 'n', 'b'].includes(v)) return 'false';
    }
    return '';
  }

  function pickJudge(el, q, values) {
    const want = judgeValue(values);
    if (!want) return { ok: false, why: '判断题答案无法识别：' + values.join('/') };
    const rows = optionRows(el);
    // 1) data=true/false
    const byData = rows.find(row => {
      const mk = markerOf(row);
      return mk && (mk.getAttribute('data') || '') === want;
    });
    if (byData) return activate(byData);
    // 2) 选项文本是「对/错」「正确/错误」「√/×」
    const wantText = want === 'true' ? /^(对|正确|√|是)$/ : /^(错|错误|×|否)$/;
    const byText = rows.find(row => wantText.test(optionText(row).replace(/\s+/g, '')));
    if (byText) return activate(byText);
    // 3) 就是 A/B（A=对、B=错）
    const byKey = rows.find(row => keyOf(row) === (want === 'true' ? 'A' : 'B'));
    if (byKey) return activate(byKey);
    return { ok: false, why: '找不到「' + (want === 'true' ? '对' : '错') + '」选项' };
  }

  // 学习通填空/简答的真实结构：每空一个 UEditor，落库字段是 textarea[name="answerEditor<qid><n>"]（n 从 1），
  // 简答是单个 textarea[id="answer<qid>"]。只改 textarea 不进编辑器实例，页面一刷新内容就没了——
  // 这是「明明填了却没保存」的主要原因，必须走 UE.setContent + sync（做法取自 Trashwbin 的回填实现）。
  function getUE() {
    try { return (typeof unsafeWindow !== 'undefined' && unsafeWindow.UE) || window.UE || null; } catch (e) { return null; }
  }

  function ueEditor(ta) {
    const UE = getUE();
    if (!UE || !UE.getEditor) return null;
    try {
      return (ta.id && UE.getEditor(ta.id)) || (ta.name && UE.getEditor(ta.name)) || null;
    } catch (e) { return null; }
  }

  function ueSet(editorId, text) {
    try {
      const UE = getUE();
      const ed = UE && UE.getEditor && UE.getEditor(editorId);
      if (!ed) return false;
      ed.setContent('<p>' + text + '</p>');
      if (ed.sync) ed.sync();
      return true;
    } catch (e) { return false; }
  }

  /* ---------------- 公式（填空里「填公式」不是纯文本） ---------------- */
  // 答案用 $...$ 包起来、或含 \frac \sqrt \mu 这类 LaTeX 命令，就按公式处理：
  // 往 UEditor 里插一个公式节点，而不是把 LaTeX 源码当字符串写进去。
  const LATEX_RE = /\$[^$]{2,}\$|\\[a-zA-Z]{2,}/;
  let formulaNote = '';
  function isLatex(s) { return LATEX_RE.test(String(s || '')); }
  function stripLatex(s) {
    const m = /\$([\s\S]*?)\$/.exec(String(s || ''));
    return (m ? m[1] : String(s || '')).trim();
  }
  function escAttr(s) {
    return String(s || '').replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');
  }

  // 各版本学习通的公式插件命令名不一样（kityformula / TEX / 自定义），逐条试；
  // 插完读一遍编辑器内容，出现 kfformula / data-latex / katex 才算真插进去了。
  function insertFormula(ed, latex) {
    if (!ed) return false;
    const hasNode = () => {
      let html = '';
      try { html = ed.getContent ? ed.getContent() : ''; } catch (e) { html = ''; }
      return /kfformula|data-latex|katex|mathquill/i.test(html);
    };
    const cmds = ['insertformula', 'insertFormula', 'kityformula', 'formula'];
    for (const c of cmds) {
      for (const arg of [{ latex: latex }, latex]) {
        try {
          ed.execCommand(c, arg);
          if (hasNode()) return true;
        } catch (e) { /* 该版本没有这个命令 */ }
      }
    }
    const htmls = [
      '<img class="kfformula" data-latex="' + escAttr(latex) + '" data-lang="katex" />',
      '<span class="kfformula" data-latex="' + escAttr(latex) + '"></span>',
    ];
    for (const html of htmls) {
      try {
        ed.execCommand('insertHtml', html);
        if (hasNode()) return true;
      } catch (e) { /* ignore */ }
    }
    return false;
  }

  // 页面有没有公式插件、命令叫什么 —— 随 /report 一起交给 cx-bridge，
  // 这样「填公式失败」不用靠猜，看一眼 last-report.json 就知道该用哪条命令。
  function formulaProbe() {
    const out = { toolbar: [], plugins: [], commands: [], hasUE: false };
    try {
      document.querySelectorAll('[class*="edui-for-"]').forEach(el => {
        const m = /edui-for-([a-z0-9_]+)/i.exec(el.className || '');
        if (m && /tex|formula|kity|math/i.test(m[1]) && !out.toolbar.includes(m[1])) out.toolbar.push(m[1]);
      });
      const UE = getUE();
      out.hasUE = !!(UE && UE.getEditor);
      if (UE && UE.plugins) out.plugins = Object.keys(UE.plugins).filter(k => /tex|formula|kity|math/i.test(k));
      if (UE && UE.instants) {
        const one = Object.values(UE.instants)[0];
        if (one && one.commands) out.commands = Object.keys(one.commands).filter(k => /formula|tex|kity|math/i.test(k));
      }
    } catch (e) { /* ignore */ }
    return out;
  }

  function writeEditor(ta, text) {
    // 公式优先：能插公式节点就插，插不进去再退化成纯文本（并记一笔，日志里会说明）
    if (isLatex(text)) {
      const ed = ueEditor(ta);
      if (ed && insertFormula(ed, stripLatex(text))) {
        try { if (ed.sync) ed.sync(); } catch (e) { /* ignore */ }
        formulaNote = '公式已插入';
        return true;
      }
      formulaNote = '公式插件不可用，已按纯文本写入（可能判错）';
      text = stripLatex(text);
    }
    const html = '<p>' + text + '</p>';
    if (ta.id && ueSet(ta.id, text)) return true;
    if (ta.name && ueSet(ta.name, text)) return true;
    ta.value = html;
    ta.dispatchEvent(new Event('input', { bubbles: true }));
    ta.dispatchEvent(new Event('change', { bubbles: true }));
    // 可见编辑器也刷一遍：人眼看到的内容才是真的
    const holder = ta.closest('.edui-editor') || ta.parentElement;
    const frame = holder && holder.querySelector('iframe');
    if (frame) {
      try {
        const d = frame.contentDocument || (frame.contentWindow && frame.contentWindow.document);
        if (d && d.body) {
          d.body.innerHTML = html;
          d.body.dispatchEvent(new Event('input', { bubbles: true }));
        }
      } catch (e) { /* ignore */ }
    }
    return String(ta.value || '').trim() !== '';
  }

  function fillBlanks(el, values) {
    const vals = values.map(v => String(v).trim()).filter(Boolean);
    if (!vals.length) return { ok: false, why: '答案为空' };

    // 1) 富文本编辑器（填空/简答的主路径），按 DOM 顺序对应每个空
    let editors = [...el.querySelectorAll('textarea[name^="answerEditor"]')];
    // 兼容路径抄自 Khihl-lucky：老版/换皮页的编辑器可能不叫 answerEditor
    if (!editors.length) {
      editors = [...el.querySelectorAll('.subEditor textarea, .Answer .divText textarea, .stem_answer textarea, .edui-editor textarea')]
        .filter(t => !t.closest('.edui-editor-toolbarbox'));
    }
    if (!editors.length) editors = [...el.querySelectorAll('textarea[id^="answer"]')];
    if (editors.length) {
      let filled = 0;
      for (let i = 0; i < editors.length; i++) {
        // 空比答案多 → 重复用第一个答案；只有一个编辑器却有多段答案 → 合起来写
        const text = editors.length === 1 ? vals.join(' ') : (vals[i] !== undefined ? vals[i] : vals[0]);
        if (writeEditor(editors[i], text)) filled++;
      }
      if (filled) {
        let note = formulaNote ? '（' + formulaNote + '）' : '';
        formulaNote = '';
        // 页面自带 syncAnswer(qid, type)：九九助手填完 UEditor 就调它落库，比找「保存」按钮可靠
        const qid = qidOf(el);
        const w = (typeof unsafeWindow !== 'undefined' && unsafeWindow) || window;
        if (qid && typeof w.syncAnswer === 'function') {
          try { w.syncAnswer(qid, '2'); note += '（已 syncAnswer 落库）'; } catch (e) { /* ignore */ }
        }
        return { ok: true, why: '写了 ' + filled + ' 个编辑器' + note };
      }
    }

    // 2) 普通输入框
    const inputs = [...el.querySelectorAll('.blankItemDiv input[type="text"], .blankItemDiv input:not([type]), .stem_answer input[type="text"]')]
      .filter(i => !i.disabled && !i.readOnly);
    let filled = 0;
    for (let i = 0; i < inputs.length && i < vals.length; i++) {
      const input = inputs[i];
      input.focus();
      input.value = vals[i];
      input.dispatchEvent(new Event('input', { bubbles: true }));
      input.dispatchEvent(new Event('change', { bubbles: true }));
      input.blur();
      filled++;
    }
    if (filled) return { ok: true, why: '填了 ' + filled + ' 个空' };

    // 3) 只有一个 iframe 编辑器（老版 UEditor 没挂 textarea 时）
    const frame = el.querySelector('.edui-editor-iframeholder iframe, iframe');
    if (frame) {
      try {
        const doc = frame.contentDocument || (frame.contentWindow && frame.contentWindow.document);
        if (doc && doc.body) {
          doc.body.innerHTML = '<p>' + vals.join(' ') + '</p>';
          doc.body.dispatchEvent(new Event('input', { bubbles: true }));
          return { ok: true, why: '写入编辑器' };
        }
      } catch (e) { /* ignore */ }
    }
    return { ok: false, why: '没有可写的输入框' };
  }

  // 学习通把作答结果同时存在隐藏字段 #answer{qid} 里（单选/多选是字母串，判断是 true/false，
  // 填空/简答是文本）。点击没生效时可以直接写这个字段——它就是平台自己保存答案的地方。
  function answerField(el, qid) {
    return el.querySelector('#answer' + qid) || document.getElementById('answer' + qid);
  }

  function fieldValue(el, qid) {
    const f = answerField(el, qid);
    return f ? String(f.value == null ? '' : f.value).trim() : null;
  }

  function writeField(el, qid, value) {
    const f = answerField(el, qid);
    if (!f) return false;
    f.value = value;
    f.dispatchEvent(new Event('input', { bubbles: true }));
    f.dispatchEvent(new Event('change', { bubbles: true }));
    return true;
  }

  // 字段写完后再把界面选中态补上（多选要 check_answer_dx）
  function syncSelection(el, letters) {
    optionRows(el).forEach(row => {
      const k = keyOf(row);
      const mk = markerOf(row) || row;
      const on = letters.includes(k);
      const cls = mk.classList && mk.classList.contains('num_option_dx') ? 'check_answer_dx' : 'check_answer';
      if (mk.classList) mk.classList.toggle(cls, on);
      if (row.classList) row.classList.toggle(cls, on);
      if (row.setAttribute) {
        row.setAttribute('aria-checked', on ? 'true' : 'false');
        row.setAttribute('aria-pressed', on ? 'true' : 'false');
      }
    });
  }

  async function fillAll() {
    const containers = questionContainers();
    // 按 qid 对齐，不按下标对齐：提取时容器并集去重过，回填时若页面又变了，
    // 下标会整体错位（把 A 题的答案填进 B 题），这是不能接受的错。
    const byId = new Map(questions.map(q => [String(q.id), q]));
    const log = [];
    const items = [];
    let okCount = 0;
    for (let i = 0; i < containers.length; i++) {
      const el = containers[i];
      const qid = qidOf(el, i);
      const q = byId.get(String(qid));
      if (!q) {
        log.push(qid + ' 跳过：这个题块不在提取结果里（提取后页面有变动？重新提取一次）');
        items.push({ id: qid, ok: false, why: '不在提取结果里' });
        continue;
      }
      const ans = answers[qid];
      if (!ans || !ans.ok || !ans.answer || !ans.answer.length) {
        log.push(qid + ' 跳过：无答案');
        items.push({ id: qid, ok: false, why: '无答案' });
        continue;
      }
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      await sleep(SCROLL_WAIT + rnd(0, 200));

      // 真实页面里「计算题」常常既没选项也没题型标签（type=unknown），但题块里有编辑器；
      // 这种情况必须按文本题填，不能落进下面的选择题分支去找 A/B/C/D。
      const rowsOfQ = optionRows(el);
      const treatText = q.type === 'blank' || q.type === 'essay' || (q.type === 'unknown' && !rowsOfQ.length);
      if (treatText) {
        const r = fillBlanks(el, ans.answer);
        let ok2 = r.ok;
        let note = r.ok ? '' : ' ' + r.why;
        // 学习通的填空/简答要点题内的「保存」才落库；不点的话刷新后内容是空的
        if (ok2 && clickSave(el)) {
          note += '（已点保存）';
          await sleep(800);
        }
        // 学习通的填空/简答也是把内容同步进 #answer{qid}；填完字段还是空 → 提醒可能没存上
        const fv = fieldValue(el, qid);
        if (ok2 && fv !== null && fv === '') note += '（已填，但隐藏字段仍为空，提交前请看一眼前端）';
        if (ok2) okCount++;
        log.push(qid + (q.type === 'essay' ? ' 简答 ' : ' 填空 ') + (ok2 ? '✓' + note : '✗' + note));
        items.push({ id: qid, ok: ok2, why: note.trim() });
      } else if (q.type === 'judge') {
        const r = pickJudge(el, q, ans.answer);
        let ok2 = r.ok;
        let note = r.ok ? '' : ' ' + r.why;
        const want = judgeValue(ans.answer);
        const fv = fieldValue(el, qid);
        if (want && fv !== null && fv !== '' && fv !== want) {
          if (writeField(el, qid, want)) { ok2 = true; note = '（点击未生效，已写入隐藏答案字段）'; }
        }
        if (ok2) okCount++;
        log.push(qid + ' 判断 ' + (ok2 ? '✓' + note : '✗' + note));
        items.push({ id: qid, ok: ok2, why: note.trim() });
      } else {
        const letters = ans.answer.map(a => String(a).trim().toUpperCase()).filter(a => /^[A-Z]$/.test(a));
        if (!letters.length) { log.push(qid + ' 跳过：答案不是选项字母'); items.push({ id: qid, ok: false, why: '答案不是选项字母' }); continue; }
        const want = letters.slice().sort().join('');
        const results = letters.map(L => pickOption(el, q, L));
        let good = results.every(r => r.ok);
        let note = good ? '' : ' ' + results.map(r => r.why).join('/');
        const fv = fieldValue(el, qid);
        // 有隐藏字段就按字段判真：它才是学习通真正保存的东西
        if (fv !== null && fv !== '') {
          good = fv.replace(/[^A-Za-z]/g, '').toUpperCase().split('').sort().join('') === want;
          note = good ? '' : ' 字段是「' + fv + '」';
          if (!good && writeField(el, qid, want)) {
            syncSelection(el, letters);
            good = true;
            note = '（点击未生效，已写入隐藏答案字段）';
          }
        } else if (!good && writeField(el, qid, want)) {
          syncSelection(el, letters);
          good = true;
          note = '（点击未生效，已写入隐藏答案字段）';
        }
        if (good) okCount++;
        log.push(qid + ' ' + letters.join('') + (good ? ' ✓' + note : ' ✗' + note));
        items.push({ id: qid, ok: good, why: note.trim() });
      }
      await sleep(rnd(Q_WAIT_MIN, Q_WAIT_MAX));
    }
    return { okCount, total: containers.length, log, items };
  }


  /* ---------------- 刷章节 ---------------- */

  // 目标：在课程章节列表页点进未完成章节，在章节学习页里依次点任务点，
  // 视频静音 2 倍速播完、文档/PPT 停留计时，然后自动下一节。不交测验、不交作业。
  const CH_KEY = 'cxb_chapter_state';
  let chapRunning = false;
  let chapSkip = false;
  let chapKeepGoing = false;   // 本次不是「跑完了」，而是要继续下一节/回列表，别把 running 清掉

  const qsa = (sel, root) => Array.from((root || document).querySelectorAll(sel));
  const norm = el => (el ? (el.textContent || '').replace(/\s+/g, ' ').trim() : '');

  function chapKind() {
    const u = location.pathname + location.search;
    if (/studentstudy|knowledge\/cards/.test(u)) return 'study';
    if (/studentcourse|mycourse\/stu/.test(u)) return 'course';
    if (/fixture_chapter/.test(u)) return /mode=study/.test(u) ? 'study' : 'course';
    try {
      if (document.querySelector('.posCatalog_select, .posCatalog_name')) return 'study';
      if (document.querySelector('.chapter_item')) return 'course';
    } catch (e) {}
    return 'other';
  }
  function chapLoad() { try { return JSON.parse(GM_getValue(CH_KEY, '{}')) || {}; } catch (e) { return {}; } }
  function chapSave(o) {
    try {
      o.at = Date.now();
      // 其它分支保存进度时把「本次统计」带上，别让中途一次 chapSave 把统计清掉
      if (!o.stats) {
        const prev = JSON.parse(GM_getValue(CH_KEY, '{}') || '{}');
        if (prev && prev.stats) o.stats = prev.stats;
      }
      GM_setValue(CH_KEY, JSON.stringify(o));
    } catch (e) {}
  }
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
    if (!list.length) {
      // 新版/学校自建页：h3 里带 chapterId 的 onclick，或 onclick 里带 toOld
      list = qsa('h3').filter(el => {
        const html = el.outerHTML || '';
        const oc = (el.getAttribute('onclick') || '') + ((el.querySelector('a') || {}).getAttribute ? (el.querySelector('a').getAttribute('onclick') || '') : '');
        return /chapterId/.test(html + oc) || /toOld/.test(oc);
      });
    }
    const seen = new Set(), out = [];
    list.forEach(el => {
      const a = el.tagName === 'A' ? el : (el.querySelector('a') || el);
      if (!a) return;
      const onclick = a.getAttribute('onclick') || a.getAttribute('href') || '';
      const isChapter = el.classList.contains('chapter_item') || !!(el.closest && el.closest('.chapter_item'));
      // 新版页面章节信息常常只在 innerHTML（data-cid / onclick 文本）里，见九九助手的判据
      const hay = onclick + ' ' + (el.outerHTML || '');
      if (!isChapter && !/chapterId|toOld|getTeacherAjax|studentstudy/.test(hay)) return;
      const cid = (onclick.match(/chapterId[=:'"]*(\d+)/) || [])[1];
      const key = cid ? 'id:' + cid : (onclick.replace(/\d+/g, '#') + '|' + norm(el).slice(0, 40));
      if (seen.has(key)) return;
      seen.add(key);
      const t = norm(el);
      const done = /已完成|100%/.test(t) || !!el.querySelector('[class*="finish"], [class*="complete"], i.icon.blue');
      out.push({ el: a, name: t.slice(0, 40) || '章节', done });
    });
    return out;
  }

  // 章节学习页：任务点。真实页面至少有三种写法（旧版/新版/学校自建），都收进来。
  function taskItems() {
    const sels = [
      '.posCatalog_select', '.posCatalog_name', '.menulist-menu-title',
      '#prevNextFocusList li', '.catalog_points li',
      '[id^="cur"]', '[id*="cur"]',
    ];
    const out = [], seen = new Set();
    sels.forEach(sel => {
      let list = [];
      try { list = qsa(sel); } catch (e) { list = []; }
      list.forEach(el => {
        const t = norm(el);
        if (!t || t.length > 80) return;
        if (el.querySelector('input, textarea')) return;
        const key = (el.id || '') + '|' + t.slice(0, 30);
        if (seen.has(key)) return; seen.add(key);
        out.push({ el, name: t.slice(0, 40), id: el.id || '' });
      });
    });
    return out.slice(0, 300);
  }

  // 递归收集同源文档（任务内容常常在 #iframe_content 里再嵌一层播放器）
  function collectDocs(rootDoc, depth) {
    const docs = [rootDoc || document];
    const d0 = depth == null ? 2 : depth;
    for (let i = 0; i < docs.length && i < 40; i++) {
      if (d0 <= 0) break;
      let frames = [];
      try { frames = qsa('iframe', docs[i]); } catch (e) { frames = []; }
      frames.forEach(f => {
        try {
          const d = f.contentDocument;
          if (d && d.body && docs.indexOf(d) < 0) docs.push(d);
        } catch (e) { /* 跨域 */ }
      });
    }
    return docs;
  }
  function sameOriginDocs() { return collectDocs(document, 2); }

  function findVideos() {
    const out = [];
    sameOriginDocs().forEach(d => {
      try {
        // 视频和音频任务点都要算：音频也能播放计时
        qsa('video, audio', d).forEach(v => out.push({ v, d }));
        // 学习通的音频任务点常是 .audioReader 里只放 <source>，没有现成 <audio>，补一个
        qsa('.audioReader', d).forEach(box => {
          if (box.querySelector('audio')) return;
          const s = box.querySelector('source');
          const src = (s && (s.getAttribute('src') || s.src)) || box.getAttribute('data-src') || box.getAttribute('src');
          if (!src) return;
          const a = d.createElement('audio');
          a.src = src;
          a.preload = 'auto';
          box.appendChild(a);
          out.push({ v: a, d });
        });
      } catch (e) {}
    });
    return out;
  }
  // 任务点是否已显示「已完成」
  function taskDone(el) {
    return !!el.querySelector('.icon.blue, [class*="complete"], [class*="finish"]') || /已完成/.test(norm(el));
  }
  function anyVideoPlaying() {
    return findVideos().some(({ v }) => !v.paused && !v.ended);
  }

  // 处理当前任务点：视频播完 / 文档停留
  // 测验/作业/考试/讨论/投票 这类任务点只点开不交也会产生「已开始」记录，直接跳过（我们只刷视频/文档）
  const SKIP_TASK_RE = /测验|作业|考试|讨论|投票|问卷|互评|章节检测|签到/;
  async function handleTask(item, idx) {
    if (SKIP_TASK_RE.test(item.name)) {
      chapLog('跳过非视频任务点：' + item.name);
      try { const s = chapLoad(); s.stats = s.stats || { tasks: 0, skipped: 0 }; s.stats.skipped += 1; chapSave(s); } catch (e) {}
      return true;
    }
    chapLog('任务点 ' + (idx + 1) + '：' + item.name);
    try { item.el.click(); } catch (e) { chapLog('点不动这个任务点：' + (e.message || e)); }
    await sleep(2500);

    const end = Date.now() + 45 * 60 * 1000;
    try { const s0 = chapLoad(); s0.stats = s0.stats || { tasks: 0, skipped: 0 }; s0.stats.tasks += 1; chapSave(s0); } catch (e) {}
    let lastLog = 0;
    // 视频卡住（currentTime 不涨）的看门狗：先重试播放，长时间不动就跳过，别把整门课卡死
    const stall = new Map();
    const STALL_WARN = Number(window.__CXB_STALL_WARN_MS) || 25000;
    const STALL_SKIP = Number(window.__CXB_STALL_SKIP_MS) || 90000;
    while (chapRunning && Date.now() < end) {
      const vids = findVideos().filter(({ v }) => !v.ended && isFinite(v.duration) && v.duration > 0);
      if (!vids.length) {
        // 文档 / PPT 页面：停留 20–40 秒算过
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
          if (v.paused && !v.ended) {
            // 有的播放器必须先点大播放按钮，直接调 play() 不生效
            try {
              const d = v.ownerDocument || document;
              const btn = d.querySelector('.vjs-big-play-button, .xgplayer-start, .prism-big-play-btn, [class*="bigPlay"], [class*="play-btn"], [class*="playButton"]');
              if (btn) btn.click(); else v.dispatchEvent(new MouseEvent('click', { bubbles: true }));
            } catch (e) {}
            await sleep(600);
            if (v.paused && !v.ended) await v.play().catch(() => {});
          }
        } catch (e) {}
        const cur = v.currentTime || 0, dur = v.duration || 0;
        if (dur && cur >= dur - 2) continue;
        const st = stall.get(v) || { cur: -1, at: Date.now(), warned: 0 };
        if (Math.abs(cur - st.cur) > 0.4) { st.cur = cur; st.at = Date.now(); }
        stall.set(v, st);
        const stuck = Date.now() - st.at;
        if (stuck > STALL_WARN && Date.now() - st.warned > 5000) {
          st.warned = Date.now();
          chapLog('视频卡住 ' + Math.round(stuck / 1000) + 's（时间不动），重试播放');
          try {
            const d = v.ownerDocument || document;
            const btn = d.querySelector('.vjs-big-play-button, .xgplayer-start, .prism-big-play-btn, [class*="bigPlay"], [class*="play-btn"]');
            if (btn) btn.click(); else v.dispatchEvent(new MouseEvent('click', { bubbles: true }));
            await v.play().catch(() => {});
          } catch (e) {}
        }
        if (stuck > STALL_SKIP) { chapLog('视频一直不动，跳过这个任务点'); return true; }
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
      state.listUrl = location.href;
      state.totalChapters = items.length;
      chapSave(state);
      chapStatus('第 ' + (idx + 1) + ' / ' + items.length + ' 章：' + items[idx].name, ((idx + 1) / items.length) * 100);
      const target = items[idx].el;
      try { target.click(); } catch (e) {}
      try { const inner = target.querySelector && target.querySelector('a'); if (inner) inner.click(); } catch (e) {}
      await sleep(4000);
      return true;
    }
    chapLog('所有章节都完成了');
    return false;
  }

  function chapterDiag() {
    const counts = {};
    ['.chapter_item', '.chapter_unit a', 'h3 a', '.posCatalog_select', '.posCatalog_name',
     '.menulist-menu-title', '#prevNextFocusList li', '[id^="cur"]', 'video', 'iframe'].forEach(sel => {
      try { counts[sel] = qsa(sel).length; } catch (e) { counts[sel] = -1; }
    });
    // 同源 iframe 里也数一遍（学习页的任务点/播放器常在 #iframe_content 内）
    let docs = 0, vids = 0;
    try {
      sameOriginDocs().forEach(d => { docs++; try { vids += qsa('video', d).length; } catch (e) {} });
    } catch (e) {}
    counts.docs = docs;
    counts.videosInDocs = vids;
    counts.nextBtn = qsa('#prevNextFocusNext, a[onclick*=getTeacherAjax], .nextChapter').length;
    counts.tasks = taskItems().length;
    return counts;
  }
  function chapterDiagText() {
    return Object.entries(chapterDiag()).map(([k, v]) => k + '=' + v).join('，');
  }
  async function reportChapter() {
    const diag = chapterDiag();
    const cands = []
      .concat(qsa('.chapter_item, .posCatalog_select, .posCatalog_name, #prevNextFocusList li'))
      .slice(0, 25)
      .map((el, i) => ({ i, id: el.id || '', cls: el.className || '', html: (el.outerHTML || '').replace(/data:image[^"']*/g, '<img>').slice(0, 400) }));
    try {
      await postJSON('/report', {
        url: location.href, at: new Date().toISOString(), kind: 'chapter',
        count: cands.length, diag, containers: cands.length,
        markup: cands, questions: [], chapter: chapterDiag(),
      });
      log('章节结构已上报（' + cands.length + ' 个候选）');
    } catch (e) { log('章节结构上报失败：' + (e.message || e)); }
  }

  async function chapterRun() {
    chapRunning = true;
    const kind = chapKind();
    let state = chapLoad();
    const courseKey = chapCourseKey();
    // 换了课程就把进度清零，避免把 A 课的第 3 章当成 B 课的第 3 章
    if (state.course && courseKey && state.course !== courseKey) {
      chapLog('换了课程（' + state.course + ' → ' + courseKey + '），进度从头开始');
      state = { chapterIdx: 0, taskIdx: 0, done: {} };
    }
    state.course = courseKey;
    state.running = true;
    state.done = state.done || {};
    chapSave(state);
    chapLog('开始：' + (kind === 'course' ? '章节列表页' : kind === 'study' ? '章节学习页' : '未知页面'));
    chapLog('选择器命中：' + chapterDiagText());
    try {
      if (kind === 'course') {
        const ok = await goNextChapter(state);
        if (!ok) chapStatus('没有可刷的章节', 100);
      } else if (kind === 'study') {
        const ok = await runChapterTaskLoop(state);
        // 本页任务点跑完 → 尝试点下一节
        const nxt = qsa('#prevNextFocusNext, a#prevNextFocusNext, a[onclick*="getTeacherAjax"], .nextChapter').find(e => /下一?节|下一个|下一章/.test(norm(e))) || qsa('#prevNextFocusNext')[0];
        if (ok && chapRunning && nxt) { chapLog('点下一节'); chapKeepGoing = true; nxt.click(); }
        else if (ok && chapRunning) {
          // 没有「下一节」按钮：记下进度，回章节列表继续下一章
          state.chapterIdx = (state.chapterIdx || 0) + 1;
          state.taskIdx = 0;
          chapSave(state);
          chapStatus('本章完成，回章节列表继续', 100);
          if (state.listUrl) { chapKeepGoing = true; chapLog('回章节列表：' + state.listUrl); location.href = state.listUrl; }
          else chapLog('没记住章节列表地址，请点「开始刷章节」所在的列表页刷新一下');
        }
      } else {
        chapLog('当前页面不是课程章节页，请先打开「课程 → 章节」');
      }
    } finally {
      chapRunning = false;
      if (!chapKeepGoing) { state.running = false; chapStatus('已停止'); }
      chapSave(state);
      chapKeepGoing = false;
    }
  }

  /* ---------------- 面板 ---------------- */

  const panel = document.createElement('div');
  panel.id = 'cxb-panel';
  panel.style.cssText = [
    'position:fixed', 'right:16px', 'bottom:16px', 'z-index:2147483647',
    'width:360px', 'max-height:70vh', 'overflow:auto',
    'background:#fff', 'border:1px solid #d7dbe0', 'border-radius:10px',
    'box-shadow:0 8px 28px rgba(0,0,0,.18)', 'font:13px/1.55 system-ui,-apple-system,sans-serif',
    'color:#1f2328', 'padding:0',
  ].join(';');

  panel.innerHTML = `
    <div style="display:flex;align-items:center;gap:8px;padding:9px 12px;border-bottom:1px solid #eef1f4">
      <strong style="font-size:13px">cx-bridge</strong>
      <span style="color:#8b5cf6;font-size:11px">v${VERSION}</span>
      <span id="cxb-state" style="color:#8a9199;font-size:12px">未连接</span>
      <button id="cxb-min" title="折叠/展开" style="margin-left:auto;border:0;background:none;cursor:pointer;font-size:15px;color:#8a9199">–</button>
      <button id="cxb-hide" title="隐藏面板（刷新回来）" style="border:0;background:none;cursor:pointer;font-size:15px;color:#8a9199">×</button>
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
        <button id="cxb-chap-diag">诊断结构</button>
        <button id="cxb-chap-resume">继续上次</button>
        <button id="cxb-chap-reset">清空进度</button>
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
      <div class="kv"><span>刷章节</span><b id="cxb-i-chap">-</b></div>
      <div class="kv"><span>上次上报</span><b id="cxb-i-report">-</b></div>
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
  `;
  const style = document.createElement('style');
  style.textContent = `#cxb-panel button{border:1px solid #d7dbe0;background:#f7f8fa;border-radius:6px;padding:5px 10px;font-size:12px;cursor:pointer}
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
  #cxb-panel .bar i{display:block;height:100%;width:0;background:#3569d4;transition:width .3s}`;
  document.head.appendChild(style);
  document.body.appendChild(panel);

  const $ = id => panel.querySelector('#' + id);
  const stateEl = $('cxb-state');
  const logEl = $('cxb-log');

  // ---- 页签 ----
  const tabBtns = qsa('#cxb-tabs button');
  function showTab(name) {
    tabBtns.forEach(b => b.classList.toggle('on', b.dataset.tab === name));
    ['quiz', 'chapter', 'info'].forEach(n => { const el = $('cxb-tab-' + n); if (el) el.hidden = (n !== name); });
  }
  tabBtns.forEach(b => { b.onclick = () => showTab(b.dataset.tab); });
  showTab((chapKind() === 'course' || chapKind() === 'study') ? 'chapter' : 'quiz');
  if (chapKind() !== 'other') setTimeout(() => log('[章节] 选择器命中：' + chapterDiagText()), 1200);

  const infoVals = {
    engine: $('cxb-i-engine'), model: $('cxb-i-model'), data: $('cxb-i-data'),
    task: $('cxb-i-task'), count: $('cxb-i-count'), chap: $('cxb-i-chap'),
    report: $('cxb-i-report'),
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
    refreshChapStats();
    try {
      const r = await getJSON('/report');
      if (r && r.ok) {
        const at = (r.at || '').replace('T', ' ').slice(5, 16);
        setInfo('report', (r.kind || '?') + ' · ' + (r.count || 0) + ' 个 · ' + at);
      } else setInfo('report', '还没有');
    } catch (e) { setInfo('report', '-'); }
  }
  function statsTail(st) {
    const s = (st && st.stats) || {};
    const parts = [];
    if (s.tasks) parts.push('本次 ' + s.tasks + ' 个任务点');
    if (s.skipped) parts.push('跳过 ' + s.skipped);
    if (st && st.at) {
      const mins = Math.round((Date.now() - (st.startAt || st.at)) / 60000);
      if (mins > 0) parts.push('用时 ' + mins + ' 分');
    }
    return parts.length ? ' · ' + parts.join(' · ') : '';
  }
  function refreshChapStats() {
    try {
      const st = chapLoad();
      const items = chapterItems();
      const done = items.filter(x => x.done).length;
      const kind = chapKind();
      let txt;
      if (kind === 'study') {
        const tasks = taskItems();
        const finished = tasks.filter(x => taskDone(x.el)).length;
        txt = '学习页 · 任务点 ' + finished + '/' + tasks.length + (st.chapterIdx != null ? ' · 第 ' + (st.chapterIdx + 1) + ' 章' : '') + statsTail(st);
      } else if (kind === 'course') {
        txt = '列表页 · 已完成 ' + done + '/' + items.length + (st.running ? ' · 运行中' : '') + statsTail(st);
      } else {
        txt = st.running ? '运行中 · 第 ' + ((st.chapterIdx || 0) + 1) + ' 章' : '未开始';
      }
      setInfo('chap', txt);
    } catch (e) { setInfo('chap', '-'); }
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


  function log(msg) {
    logEl.textContent += (logEl.textContent ? '\n' : '') + msg;
    logEl.scrollTop = logEl.scrollHeight;
  }
  function setState(t, color) {
    stateEl.textContent = t;
    stateEl.style.color = color || '#8a9199';
  }
  function setBusy(b) {
    busy = b;
    ['cxb-agent', 'cxb-all', 'cxb-extract', 'cxb-solve', 'cxb-fill', 'cxb-report'].forEach(id => { const el = $(id); if (el) el.disabled = b; });
  }

  async function withBusy(fn) {
    if (busy) return;
    setBusy(true);
    try { await fn(); }
    catch (e) { log('错误：' + (e && e.message ? e.message : e)); setState('出错', '#c0392b'); }
    finally { setBusy(false); }
  }

  // 调试入口：控制台执行__cxb_state() 可看到当前提取/作答结果
  window.__cxb_state = () => ({ questions, answers, chapter: chapLoad(), diag: chapterDiag() });

  $('cxb-hide').onclick = () => { panel.style.display = 'none'; };

  function diagText() {
    return Object.entries(lastDiag)
      .filter(([, n]) => n)
      .map(([sel, n]) => sel.replace(/^\./, '') + '=' + n)
      .join('，');
  }

  // 每次提取都顺手把结构报给 cx-bridge（last-report.json）。
  // 这样页面一改版，我看一眼真实计数就能定位是哪条选择器掉了，不用你再描述页面。
  // 报告里带一段 HTML 快照：选择器对不上时我可以直接看真实标记，不用你描述页面。
  // base64 图片要剔掉，否则 last-report.json 会涨到几 MB。
  function htmlSnippet(el) {
    try {
      let h = el.outerHTML || '';
      h = h.replace(/data:image\/[a-z0-9.+-]+;base64,[A-Za-z0-9+/=]+/gi, 'data:image/...;base64,<omitted>');
      h = h.replace(/\s+/g, ' ');
      return h.slice(0, 2000);
    } catch (e) { return ''; }
  }

  async function reportStructure() {
    try {
      // 图片题会把整张 dataURL 塞进报告，last-report.json 能涨到几 MB；
      // 报告只用来校准选择器，图片只留体积占位即可。
      const slim = questions.map(q => Object.assign({}, q, {
        images: (q.images || []).map(s => '[图片 ' + Math.round(String(s).length / 1024) + 'KB]'),
      }));
      const conts = questionContainers();
      const markup = conts.slice(0, 40).map((el, i) => ({ id: qidOf(el, i), html: htmlSnippet(el) }));
      await postJSON('/report', {
        url: location.href,
        at: new Date().toISOString(),
        kind: pageKind(),
        fontEncrypted: pageFontEncrypted(),
        count: questions.length,
        diag: lastDiag,
        containers: conts.length,
        markup: markup,
        formula: formulaProbe(),
        questions: slim,
      });
      return true;
    } catch (e) { return false; }
  }

  $('cxb-report').onclick = () => withBusy(async () => {
    logEl.textContent = '';
    log('开始提取并导出结构…');
    questions = await extractAll();
    const ok = await reportStructure();
    log('提取 ' + questions.length + ' 道，结构诊断：' + (diagText() || '无'));
    log(ok ? '已写入 cx-bridge/last-report.json' : '导出失败：桥接服务没起（server.py）');
  });

  async function doExtract(clear) {
    if (clear !== false) logEl.textContent = '';
    log('开始提取…');
    questions = await extractAll();
    refreshQuizStats();
    const byType = questions.reduce((m, q) => (m[q.type] = (m[q.type] || 0) + 1, m), {});
    log('共 ' + questions.length + ' 道：' + Object.entries(byType).map(([k, v]) => k + ' ' + v).join('，'));
    const imgs = questions.filter(q => q.images && q.images.length).length;
    log('带图片的题：' + imgs + ' 道');
    const garbled = questions.filter(q => q._garbled).length;
    if (garbled) log('⚠ ' + garbled + ' 道题干疑似字体加密（乱码），这些题答案不可信，建议跳过');
    if (!questions.length) log('⚠ 没抓到题：页面结构可能不同，点「导出结构」发我');
    log('结构诊断：' + (diagText() || '无命中'));
    // 页面类型与字体加密先说清楚：这是「答了也白答」的两种典型情况
    const kind = pageKind();
    if (kind === 'exam') log('⚠ 这是考试页：我只提取和填，绝不提交；保存入口和作业页不一样，必要时你手动点保存');
    if (kind === 'view') log('⚠ 这是查看/批改页，没有作答入口，填不进去；请回到作业作答页');
    if (pageFontEncrypted()) log('⚠ 页面用了字体加密（font-cxsecret），抓到的文字可能是错的，这次答案别信');
    if (await reportStructure()) log('结构已存到 cx-bridge/last-report.json（选择器校准用）');
    setState('已提取 ' + questions.length + ' 题', '#1a7f37');
  }

  const POLL_MS = 2000;

  function showAnswers() {
    const ok = Object.values(answers).filter(a => a.ok).length;
    Object.entries(answers).sort((a, b) => a[0].localeCompare(b[0], undefined, { numeric: true }))
      .forEach(([id, a]) => {
        log(id + '  ' + (a.ok ? a.answer.join('、') : '失败：' + a.error) + (a.reason ? '  // ' + a.reason : ''));
      });
    return ok;
  }
  const WAIT_MS = 60 * 60 * 1000;   // 只用来提示，不再是流程终点

  // 事件化等待：答案一落盘就返回；做题会话退出且没答案才放弃（不再固定计时到点就失败）。
  async function waitAnswers() {
    const t0 = Date.now();
    let tick = 0, hinted = false, deadChecks = 0, gaveUp = false;
    while (true) {
      await sleep(POLL_MS);
      tick++;
      try {
        const a = await getJSON('/answers');
        if (a && a.ready && a.answers) {
          answers = a.answers;
          refreshQuizStats();
          const ok = showAnswers();
          log('已作答 ' + ok + '/' + Object.keys(answers).length);
          setState('已作答 ' + ok + '/' + Object.keys(answers).length, '#1a7f37');
          return true;
        }
      } catch (e) { /* 服务短暂重启，继续等 */ }

      if (tick % 10 === 0) {
        setState('等答案 ' + Math.round((Date.now() - t0) / 1000) + 's…', '#8b5cf6');
        let st = null;
        try { st = await getJSON('/agent-status'); } catch (e) { }
        if (st && st.running === false) {
          if ((st.answered || 0) > 0) {
            if (!gaveUp) { log('做题会话结束了，但答案和当前这批题对不上（' + (st.reason || '指纹不一致') + '）。点「提取」刷新后点「开始做题」即可复用/补做。'); gaveUp = true; }
            return false;
          }
          deadChecks++;
          // 会话退出后答案可能刚好才落盘：再耐心查几轮 /answers 才认定失败
          if (deadChecks >= 2) {
            try {
              const a2 = await getJSON('/answers');
              if (a2 && a2.ready && a2.answers) {
                answers = a2.answers;
                refreshQuizStats();
                const ok2 = showAnswers();
                log('已作答 ' + ok2 + '/' + Object.keys(answers).length);
                setState('已作答 ' + ok2 + '/' + Object.keys(answers).length, '#1a7f37');
                return true;
              }
            } catch (e) { /* ignore */ }
          }
          if (deadChecks >= 5) {
            log('做题会话已退出，没等到答案。看 http://127.0.0.1:8790/logs 排查；可以点「回填」用已有答案，或点「开始做题」重试（已答的题会复用）。');
            setState('做题会话退出', '#c0392b');
            return false;
          }
        } else if (st && st.running) {
          deadChecks = 0;
        }
      }
      if (!hinted && Date.now() - t0 > WAIT_MS) {
        hinted = true;
        log('已经等了 60 分钟，脚本继续等；也可以先点「回填」用已有答案试一次。');
      }
    }
  }

  // 手动点「开始做题」：把题交上去，再让 server 起一个全新的 DSH 会话（flash / 思考 low）做题，
  // 本页只负责等答案并回填。不会新建浏览器里任何东西。
  async function doAgentSolve() {
    if (!questions.length) { log('先点「提取」'); return; }
    const p = await ping();
    log('桥接服务在线（engine=' + (p.engine || 'agent') + '）');
    const payload = questions.map(({ id, type, stem, options, images }) => ({ id, type, stem, options, images }));
    const q = await postJSON('/extract', { questions: payload });
    LAST_TASK = q.task_id || LAST_TASK;

    // 题目指纹没变：服务端会复用已有答案，重复点不会把上一轮答案清掉
    if (q.reused) {
      log('题目没变（' + q.fingerprint + '），复用已有 ' + (q.answered || 0) + ' 条答案，不重复做题');
      if (q.ready) {
        setState('复用已有答案', '#1a7f37');
        const got0 = await waitAnswers();
        if (!got0) return;
        await doFill();
        log('回填完成。请自己核对一遍再提交。');
        return;
      }
      log('有 ' + (q.answered || 0) + ' 条旧答案，还差一些，起新会话补做（它会把全量答案重交一次）');
      setState('补做缺的题…', '#8b5cf6');
    } else {
      LAST_TASK = q.task_id || null;
      log('题目已登记（' + q.count + ' 道，task ' + q.task_id + '）');
    }

    const r = await postJSON('/agent-solve', {});
    if (!r.ok) { log('启动新会话失败：' + (r.error || '未知')); return; }
    log('已开新会话做题（' + (r.count || q.count) + ' 道，deepseek-v4.1-flash / 思考 low）');
    setState('新会话做题中…', '#8b5cf6');
    const got = await waitAnswers();
    if (!got) return;
    await doFill();
    log('回填完成。请自己核对一遍再提交。');
  }

  async function doSolve() {
    if (!questions.length) { log('先点「提取」'); return; }
    const p = await ping();
    log('桥接服务在线（engine=' + (p.engine || 'direct') + '）');
    setState('作答中…', '#3569d4');
    const payload = questions.map(({ id, type, stem, options, images }) => ({ id, type, stem, options, images }));

    // agent 模式：不调外部 API，题目交给 DSH 这边的模型（也就是我）；脚本轮询等答案
    if ((p.engine || 'agent') !== 'direct') {
      const q = await postJSON('/extract', { questions: payload });
      LAST_TASK = q.task_id || LAST_TASK;
      if (q.reused) {
        log('题目没变，复用已有 ' + (q.answered || 0) + ' 条答案（不重复做题、不清空）');
        setState('复用已有答案…', '#8b5cf6');
      } else {
        log('题目已交给 DSH 侧（' + q.count + ' 道）。跟助手说一声「作答」，脚本会自动等答案…');
        setState('已交给助手，等它作答…', '#8b5cf6');
      }
      return await waitAnswers();
    }

    // direct 模式：服务端自己调模型
    const r = await postJSON('/solve', { questions: payload });
    answers = r.answers || {};
    refreshQuizStats();
    log('完成：' + r.solved + '/' + r.total + '，用时 ' + r.elapsed + 's');
    showAnswers();
    setState('已作答 ' + r.solved + '/' + r.total, '#1a7f37');
  }

  async function doFill() {
    // 页面可能因为刷新/等待超时没把答案留在内存里：先从服务端取一次
    if (!Object.keys(answers).length) {
      try {
        const a = await getJSON('/answers');
        if (a && a.ready && a.answers) {
          answers = a.answers;
          refreshQuizStats();
          LAST_TASK = a.task_id || LAST_TASK;
          log('已从服务端取到 ' + Object.keys(answers).length + ' 条答案');
        }
      } catch (e) { /* 服务没起就算了 */ }
    }
    if (!Object.keys(answers).length) { log('还没有答案：先点「开始做题」，或在会话里说「作答」'); return; }
    log('开始回填（不会提交，请自行核对后手动提交）…');
    const r = await fillAll();
    log('回填完成：' + r.okCount + '/' + r.total);
    r.log.forEach(l => log('  ' + l));
    setState('已回填 ' + r.okCount + '/' + r.total, '#1a7f37');
    // 把回填结果落到服务端，助手不用问也能看到成功几题、哪几题失败
    try {
      const fails = (r.items || []).filter(x => !x.ok).map(x => ({ id: x.id, why: x.why }));
      await postJSON('/fill-report', {
        url: location.href,
        at: new Date().toISOString(),
        task_id: LAST_TASK,
        ok: r.okCount, total: r.total, fails: fails,
      });
    } catch (e) { log('回填结果上报失败：' + (e.message || e)); }
  }

  $('cxb-all').onclick = () => withBusy(async () => {
    await doExtract();
    if (!questions.length) return;
    await doSolve();
    if (!Object.keys(answers).length) return;
    await doFill();
    log('一键完成。请自己核对一遍再提交。');
  });
  $('cxb-agent').onclick = () => withBusy(() => doAgentSolve());
  $('cxb-extract').onclick = () => withBusy(() => doExtract());
  $('cxb-solve').onclick = () => withBusy(() => doSolve());
  $('cxb-fill').onclick = () => withBusy(() => doFill());
  $('cxb-chap-start').onclick = () => withBusy(chapterRun);
  // 点进章节会整页跳转，脚本重载后自动接着刷（状态存在 GM 里）
  setTimeout(() => {
    if (!chapRunning && (chapKind() === 'study' || chapKind() === 'course')) {
      const st = chapLoad();
      if (st && st.running) {
        const ageH = st.at ? (Date.now() - st.at) / 3600000 : 0;
        if (st.at && ageH > 12) {
          // 隔了很久（比如隔天）不自动开跑，免得你打开课程页它突然自己动
          st.running = false; chapSave(st);
          chapLog('上次进度是 ' + ageH.toFixed(1) + ' 小时前的，没有自动继续；要接着刷就点「继续上次」');
        } else {
          chapLog('检测到上次没刷完，自动继续（' + (ageH ? ageH.toFixed(1) + ' 小时前' : '刚刚') + '）');
          withBusy(chapterRun);
        }
      }
    }
  }, 2000);
  $('cxb-min').onclick = () => {
    const mini = panel.classList.toggle('mini');
    ['#cxb-tabs', '#cxb-tab-quiz', '#cxb-tab-chapter', '#cxb-tab-info', '#cxb-log-wrap'].forEach(sel => {
      const el = qsa(sel)[0]; if (el) el.style.display = mini ? 'none' : '';
    });
    $('cxb-min').textContent = mini ? '+' : '–';
    $('cxb-min').title = mini ? '展开' : '折叠/展开';
  };
  $('cxb-chap-reset').onclick = () => {
    chapSave({ running: false, done: {}, chapterIdx: 0, taskIdx: 0, stats: { tasks: 0, skipped: 0 } });
    chapStatus('进度已清空', 0);
    chapLog('章节进度已清空（下次从第 1 章开始）');
    refreshChapStats();
  };
  $('cxb-chap-stop').onclick = () => { chapRunning = false; const st = chapLoad(); st.running = false; chapSave(st); chapLog('你点了停止'); chapStatus('已停止'); };
  $('cxb-chap-skip').onclick = () => { chapSkip = true; chapLog('跳过当前任务点'); };
  $('cxb-chap-diag').onclick = () => withBusy(async () => { log('选择器命中：' + chapterDiagText()); await reportChapter(); });
  $('cxb-chap-resume').onclick = () => withBusy(async () => {
    const st = chapLoad();
    if (!st.chapterIdx && st.chapterIdx !== 0) { log('没有上次进度，直接点「开始刷章节」'); return; }
    st.running = true; chapSave(st);
    log('继续上次进度：第 ' + ((st.chapterIdx || 0) + 1) + ' 章');
    await chapterRun();
  });


  // 打开页面就自动上报一次结构：这样我不需要你点任何按钮，刷新一下我就能拿到真实标记。
  // 只报容器 + HTML 片段 + 诊断，不下载图片（避免一开页面就拖 18 张图）。
  async function quickReport() {
    try {
      const conts = questionContainers();
      if (conts.length < 3) return;             // 不像题目页就别覆盖上一份报告
      const markup = conts.slice(0, 40).map((el, i) => ({ id: qidOf(el, i), html: htmlSnippet(el) }));
      await postJSON('/report', {
        url: location.href,
        at: new Date().toISOString(),
        kind: pageKind(),
        fontEncrypted: pageFontEncrypted(),
        count: conts.length,
        diag: lastDiag,
        containers: conts.length,
        markup: markup,
        formula: formulaProbe(),
        questions: [],
        auto: true,
      });
      log('已自动上报页面结构（' + conts.length + ' 个题块），助手可据此校准选择器');
    } catch (e) { /* 服务没起就静默 */ }
  }

  // 全自动流程：作业作答页打开/刷新后，自己完成 提取 → 交 DSH → 等答案 → 回填。
  // 你不需要点任何按钮；当然也不会替你提交。加 ?cxb_manual=1 可关掉自动流程。
  let autoRan = false;
  async function autoRun() {
    if (autoRan) return;
    if (!/[?&]cxb_auto=1/.test(location.search)) return;   // 默认不自动：要自动跑加 ?cxb_auto=1
    if (pageKind() !== 'work') return;   // 只在作业作答页全自动；考试页/查看页不动
    autoRan = true;
    log('自动流程启动：提取 → 交给 DSH → 轮询答案 → 回填（不会提交）');
    await withBusy(async () => {
      await doExtract();
      if (!questions.length) { log('⚠ 没抓到题，自动流程停止'); return; }
      await doSolve();
      if (!Object.keys(answers).length) { log('⚠ 没等到答案，自动流程停止'); return; }
      await doFill();
      log('自动流程完成。请核对一遍，自己点提交。');
    });
  }

  // 打开时就探一次桥接服务
  ping().then(async p => {
    setState('已连接 · ' + p.model, '#1a7f37');
    setTimeout(async () => {
      await quickReport();
      try {
        const k = 'cxb_chap_reported:' + location.href;
        if (chapKind() !== 'other' && !sessionStorage.getItem(k)) {
          sessionStorage.setItem(k, '1');
          await reportChapter();
        }
      } catch (e) {}
      await autoRun();
    }, 1500);
  }).catch(() => setState('未连接（先运行 server.py）', '#c0392b'));
})();
