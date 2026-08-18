// 任务组件状态收集器（v1.0 §5.3）：监听任务 SSE 事件，节流收集激活组件状态并上报
// - 触发：agent:think / tool:call / tool:result / task:update / task:finish
// - 节流：最小间隔 1000ms；task:finish 等关键事件强制收集
import { api } from './api.js'
import { eventBus } from './eventBus.js'

const TASK_EVENTS = ['agent:think', 'tool:call', 'tool:result', 'task:update', 'task:finish']
const THROTTLE_MS = 1000

let getActiveStates = () => []
let eventSeq = 0
let lastCollectAt = 0
let timer = null

function report(taskId, seq, eventType, states) {
  if (!taskId || !states.length) return
  api.post(`/api/v1/task/${taskId}/ui-state-snapshot`, {
    event_seq: seq,
    event_type: eventType,
    states,
  }).catch(() => {})  // 回放辅助数据，上报失败不阻断实时链路
}

function collect(taskId, eventType, force) {
  const run = () => {
    lastCollectAt = Date.now()
    report(taskId, eventSeq, eventType, getActiveStates())
  }
  if (force) {
    clearTimeout(timer)
    run()
    return
  }
  const elapsed = Date.now() - lastCollectAt
  if (elapsed >= THROTTLE_MS) {
    run()
  } else {
    clearTimeout(timer)
    timer = setTimeout(run, THROTTLE_MS - elapsed)
  }
}

function onTaskEvent(type, payload) {
  const taskId = payload && payload.task_id
  if (!taskId) return
  eventSeq += 1
  collect(taskId, type, type === 'task:finish')
}

export function startStateCollector(injectGetActiveStates) {
  getActiveStates = injectGetActiveStates || (() => [])
  TASK_EVENTS.forEach((type) => {
    eventBus.on(type, (payload) => onTaskEvent(type, payload))
  })
}
