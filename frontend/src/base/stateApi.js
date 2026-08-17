// 插件状态隔离 API（§4.6 / §4.9）：按插件id隔离的私有状态 + 后端持久化
// - 激活时 GET 恢复；变更时防抖 PUT 保存；卸载时强制落盘
// - 插件仅能读写自身 plugin_id 作用域（scopedHandle 强制绑定）
import { api } from './api.js'

const memStates = new Map() // pluginId -> object
const timers = new Map()

export async function restoreState(pluginId) {
  try {
    const data = await api.get(`/api/v1/plugins/${pluginId}/state`)
    memStates.set(pluginId, (data && data.state) || {})
  } catch {
    memStates.set(pluginId, {})
  }
  return memStates.get(pluginId)
}

export function getState(pluginId) {
  if (!memStates.has(pluginId)) memStates.set(pluginId, {})
  return memStates.get(pluginId)
}

export function saveState(pluginId, patch) {
  const current = getState(pluginId)
  Object.assign(current, patch || {})
  clearTimeout(timers.get(pluginId))
  timers.set(pluginId, setTimeout(() => flushState(pluginId), 800))
}

export async function flushState(pluginId) {
  clearTimeout(timers.get(pluginId))
  timers.delete(pluginId)
  const state = getState(pluginId)
  try {
    await api.put(`/api/v1/plugins/${pluginId}/state`, { state })
  } catch (err) {
    console.warn(`[nvwa:state] 插件 ${pluginId} 状态保存失败`, err)
  }
}

export function clearState(pluginId) {
  // 卸载时：先落盘最终状态，再清空内存私有状态（§4.9.4）
  flushState(pluginId)
  memStates.delete(pluginId)
}

// 绑定插件自身作用域的句柄（注入 props.nvwa / setup 参数）
export function scopedStateHandle(pluginId) {
  return {
    get: () => getState(pluginId),
    save: (patch) => saveState(pluginId, patch),
    flush: () => flushState(pluginId),
  }
}
