// 错误边界容器（§4.1.6）：每个UI插件外层独立包裹，渲染异常展示占位UI
// 捕获后自动向后端上报 POST /plugins/{id}/ui-error（§9.10 / §11 场景5）
import React from 'react'
import { Alert, Button } from 'antd'
import { api } from './api.js'

export class PluginErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    const { pluginId } = this.props
    console.error(`[nvwa:ErrorBoundary] 插件 ${pluginId} 渲染异常`, error)
    api.post(`/api/v1/plugins/${pluginId}/ui-error`, {
      error_msg: String(error && error.message ? error.message : error),
      stack: (info && info.componentStack ? String(info.componentStack).slice(0, 2000) : null),
    }).catch(() => {})
    if (window.nvwa && window.nvwa.events) {
      window.nvwa.events.emit('nvwa:plugin-render-error', { plugin_id: pluginId })
    }
  }

  render() {
    if (this.state.error) {
      return (
        <Alert
          type="error"
          showIcon
          message={`插件「${this.props.pluginId}」渲染异常`}
          description={String(this.state.error)}
          action={<Button size="small" onClick={() => this.setState({ error: null })}>重试</Button>}
        />
      )
    }
    return this.props.children
  }
}
