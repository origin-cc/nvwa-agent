// 插件管理页面插件（手写原生 ES Module）
// 展示全量插件元数据与双端状态；提供 激活/禁用/卸载/扫描 操作
// 后端状态来自 /plugins/list；前端状态本地维护（plugin:* SSE 事件驱动 + 初始推断）

const { useState, useEffect, useCallback } = window.React
const h = window.React.createElement
const { Table, Button, Tag, Space, Select, message, Tooltip, Popconfirm, Typography } = window.antd

const TYPE_LABEL = {
  backend_agent: 'Agent',
  backend_tool: '工具',
  ui_page_plugin: '页面',
  ui_component_plugin: '组件',
}

function stateTag(state) {
  const colorMap = {
    activated: 'green', loaded: 'blue', deactivated: 'orange',
    unloaded: 'default', fault: 'red',
  }
  return h(Tag, { color: colorMap[state] || 'default' }, state || '-')
}

function PageComponent({ nvwa }) {
  const [plugins, setPlugins] = useState([])
  const [feStates, setFeStates] = useState({})
  const [errors, setErrors] = useState({})
  const [typeFilter, setTypeFilter] = useState('all')
  const [loading, setLoading] = useState(false)
  const [scanning, setScanning] = useState(false)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const data = await nvwa.api.get('/api/v1/plugins/list')
      setPlugins(data.plugins || [])
      // 初始推断：UI插件后端为 activated 时前端通常已联动激活
      setFeStates((prev) => {
        const next = Object.assign({}, prev)
        ;(data.plugins || []).forEach((p) => {
          if (!String(p.type).startsWith('ui_')) return
          if (!next[p.plugin_id] || next[p.plugin_id] === 'activated') {
            next[p.plugin_id] = p.state === 'activated' ? 'activated' : next[p.plugin_id] || 'deactivated'
          }
        })
        return next
      })
    } catch (err) {
      message.error(`加载插件列表失败：${err.message}`)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { refresh() }, [])

  // 双端状态实时同步
  useEffect(() => {
    const setFe = (id, state, error) => {
      setFeStates((prev) => Object.assign({}, prev, { [id]: state }))
      if (error !== undefined) setErrors((prev) => Object.assign({}, prev, { [id]: error }))
    }
    const offs = [
      nvwa.events.on('plugin:loaded', (p) => setFe(p.plugin_id, 'loaded')),
      nvwa.events.on('plugin:activated', (p) => setFe(p.plugin_id, 'activated', '')),
      nvwa.events.on('plugin:deactivated', (p) => setFe(p.plugin_id, 'deactivated')),
      nvwa.events.on('plugin:unloaded', (p) => setFe(p.plugin_id, 'unloaded')),
      nvwa.events.on('plugin:error', (p) => setErrors((prev) =>
        Object.assign({}, prev, { [p.plugin_id]: `[${p.error_code || 'PLUGIN_ERROR'}] ${p.error_msg}` }))),
      nvwa.events.on('nvwa:plugin-fe-fault', (p) => setFe(p.plugin_id, 'fault', '前端渲染故障（详见控制台）')),
      // 任意插件事件后软刷新后端状态行
      nvwa.events.on('plugin:activated', refresh),
      nvwa.events.on('plugin:deactivated', () => setTimeout(refresh, 200)),
      nvwa.events.on('plugin:unloaded', () => setTimeout(refresh, 200)),
    ]
    return () => offs.forEach((off) => off && off())
  }, [])

  const op = async (path, okMsg) => {
    try {
      await nvwa.api.post(`/api/v1/plugins/${path}`)
      message.success(okMsg)
      setTimeout(refresh, 250) // 等后端事件落地后刷新
    } catch (err) {
      message.error(err.message)
      refresh()
    }
  }

  const scan = async () => {
    setScanning(true)
    try {
      const data = await nvwa.api.post('/api/v1/plugins/scan')
      message.success(`扫描完成：新增 ${data.loaded_new ?? data.new ?? 0}，恢复 ${data.restored ?? 0}`)
      refresh()
    } catch (err) {
      message.error(`扫描失败：${err.message}`)
    } finally {
      setScanning(false)
    }
  }

  const dataSource = plugins.filter((p) => typeFilter === 'all' || p.type === typeFilter)

  const columns = [
    { title: '插件', key: 'id', render: (_, p) => h('div', null,
        h('div', { style: { fontWeight: 600 } }, p.name, ' ', h(Typography.Text, { code: true, style: { fontSize: 12 } }, p.plugin_id)),
        h(Typography.Text, { type: 'secondary', style: { fontSize: 12 } }, p.description || '')) },
    { title: '类型', key: 'type', width: 90, render: (_, p) => h(Tag, null, TYPE_LABEL[p.type] || p.type) },
    { title: '版本', dataIndex: 'version', key: 'version', width: 80 },
    { title: '后端状态', key: 'state', width: 110, render: (_, p) => h('div', null,
        stateTag(p.state),
        p.disk_missing ? h(Tag, { color: 'volcano' }, '磁盘缺失') : null) },
    { title: '前端状态', key: 'fe', width: 110,
      render: (_, p) => String(p.type).startsWith('ui_') ? stateTag(feStates[p.plugin_id]) : h(Tag, null, '—') },
    { title: '错误信息', key: 'error', ellipsis: true,
      render: (_, p) => {
        const err = errors[p.plugin_id] || p.error_msg
        return err ? h(Typography.Text, { type: 'danger', style: { fontSize: 12 } }, err) : '—'
      } },
    { title: '操作', key: 'ops', width: 190, render: (_, p) => {
        const st = p.state
        return h(Space, { size: 4 },
          st !== 'activated' && st !== 'fault'
            ? h(Button, { size: 'small', type: 'primary', onClick: () => op(`${p.plugin_id}/activate`, '已激活') }, '激活') : null,
          st === 'activated'
            ? h(Button, { size: 'small', onClick: () => op(`${p.plugin_id}/deactivate`, '已禁用') }, '禁用') : null,
          (st === 'loaded' || st === 'deactivated' || st === 'fault')
            ? h(Popconfirm, { title: `确认卸载插件 ${p.plugin_id}？` },
                h(Button, { size: 'small', danger: true, onClick: () => op(`${p.plugin_id}/unload`, '已卸载') }, '卸载')) : null,
          st === 'fault'
            ? h(Tooltip, { title: '故障插件需先卸载再重新激活' }, h(Tag, { color: 'red' }, '需先卸载')) : null)
      } },
  ]

  return h('div', null,
    h('div', { style: { display: 'flex', justifyContent: 'space-between', marginBottom: 12 } },
      h(Space, null,
        h(Select, {
          value: typeFilter, onChange: setTypeFilter, style: { width: 140 },
          options: [
            { value: 'all', label: '全部类型' },
            { value: 'backend_agent', label: 'Agent 插件' },
            { value: 'backend_tool', label: '工具插件' },
            { value: 'ui_page_plugin', label: '页面插件' },
            { value: 'ui_component_plugin', label: '组件插件' },
          ],
        }),
        h(Typography.Text, { type: 'secondary' }, `共 ${dataSource.length} 个插件`)),
      h(Space, null,
        h(Button, { onClick: refresh, loading: loading }, '刷新'),
        h(Button, { type: 'primary', onClick: scan, loading: scanning }, '扫描插件目录'))),
    h(Table, {
      rowKey: 'plugin_id', columns, dataSource,
      size: 'middle', loading,
      pagination: false,
      expandable: {
        rowExpandable: (p) => Boolean(p.bind_ui_plugin_id || p.bind_backend_plugin_id || (p.dependencies && p.dependencies.length) || (p.ui && (p.ui.route_path || p.ui.target_slot))),
        expandedRowRender: (p) => h('div', { style: { fontSize: 12 } },
          p.bind_ui_plugin_id ? h('div', null, `绑定前端插件：${p.bind_ui_plugin_id}`) : null,
          p.bind_backend_plugin_id ? h('div', null, `绑定后端插件：${p.bind_backend_plugin_id}`) : null,
          p.dependencies && p.dependencies.length ? h('div', null, `依赖：${p.dependencies.join(', ')}`) : null,
          p.ui && p.ui.route_path ? h('div', null, `路由：${p.ui.route_path}`) : null,
          p.ui && p.ui.target_slot ? h('div', null, `目标插槽：${p.ui.target_slot}`) : null,
          p.ui && p.ui.slots && p.ui.slots.length ? h('div', null, `声明插槽：${p.ui.slots.join(', ')}`) : null),
      },
    }),
  )
}

export { PageComponent }
export default { PageComponent }
