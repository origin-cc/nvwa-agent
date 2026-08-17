// 知识库管理页面插件（手写原生 ES Module）
// 上传（txt/md/pdf）→ status 轮询（parsing/indexing/ready/failed）→ 删除

const { useState, useEffect, useRef, useCallback } = window.React
const h = window.React.createElement
const { Table, Button, Tag, Upload, Typography, Space, message, Popconfirm, Empty, Tooltip } = window.antd

const STATUS_META = {
  parsing: ['解析中', 'processing'],
  indexing: ['向量化中', 'processing'],
  ready: ['就绪', 'success'],
  failed: ['失败', 'error'],
}

function statusTag(status) {
  const [label, color] = STATUS_META[status] || [status, 'default']
  return h(Tag, { color: label === '解析中' || label === '向量化中' ? 'processing' : color },
    label === '解析中' || label === '向量化中' ? h('span', null, label + '…') : label)
}

function PageComponent({ nvwa }) {
  const [docs, setDocs] = useState([])
  const [loading, setLoading] = useState(false)
  const [uploading, setUploading] = useState(false)
  const pollingRef = useRef(null)

  const refresh = useCallback(async (silent = false) => {
    if (!silent) setLoading(true)
    try {
      const data = await nvwa.api.get('/api/v1/knowledge/list')
      setDocs(data.docs || [])
      return data.docs || []
    } catch (err) {
      if (!silent) message.error(`加载知识库失败：${err.message}`)
      return []
    } finally {
      if (!silent) setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [])

  // 存在进行中的解析/向量化时轮询（2s），全部终态后停止
  useEffect(() => {
    const hasPending = docs.some((d) => d.status === 'parsing' || d.status === 'indexing')
    if (hasPending && !pollingRef.current) {
      pollingRef.current = setInterval(() => refresh(true), 2000)
    } else if (!hasPending && pollingRef.current) {
      clearInterval(pollingRef.current)
      pollingRef.current = null
    }
    return () => { if (pollingRef.current) { clearInterval(pollingRef.current); pollingRef.current = null } }
  }, [docs])

  const customRequest = async ({ file, onSuccess, onError }) => {
    setUploading(true)
    try {
      const data = await nvwa.api.upload('/api/v1/knowledge/upload', file)
      message.success(`已上传「${file.name}」，后台解析向量化中`)
      onSuccess(data)
      setTimeout(() => refresh(true), 500)
    } catch (err) {
      message.error(`上传失败：${err.message}`)
      onError(err)
    } finally {
      setUploading(false)
    }
  }

  const remove = async (docId) => {
    try {
      await nvwa.api.del(`/api/v1/knowledge/${docId}`)
      message.success('文档已删除（索引已重建）')
      refresh()
    } catch (err) { message.error(err.message) }
  }

  const columns = [
    { title: '文件名', dataIndex: 'file_name', key: 'name', ellipsis: true,
      render: (n) => h(Typography.Text, { strong: true }, n) },
    { title: '状态', key: 'status', width: 120, render: (_, d) => statusTag(d.status) },
    { title: '切片数', dataIndex: 'chunk_count', key: 'chunks', width: 90 },
    { title: '错误信息', key: 'error', ellipsis: true,
      render: (_, d) => d.error_msg
        ? h(Tooltip, { title: d.error_msg }, h(Typography.Text, { type: 'danger', style: { fontSize: 12 } }, d.error_msg))
        : '—' },
    { title: '上传时间', dataIndex: 'created_at', key: 'time', width: 170,
      render: (t) => t ? String(t).replace('T', ' ').slice(0, 19) : '—' },
    { title: '操作', key: 'ops', width: 90,
      render: (_, d) => h(Popconfirm, { title: `删除「${d.file_name}」并重建索引？`, onConfirm: () => remove(d.doc_id) },
        h(Button, { size: 'small', danger: true }, '删除')) },
  ]

  return h('div', null,
    h('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 } },
      h('div', null,
        h(Typography.Title, { level: 5, style: { marginBottom: 0 } }, '知识库管理'),
        h(Typography.Text, { type: 'secondary', style: { fontSize: 12 } },
          '上传文档自动解析切片并向量化入库；Agent 通过知识库检索工具引用内容回答')),
      h(Space, null,
        h(Upload, {
          accept: '.txt,.md,.markdown,.pdf', showUploadList: false,
          customRequest, disabled: uploading,
        }, h(Button, { type: 'primary', loading: uploading }, '上传文档')),
        h(Button, { onClick: () => refresh(), loading: loading }, '刷新'))),
    docs.length === 0 && !loading
      ? h(Empty, { style: { marginTop: 80 }, description: '暂无知识库文档，上传 txt / md / pdf 开始' })
      : h(Table, { rowKey: 'doc_id', columns, dataSource: docs, size: 'middle', loading, pagination: false }),
  )
}

export { PageComponent }
export default { PageComponent }
