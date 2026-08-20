// 示例对话页面插件（手写原生 ES Module）
// 依赖基座注入的 window.React / window.antd / window.NvwaMarkdown；导出 PageComponent
// 功能：会话管理 / 任务提交 / agent:think 流式渲染 / tool 调用折叠展示 / 历史回放 / 插槽渲染 / 停止与重新生成

const { useState, useEffect, useRef, useCallback, Fragment } = window.React
const h = window.React.createElement
const {
  Button, Input, Tag, Spin, message, Popconfirm, Modal, Tooltip, Typography,
  Avatar, Collapse, Badge,
} = window.antd

// Markdown 渲染器（基座注入）；缺失时降级为纯文本，避免组件崩溃
const Markdown = window.NvwaMarkdown || function MarkdownFallback({ children }) {
  return h('div', null, children)
}

let _msgSeq = 0
function newMsg(kind, content, extra) {
  _msgSeq += 1
  return Object.assign({ id: `m${_msgSeq}`, kind, content, ts: Date.now() }, extra || {})
}

// 「折叠过程」开关：隐藏思考/工具调用气泡，仅展示最终输出结果（localStorage 持久化）
const PROCESS_HIDE_KEY = 'nvwa-chat-process-hidden'

function loadProcessHidden() {
  try {
    return localStorage.getItem(PROCESS_HIDE_KEY) === '1'
  } catch (e) {
    return false
  }
}

// 最终回答：若上一条是同任务的"思考"气泡（agent:think 流式内容=模型输出），
// 直接升级为"回答"，避免同一份答案在思考区+回答区重复显示（无 reasoning 模型二者同源）。
function pushAssistant(list, content, taskId) {
  const last = list[list.length - 1]
  if (last && last.kind === 'think' && last.taskId === taskId) {
    if (content) {
      return [...list.slice(0, -1), Object.assign({}, last, { kind: 'assistant', content })]
    }
    return list // 结果为空时保留思考气泡内容
  }
  return [...list, newMsg('assistant', content || '(空结果)', { taskId })]
}

// 工具消息内容统一格式化，供实时 SSE 与历史回放共用
function toolContent(status, p) {
  if (status === 'running') return JSON.stringify(p.call_args || {}, null, 2)
  if (status === 'done') return typeof p.result === 'string' ? p.result : JSON.stringify(p.result, null, 2)
  return p.error_msg || '未知错误'
}

function toolLabel(status) {
  if (status === 'running') return '调用参数'
  if (status === 'done') return '结果'
  return '失败信息'
}

function kindTag(kind) {
  const map = {
    user: ['我', 'blue'],
    assistant: ['回答', 'green'],
    think: ['思考', 'orange'],
    tool: ['工具', 'purple'],
    error: ['错误', 'red'],
    cancelled: ['已取消', 'orange'],
  }
  const [label, color] = map[kind] || [kind, 'default']
  return h(Tag, { color }, label)
}

function toolStatusIcon(status) {
  if (status === 'running') return h(Spin, { size: 'small' })
  if (status === 'done') return h(Badge, { status: 'success' })
  if (status === 'failed') return h(Badge, { status: 'error' })
  return null
}

// 工具调用折叠卡片：参考 DeepSeek 风格——工具图标 + 工具名 + 状态图标，展开显示参数/结果（等宽代码块）
function ToolCard({ msg }) {
  return h(Collapse, {
    size: 'small',
    className: 'nvwa-tool-card',
    style: {
      width: '100%',
      background: 'transparent',
      border: 'none',
      borderRadius: 0,
    },
    items: [{
      key: msg.id,
      label: h('div', { style: { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' } },
        h('span', { style: { fontSize: 14, lineHeight: 1 } }, '🔧'),
        h('span', { style: { fontWeight: 600, fontSize: 13 } }, msg.toolId || '未知工具'),
        toolStatusIcon(msg.status)),
      children: h('div', { style: { fontSize: 12, lineHeight: 1.7 } },
        h('div', { style: { color: 'var(--nvwa-text-secondary)', marginBottom: 4 } }, toolLabel(msg.status)),
        h('pre', {
          style: {
            margin: 0, padding: '10px 12px',
            background: 'var(--nvwa-bg-hover)', borderRadius: 8,
            whiteSpace: 'pre-wrap', wordBreak: 'break-word',
            fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
            fontSize: 12,
          },
        }, msg.content || '')),
    }],
  })
}

// 消息气泡：用户右对齐（主色浅底），助手/其它左对齐（容器底），头像区分「我」/「Nvwae」
function MsgBubble({ msg, isLastUser, onRegenerate, busy }) {
  const [hover, setHover] = useState(false)
  const isUser = msg.kind === 'user'
  const isAssistant = msg.kind === 'assistant'
  const isTool = msg.kind === 'tool'
  const copyable = isUser || isAssistant

  // 对话消息背景透明化：用户/助手文字直接显示在背景上，仅错误消息保留浅红底提示
  const bubbleBg = msg.kind === 'error' ? 'var(--nvwa-error-bg)' : 'transparent'

  const avatar = h(Avatar, {
    size: 32,
    style: {
      flexShrink: 0,
      backgroundColor: isUser ? 'var(--nvwa-primary-bg)' : 'var(--nvwa-border)',
      color: 'var(--nvwa-text-secondary)',
      fontSize: 13,
    },
  }, isUser ? '我' : 'Nvwae')

  let body
  if (isTool) {
    body = h(ToolCard, { msg })
  } else if (isAssistant) {
    // 助手回答使用 Markdown 渲染（支持代码高亮、表格等）
    body = h('div', { style: { minWidth: 0 } }, h(Markdown, null, msg.content || ''))
  } else {
    body = h('div', { style: { whiteSpace: 'pre-wrap', wordBreak: 'break-word' } },
      (!isUser && !isAssistant)
        ? h('div', { style: { marginBottom: 6, display: 'flex', alignItems: 'center', gap: 6 } },
            kindTag(msg.kind),
            msg.kind === 'think' ? h(Spin, { size: 'small' }) : null,
            msg.kind === 'error' ? h(Badge, { status: 'error' }) : null,
            msg.kind === 'cancelled' ? h(Badge, { status: 'warning' }) : null)
        : null,
      msg.content || (msg.kind === 'think' ? '…' : ''))
  }

  const copyText = async () => {
    try {
      await navigator.clipboard.writeText(msg.content || '')
      message.success('已复制到剪贴板')
    } catch (err) {
      message.error('复制失败')
    }
  }

  const actionBar = h('div', {
    style: { display: 'flex', gap: 4, alignSelf: 'flex-end', paddingBottom: 2, flexShrink: 0 },
  },
    h(Button, { size: 'small', type: 'text', onClick: copyText, style: { fontSize: 12 } }, '复制'),
    isLastUser
      ? h(Button, { size: 'small', type: 'text', disabled: busy, onClick: onRegenerate, style: { fontSize: 12 } }, '重新生成')
      : null)

  const bubble = h('div', {
    style: {
      maxWidth: '78%',
      padding: '10px 14px',
      borderRadius: 12,
      background: bubbleBg,
      border: msg.kind === 'error' ? '1px solid var(--nvwa-border)' : 'none',
      fontSize: 13,
      lineHeight: 1.7,
      minWidth: 0,
    },
  }, body)

  const left = isUser ? (hover && copyable ? actionBar : null) : avatar
  const right = isUser ? avatar : (hover && copyable ? actionBar : null)

  return h('div', {
    style: {
      display: 'flex', gap: 8, marginBottom: 12, padding: '0 4px',
      alignItems: 'flex-start', justifyContent: isUser ? 'flex-end' : 'flex-start',
    },
    onMouseEnter: () => setHover(true),
    onMouseLeave: () => setHover(false),
  },
    h(Fragment, null, left, bubble, right))
}

// 欢迎/空态引导页：标题 + 能力简述 + 示例问题卡片
function WelcomePanel({ onExample }) {
  const examples = [
    { title: '规划一次三日北京旅行', desc: '行程安排 / 交通 / 美食推荐' },
    { title: '用 Python 实现快速排序', desc: '代码 + 思路解释' },
    { title: '解释什么是 Agent 工作流', desc: '概念、组成与运行方式' },
    { title: '帮我写一份周报总结', desc: '结构化输出工作要点' },
  ]
  return h('div', {
    style: {
      flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center',
      justifyContent: 'center', padding: 24, textAlign: 'center', minHeight: 0,
    },
  },
    h(Typography.Title, { level: 3, style: { marginBottom: 8 } }, '欢迎使用女娲 Agent'),
    h(Typography.Paragraph, { type: 'secondary', style: { maxWidth: 560, marginBottom: 24 } },
      '多智能体协作 · 流式推理 · 工具调用 · 会话记忆。输入问题，或点击下方示例快速开始。'),
    h('div', {
      style: {
        display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))',
        gap: 12, width: '100%', maxWidth: 760,
      },
    },
      examples.map((ex) => h('div', {
        key: ex.title,
        onClick: () => onExample(ex.title),
        style: {
          cursor: 'pointer', padding: '14px 16px', borderRadius: 10, textAlign: 'left',
          background: 'var(--nvwa-bg-container)', border: '1px solid var(--nvwa-border)',
        },
      },
        h('div', { style: { fontWeight: 600, marginBottom: 4, fontSize: 14 } }, ex.title),
        h('div', { style: { color: 'var(--nvwa-text-secondary)', fontSize: 12 } }, ex.desc)))))
}

function PageComponent({ nvwa, slots }) {
  const [activeId, setActiveId] = useState(null)
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [cancelling, setCancelling] = useState(false)
  const [loadingHistory, setLoadingHistory] = useState(false)
  const [rightCollapsed, setRightCollapsed] = useState(() => typeof window !== 'undefined' && window.innerWidth < 1100)
  const [processHidden, setProcessHidden] = useState(loadProcessHidden)
  const taskRef = useRef(null)
  const listEndRef = useRef(null)

  const toggleProcessHidden = () => {
    setProcessHidden((prev) => {
      const next = !prev
      try { localStorage.setItem(PROCESS_HIDE_KEY, next ? '1' : '0') } catch (e) { /* ignore */ }
      return next
    })
  }

  const loadHistory = useCallback(async (conversationId) => {
    if (!conversationId) { setMessages([]); return }
    setLoadingHistory(true)
    try {
      const listData = await nvwa.api.get(`/api/v1/task/list?conversation_id=${encodeURIComponent(conversationId)}&page_size=100`)
      const tasks = (listData.tasks || []).slice().reverse() // created_at desc -> 时间正序
      let rebuilt = []
      for (const t of tasks) {
        rebuilt.push(newMsg('user', t.input_prompt, { taskId: t.task_id }))
        let logEvents = []
        try {
          const logData = await nvwa.api.get(`/api/v1/task/${t.task_id}/log`)
          logEvents = logData.events || []
        } catch { /* 日志缺失时仅展示结果 */ }
        for (const ev of logEvents) {
          const p = ev.event_payload || {}
          if (ev.event_type === 'agent:think' && p.think_content) {
            const last = rebuilt[rebuilt.length - 1]
            if (last && last.kind === 'think' && last.agentId === p.agent_id && last.taskId === t.task_id) {
              last.content += p.think_content
            } else {
              rebuilt.push(newMsg('think', p.think_content, { agentId: p.agent_id, taskId: t.task_id }))
            }
          } else if (ev.event_type === 'tool:call') {
            rebuilt.push(newMsg('tool', toolContent('running', p), { toolId: p.tool_id, taskId: t.task_id, status: 'running' }))
          } else if (ev.event_type === 'tool:result') {
            rebuilt.push(newMsg('tool', toolContent('done', p), { toolId: p.tool_id, taskId: t.task_id, status: 'done' }))
          } else if (ev.event_type === 'tool:error') {
            rebuilt.push(newMsg('tool', toolContent('failed', p), { toolId: p.tool_id, taskId: t.task_id, status: 'failed' }))
          }
        }
        if (t.status === 'finish' && t.result) rebuilt = pushAssistant(rebuilt, t.result, t.task_id)
        if (t.status === 'failed') rebuilt.push(newMsg('error', t.error_msg || '任务执行失败', { taskId: t.task_id }))
        if (t.status === 'cancelled') rebuilt.push(newMsg('cancelled', '任务已中断', { taskId: t.task_id }))
      }
      setMessages(rebuilt)
    } catch (err) {
      message.error(`加载会话历史失败：${err.message}`)
    } finally {
      setLoadingHistory(false)
    }
  }, [])

  // 初始化：恢复上次会话 + 订阅 SSE 任务事件
  useEffect(() => {
    const saved = nvwa.state.get() || {}
    if (saved.conversation_id) {
      setActiveId(saved.conversation_id)
      loadHistory(saved.conversation_id)
    }
  }, [])

  // SSE 事件订阅（作用域内自动随插件卸载注销）
  useEffect(() => {
    const offs = []
    const isCurrent = (p) => taskRef.current && p.task_id === taskRef.current

    offs.push(nvwa.events.on('agent:think', (p) => {
      if (!isCurrent(p) || !p.think_content) return
      setMessages((prev) => {
        const last = prev[prev.length - 1]
        if (last && last.kind === 'think' && last.agentId === p.agent_id) {
          return [...prev.slice(0, -1), Object.assign({}, last, { content: last.content + p.think_content })]
        }
        return [...prev, newMsg('think', p.think_content, { agentId: p.agent_id, taskId: p.task_id })]
      })
    }))
    offs.push(nvwa.events.on('tool:call', (p) => {
      if (!isCurrent(p)) return
      setMessages((prev) => [...prev, newMsg('tool', toolContent('running', p), { toolId: p.tool_id, taskId: p.task_id, status: 'running' })])
    }))
    offs.push(nvwa.events.on('tool:result', (p) => {
      if (!isCurrent(p)) return
      setMessages((prev) => [...prev, newMsg('tool', toolContent('done', p), { toolId: p.tool_id, taskId: p.task_id, status: 'done' })])
    }))
    offs.push(nvwa.events.on('tool:error', (p) => {
      if (!isCurrent(p)) return
      setMessages((prev) => [...prev, newMsg('tool', toolContent('failed', p), { toolId: p.tool_id, taskId: p.task_id, status: 'failed' })])
    }))
    offs.push(nvwa.events.on('task:finish', (p) => {
      if (!isCurrent(p)) return
      setMessages((prev) => pushAssistant(prev, p.result, p.task_id))
      setSending(false)
      taskRef.current = null
      nvwa.events.emit('demo-ui-chat:conversation-changed', {})
    }))
    offs.push(nvwa.events.on('task:error', (p) => {
      if (!isCurrent(p)) return
      setMessages((prev) => [...prev, newMsg('error', `[${p.error_code || 'TASK_ERROR'}] ${p.error_msg || '任务执行失败'}`, { taskId: p.task_id })])
      setSending(false)
      taskRef.current = null
    }))
    offs.push(nvwa.events.on('task:cancelled', (p) => {
      if (!isCurrent(p)) return
      setMessages((prev) => [...prev, newMsg('cancelled', '任务已中断', { taskId: p.task_id })])
      setSending(false)
      setCancelling(false)
      taskRef.current = null
    }))
    return () => offs.forEach((off) => off && off())
  }, [])

  // 消息变化自动滚动到底部
  useEffect(() => {
    if (listEndRef.current) listEndRef.current.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // 提交 Prompt：send 与「重新生成」共用
  const submitPrompt = useCallback(async (prompt) => {
    const text = (prompt || '').trim()
    if (!text) return
    setSending(true)
    setMessages((prev) => [...prev, newMsg('user', text)])
    try {
      const data = await nvwa.api.post('/api/v1/task/submit', { prompt: text, conversation_id: activeId })
      taskRef.current = data.task_id
      if (!activeId) {
        setActiveId(data.conversation_id)
        nvwa.state.save({ conversation_id: data.conversation_id })
        nvwa.events.emit('demo-ui-chat:conversation-changed', {})
      }
    } catch (err) {
      setMessages((prev) => [...prev, newMsg('error', `提交失败：${err.message}`)])
      setSending(false)
      taskRef.current = null
    }
  }, [activeId])

  const send = () => {
    const prompt = input.trim()
    if (!prompt) return
    setInput('')
    submitPrompt(prompt)
  }

  const stopTask = async () => {
    const tid = taskRef.current
    if (!tid) return
    setCancelling(true)
    try {
      await nvwa.api.post(`/api/v1/task/${tid}/cancel`)
      // 成功取消后由 task:cancelled 事件统一收尾（复位 sending / taskRef）
    } catch (err) {
      message.error(`停止失败：${err.message}`)
      setCancelling(false)
    }
  }

  // 基座左侧导航栏会话选择/清空动作
  useEffect(() => {
    const off = nvwa.events.on('demo-ui-chat:sider-subnav', (payload) => {
      const key = payload && payload.key
      if (key === 'select') {
        const conversationId = payload.conversation_id || null
        setActiveId(conversationId)
        taskRef.current = null
        loadHistory(conversationId)
      } else if (key === 'clear') {
        setActiveId(null)
        taskRef.current = null
        setMessages([])
      }
    })
    return off
  }, [])

  const sidePanel = (slots && slots['chat:side-panel']) || []

  // 最后一条用户消息用于「重新生成」入口
  let lastUserId = null
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    if (messages[i].kind === 'user') { lastUserId = messages[i].id; break }
  }

  const hasMessages = messages.length > 0
  const empty = !hasMessages && !loadingHistory
  const executing = sending || Boolean(taskRef.current)

  return h('div', { style: { display: 'flex', gap: 12, height: '100%' } },
    // 中：消息流 + 输入
    h('div', { style: { flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 } },
      h('div', { style: { display: 'flex', alignItems: 'center', gap: 4, padding: '0 0 8px', borderBottom: '1px solid var(--nvwa-border)' } },
        h('span', { style: { flex: 1 } }),
        h(Tooltip, {
          title: processHidden
            ? '展开思考与工具调用过程'
            : '折叠思考与工具调用过程，仅显示最终输出结果',
        },
          h(Button, {
            size: 'small',
            type: processHidden ? 'primary' : 'text',
            onClick: toggleProcessHidden,
          }, processHidden ? '展开过程' : '折叠过程')),
        sidePanel.length > 0
          ? h(Tooltip, { title: rightCollapsed ? '展开侧栏' : '收起侧栏' },
              h(Button, { size: 'small', type: 'text', onClick: () => setRightCollapsed((v) => !v) }, rightCollapsed ? '«' : '»'))
          : null),
      h('div', { style: { flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', position: 'relative' } },
        h('div', {
          style: {
            flex: 1, minHeight: 0, overflowY: 'auto', padding: '12px 16px',
            display: empty ? 'flex' : 'block',
          },
        },
          empty
            ? h(WelcomePanel, { onExample: (p) => submitPrompt(p) })
            : h('div', null,
                messages
                  .filter((m) => !(processHidden && (m.kind === 'think' || m.kind === 'tool')))
                  .map((m) => h(MsgBubble, {
                    key: m.id,
                    msg: m,
                    isLastUser: m.kind === 'user' && m.id === lastUserId,
                    busy: sending,
                    onRegenerate: () => submitPrompt(m.content),
                  })),
                h('div', { ref: listEndRef }))),
        loadingHistory
          ? h('div', { style: { position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 2 } },
              h(Spin, { size: 'large', tip: '加载历史中…' }))
          : null),
      h('div', {
        style: {
          borderTop: '1px solid var(--nvwa-border)', padding: '10px 16px',
          display: 'flex', gap: 8, alignItems: 'flex-end', background: 'var(--nvwa-bg-container)',
        },
      },
        h(Input.TextArea, {
          value: input, onChange: (e) => setInput(e.target.value),
          placeholder: '输入消息，Enter 发送 / Shift+Enter 换行',
          autoSize: { minRows: 1, maxRows: 5 },
          onPressEnter: (e) => { if (!e.shiftKey) { e.preventDefault(); send() } },
        }),
        executing
          ? h(Button, { danger: true, loading: cancelling, onClick: stopTask, style: { alignSelf: 'flex-end' } }, '停止')
          : h(Button, { type: 'primary', loading: sending, onClick: send, style: { alignSelf: 'flex-end' } }, '发送'))),
    // 右：组件插件插槽（chat:side-panel，可折叠）
    sidePanel.length > 0 && !rightCollapsed
      ? h('div', { style: { width: 320, flexShrink: 0, borderLeft: '1px solid var(--nvwa-border)', paddingLeft: 12, overflowY: 'auto' } }, sidePanel)
      : null,
  )
}

export { PageComponent }
export default { PageComponent }
