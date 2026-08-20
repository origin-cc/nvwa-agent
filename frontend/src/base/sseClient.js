// SSE 客户端（§4.7）：订阅 / 心跳检测 / 断线重连 / 状态恢复
// - 连续2个心跳周期(60s)未收到 sse:heartbeat 判定断连并重连
// - 重连成功不回放历史事件，通过 REST 拉取最新插件与任务状态
import { api } from './api.js'
import { eventBus } from './eventBus.js'

const HEARTBEAT_MS = 30000
const MAX_SILENCE_MS = HEARTBEAT_MS * 2 + 5000

let source = null
let lastHeartbeatAt = 0
let watchdogTimer = null
let reconnectDelay = 1000
let connected = false

function setConnected(value) {
  if (connected !== value) {
    connected = value
    eventBus.emit('nvwa:sse-status', { connected })
    if (value) refreshStateAfterReconnect()
  }
}

async function refreshStateAfterReconnect() {
  // 重连后：REST 拉取最新插件状态（不回放历史SSE事件，§4.7）
  try {
    const data = await api.get('/api/v1/plugins/list')
    eventBus.emit('nvwa:plugins-refresh', data.plugins || [])
  } catch {
    /* 下次心跳/事件会再同步 */
  }
}

function connect() {
  if (source) { source.close(); source = null }
  const es = new EventSource('/api/v1/sse/subscribe')
  source = es

  es.onopen = () => {
    reconnectDelay = 1000
    lastHeartbeatAt = Date.now()
    setConnected(true)
  }

  es.addEventListener('sse:heartbeat', () => {
    lastHeartbeatAt = Date.now()
  })

  const forward = (evt) => {
    lastHeartbeatAt = Date.now()
    let payload = {}
    try { payload = JSON.parse(evt.data) } catch { payload = { raw: evt.data } }
    eventBus.emit(evt.type, payload)
  }
  const types = [
    'plugin:loaded', 'plugin:activated', 'plugin:deactivated', 'plugin:unloaded',
    'plugin:error', 'task:start', 'task:update', 'task:finish', 'task:error',
    'task:cancelled', 'agent:think', 'tool:call', 'tool:result', 'tool:error',
  ]
  types.forEach((t) => es.addEventListener(t, forward))

  es.onerror = () => {
    setConnected(false)
    es.close()
    source = null
    setTimeout(connect, reconnectDelay)
    reconnectDelay = Math.min(reconnectDelay * 2, 15000)
  }
}

function watchdog() {
  if (connected && Date.now() - lastHeartbeatAt > MAX_SILENCE_MS) {
    // 心跳超时：判定断连，强制重连
    if (source) { source.close(); source = null }
    setConnected(false)
    connect()
  }
}

export const sseClient = {
  start() {
    if (watchdogTimer) return
    connect()
    watchdogTimer = setInterval(watchdog, 5000)
  },
  stop() {
    if (watchdogTimer) clearInterval(watchdogTimer)
    watchdogTimer = null
    if (source) source.close()
    source = null
    setConnected(false)
  },
  isConnected: () => connected,
}
