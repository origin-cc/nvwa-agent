// 插件调试面板页面插件（手写原生 ES Module，v1.0 §6）
// 插件列表 + 详情抽屉（基本信息 / error_msg + error_stack / 运行日志过滤）

const { useState, useEffect, useCallback } = window.React
const h = window.React.createElement
const { Table, Button, Tag, Typography, Space, Drawer, Descriptions, Empty, Spin, message, List, Select, Input } = window.antd

const STATE_COLOR = {
  loaded: 'default', activated: 'success', deactivated: 'warning',
  unloaded: 'default', fault: 'error',
}

const LEVEL_COLOR = { ERROR: 'red', WARN: 'orange', INFO: 'blue', DEBUG: 'default' }

function PageComponent({ nvwa }) {
  const [plugins, setPlugins] = useState([])
  const [loading, setLoading] = useState(false)
  const [selected, setSelected] = useState(null)
  const [logs, setLogs] = useState([])
  const [logLoading, setLogLoading] = useState(false)
  const [level, setLevel] = useState(undefined)
  const [keyword, setKeyword] = useState('')

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const data = await nvwa.api.get('/api/v1/plugins/list')
      setPlugins(data.plugins || [])
    } catch (err) {
      message.error(`加载插件列表失败：${err.message}`)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { refresh() }, [])

  const openDetail = async (p) => {
    setSelected(p)
    setLogs([])
    setLogLoading(true)
    try {
      const params = new URLSearchParams()
      if (level) params.append('level', level)
      if (keyword) params.append('keyword', keyword)
      const qs = params.toString()
      const data = await nvwa.api.get(`/api/v1/plugins/${p.plugin_id}/logs${qs ? '?' + qs : ''}`)
      setLogs(data.logs || [])
    } catch (err) {
      message.error(`加载插件日志失败：${err.message}`)
    } finally {
      setLogLoading(false)
    }
  }

  const columns = [
    { title: '插件', key: 'id', ellipsis: true,
      render: (_, p) => h('div', null,
        h(Typography.Text, { strong: true }, p.name),
        h('div', null, h(Typography.Text, { type: 'secondary', style: { fontSize: 12 } }, p.plugin_id))) },
    { title: '类型', dataIndex: 'type', key: 'type', width: 160 },
    { title: '状态', dataIndex: 'state', key: 'state', width: 110,
      render: (s) => h(Tag, { color: STATE_COLOR[s] || 'default' }, s) },
    { title: '操作', key: 'ops', width: 70,
      render: (_, p) => h(Button, { size: 'small', type: 'link', onClick: () => openDetail(p) }, '详情') },
  ]

  const renderLogItem = (log) => h(List.Item, { style: { padding: '4px 0' } },
    h(Typography.Text, { type: 'secondary', style: { fontSize: 12, width: 150, flexShrink: 0 } }, log.time),
    h(Tag, { color: LEVEL_COLOR[log.level] || 'default', style: { marginLeft: 8 } }, log.level),
    h(Typography.Text, { style: { fontSize: 12, wordBreak: 'break-all' } }, log.message))

  const renderDetail = (p) => {
    if (!p) return null
    return h('div', null,
      h(Descriptions, { size: 'small', column: 2, bordered: true },
        h(Descriptions.Item, { label: '类型' }, p.type),
        h(Descriptions.Item, { label: '版本' }, p.version),
        h(Descriptions.Item, { label: '状态' }, h(Tag, { color: STATE_COLOR[p.state] || 'default' }, p.state)),
        h(Descriptions.Item, { label: '目录' }, p.dir_name || '-')),
      p.error_msg ? h('div', { style: { marginTop: 8 } },
        h(Typography.Text, { type: 'danger', strong: true }, '错误摘要：'),
        h('div', { style: { background: 'var(--nvwa-error-bg)', padding: 8, borderRadius: 4, whiteSpace: 'pre-wrap', wordBreak: 'break-all' } }, p.error_msg)) : null,
      p.error_stack ? h('div', { style: { marginTop: 8 } },
        h(Typography.Text, { type: 'danger', strong: true }, '错误堆栈：'),
        h('pre', { style: { background: 'var(--nvwa-bg-hover)', padding: 8, borderRadius: 4, whiteSpace: 'pre-wrap', maxHeight: 300, overflow: 'auto', fontSize: 12 } }, p.error_stack)) : null,
      h('div', { style: { marginTop: 12 } },
        h(Space, { style: { marginBottom: 8 } },
          h(Select, { size: 'small', placeholder: '级别', allowClear: true, style: { width: 110 },
            value: level, onChange: (v) => setLevel(v || undefined),
            options: ['DEBUG', 'INFO', 'WARN', 'ERROR'].map((l) => ({ value: l, label: l })) }),
          h(Input, { size: 'small', placeholder: '关键字', style: { width: 200 },
            value: keyword, onChange: (e) => setKeyword(e.target.value), allowClear: true }),
          h(Button, { size: 'small', type: 'primary', onClick: () => openDetail(p) }, '查询日志')),
        h(Spin, { spinning: logLoading },
          logs.length === 0
            ? h(Empty, { image: Empty.PRESENTED_IMAGE_SIMPLE, description: '无匹配日志' })
            : h(List, { size: 'small', dataSource: logs, renderItem: renderLogItem }))))
  }

  return h('div', { style: { padding: 16 } },
    h('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 } },
      h(Typography.Title, { level: 5, style: { marginBottom: 0 } }, '插件调试面板'),
      h(Button, { size: 'small', onClick: refresh, loading }, '刷新')),
    h(Table, { rowKey: 'plugin_id', columns, dataSource: plugins, size: 'small', loading, pagination: false }),
    h(Drawer, {
      title: selected ? `${selected.name}（${selected.plugin_id}）` : '',
      open: Boolean(selected),
      width: 680,
      onClose: () => setSelected(null),
    }, renderDetail(selected)))
}

export { PageComponent }
export default { PageComponent }
