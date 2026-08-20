// 基座外壳（唯一常驻布局）：侧边菜单 = 已激活页面插件；内容区 = 动态路由渲染
// 侧边栏参考 dsh-web-ui 实现：CSS 变量驱动宽度 + 平滑过渡 + 细轨 + 状态持久化
// 背景板 + 毛玻璃由 index.css 的 --nvwa-* 变量与 .nvwa-glass 承担
import React, { useEffect, useMemo, useRef, useState } from 'react'
import { Button, Dropdown, Empty, Input, Layout, Menu, Modal, Tag, message } from 'antd'
import { Link, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'

import { api } from '../base/api.js'
import { eventBus } from '../base/eventBus.js'
import { getTheme, setTheme, subscribe } from '../base/theme.js'
import { usePluginStore } from '../base/pluginStore.js'
import {
  activeComponentEntries,
  activePageEntries,
  renderPagePlugin,
} from '../base/runtime.jsx'
import { buildSlotMap } from '../base/slots.jsx'

const SIDER_KEY = 'nvwa-sider-collapsed'

function loadSiderCollapsed() {
  try {
    return localStorage.getItem(SIDER_KEY) === '1'
  } catch (e) {
    return false
  }
}

function ConnectionTag() {
  const [connected, setConnected] = useState(false)
  useEffect(() => {
    const off = eventBus.on('nvwa:sse-status', ({ connected }) => setConnected(connected))
    return off
  }, [])
  return connected
    ? <Tag color="green">SSE 已连接</Tag>
    : <Tag color="red">SSE 断连/重连中</Tag>
}

function ConversationNavLabel({ item, onRename, onDelete }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 4, minWidth: 0 }}>
      <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {item.title}
      </span>
      <span style={{ fontSize: 11, color: 'var(--nvwa-text-secondary)' }}>{item.task_count || 0}</span>
      <Dropdown
        trigger={['click']}
        menu={{
          items: [
            { key: 'rename', label: '重命名' },
            { key: 'delete', label: '删除', danger: true },
          ],
          onClick: ({ key, domEvent }) => {
            if (domEvent && domEvent.stopPropagation) domEvent.stopPropagation()
            if (key === 'rename') onRename(item)
            if (key === 'delete') onDelete(item)
          },
        }}
      >
        <Button
          type="text"
          size="small"
          onClick={(event) => event.stopPropagation()}
        >
          ⋯
        </Button>
      </Dropdown>
    </div>
  )
}

export default function Shell() {
  const store = usePluginStore()
  const location = useLocation()
  const navigate = useNavigate()
  const pages = activePageEntries(store.feStates)
  const components = activeComponentEntries(store.feStates)
  const markedFault = useRef(new Set())
  const [theme, setThemeState] = useState(getTheme())
  const [collapsed, setCollapsed] = useState(loadSiderCollapsed)
  const [conversations, setConversations] = useState([])
  const [activeConversationId, setActiveConversationId] = useState(null)
  const [sortMode, setSortMode] = useState('updated')
  const [filterMode, setFilterMode] = useState('all')

  useEffect(() => subscribe(setThemeState), [])

  const chatEntry = pages.find((entry) => entry.meta.plugin_id === 'demo-ui-chat')
  const chatHandle = chatEntry && chatEntry.meta.__nvwaHandle

  const refreshConversations = async () => {
    try {
      const data = await api.get('/api/v1/conversation/list')
      setConversations(data.conversations || [])
    } catch (err) {
      message.error(err.message)
    }
  }

  const saveChatState = (patch) => {
    if (chatHandle) chatHandle.state.save(patch || {})
  }

  const emitConversationSelect = (conversationId) => {
    eventBus.emit('demo-ui-chat:sider-subnav', {
      key: 'select',
      conversation_id: conversationId || null,
    })
  }

  const emitConversationClear = () => {
    eventBus.emit('demo-ui-chat:sider-subnav', { key: 'clear' })
  }

  const switchConversation = (conversationId) => {
    setActiveConversationId(conversationId)
    saveChatState({ conversation_id: conversationId || null })
    if (conversationId) emitConversationSelect(conversationId)
    else emitConversationClear()
  }

  const createConversation = async () => {
    try {
      const data = await api.post('/api/v1/conversation/create')
      await refreshConversations()
      switchConversation(data.conversation_id)
    } catch (err) {
      message.error(err.message)
    }
  }

  const deleteConversation = async (conversationId) => {
    try {
      await api.del(`/api/v1/conversation/${conversationId}`)
      if (activeConversationId === conversationId) {
        setActiveConversationId(null)
        saveChatState({ conversation_id: null })
        emitConversationClear()
      }
      await refreshConversations()
      message.success('会话已删除')
    } catch (err) {
      message.error(err.message)
    }
  }

  const renameConversation = (item) => {
    let inputRef
    const handleOk = async () => {
      const title = (inputRef && inputRef.value || '').trim()
      if (!title) return
      try {
        await api.put(`/api/v1/conversation/${item.conversation_id}`, { title })
        message.success('已重命名')
        await refreshConversations()
      } catch (err) {
        message.error(err.message)
      }
    }
    Modal.confirm({
      title: '重命名会话',
      content: <Input defaultValue={item.title} ref={(r) => { inputRef = r }} />,
      onOk: handleOk,
    })
  }

  const confirmDeleteConversation = (item) => {
    Modal.confirm({
      title: '删除会话',
      content: `确定删除「${item.title}」及其全部任务吗？`,
      okText: '删除',
      okButtonProps: { danger: true },
      onOk: () => deleteConversation(item.conversation_id),
    })
  }

  useEffect(() => {
    refreshConversations()
  }, [])

  useEffect(() => {
    if (!chatHandle) return
    const saved = chatHandle.state.get() || {}
    if (saved.conversation_id) setActiveConversationId(saved.conversation_id)
  }, [chatHandle])

  useEffect(() => {
    const off = eventBus.on('demo-ui-chat:conversation-changed', () => {
      refreshConversations()
    })
    return off
  }, [])

  const toggleSider = () => {
    setCollapsed((prev) => {
      const next = !prev
      try { localStorage.setItem(SIDER_KEY, next ? '1' : '0') } catch (e) { /* ignore */ }
      return next
    })
  }

  // target_slot 指向不存在插槽的组件插件标记 fault（§4.8.3）
  useEffect(() => {
    pages.forEach((entry) => {
      const { invalidPlugins } = buildSlotMap(entry.meta, components)
      invalidPlugins.forEach((id) => {
        if (!markedFault.current.has(id)) {
          markedFault.current.add(id)
          bumpFeFault(id, `目标插槽不存在（所属页面未激活或未声明该slot）`)
        }
      })
    })
  }, [pages, components])

  const visibleConversations = useMemo(() => {
    let list = conversations.slice()
    if (sortMode === 'tasks') {
      list.sort((a, b) =>
        ((b.task_count || 0) - (a.task_count || 0))
        || String(b.updated_at || '').localeCompare(String(a.updated_at || '')),
      )
    } else {
      list.sort((a, b) => String(b.updated_at || '').localeCompare(String(a.updated_at || '')))
    }
    if (filterMode === 'active') list = list.filter((item) => (item.task_count || 0) > 0)
    if (filterMode === 'empty') list = list.filter((item) => !(item.task_count || 0))
    return list
  }, [conversations, sortMode, filterMode])

  const emitSubnav = (pluginId, action) => {
    eventBus.emit(`${pluginId}:sider-subnav`, { key: action })
  }

  const menuItems = pages.map((entry) => {
    const routePath = entry.meta.ui.route_path
    const subnav = Array.isArray(entry.meta.ui && entry.meta.ui.sider_subnav)
      ? entry.meta.ui.sider_subnav
      : []
    const hasConversationList = Boolean(entry.meta.ui && entry.meta.ui.sider_conversation_list)
    if (!subnav.length && !hasConversationList) {
      return {
        key: routePath,
        label: <Link to={routePath}>{entry.meta.name}</Link>,
      }
    }

    const buildSubnavItem = (item) => {
      const itemKey = `${entry.meta.plugin_id}::${item.key}`
      if (Array.isArray(item.children) && item.children.length) {
        return {
          key: itemKey,
          label: item.label,
          children: item.children.map(buildSubnavItem),
        }
      }
      return {
        key: itemKey,
        label: item.label,
        onClick: () => emitSubnav(entry.meta.plugin_id, item.key),
      }
    }

    const children = subnav.map(buildSubnavItem)
    if (hasConversationList) {
      children.push({ type: 'divider' })
      visibleConversations.forEach((conversation) => {
        children.push({
          key: `${entry.meta.plugin_id}::select::${conversation.conversation_id}`,
          label: (
            <ConversationNavLabel
              item={conversation}
              onRename={renameConversation}
              onDelete={confirmDeleteConversation}
            />
          ),
          onClick: () => switchConversation(conversation.conversation_id),
        })
      })
    }

    return {
      key: routePath,
      label: entry.meta.name,
      onTitleClick: () => navigate(routePath),
      children,
    }
  })

  const activeSubnavRoutes = pages
    .filter((entry) =>
      (Array.isArray(entry.meta.ui && entry.meta.ui.sider_subnav) && entry.meta.ui.sider_subnav.length)
      || Boolean(entry.meta.ui && entry.meta.ui.sider_conversation_list),
    )
    .filter((entry) => entry.meta.ui.route_path === location.pathname)
    .map((entry) => entry.meta.ui.route_path)

  const activeConversationMenuKey = activeConversationId && chatEntry
    ? `${chatEntry.meta.plugin_id}::select::${activeConversationId}`
    : null

  return (
    <Layout style={{ minHeight: '100vh', background: 'transparent', display: 'flex', flexDirection: 'row' }}>
      <aside className="nvwa-sider" data-collapsed={collapsed}>
        <div className="nvwa-sider-logo">
          {collapsed ? '娲' : (<><span>NvwaAgent</span> <span className="nvwa-sider-sub">女娲</span></>)}
        </div>
        {!collapsed && (
          <div className="nvwa-sider-row"><ConnectionTag /></div>
        )}
        {!collapsed && (
          <div className="nvwa-sider-row">
            <Button size="small" block onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}>
              {theme === 'dark' ? '浅色' : '深色'}
            </Button>
          </div>
        )}
        <Menu
          key={location.pathname}
          mode="inline"
          inlineCollapsed={collapsed}
          selectedKeys={[location.pathname, activeConversationMenuKey].filter(Boolean)}
          defaultOpenKeys={activeSubnavRoutes}
          items={menuItems}
        />
        <button
          type="button"
          className="nvwa-sider-toggle"
          onClick={toggleSider}
          title={collapsed ? '展开侧边栏' : '收起侧边栏'}
          aria-label={collapsed ? '展开侧边栏' : '收起侧边栏'}
        >
          {collapsed ? '»' : '«'}
        </button>
      </aside>
      <div className="nvwa-content">
        <div className="nvwa-glass">
          {pages.length === 0 ? (
            <Empty style={{ marginTop: 120 }} description="暂无已激活的页面插件（可在插件管理页启用）" />
          ) : (
            <Routes>
              {pages.map((entry) => {
                const { slotMap } = buildSlotMap(entry.meta, components)
                return (
                  <Route
                    key={entry.meta.plugin_id}
                    path={entry.meta.ui.route_path}
                    element={renderPagePlugin(entry, slotMap)}
                  />
                )
              })}
              <Route path="*" element={<Navigate to={pages[0].meta.ui.route_path} replace />} />
            </Routes>
          )}
        </div>
      </div>
    </Layout>
  )
}

function bumpFeFault(pluginId, message) {
  import('../base/pluginStore.js').then(({ bumpStore }) =>
    bumpStore((s) => {
      s.feStates[pluginId] = 'fault'
      s.errors[pluginId] = message
    }),
  )
}
