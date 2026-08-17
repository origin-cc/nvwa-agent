// 基座运行时总装（§4）：生命周期管理 + 动态路由 + SSE 联动 + 前后端状态同步
import React from 'react'
import * as ReactDOM from 'react-dom'
import * as antd from 'antd'

import { api } from './api.js'
import { eventBus, ownedHandler } from './eventBus.js'
import { PluginErrorBoundary } from './ErrorBoundary.jsx'
import { dropModule, loadModule } from './loader.js'
import { bumpStore, setMetas } from './pluginStore.js'
import { sseClient } from './sseClient.js'
import { clearState, restoreState, scopedStateHandle } from './stateApi.js'

// UI插件通过 window.React / window.antd 使用基座依赖（手写ES Module产物约定）
function injectGlobals() {
  window.React = React
  window.ReactDOM = ReactDOM
  window.antd = antd
}

const metas = new Map()        // pluginId -> meta（后端元数据）
const modules = new Map()      // pluginId -> ES module
const handles = new Map()      // pluginId -> scoped nvwa 句柄
const routeOwner = new Map()   // routePath -> pluginId（路由冲突检测 §4.4）

function feState(pluginId, state, error) {
  bumpStore((s) => {
    s.feStates[pluginId] = state
    if (error !== undefined) s.errors[pluginId] = error
  })
}

function scopedHandle(meta) {
  const pluginId = meta.plugin_id
  return {
    pluginId,
    api,
    state: scopedStateHandle(pluginId),
    events: {
      on: (type, handler) => eventBus.on(type, ownedHandler(pluginId, handler)),
      emit: (type, payload) => {
        if (!type.startsWith(`${pluginId}:`)) {
          throw new Error(`自定义事件名必须以插件id前缀（${pluginId}:xxx）`)
        }
        eventBus.emit(type, payload)
      },
    },
    reportError: (msg) => api.post(`/api/v1/plugins/${pluginId}/ui-error`, { error_msg: msg }).catch(() => {}),
  }
}

// ---------------- 生命周期（§4.3 前端状态机） ----------------
export async function activatePlugin(pluginId) {
  const meta = metas.get(pluginId)
  if (!meta || !String(meta.type).startsWith('ui_')) return
  if (meta.state === 'fault' || meta.disk_missing) return

  try {
    if (!modules.has(pluginId)) {
      const handle = scopedHandle(meta)
      handles.set(pluginId, handle)
      meta.__nvwaHandle = handle
      const module = await loadModule(meta)
      modules.set(pluginId, module)
      if (module.setup) await module.setup(handle)
    } else if (!meta.__nvwaHandle) {
      // meta 可能因 resync 重建（SSE重连/插件刷新）：确保句柄始终注入当前 meta
      meta.__nvwaHandle = handles.get(pluginId) || scopedHandle(meta)
    }
    if (meta.type === 'ui_page_plugin') {
      const route = meta.ui && meta.ui.route_path
      if (route) {
        const owner = routeOwner.get(route)
        if (owner && owner !== pluginId) {
          feState(pluginId, 'fault', `路由冲突：${route} 已被插件 ${owner} 注册`)
          eventBus.emit('nvwa:plugin-fe-fault', { plugin_id: pluginId })
          return
        }
        routeOwner.set(route, pluginId)
      }
    }
    await restoreState(pluginId)
    feState(pluginId, 'activated', '')
  } catch (err) {
    console.error(`[nvwa:runtime] 插件 ${pluginId} 激活失败`, err)
    feState(pluginId, 'fault', String(err && err.message ? err.message : err))
  }
}

export async function deactivatePlugin(pluginId) {
  const module = modules.get(pluginId)
  if (module && module.onDestroy) {
    try { module.onDestroy() } catch (err) { console.error(err) }
  }
  if (metaOf(pluginId) && metaOf(pluginId).type === 'ui_page_plugin') {
    for (const [route, owner] of routeOwner) {
      if (owner === pluginId) routeOwner.delete(route)
    }
  }
  feState(pluginId, 'deactivated')
}

export async function unloadPlugin(pluginId) {
  await deactivatePlugin(pluginId)
  modules.delete(pluginId)
  handles.delete(pluginId)
  eventBus.offAll(pluginId)     // 注销该插件全部事件订阅
  clearState(pluginId)          // 落盘最终状态并清空内存私有状态
  feState(pluginId, 'unloaded')
}

function metaOf(pluginId) {
  return metas.get(pluginId)
}

// ---------------- SSE 联动（§4.5 / 前后端插件状态同步） ----------------
function bindSseHandlers() {
  eventBus.on('plugin:activated', ({ plugin_id }) => activatePlugin(plugin_id))
  eventBus.on('plugin:deactivated', ({ plugin_id }) => deactivatePlugin(plugin_id))
  eventBus.on('plugin:unloaded', ({ plugin_id }) => unloadPlugin(plugin_id))
  eventBus.on('plugin:error', (payload) => {
    const { plugin_id, error_msg } = payload
    if (metas.has(plugin_id)) {
      bumpStore((s) => { s.errors[plugin_id] = `[${payload.error_code || 'PLUGIN_ERROR'}] ${error_msg}` })
    }
  })
  // SSE重连后全量刷新插件状态（§4.7）
  eventBus.on('nvwa:plugins-refresh', (plugins) => applyPlugins(plugins, { resync: true }))
}

// ---------------- 元数据应用 / 状态同步 ----------------
async function applyPlugins(plugins, { resync = false } = {}) {
  const prev = new Map(metas)
  metas.clear()
  ;(plugins || []).forEach((p) => metas.set(p.plugin_id, p))
  setMetas(plugins || [])

  if (resync) {
    // 重连/扫描后的全量对齐：后端 activated 的UI插件在前端激活；其余卸载
    for (const [id, meta] of metas) {
      if (!String(meta.type).startsWith('ui_')) continue
      if (meta.state === 'activated') {
        await activatePlugin(id)
      } else {
        await unloadPlugin(id).catch(() => {})
      }
    }
    return
  }

  // 首次启动：恢复后端已激活的UI插件
  for (const [id, meta] of metas) {
    if (String(meta.type).startsWith('ui_') && meta.state === 'activated') {
      await activatePlugin(id)
    }
  }
  // 后端已消失（磁盘缺失等）的插件清理前端残留
  for (const id of [...prev.keys()]) {
    if (!metas.has(id) && modules.has(id)) await unloadPlugin(id).catch(() => {})
  }
}

// ---------------- 启动 ----------------
let booted = false

export async function bootRuntime() {
  if (booted) return
  booted = true
  injectGlobals()
  bindSseHandlers()
  const data = await api.get('/api/v1/plugins/list')
  await applyPlugins(data.plugins || [])
  sseClient.start()
}

// 页面插件渲染（含插槽注入）
export function renderPagePlugin(entry, slotMap) {
  const { meta, module } = entry
  return (
    <PluginErrorBoundary pluginId={meta.plugin_id}>
      <module.PageComponent nvwa={meta.__nvwaHandle} slots={slotMap || {}} />
    </PluginErrorBoundary>
  )
}

// 已激活插件条目（供 Shell 渲染）：priority 降序，同优先级按id字典序
function activeEntries(feStates, type) {
  const result = []
  metas.forEach((meta) => {
    if (meta.type !== type) return
    if (feStates[meta.plugin_id] !== 'activated') return
    const module = modules.get(meta.plugin_id)
    if (module) result.push({ meta, module })
  })
  result.sort((a, b) => {
    if (b.meta.priority !== a.meta.priority) return b.meta.priority - a.meta.priority
    return a.meta.plugin_id < b.meta.plugin_id ? -1 : 1
  })
  return result
}

export function activePageEntries(feStates) {
  return activeEntries(feStates, 'ui_page_plugin')
}

export function activeComponentEntries(feStates) {
  return activeEntries(feStates, 'ui_component_plugin')
}
