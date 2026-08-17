// Slot 插槽管理器（§4.8）：target_slot 匹配 + priority 排序 + 联动卸载
import React from 'react'
import { PluginErrorBoundary } from './ErrorBoundary.jsx'

// 组件插件排序：priority 降序，相同 priority 按插件id字典序（§4.8.3）
export function sortComponents(components) {
  return [...components].sort((a, b) => {
    if (b.priority !== a.priority) return b.priority - a.priority
    return a.plugin_id < b.plugin_id ? -1 : 1
  })
}

// 构建页面插件的插槽元素表：{slotId: ReactNode[]}
// activatedPage: 页面插件meta；componentPlugins: 已激活组件插件[{meta, module}]
// 返回 { slotMap, invalidPlugins }（target_slot 不存在的组件插件标记fault）
export function buildSlotMap(activatedPage, componentPlugins) {
  const slotMap = {}
  const declared = (activatedPage.ui && activatedPage.ui.slots) || []
  declared.forEach((slotId) => { slotMap[slotId] = [] })

  const invalid = []
  sortComponents(componentPlugins).forEach(({ meta, module }) => {
    const target = meta.ui && meta.ui.target_slot
    if (!declared.includes(target)) {
      invalid.push(meta.plugin_id) // 目标插槽不存在：组件插件fault（§4.8.3）
      return
    }
    slotMap[target].push(
      <PluginErrorBoundary key={meta.plugin_id} pluginId={meta.plugin_id}>
        <module.Component nvwa={meta.__nvwaHandle} />
      </PluginErrorBoundary>,
    )
  })
  return { slotMap, invalidPlugins: invalid }
}
