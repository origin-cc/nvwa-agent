// 思考可视化组件插件（手写原生 ES Module）
// 挂载到 demo-ui-chat 声明的 chat:side-panel 插槽（§4.8）
// 展示最近任务的事件时间线：task:start / agent:think / tool:call / tool:result / tool:finish

const { useState, useEffect, useRef } = window.React
const h = window.React.createElement
const { Tag, Empty, Typography, Tooltip } = window.antd

const MAX_ITEMS = 200

function PageComponent({ nvwa }) {
  const [taskId, setTaskId] = useState(null)
  const [items, setItems] = useState([])
  const seqRef = useRef(0)

  useEffect(() => {
    const push = (text, tag, color) => {
      seqRef.current += 1
      setItems((prev) => [...prev, { seq: seqRef.current, text, tag, color }].slice(-MAX_ITEMS))
    }
    const offs = [
      nvwa.events.on('task:start', (p) => {
        setTaskId(p.task_id)
        seqRef.current = 0
        setItems([])
        push('任务开始', 'task:start', 'blue')
      }),
      nvwa.events.on('agent:think', (p) => {
        if (p.is_final) push(`智能体 ${p.agent_id || ''} 输出完成（第${p.seq}片）`, 'think', 'orange')
        else if (p.seq === 1) push(`智能体 ${p.agent_id || ''} 开始思考`, 'think', 'orange')
      }),
      nvwa.events.on('tool:call', (p) => push(`调用工具 ${p.tool_id}`, 'tool', 'purple')),
      nvwa.events.on('tool:result', () => push('工具返回结果', 'tool', 'purple')),
      nvwa.events.on('tool:error', (p) => push(`工具失败：${p.error_msg || ''}`, 'tool:error', 'red')),
      nvwa.events.on('task:finish', () => { push('任务完成', 'task:finish', 'green'); setTaskId(null) }),
      nvwa.events.on('task:error', (p) => { push(`任务失败：${p.error_code || ''}`, 'task:error', 'red'); setTaskId(null) }),
    ]
    return () => offs.forEach((off) => off && off())
  }, [])

  return h('div', { style: { fontSize: 13 } },
    h(Typography.Title, { level: 5, style: { marginTop: 4 } }, '任务链路可视化'),
    h(Typography.Paragraph, { type: 'secondary', style: { fontSize: 12 } },
      '组件插件示例（ui_component_plugin），挂载于 chat:side-panel 插槽'),
    taskId ? h(Tag, { color: 'processing', style: { marginBottom: 8 } }, `执行中：${taskId.slice(0, 8)}…`) : null,
    items.length === 0
      ? h(Empty, { image: Empty.PRESENTED_IMAGE_SIMPLE, description: '暂无任务事件' })
      : h('div', null, items.map((it) =>
          h('div', { key: it.seq, style: { display: 'flex', gap: 6, padding: '3px 0', alignItems: 'center' } },
            h(Tag, { color: it.color, style: { marginRight: 0 } }, it.tag),
            h('span', { style: { wordBreak: 'break-all' } }, it.text)))),
  )
}

export { PageComponent, PageComponent as Component }
export default { PageComponent, Component: PageComponent }
