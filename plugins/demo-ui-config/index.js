// 系统配置页面插件（手写原生 ES Module）
// GET /system/config 全量配置 → 行内编辑 → PUT 保存；restart_required 项保存后弹窗提示

const { useState, useEffect, useCallback } = window.React
const h = window.React.createElement
const { Table, Button, Input, Switch, Tag, Typography, Space, message, Modal, Alert } = window.antd

function isBoolLike(v) { return typeof v === 'boolean' }
function isNumberLike(v) { return typeof v === 'number' }

function PageComponent({ nvwa }) {
  const [configs, setConfigs] = useState([])
  const [draft, setDraft] = useState({})
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const data = await nvwa.api.get('/api/v1/system/config')
      setConfigs(data.configs || [])
      setDraft({})
    } catch (err) {
      message.error(`加载配置失败：${err.message}`)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { refresh() }, [])

  const valueOf = (row) => (row.key in draft ? draft[row.key] : row.value)
  const dirtyKeys = Object.keys(draft).filter((k) => {
    const row = configs.find((c) => c.key === k)
    return row && row.value !== draft[k]
  })

  const setValue = (key, v) => setDraft((prev) => Object.assign({}, prev, { [key]: v }))

  const save = async () => {
    if (dirtyKeys.length === 0) { message.info('没有修改项'); return }
    const payload = {}
    dirtyKeys.forEach((k) => { payload[k] = draft[k] })
    setSaving(true)
    try {
      const data = await nvwa.api.put('/api/v1/system/config', { configs: payload })
      if (data.restart_required) {
        Modal.warning({
          title: '配置已保存，需重启后端生效',
          content: h('div', null,
            h('p', null, '以下配置项需要重启后端进程才能生效：'),
            h('ul', null, (data.restart_required_keys || []).map((k) => h('li', { key: k }, h(Typography.Text, { code: true }, k))))),
        })
      } else {
        message.success(`已保存 ${data.updated.length} 项配置`)
      }
      refresh()
    } catch (err) {
      message.error(`保存失败：${err.message}`)
    } finally {
      setSaving(false)
    }
  }

  const columns = [
    { title: '配置项', dataIndex: 'key', key: 'key', width: 280,
      render: (k) => h(Typography.Text, { code: true }, k) },
    { title: '值', key: 'value', width: 380, render: (_, row) => {
        const v = valueOf(row)
        if (isBoolLike(row.value)) return h(Switch, { checked: Boolean(v), onChange: (nv) => setValue(row.key, nv) })
        if (isNumberLike(row.value)) return h(Input, {
          value: String(v), style: { width: 200 },
          onChange: (e) => { const s = e.target.value; setValue(row.key, s === '' ? 0 : Number(s)) },
        })
        return h(Input, { value: String(v ?? ''), style: { width: 320 }, onChange: (e) => setValue(row.key, e.target.value) })
      } },
    { title: '说明', dataIndex: 'description', key: 'desc', ellipsis: true },
    { title: '重启生效', key: 'restart', width: 100, render: (_, row) =>
        row.restart_required ? h(Tag, { color: 'orange' }, '需重启') : h(Tag, null, '即时') },
  ]

  return h('div', null,
    h(Typography.Title, { level: 5 }, '系统全局配置'),
    dirtyKeys.length > 0
      ? h(Alert, { type: 'warning', showIcon: true, style: { marginBottom: 12 },
          message: `有 ${dirtyKeys.length} 项未保存修改`, closable: false }) : null,
    h(Table, { rowKey: 'key', columns, dataSource: configs, size: 'middle', loading, pagination: false }),
    h('div', { style: { marginTop: 16 } },
      h(Space, null,
        h(Button, { type: 'primary', loading: saving, disabled: dirtyKeys.length === 0, onClick: save }, '保存修改'),
        h(Button, { onClick: refresh, disabled: saving }, '放弃修改'))),
  )
}

export { PageComponent }
export default { PageComponent }
