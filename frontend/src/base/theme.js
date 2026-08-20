// 轻量主题 store：'light' | 'dark'，localStorage(nvwa-theme) 优先，否则跟随系统 prefers-color-scheme
const STORAGE_KEY = 'nvwa-theme'

let current = null
const listeners = new Set()

function normalize(mode) {
  return mode === 'dark' ? 'dark' : 'light'
}

function readStored() {
  try {
    const v = localStorage.getItem(STORAGE_KEY)
    if (v === 'dark' || v === 'light') return v
  } catch (e) {
    // localStorage 不可用时忽略
  }
  return null
}

function systemPrefersDark() {
  try {
    return window.matchMedia('(prefers-color-scheme: dark)').matches
  } catch (e) {
    return false
  }
}

function resolve() {
  return readStored() || (systemPrefersDark() ? 'dark' : 'light')
}

function applyTheme(mode) {
  const next = normalize(mode)
  current = next
  document.documentElement.setAttribute('data-theme', next)
  document.documentElement.style.colorScheme = next
  listeners.forEach((fn) => {
    try { fn(next) } catch (e) { /* 订阅者异常不影响其它订阅者 */ }
  })
  return next
}

export function getTheme() {
  if (!current) current = resolve()
  return current
}

// 用户主动切换：同步 DOM + 持久化
export function setTheme(mode) {
  const next = applyTheme(mode)
  try { localStorage.setItem(STORAGE_KEY, next) } catch (e) { /* ignore */ }
  return next
}

export function subscribe(fn) {
  listeners.add(fn)
  return () => listeners.delete(fn)
}

// 启动初始化：无持久化值时跟随系统，仅应用不落盘（保留后续跟随系统的能力）
export function initTheme() {
  return applyTheme(resolve())
}
