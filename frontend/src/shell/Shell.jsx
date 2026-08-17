// 基座外壳（唯一常驻布局）：侧边菜单 = 已激活页面插件；内容区 = 动态路由渲染
// 无任何业务逻辑；无已激活页面插件时展示空态
import React, { useEffect, useRef, useState } from 'react'
import { Empty, Layout, Menu, Tag } from 'antd'
import { Link, Navigate, Route, Routes, useLocation } from 'react-router-dom'

import { eventBus } from '../base/eventBus.js'
import { usePluginStore } from '../base/pluginStore.js'
import {
  activeComponentEntries,
  activePageEntries,
  renderPagePlugin,
} from '../base/runtime.jsx'
import { buildSlotMap } from '../base/slots.jsx'

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

export default function Shell() {
  const store = usePluginStore()
  const location = useLocation()
  const pages = activePageEntries(store.feStates)
  const components = activeComponentEntries(store.feStates)
  const markedFault = useRef(new Set())

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

  const menuItems = pages.map((entry) => ({
    key: entry.meta.ui.route_path,
    label: <Link to={entry.meta.ui.route_path}>{entry.meta.name}</Link>,
  }))

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Layout.Sider theme="light" width={208} style={{ borderRight: '1px solid #f0f0f0' }}>
        <div style={{ padding: '18px 16px 8px', fontWeight: 700, fontSize: 18 }}>
          NvwaAgent <span style={{ fontSize: 12, fontWeight: 400 }}>女娲</span>
        </div>
        <div style={{ padding: '0 16px 12px' }}><ConnectionTag /></div>
        <Menu mode="inline" selectedKeys={[location.pathname]} items={menuItems} />
      </Layout.Sider>
      <Layout.Content style={{ padding: 16, overflow: 'auto', height: '100vh' }}>
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
      </Layout.Content>
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
