// 任务回放页面插件（手写原生 ES Module，v1.0 增强版）
// 左：任务列表（/task/list 分页）
// 右：任务详情 + 事件时间线（/task/{id}/log）+ 组件状态回放（/task/{id}/ui-state-snapshots）
// 组件状态回放：按 event_seq 顺序注入快照到组件命名空间，复现组件渲染状态（§5）

const { useState, useEffect, useCallback, useRef } = window.React
const h = window.React.createElement
const { Table, Button, Tag, Typography, Space, Timeline, Empty, Spin, message, Tooltip, Pagination, Card, Select, Slider, Divider } = window.antd

const STATUS_COLOR = {
  pending: 'default', running: 'processing', success: 'success',
  succeeded: 'success', failed: 'error',
}

// 事件类型展示元数据：[标签, 颜色]
const EVENT_META = {
  'task:submitted': ['任务提交', 'blue'],
  'task:start': ['任务开始', 'blue'],
  'agent:think': ['思考流', 'geekblue'],
  'tool:call': ['工具调用', 'cyan'],
  'tool:result': ['工具结果', 'green'],
  'tool:error': ['工具错误', 'red'],
  'task:finish': ['任务完成', 'green'],
  'task:failed': ['任务失败', 'red'],
}

// 连续 agent:think 分片合并为一条展示（保留首尾时间与拼接内容）
function mergeEvents(events) {
  const merged = []
  events.forEach((e) => {
    const last = merged[merged.length - 1]
    if (e.event_type === 'agent:think' && last && last.event_type === 'agent:think') {
      if (e.event_payload && e.event_payload.think_content) {
        last.thinkText += e.event_payload.think_content
      }
      return
    }
    merged.push({
      ...e,
      thinkText: (e.event_payload && e.event_payload.think_content) || '',
    })
  })
  return merged
}

function payloadPreview(e) {
  const p = e.event_payload || {}
  if (e.event_type === 'agent:think') {
    return e.thinkText.length > 200 ? e.thinkText.slice(0, 200) + '…' : e.thinkText
  }
  if (e.event_type === 'tool:call') {
    return `${p.tool_id || p.tool_name || '?'} ${JSON.stringify(p.args || p.arguments || {})}`
  }
  if (e.event_type === 'tool:result') {
    const d = typeof p.result === 'string' ? p.result : JSON.stringify(p.result)
    return (d || '').slice(0, 200)
  }
  if (e.event_type === 'tool:error') {
    return `[${p.error_code || 'TOOL_ERROR'}] ${p.error_msg || p.error || ''}`
  }
  if (e.event_type === 'task:finish') {
    return typeof p.result === 'string' ? p.result : JSON.stringify(p.result || {})
  }
  if (e.event_type === 'task:failed') {
    return `[${p.error_code || 'TASK_FAILED'}] ${p.error_msg || ''}`
  }
  return JSON.stringify(p).slice(0, 200)
}

function fmtTime(t) {
  return t ? String(t).replace('T', ' ').slice(11, 23) : ''
}

function PageComponent({ nvwa }) {
  const [tasks, setTasks] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [selected, setSelected] = useState(null)   // 任务详情
  const [events, setEvents] = useState([])
  const [logLoading, setLogLoading] = useState(false)
  const [taskDeleted, setTaskDeleted] = useState(false)
  const [snapshots, setSnapshots] = useState([])
  const [playIdx, setPlayIdx] = useState(-1)       // -1 未播放
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(1)
  const playTimerRef = useRef(null)
  const pageSize = 15

  const refresh = useCallback(async (p = 1) => {
    setLoading(true)
    try {
      const data = await nvwa.api.get(`/api/v1/task/list?page=${p}&page_size=${pageSize}`)
      setTasks(data.tasks || [])
      setTotal(data.total || 0)
      setPage(p)
    } catch (err) {
      message.error(`加载任务列表失败：${err.message}`)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { refresh(1) }, [])

  const stopPlay = useCallback(() => {
    setPlaying(false)
    setPlayIdx(-1)
    if (playTimerRef.current) clearTimeout(playTimerRef.current)
  }, [])

  const openTask = async (task) => {
    stopPlay()
    setSelected(task)
    setSnapshots([])
    setLogLoading(true)
    try {
      const data = await nvwa.api.get(`/api/v1/task/${task.task_id}/log`)
      setEvents(mergeEvents(data.events || []))
      setTaskDeleted(Boolean(data.task_deleted))
      const snap = await nvwa.api.get(`/api/v1/task/${task.task_id}/ui-state-snapshots`)
      setSnapshots(snap.snapshots || [])
    } catch (err) {
      message.error(`加载事件日志失败：${err.message}`)
      setEvents([])
    } finally {
      setLogLoading(false)
    }
  }

  // 播放推进：按 event_seq 顺序注入快照状态（§5.4）
  useEffect(() => {
    if (!playing || playIdx < 0 || playIdx >= snapshots.length) {
      if (playing && playIdx >= snapshots.length) setPlaying(false)
      return
    }
    const snap = snapshots[playIdx]
    if (snap && nvwa.replay) {
      try { nvwa.replay.inject(snap.plugin_id, snap.state) } catch (e) { /* 注入失败忽略 */ }
    }
    playTimerRef.current = setTimeout(() => setPlayIdx((i) => i + 1), 1000 / speed)
    return () => { if (playTimerRef.current) clearTimeout(playTimerRef.current) }
  }, [playing, playIdx, snapshots, speed])

  const startPlay = () => {
    if (!snapshots.length) { message.info('该任务无组件状态快照'); return }
    setPlayIdx(0)
    setPlaying(true)
  }

  const columns = [
    { title: '任务', key: 'prompt', ellipsis: true,
      render: (_, t) => h('div', null,
        h(Typography.Text, { style: { fontSize: 13 } }, (t.input_prompt || '').slice(0, 60) || '(空)'),
        h('div', null, h(Typography.Text, { type: 'secondary', style: { fontSize: 12 } },
          fmtTime(t.created_at)))) },
    { title: '状态', dataIndex: 'status', key: 'status', width: 95,
      render: (s) => h(Tag, { color: STATUS_COLOR[s] || 'default' }, s) },
    { title: '操作', key: 'ops', width: 70,
      render: (_, t) => h(Button, { size: 'small', type: 'link', onClick: () => openTask(t) }, '回放') },
  ]

  const timelineItems = events.map((e) => {
    const [label, color] = EVENT_META[e.event_type] || [e.event_type, 'gray']
    return {
      key: e.log_id,
      color: e.event_type === 'tool:error' || e.event_type === 'task:failed' ? 'red' : 'blue',
      children: h('div', { style: { fontSize: 12 } },
        h(Space, { size: 6 },
          h(Tag, { color }, label),
          h(Typography.Text, { type: 'secondary', style: { fontSize: 11 } }, fmtTime(e.event_time))),
        h('div', { style: { marginTop: 2, wordBreak: 'break-all', whiteSpace: 'pre-wrap' } },
          payloadPreview(e) || '—')),
    }
  })

  const currentSnap = playIdx >= 0 && playIdx < snapshots.length ? snapshots[playIdx] : null

  return h('div', { style: { display: 'flex', gap: 12, height: 'calc(100vh - 32px)' } },
    // 左：任务列表
    h('div', { style: { width: 420, flexShrink: 0, display: 'flex', flexDirection: 'column' } },
      h('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 } },
        h(Typography.Title, { level: 5, style: { marginBottom: 0 } }, '任务回放'),
        h(Button, { size: 'small', onClick: () => refresh(page), loading }, '刷新')),
      h(Table, {
        rowKey: 'task_id', columns, dataSource: tasks,
        size: 'small', loading, pagination: false,
        onRow: (t) => ({ onClick: () => openTask(t), style: { cursor: 'pointer' } }),
      }),
      h('div', { style: { marginTop: 8, textAlign: 'right' } },
        h(Pagination, {
          size: 'small', current: page, pageSize: pageSize, total,
          showTotal: (n) => `共 ${n} 条`,
          onChange: (p) => refresh(p),
        }))),
    // 右：时间线 + 组件状态回放
    h('div', { style: { flex: 1, minWidth: 0, borderLeft: '1px solid var(--nvwa-border)', paddingLeft: 16, overflowY: 'auto' } },
      !selected
        ? h(Empty, { style: { marginTop: 120 }, description: '左侧选择一个任务查看事件时间线' })
        : h(Spin, { spinning: logLoading },
            h('div', { style: { marginBottom: 12 } },
              h(Typography.Title, { level: 5, style: { marginBottom: 4 } },
                '任务详情',
                ' ',
                h(Tag, { color: STATUS_COLOR[selected.status] || 'default' }, selected.status)),
              taskDeleted
                ? h(Tag, { color: 'volcano' }, '任务记录已删除（悬空日志，仅事件回放）')
                : h('div', { style: { fontSize: 12 } },
                    h('div', null, h('b', null, '输入：'), selected.input_prompt),
                    selected.result ? h('div', { style: { marginTop: 4 } }, h('b', null, '结果：'), selected.result) : null)),
            events.length === 0 && !logLoading
              ? h(Empty, { description: '该任务暂无事件日志' })
              : h(Timeline, { items: timelineItems }),
            h(Divider, null),
            // 组件状态回放面板（§5.4）
            h(Card, {
              size: 'small', title: '组件状态回放',
              extra: h(Typography.Text, { type: 'secondary', style: { fontSize: 12 } },
                `共 ${snapshots.length} 个快照`),
            },
              snapshots.length === 0
                ? h(Empty, { image: Empty.PRESENTED_IMAGE_SIMPLE, description: '该任务无组件状态快照（任务执行期间由基座自动收集）' })
                : h('div', null,
                    h(Space, { style: { marginBottom: 8 } },
                      h(Button, { size: 'small', type: 'primary', disabled: playing, onClick: startPlay }, '播放'),
                      h(Button, { size: 'small', disabled: !playing, onClick: () => setPlaying(false) }, '暂停'),
                      h(Button, { size: 'small', onClick: stopPlay }, '停止'),
                      h(Select, {
                        size: 'small', value: speed, style: { width: 90 },
                        onChange: (v) => setSpeed(v),
                        options: [
                          { value: 1, label: '1x' }, { value: 2, label: '2x' },
                          { value: 4, label: '4x' }, { value: 8, label: '8x' },
                        ],
                      })),
                    h('div', { style: { fontSize: 12, marginBottom: 4 } },
                      currentSnap
                        ? h('span', null,
                            `event_seq=${currentSnap.event_seq} · ${currentSnap.event_type || '-'} · ${currentSnap.plugin_id}`)
                        : '点击「播放」开始按时间轴复现组件状态'),
                    h('div', { style: { fontSize: 12, wordBreak: 'break-all', whiteSpace: 'pre-wrap' } },
                      currentSnap ? JSON.stringify(currentSnap.state) : '—')))),
  ))
}

export { PageComponent }
export default { PageComponent }
