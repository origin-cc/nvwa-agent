// 前端事件总线（§4.1.5）：SSE 事件分发 + 插件间受控通信
// 插件通过 window.nvwa.events 访问；禁止直接互相访问组件实例与状态（§4.6）
const listeners = new Map() // eventType -> Set<handler>

export const eventBus = {
  on(eventType, handler) {
    if (!listeners.has(eventType)) listeners.set(eventType, new Set())
    listeners.get(eventType).add(handler)
    return () => eventBus.off(eventType, handler)
  },
  off(eventType, handler) {
    const set = listeners.get(eventType)
    if (set) set.delete(handler)
  },
  emit(eventType, payload) {
    const set = listeners.get(eventType)
    if (set) [...set].forEach((h) => {
      try {
        h(payload)
      } catch (err) {
        console.error(`[nvwa:eventBus] 事件处理器异常 ${eventType}`, err)
      }
    })
  },
  // 注销某插件全部订阅（插件卸载联动，§4.5 步骤5）
  offAll(ownerTag) {
    listeners.forEach((set) => {
      set.forEach((h) => {
        if (h.__nvwa_owner === ownerTag) set.delete(h)
      })
    })
  },
}

export function ownedHandler(ownerTag, handler) {
  handler.__nvwa_owner = ownerTag
  return handler
}
