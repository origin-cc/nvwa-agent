// 示例对话页面插件（手写原生 ES Module）
// 依赖基座注入的 window.React / window.antd；导出 PageComponent（§4.2）
// 功能：会话管理 / 任务提交 / agent:think 流式渲染 / tool 调用展示 / 历史回放 / 插槽渲染

const { useState, useEffect, useRef, useCallback } = window.React
const h = window.React.createElement
const {
  Button, Input, List, Tag, Empty, Spin, message, Popconfirm, Modal, Tooltip, Typography,
} = window.antd

let _msgSeq = 0
function newMsg(kind, content, extra) {
  _msgSeq += 1
  return Object.assign({ id: `m${_msgSeq}`, kind, content, ts: Date.now() }, extra || {})
}

function kindTag(kind) {
  const map = {
    user: ['我', 'blue'],
    assistant: ['回答', 'green'],
    think: ['思考', 'orange'],
    tool: ['工具', 'purple'],
    error: ['错误', 'red'],
  }
  const [label, color] = map[kind] || [kind, 'default']
  return h(Tag, { color }, label)
}

function MsgBubble({ msg }) {
  const isUser = msg.kind === 'user'
  return h('div', {
    style: {
      display: 'flex', justifyContent: isUser ? 'flex-end' : 'flex-start',
      marginBottom: 10, padding: '0 4px',
    },
  },
    h('div', {
      style: {
        maxWidth: '78%', padding: '8px 12px', borderRadius: 10,
        background: isUser ? '#e6f4ff' : '#fafafa',
        border: '1px solid #f0f0f0', whiteSpace: 'pre-wrap',
        wordBreak: 'break-word', fontSize: 13, lineHeight: 1.7,
      },
    },
      msg.kind !== 'user' && msg.kind !== 'assistant'
        ? h('div', { style: { marginBottom: 4 } },
            kindTag(msg.kind),
            msg.toolId ? h(Tag, null, msg.toolId) : null,
            msg.agentId ? h(Tag, null, msg.agentId) : null,
            msg.kind === 'tool' && msg.status === 'running' ? h(Spin, { size: 'small' }) : null)
        : null,
      h(Typography.Paragraph, { style: { marginBottom: 0, color: msg.kind === 'error' ? '#cf1322' : undefined } },
        msg.content || (msg.kind === 'think' ? '…' : '')),
    ))
}

function PageComponent({ nvwa, slots }) {
  const [conversations, setConversations] = useState([])
  const [activeId, setActiveId] = useState(null)
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [loadingHistory, setLoadingHistory] = useState(false)
  const taskRef = useRef(null)
  const listEndRef = useRef(null)

  const refreshConversations = useCallback(async () => {
    try {
      const data = await nvwa.api.get('/api/v1/conversation/list')
      setConversations(data.conversations || [])
    } catch (err) { /* 静默：下次操作再刷新 */ }
  }, [])

  const loadHistory = useCallback(async (conversationId) => {
    if (!conversationId) { setMessages([]); return }
    setLoadingHistory(true)
    try {
      const listData = await nvwa.api.get(`/api/v1/task/list?conversation_id=${encodeURIComponent(conversationId)}&page_size=100`)
      const tasks = (listData.tasks || []).slice().reverse() // created_at desc -> 时间正序
      const rebuilt = []
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
            rebuilt.push(newMsg('tool', `调用参数：${JSON.stringify(p.call_args || {})}`, { toolId: p.tool_id, taskId: t.task_id, status: 'running' }))
          } else if (ev.event_type === 'tool:result') {
            rebuilt.push(newMsg('tool', `结果：${typeof p.result === 'string' ? p.result : JSON.stringify(p.result)}`, { toolId: p.tool_id, taskId: t.task_id, status: 'done' }))
          } else if (ev.event_type === 'tool:error') {
            rebuilt.push(newMsg('tool', `失败：${p.error_msg}`, { toolId: p.tool_id, taskId: t.task_id, status: 'failed' }))
          }
        }
        if (t.status === 'finish' && t.result) rebuilt.push(newMsg('assistant', t.result, { taskId: t.task_id }))
        if (t.status === 'failed') rebuilt.push(newMsg('error', t.error_msg || '任务执行失败', { taskId: t.task_id }))
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
    refreshConversations().then(() => {
      if (saved.conversation_id) {
        setActiveId(saved.conversation_id)
        loadHistory(saved.conversation_id)
      }
    })
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
      setMessages((prev) => [...prev, newMsg('tool', `调用参数：${JSON.stringify(p.call_args || {})}`, { toolId: p.tool_id, taskId: p.task_id, status: 'running' })])
    }))
    offs.push(nvwa.events.on('tool:result', (p) => {
      if (!isCurrent(p)) return
      setMessages((prev) => [...prev, newMsg('tool', `结果：${typeof p.result === 'string' ? p.result : JSON.stringify(p.result)}`, { toolId: p.tool_id, taskId: p.task_id, status: 'done' })])
    }))
    offs.push(nvwa.events.on('tool:error', (p) => {
      if (!isCurrent(p)) return
      setMessages((prev) => [...prev, newMsg('tool', `失败：${p.error_msg}`, { toolId: p.tool_id, taskId: p.task_id, status: 'failed' })])
    }))
    offs.push(nvwa.events.on('task:finish', (p) => {
      if (!isCurrent(p)) return
      setMessages((prev) => [...prev, newMsg('assistant', p.result || '(空结果)', { taskId: p.task_id })])
      setSending(false)
      taskRef.current = null
      refreshConversations()
    }))
    offs.push(nvwa.events.on('task:error', (p) => {
      if (!isCurrent(p)) return
      setMessages((prev) => [...prev, newMsg('error', `[${p.error_code || 'TASK_ERROR'}] ${p.error_msg || '任务执行失败'}`, { taskId: p.task_id })])
      setSending(false)
      taskRef.current = null
    }))
    return () => offs.forEach((off) => off && off())
  }, [])

  // 消息变化自动滚动到底部
  useEffect(() => {
    if (listEndRef.current) listEndRef.current.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const switchConversation = (id) => {
    setActiveId(id)
    taskRef.current = null
    nvwa.state.save({ conversation_id: id })
    loadHistory(id)
  }

  const createConversation = async () => {
    try {
      const data = await nvwa.api.post('/api/v1/conversation/create')
      await refreshConversations()
      switchConversation(data.conversation_id)
    } catch (err) { message.error(err.message) }
  }

  const renameConversation = (item) => {
    let inputRef
    const handleOk = async () => {
      const title = (inputRef && inputRef.value || '').trim()
      if (!title) return
      try {
        await nvwa.api.put(`/api/v1/conversation/${item.conversation_id}`, { title })
        message.success('已重命名')
        refreshConversations()
      } catch (err) { message.error(err.message) }
    }
    Modal.confirm({
      title: '重命名会话',
      content: h(Input, { defaultValue: item.title, ref: (r) => { inputRef = r } }),
      onOk: handleOk,
    })
  }

  const deleteConversation = async (id) => {
    try {
      await nvwa.api.del(`/api/v1/conversation/${id}`)
      if (activeId === id) { setActiveId(null); setMessages([]); nvwa.state.save({ conversation_id: null }) }
      refreshConversations()
      message.success('会话已删除')
    } catch (err) { message.error(err.message) }
  }

  const send = async () => {
    const prompt = input.trim()
    if (!prompt) return
    setSending(true)
    setInput('')
    setMessages((prev) => [...prev, newMsg('user', prompt)])
    try {
      const data = await nvwa.api.post('/api/v1/task/submit', { prompt, conversation_id: activeId })
      taskRef.current = data.task_id
      if (!activeId) {
        setActiveId(data.conversation_id)
        nvwa.state.save({ conversation_id: data.conversation_id })
        refreshConversations()
      }
    } catch (err) {
      setMessages((prev) => [...prev, newMsg('error', `提交失败：${err.message}`)])
      setSending(false)
    }
  }

  const sidePanel = (slots && slots['chat:side-panel']) || []

  return h('div', { style: { display: 'flex', gap: 12, height: 'calc(100vh - 32px)' } },
    // 左：会话列表
    h('div', { style: { width: 230, flexShrink: 0, borderRight: '1px solid #f0f0f0', paddingRight: 8, display: 'flex', flexDirection: 'column' } },
      h(Button, { type: 'primary', block: true, onClick: createConversation, style: { marginBottom: 8 } }, '新建会话'),
      h('div', { style: { flex: 1, overflowY: 'auto' } },
        h(List, {
          dataSource: conversations,
          renderItem: (item) => h(List.Item, {
            style: {
              cursor: 'pointer', padding: '8px 10px', borderRadius: 8,
              background: item.conversation_id === activeId ? '#e6f4ff' : undefined,
            },
            onClick: () => switchConversation(item.conversation_id),
          },
            h(List.Item.Meta, {
              title: h('span', { style: { fontSize: 13 } }, item.title),
              description: h('span', { style: { fontSize: 12 } }, `${item.task_count || 0} 个任务`),
            }),
            h('div', null,
              h(Tooltip, { title: '重命名' }, h(Button, { size: 'small', type: 'text', onClick: (e) => { e.stopPropagation(); renameConversation(item) } }, '✎')),
              h(Popconfirm, { title: '删除该会话及其全部任务？', onConfirm: (e) => { e && e.stopPropagation(); deleteConversation(item.conversation_id) }, onCancel: (e) => e && e.stopPropagation() },
                h(Tooltip, { title: '删除' }, h(Button, { size: 'small', type: 'text', danger: true, onClick: (e) => e.stopPropagation() }, '🗑')))),
          ),
        })),
    ),
    // 中：消息流 + 输入
    h('div', { style: { flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 } },
      h(Spin, { spinning: loadingHistory },
        h('div', { style: { flex: 1, overflowY: 'auto', padding: '4px 8px' } },
          messages.length === 0 && !loadingHistory
            ? h(Empty, { style: { marginTop: 120 }, description: activeId ? '发送第一条消息开始对话' : '左侧选择或新建一个会话' })
            : messages.map((m) => h(MsgBubble, { key: m.id, msg: m })),
          h('div', { ref: listEndRef }))),
      h('div', { style: { borderTop: '1px solid #f0f0f0', paddingTop: 10, display: 'flex', gap: 8 } },
        h(Input.TextArea, {
          value: input, onChange: (e) => setInput(e.target.value),
          placeholder: '输入消息，Enter 发送 / Shift+Enter 换行',
          autoSize: { minRows: 1, maxRows: 5 },
          onPressEnter: (e) => { if (!e.shiftKey) { e.preventDefault(); send() } },
        }),
        h(Button, { type: 'primary', loading: sending, onClick: send, style: { alignSelf: 'flex-end' } }, '发送'))),
    // 右：组件插件插槽（chat:side-panel）
    sidePanel.length > 0
      ? h('div', { style: { width: 320, flexShrink: 0, borderLeft: '1px solid #f0f0f0', paddingLeft: 12, overflowY: 'auto' } }, sidePanel)
      : null,
  )
}

export { PageComponent }
export default { PageComponent }
