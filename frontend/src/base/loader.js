// 动态组件加载器（§4.1.2）：后端静态资源接口动态 import() + 缓存
// URL 规则：/api/v1/plugins/static/{plugin_id}/{ui.entry相对路径}
const moduleCache = new Map() // pluginId -> { version, module }

// 会话级防缓存：同一页面会话内 URL 稳定（模块不重复执行）；页面刷新后 URL 变化，
// 强制回源拉取最新插件文件（开发期插件文件随时修改，绕过浏览器模块缓存）
const BOOT_ID = Date.now()

function normalizeEntry(entry) {
  return String(entry || '').replace(/^\.\//, '').replace(/^\/+/, '')
}

export function pluginModuleUrl(meta) {
  const entry = normalizeEntry(meta.ui && meta.ui.entry)
  return `/api/v1/plugins/static/${meta.plugin_id}/${entry}?__nvwa=${BOOT_ID}`
}

export async function loadModule(meta) {
  const cached = moduleCache.get(meta.plugin_id)
  if (cached && cached.version === meta.version) return cached.module

  const url = pluginModuleUrl(meta)
  const module = await import(/* @vite-ignore */ url)

  // 导出契约校验（§4.2）
  if (!module.PageComponent && !module.Component) {
    throw new Error(`UI插件 ${meta.plugin_id} 未导出 PageComponent / Component`)
  }
  moduleCache.set(meta.plugin_id, { version: meta.version, module })
  return module
}

export function dropModule(pluginId) {
  moduleCache.delete(pluginId)
}

export function hasModule(pluginId) {
  return moduleCache.has(pluginId)
}
