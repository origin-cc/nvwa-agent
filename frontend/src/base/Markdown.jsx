// Markdown 渲染基础设施：GFM + 代码高亮（github-dark）+ 代码块复制
import React, { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeHighlight from 'rehype-highlight'
import 'highlight.js/styles/github-dark.css'

function extractText(node) {
  if (node == null) return ''
  if (typeof node === 'string' || typeof node === 'number') return String(node)
  if (Array.isArray(node)) return node.map(extractText).join('')
  if (node.props && node.props.children != null) return extractText(node.props.children)
  return ''
}

function CodeBlock({ language, code, children }) {
  const [copied, setCopied] = useState(false)
  const onCopy = () => {
    navigator.clipboard
      .writeText(code)
      .then(() => {
        setCopied(true)
        setTimeout(() => setCopied(false), 1500)
      })
      .catch(() => {})
  }
  const headStyle = {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: '6px 12px',
    background: '#161b22',
    color: '#8b949e',
    fontSize: 12,
  }
  const buttonStyle = {
    border: 'none',
    background: 'transparent',
    color: '#8b949e',
    cursor: 'pointer',
    fontSize: 12,
    padding: 0,
  }
  return (
    <div style={{ margin: '12px 0', borderRadius: 8, overflow: 'hidden', border: '1px solid #30363d' }}>
      <div style={headStyle}>
        <span>{language || 'text'}</span>
        <button type="button" style={buttonStyle} onClick={onCopy}>
          {copied ? '已复制' : '复制'}
        </button>
      </div>
      <pre style={{ margin: 0, padding: '12px 16px', overflow: 'auto', background: '#0d1117' }}>
        <code className={`hljs language-${language || 'plaintext'}`}>{children}</code>
      </pre>
    </div>
  )
}

export default function Markdown({ children }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      rehypePlugins={[rehypeHighlight]}
      components={{
        // 代码块外层 pre 仅透传，避免与我们自定义的深色容器嵌套
        pre: (props) => <>{props.children}</>,
        code: ({ className, children }) => {
          const match = /language-(\w+)/.exec(className || '')
          // 行内代码（无 language- 前缀）
          if (!match) {
            return (
              <code
                className={className}
                style={{
                  padding: '0.2em 0.4em',
                  background: 'rgba(175,184,193,0.2)',
                  borderRadius: 6,
                  fontSize: '0.9em',
                }}
              >
                {children}
              </code>
            )
          }
          // 块级代码（含 language-xxx，children 保留 rehype-highlight 的 hljs 高亮）
          return (
            <CodeBlock language={match[1]} code={extractText(children)}>
              {children}
            </CodeBlock>
          )
        },
      }}
    >
      {children}
    </ReactMarkdown>
  )
}
