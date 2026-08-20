import React, { useEffect, useState } from 'react'
import ReactDOM from 'react-dom/client'
import * as antd from 'antd'
import zhCN from 'antd/locale/zh_CN'
import App from './App.jsx'
import { getTheme, initTheme, subscribe } from './base/theme.js'
import './index.css'

// 启动时初始化主题（读取 localStorage 或跟随系统，并同步 data-theme 属性）
initTheme()

const lightTheme = {
  algorithm: antd.theme.defaultAlgorithm,
  token: {
    colorPrimary: '#4f7dd9',
    colorInfo: '#4f7dd9',
    colorBgBase: '#e8edf4',
    colorBgContainer: 'rgba(248, 250, 253, 0.62)',
    colorBgElevated: 'rgba(255, 255, 255, 0.88)',
    colorBgLayout: '#e8edf4',
    colorTextBase: '#192230',
    colorText: 'rgba(25, 34, 48, 0.88)',
    colorTextSecondary: 'rgba(25, 34, 48, 0.58)',
    colorTextTertiary: 'rgba(25, 34, 48, 0.45)',
    colorBorder: 'rgba(29, 42, 68, 0.14)',
    colorBorderSecondary: 'rgba(29, 42, 68, 0.10)',
    controlOutline: 'rgba(79, 125, 217, 0.16)',
    boxShadowSecondary: '0 6px 16px rgba(30, 45, 72, 0.12)',
    borderRadius: 8,
  },
}

const darkTheme = {
  algorithm: antd.theme.darkAlgorithm,
  token: {
    colorPrimary: '#6f9be8',
    colorInfo: '#6f9be8',
    colorBgBase: '#0b0d12',
    colorBgContainer: 'rgba(24, 24, 28, 0.72)',
    colorBgElevated: 'rgba(29, 33, 42, 0.92)',
    colorBgLayout: '#000000',
    colorTextBase: '#f2f5f9',
    colorText: 'rgba(242, 245, 249, 0.90)',
    colorTextSecondary: 'rgba(242, 245, 249, 0.58)',
    colorTextTertiary: 'rgba(242, 245, 249, 0.45)',
    colorBorder: 'rgba(255, 255, 255, 0.14)',
    colorBorderSecondary: 'rgba(255, 255, 255, 0.10)',
    controlOutline: 'rgba(111, 155, 232, 0.24)',
    boxShadowSecondary: '0 6px 16px rgba(0, 0, 0, 0.30)',
    borderRadius: 8,
  },
}

function Root() {
  const [theme, setTheme] = useState(getTheme())
  useEffect(() => subscribe(setTheme), [])
  return (
    <antd.ConfigProvider
      locale={zhCN}
      theme={theme === 'dark' ? darkTheme : lightTheme}
    >
      <App />
    </antd.ConfigProvider>
  )
}

ReactDOM.createRoot(document.getElementById('root')).render(<Root />)
