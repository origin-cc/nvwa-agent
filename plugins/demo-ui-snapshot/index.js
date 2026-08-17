// 快照管理组件插件（手写原生 ES Module）
// 保存当前组合 / 加载（全量覆盖）/ 删除 / 导出下载 / 导入（缺失插件告警跳过）

const { useState, useEffect, useCallback, useRef } = window.React
const h = window.React.createElement
const { Button, Tag, Space, List, Input, message, Popconfirm, Typography, Upload, Modal, Alert, Empty, Spin, Tooltip } = window.antd

function PageComponent({ nvwa }) {
  const [snapshots, setSnapshots] = useState([])
  const [loading, setLoading] = useState(false)
  const [name, setName] = useState('')
  const [saving, setSaving] = useState(false)
  const [busyId, setBusyId] = useState(null)
  // 导入/加载结果告警（缺失插件）
  const [warning, setWarning] = useState(null)
  const warningTimer = useRef(null)

  const showWarning = useCallback((text) => {
    setWarning(text)
    if (warningTimer.current) clearTimeout(warningTimer.current)
    warningTimer.current = setTimeout(() => setWarning(null), 15000)
  }, [])

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const data = await nvwa.api.get('/api/v1/snapshot/list')
      setSnapshots(data.snapshots || [])
    } catch (err) {
      message.error(`加载快照列表失败：${err.message}`)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { refresh() }, [])

  const save = async () => {
    const n = name.trim()
    if (!n) { message.warning('请输入快照名称'); return }
    setSaving(true)
    try {
      const data = await nvwa.api.post('/api/v1/snapshot/save', { name: n })
      message.success(`快照「${data.name}」已保存（#${data.snapshot_id}）`)
      setName('')
      refresh()
    } catch (err) { message.error(err.message) } finally { setSaving(false) }
  }

  const load = async (s) => {
    setBusyId(s.snapshot_id)
    try {
      const r = await nvwa.api.post(`/api/v1/snapshot/${s.snapshot_id}/load`)
      const miss = (r.missing_plugin_ids || []).length
      message.success(`快照已加载：激活 ${r.applied.length} 个，禁用 ${r.deactivated.length} 个`)
      if (miss) showWarning((r.warnings || []).join('；'))
    } catch (err) { message.error(err.message) } finally { setBusyId(null) }
  }

  const remove = async (s) => {
    try {
      await nvwa.api.del(`/api/v1/snapshot/${s.snapshot_id}`)
      message.success(`快照「${s.name}」已删除`)
      refresh()
    } catch (err) { message.error(err.message) }
  }

  const exportSnapshot = async (s) => {
    try {
      const resp = await fetch(`/api/v1/snapshot/${s.snapshot_id}/export`)
      if (!resp.ok) throw new Error(`导出失败(${resp.status})`)
      const blob = await resp.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${s.name}.snapshot.json`
      a.click()
      URL.revokeObjectURL(url)
    } catch (err) { message.error(err.message) }
  }

  const importFile = async ({ file, onSuccess, onError }) => {
    try {
      const r = await nvwa.api.upload('/api/v1/snapshot/import', file)
      const miss = (r.missing_plugin_ids || []).length
      Modal.success({
        title: `快照已导入（#${r.snapshot_id}）`,
        content: miss
          ? h('div', null,
              h('p', null, `激活 ${r.applied.length} 个，禁用 ${r.deactivated.length} 个`),
              h(Alert, { type: 'warning', showIcon: true, message: '缺失插件已跳过', description: (r.warnings || []).join('；') }))
          : `激活 ${r.applied.length} 个，禁用 ${r.deactivated.length} 个`,
      })
      if (miss) showWarning((r.warnings || []).join('；'))
      onSuccess(r)
      refresh()
    } catch (err) {
      message.error(`导入失败：${err.message}`)
      onError(err)
    }
  }

  return h('div', { style: { fontSize: 13 } },
    h('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 } },
      h('span', { style: { fontWeight: 600 } }, '快照管理'),
      h(Space, { size: 4 },
        h(Upload, { accept: '.json', showUploadList: false, customRequest: importFile },
          h(Button, { size: 'small' }, '导入')),
        h(Button, { size: 'small', type: 'text', onClick: refresh }, '刷新'))),
    h(Space.Compact, { style: { width: '100%', marginBottom: 8 } },
      h(Input, {
        size: 'small', value: name, onChange: (e) => setName(e.target.value),
        placeholder: '新快照名称', onPressEnter: save, maxLength: 40,
      }),
      h(Button, { size: 'small', type: 'primary', loading: saving, onClick: save }, '保存')),
    warning ? h(Alert, { type: 'warning', showIcon: true, style: { marginBottom: 8 }, message: warning }) : null,
    h(Spin, { spinning: loading },
      snapshots.length === 0 && !loading
        ? h(Empty, { image: Empty.PRESENTED_IMAGE_SIMPLE, description: '暂无快照' })
        : h(List, {
            size: 'small', dataSource: snapshots,
            renderItem: (s) => h(List.Item, {
              style: { padding: '6px 2px' },
              actions: [
                h(Button, { size: 'small', type: 'primary', loading: busyId === s.snapshot_id, onClick: () => load(s) }, '加载'),
                h(Tooltip, { title: '导出JSON' },
                  h(Button, { size: 'small', onClick: () => exportSnapshot(s) }, '⇩')),
                h(Popconfirm, { title: `删除快照「${s.name}」？` },
                  h(Button, { size: 'small', danger: true, onClick: () => remove(s) }, '删')),
              ].map((btn, i) => h('span', { key: i }, btn)),
            },
              h(List.Item.Meta, {
                title: h('span', { style: { fontSize: 13 } },
                  s.name, ' ',
                  s.is_preset ? h(Tag, { color: 'purple', style: { fontSize: 11 } }, '预置') : null),
                description: h('span', { style: { fontSize: 11 } },
                  `#${s.snapshot_id} · ${s.created_at ? String(s.created_at).replace('T', ' ').slice(0, 16) : ''}`),
              })),
          })),
    h(Typography.Text, { type: 'secondary', style: { fontSize: 11, display: 'block', marginTop: 6 } },
      '加载为全量覆盖：快照外已启用插件将被禁用；运行中任务不受影响'),
  )
}

export { PageComponent, PageComponent as Component }
export default { PageComponent, Component: PageComponent }
