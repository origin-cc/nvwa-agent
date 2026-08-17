import React, { useEffect, useState } from 'react'
import { BrowserRouter } from 'react-router-dom'
import { Result, Spin } from 'antd'

import { bootRuntime } from './base/runtime.jsx'
import Shell from './shell/Shell.jsx'

// 基座入口：启动插件运行时（拉取插件元数据 + SSE），业务界面全部由UI插件提供
export default function App() {
  const [status, setStatus] = useState('booting') // booting | ready | error
  useEffect(() => {
    bootRuntime()
      .then(() => setStatus('ready'))
      .catch((err) => {
        console.error('[nvwa] 基座启动失败', err)
        setStatus('error')
      })
  }, [])

  if (status === 'booting') {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh' }}>
        <Spin size="large" tip="NvwaAgent 基座启动中…">
          <div style={{ width: 240, height: 80 }} />
        </Spin>
      </div>
    )
  }
  if (status === 'error') {
    return (
      <Result
        status="error"
        title="基座启动失败"
        subTitle="请确认后端服务已启动（默认 http://127.0.0.1:8000），刷新页面重试"
      />
    )
  }
  return (
    <BrowserRouter>
      <Shell />
    </BrowserRouter>
  )
}
