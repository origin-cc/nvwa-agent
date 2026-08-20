// 工具资源管理页面插件（手写原生 ES Module）
// 数据源：/plugins/list（backend_tool 行含 tool_name/description/parameters_schema）
// 展示：全局工具 / 私有工具（owner_agent_id）、归属声明（backend_agent 的 private_tool_ids）

const { useState, useEffect, useCallback } = window.React
const h = window.React.createElement
const { Table, Button, Tag, Typography, Space, message, Modal, Descriptions } = window.antd

function stateTag(state) {
  const colorMap = { activated: 'green', loaded: 'blue', deactivated: 'orange', unloaded: 'default', fault: 'red' }
  return h(Tag, { color: colorMap[state] || 'default' }, state || '-')
}

function PageComponent({ nvwa }) {
  const [tools, setTools] = useState([])
  const [agents, setAgents] = useState([])
  const [loading, setLoading] = useState(false)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const data = await nvwa.api.get('/api/v1/plugins/list')
      const all = data.plugins || []
      setTools(all.filter((p) => p.type === 'backend_tool'))
      setAgents(all.filter((p) => p.type === 'backend_agent'))
    } catch (err) {
      message.error(`加载工具清单失败：${err.message}`)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { refresh() }, [])

  // 私有归属视图：private_tool_id -> 声明它的 agent 列表
  const ownerMap = {}
  agents.forEach((a) => (a.private_tool_ids || []).forEach((tid) => {
    ownerMap[tid] = ownerMap[tid] || []
    ownerMap[tid].push(a.plugin_id)
  }))

  const showSchema = (tool) => {
    Modal.info({
      title: `${tool.tool_name || tool.plugin_id} 参数 Schema`,
      width: 640,
      content: h('pre', {
        style: { maxHeight: 360, overflow: 'auto', fontSize: 12, background: 'var(--nvwa-bg-hover)', padding: 12, borderRadius: 8 },
      }, JSON.stringify(tool.parameters_schema || {}, null, 2)),
    })
  }

  const columns = [
    { title: '工具', key: 'name', render: (_, t) => h('div', null,
        h('div', { style: { fontWeight: 600 } }, t.tool_name || t.plugin_id),
        h(Typography.Text, { type: 'secondary', style: { fontSize: 12 } }, t.plugin_id)) },
    { title: '描述', key: 'desc', ellipsis: true, render: (_, t) => t.description || '—' },
    { title: '作用域', key: 'scope', width: 130, render: (_, t) =>
        t.owner_agent_id
          ? h(Tooltipless, { label: `私有（${t.owner_agent_id}）`, color: 'purple' })
          : h(Tag, { color: 'geekblue' }, '全局') },
    { title: '被声明于', key: 'declared', width: 180, ellipsis: true,
      render: (_, t) => (ownerMap[t.plugin_id] || []).join(', ') || '—' },
    { title: '状态', dataIndex: 'state', key: 'state', width: 110,
      render: (s) => stateTag(s) },
    { title: '操作', key: 'ops', width: 130, render: (_, t) => h(Space, { size: 4 },
        h(Button, { size: 'small', onClick: () => showSchema(t) }, '参数Schema'),
        t.state === 'activated'
          ? h(Button, { size: 'small', onClick: async () => {
              try { await nvwa.api.post(`/api/v1/plugins/${t.plugin_id}/deactivate`); message.success('已禁用'); refresh() }
              catch (err) { message.error(err.message) }
            } }, '禁用')
          : h(Button, { size: 'small', type: 'primary', onClick: async () => {
              try { await nvwa.api.post(`/api/v1/plugins/${t.plugin_id}/activate`); message.success('已激活'); refresh() }
              catch (err) { message.error(err.message) }
            } }, '激活')) },
  ]

  // antd 未在解构中引入 Tooltip，用简单封装保持一致性
  function Tooltipless({ label, color }) { return h(Tag, { color }, label) }

  return h('div', null,
    h(Typography.Title, { level: 5 }, '工具资源管理'),
    h(Typography.Paragraph, { type: 'secondary', style: { fontSize: 12 } },
      '全局工具对所有激活Agent可用；私有工具仅归属Agent（owner_agent_id）可调用。工具调用名供LLM function calling使用。'),
    h(Table, { rowKey: 'plugin_id', columns, dataSource: tools, size: 'middle', loading, pagination: false }),
    h('div', { style: { marginTop: 20 } },
      h(Typography.Title, { level: 5 }, 'Agent 私有工具声明'),
      h(Table, {
        rowKey: 'plugin_id', size: 'small', pagination: false,
        dataSource: agents.filter((a) => (a.private_tool_ids || []).length > 0),
        columns: [
          { title: 'Agent', dataIndex: 'plugin_id', key: 'aid', width: 240,
            render: (id) => h(Typography.Text, { code: true }, id) },
          { title: '私有工具', key: 'ptools',
            render: (_, a) => h(Space, { wrap: true },
              (a.private_tool_ids || []).map((tid) => h(Tag, { key: tid, color: 'purple' }, tid))) },
          { title: 'Agent状态', dataIndex: 'state', key: 'ast', width: 110, render: (s) => stateTag(s) },
        ],
      })),
    h('div', { style: { marginTop: 16 } },
      h(Button, { onClick: refresh, loading: loading }, '刷新')),
  )
}

export { PageComponent }
export default { PageComponent }
