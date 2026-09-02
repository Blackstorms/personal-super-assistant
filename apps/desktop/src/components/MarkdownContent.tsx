/**
 * 助手回复 Markdown 渲染（GFM：表格、代码块、任务列表等）。
 */
import type { Components } from 'react-markdown'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

type Props = {
  content: string
  streaming?: boolean
}

const components: Components = {
  a: ({ href, children }) => (
    <a href={href} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  ),
  pre: ({ children }) => <pre className="md-pre">{children}</pre>,
  code: ({ className, children, ...props }) => {
    // 无 language 的围栏代码块也会进 pre；勿当成行内 code（否则深色 pre 里浅底/继承色会「白条看不见字」）
    const text = String(children)
    const isBlock = Boolean(className?.startsWith('language-')) || text.includes('\n')
    if (isBlock) {
      return (
        <code className={className ? `md-code-block ${className}` : 'md-code-block'} {...props}>
          {children}
        </code>
      )
    }
    return (
      <code className="md-inline-code" {...props}>
        {children}
      </code>
    )
  },
  table: ({ children }) => (
    <div className="md-table-wrap">
      <table className="md-table">{children}</table>
    </div>
  ),
}

export default function MarkdownContent({ content, streaming = false }: Props) {
  if (!content && streaming) {
    return <span className="md-cursor">…</span>
  }

  return (
    <div className="markdown-body">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {content}
      </ReactMarkdown>
      {streaming && content ? <span className="md-cursor">▍</span> : null}
    </div>
  )
}
