// 插件元数据管理器 + 前端可订阅store（§4.1.1）
// 数据源：GET /plugins/list（后端拉取，不在前端扫描本地插件）
import { useSyncExternalStore } from 'react'

let snapshot = { pagePlugins: [], componentPlugins: [], backendPlugins: [], feStates: {}, errors: {}, version: 0 }
let listeners = new Set()

export function getSnapshot() {
  return snapshot
}

export function subscribe(listener) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function bumpStore(mutator) {
  const next = { ...snapshot, feStates: { ...snapshot.feStates }, errors: { ...snapshot.errors } }
  mutator(next)
  next.version = snapshot.version + 1
  snapshot = next
  listeners.forEach((l) => l())
}

export function setMetas(plugins) {
  const pages = plugins.filter((p) => p.type === 'ui_page_plugin')
  const comps = plugins.filter((p) => p.type === 'ui_component_plugin')
  const backends = plugins.filter((p) => p.type === 'backend_agent' || p.type === 'backend_tool')
  bumpStore((s) => {
    s.pagePlugins = pages
    s.componentPlugins = comps
    s.backendPlugins = backends
  })
}

export function usePluginStore() {
  return useSyncExternalStore(subscribe, getSnapshot)
}
