#!/usr/bin/env node
// cx-bridge 的 DSH 侧 MCP 服务（stdio，零依赖手写 JSON-RPC）。
//
// 作用：让助手（DSH 会话里的模型）能通过**工具调用**直接操控 cx-bridge，
// 而不是只在聊天里贴文件内容。做题的仍然是 DSH 的模型（就是助手自己），
// 这里只做两件事：把页面交上来的题目读给助手、把助手的答案写回去。
//
// 协议：MCP = 换行分隔的 JSON-RPC 2.0。只实现 initialize / tools/list / tools/call / ping。
// 工具：
//   cx_status        看服务状态、有没有待答的题
//   cx_take_questions 取走当前待答题目（pending.json）
//   cx_submit_answers 写入答案（answers.json），页面脚本轮询到就自动回填
//   cx_report        最近一次「导出结构」的内容（选择器校准用）
//
// 数据流不变：脚本 /extract → pending.json → 本 MCP 读给助手 → 助手答 → 本 MCP 写
// answers.json → 脚本轮询 /answers → 回填。
import fs from 'node:fs';
import path from 'node:path';

const HERE = process.env.CXD_DATA_DIR || 'C:\\Users\\10183\\Desktop\\ds\\cx-bridge';
const PENDING = path.join(HERE, 'pending.json');
const ANSWERS = path.join(HERE, 'answers.json');
const REPORT = path.join(HERE, 'last-report.json');

function readJSON(p, fallback = null) {
  try {
    return JSON.parse(fs.readFileSync(p, 'utf8'));
  } catch {
    return fallback;
  }
}

function writeJSON(p, obj) {
  fs.writeFileSync(p, JSON.stringify(obj, null, 1), 'utf8');
}

// 有些客户端会把 object 参数串化成 JSON 字符串传进来（模型侧常见），这里统一兜一下。
function asObject(v) {
  if (v == null) return {};
  if (typeof v === 'string') {
    try {
      const o = JSON.parse(v);
      return o && typeof o === 'object' ? o : {};
    } catch {
      return {};
    }
  }
  return typeof v === 'object' ? v : {};
}

const TOOLS = [
  {
    name: 'cx_status',
    description: '查看 cx-bridge 状态：有没有待作答的题目、上一轮答案是否还在。',
    inputSchema: { type: 'object', properties: {}, additionalProperties: false },
  },
  {
    name: 'cx_take_questions',
    description:
      '取走学习通页面交上来的待答题目（题干/选项/图片）。返回 task_id 和题目列表；作答后必须用 cx_submit_answers 交回，页面才会自动回填。',
    inputSchema: { type: 'object', properties: {}, additionalProperties: false },
  },
  {
    name: 'cx_submit_answers',
    description:
      '把答案交回 cx-bridge，页面脚本轮询到后自动回填。answers 的键是题目 id，值是 {answer:[...], reason:"..."}；选择题用选项字母（多选多个），判断题用 ["true"]/["false"]，填空题按空的顺序给文本。',
    inputSchema: {
      type: 'object',
      properties: {
        answers: {
          type: 'object',
          description: '题目 id -> {answer: string[], reason?: string}',
          additionalProperties: true,
        },
        task_id: { type: 'string', description: '可选：必须与 pending.json 的 task_id 一致' },
      },
      required: ['answers'],
      additionalProperties: false,
    },
  },
  {
    name: 'cx_report',
    description: '读取最近一次页面「导出结构」的结果（选择器校准、排查抓不到题时用）。',
    inputSchema: { type: 'object', properties: {}, additionalProperties: false },
  },
];

function callTool(name, rawArgs) {
  const args = asObject(rawArgs);
  if (name === 'cx_status') {
    const pend = readJSON(PENDING);
    const ans = readJSON(ANSWERS);
    return {
      pending: pend
        ? { task_id: pend.task_id, count: pend.count, created: pend.created }
        : null,
      answered: ans ? { task_id: ans.task_id, count: Object.keys(ans.answers || {}).length } : null,
    };
  }
  if (name === 'cx_take_questions') {
    const pend = readJSON(PENDING);
    if (!pend) throw new Error('没有待答题目：先在页面上点「提取」或「一键做完」');
    return pend;
  }
  if (name === 'cx_submit_answers') {
    const pend = readJSON(PENDING);
    if (!pend) throw new Error('没有待答题目（pending.json 不存在）');
    const taskId = (args && args.task_id) || pend.task_id;
    if (taskId !== pend.task_id) {
      throw new Error(`task_id 不匹配：当前 ${pend.task_id}，收到 ${taskId}`);
    }
    const raw = asObject(args.answers);
    const rawKeys = Object.keys(raw);
    if (!rawKeys.length) {
      throw new Error('answers 是空的或不是对象（如果客户端把参数串化成了字符串，这里会自动解析；解析不出就说明模型没传对）');
    }
    const prev = readJSON(ANSWERS) || {};
    const sameRound =
      prev.task_id === pend.task_id ||
      (prev.fingerprint && pend.fingerprint && prev.fingerprint === pend.fingerprint);
    const answers = sameRound ? { ...(prev.answers || {}) } : {};
    let accepted = 0;
    for (const q of pend.questions || []) {
      const id = String(q.id);
      const a = raw[id];
      if (!a) continue;
      const obj = asObject(a);
      const arr = Array.isArray(obj.answer) ? obj.answer : obj.answer != null ? [obj.answer] : [];
      const clean = arr.map((x) => String(x).trim()).filter(Boolean);
      answers[id] = {
        ok: clean.length > 0,
        answer: clean,
        reason: String(obj.reason || '').slice(0, 300),
      };
      accepted++;
    }
    const missing = (pend.questions || []).map((q) => String(q.id)).filter((id) => !(answers[id] && answers[id].ok));
    writeJSON(ANSWERS, {
      task_id: pend.task_id,
      fingerprint: pend.fingerprint || null,
      answers,
      by: 'dsh-mcp',
      updated: new Date().toISOString(),
    });
    return { ok: true, written: Object.keys(answers).length, acceptedThisCall: accepted, missing };
  }
  if (name === 'cx_report') {
    const rep = readJSON(REPORT);
    if (!rep) throw new Error('还没有导出过结构：先在页面上点「导出结构」');
    return rep;
  }
  throw new Error('未知工具：' + name);
}

/* ---------------- 最小 MCP 传输（换行分隔 JSON-RPC） ---------------- */

function send(obj) {
  process.stdout.write(JSON.stringify(obj) + '\n');
}

function reply(id, result) {
  send({ jsonrpc: '2.0', id, result });
}

function fail(id, message) {
  send({ jsonrpc: '2.0', id, error: { code: -32603, message: String(message) } });
}

function handle(msg) {
  const { id, method, params } = msg || {};
  if (method === 'initialize') {
    return reply(id, {
      protocolVersion: (params && params.protocolVersion) || '2024-11-05',
      capabilities: { tools: {} },
      serverInfo: { name: 'cx-bridge', version: '1.0.0' },
    });
  }
  if (method === 'notifications/initialized' || method === 'initialized') return;
  if (method === 'ping') return reply(id, {});
  if (method === 'tools/list') return reply(id, { tools: TOOLS });
  if (method === 'tools/call') {
    const name = params && params.name;
    try {
      const out = callTool(name, (params && params.arguments) || {});
      return reply(id, {
        content: [{ type: 'text', text: JSON.stringify(out, null, 1) }],
        isError: false,
      });
    } catch (e) {
      return reply(id, { content: [{ type: 'text', text: '错误：' + e.message }], isError: true });
    }
  }
  if (id !== undefined && id !== null) {
    send({ jsonrpc: '2.0', id, error: { code: -32601, message: 'method not found: ' + method } });
  }
}

let buf = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', (chunk) => {
  buf += chunk;
  let idx;
  while ((idx = buf.indexOf('\n')) >= 0) {
    const line = buf.slice(0, idx).trim();
    buf = buf.slice(idx + 1);
    if (!line) continue;
    let msg;
    try {
      msg = JSON.parse(line);
    } catch {
      continue;
    }
    try {
      handle(msg);
    } catch (e) {
      if (msg && msg.id != null) fail(msg.id, e.message);
    }
  }
});
process.stdin.on('end', () => process.exit(0));
