// 审计面板页面插件（手写原生 ES Module，v1.0 §7）
// session_event_log 追加审计日志：多维过滤 + 分页，只读展示（不可修改/删除）

const { useState, useEffect, useCallback } = window.React
const h = window.React.createElement
const { Table, Button, Tag, Typography, Space, Input, Select, Alert, message, DatePicker } = window.antd

const EVENT_META = {
  'task:start': ['任务开始', 'blue'],
  'task:update': ['任务更新', 'blue'],
  'task:finish': ['任务完成', 'green'],
  'task:error': ['任务失败', 'red'],
  'agent:think': ['思考流', 'geekblue'],
  'tool:call': ['工具调用', 'cyan'],
  'tool:result': ['工具结果', 'green'],
  'tool:error': ['工具错误', 'red'],
  'plugin:loaded': ['插件加载', 'purple'],
  'plugin:activated': ['插件激活', 'purple'],
  'plugin:deactivated': ['插件禁用', 'purple'],
  'plugin:unloaded': ['插件卸载', 'purple'],
  'plugin:error': ['插件错误', 'red'],
}

const EVENT_OPTIONS = Object.keys(EVENT_META).map((t) => ({ value: t, label: t }))

function PageComponent({ nvwa }) {
  const [events, setEvents] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [taskId, setTaskId] = useState('')
  const [eventType, setEventType] = useState(undefined)
  const [pluginId, setPluginId] = useState('')
  const [range, setRange] = useState(null)
  const pageSize = 20

  const refresh = useCallback(async (p = 1) => {
    setLoading(true)
    try {
      const params = new URLSearchParams()
      if (taskId) params.append('task_id', taskId)
      if (eventType) params.append('event_type', eventType)
      if (pluginId) params.append('plugin_id', pluginId)
      if (range && range[0]) params.append('start', range[0].toISOString())
      if (range && range[1]) params.append('end', range[1].toISOString())
      params.append('page', String(p))
      params.append('page_size', String(pageSize))
      const data = await nvwa.api.get(`/api/v1/audit/events?${params.toString()}`)
      setEvents(data.events || [])
      setTotal(data.total || 0)
      setPage(p)
    } catch (err) {
      message.error(`加载审计事件失败：${err.message}`)
    } finally {
      setLoading(false)
    }
  }, [taskId, eventType, pluginId, range])

  useEffect(() => { refresh(1) }, [refresh])

  const pluginOf = (payload) => payload.plugin_id || payload.agent_id || payload.tool_id || null

  const columns = [
    { title: '时间', dataIndex: 'event_time', key: 'event_time', width: 175,
      render: (t) => h(Typography.Text, { type: 'secondary', style: { fontSize: 12 } },
        t ? String(t).replace('T', ' ').slice(0, 19) : '') },
    { title: '任务', dataIndex: 'task_id', key: 'task_id', width: 150, ellipsis: true,
      render: (id) => h(Typography.Text, { style: { fontSize: 12 } }, id ? id.slice(0, 12) + '…' : '-') },
    { title: '事件类型', dataIndex: 'event_type', key: 'event_type', width: 150,
      render: (t) => {
        const [label, color] = EVENT_META[t] || [t, 'default']
        return h(Tag, { color }, label)
      } },
    { title: '插件', key: 'plugin', width: 180, ellipsis: true,
      render: (_, r) => h(Typography.Text, { style: { fontSize: 12 } },
        pluginOf(r.event_payload || {}) || '-') },
    { title: '内容', dataIndex: 'event_payload', key: 'payload', ellipsis: true,
      render: (p) => h(Typography.Text, { type: 'secondary', style: { fontSize: 12 } },
        JSON.stringify(p || {}).slice(0, 120)) },
  ]

  const expandedRowRender = (r) => h('pre', {
    style: { background: '#fafafa', padding: 8, borderRadius: 4, whiteSpace: 'pre-wrap', fontSize: 12, margin: 0 },
  }, JSON.stringify(r.event_payload || {}, null, 2))

  return h('div', { style: { padding: 16 } },
    h(Alert, {
      type: 'info', showIcon: true, style: { marginBottom: 12 },
      message: '审计日志仅追加，不可修改/删除',
      description: '删除会话后日志保留（task_id 允许悬空），用于审计追溯。',
    }),
    h(Space, { wrap: true, style: { marginBottom: 12 } },
      h(Input, { placeholder: '任务 ID', allowClear: true, style: { width: 180 },
        value: taskId, onChange: (e) => setTaskId(e.target.value) }),
      h(Select, { placeholder: '事件类型', allowClear: true, style: { width: 180 },
        value: eventType, onChange: (v) => setEventType(v || undefined), options: EVENT_OPTIONS }),
      h(Input, { placeholder: '插件 ID', allowClear: true, style: { width: 180 },
        value: pluginId, onChange: (e) => setPluginId(e.target.value) }),
      h(DatePicker.RangePicker, { showTime: true, onChange: (v) => setRange(v || null) }),
      h(Button, { type: 'primary', onClick: () => refresh(1) }, '查询')),
    h(Table, {
      rowKey: 'log_id', columns, dataSource: events,
      size: 'small', loading,
      expandable: { expandedRowRender },
      pagination: {
        current: page, pageSize, total,
        showTotal: (n) => `共 ${n} 条`,
        onChange: (p) => refresh(p),
      },
    }))
}

export { PageComponent }
export default { PageComponent }
