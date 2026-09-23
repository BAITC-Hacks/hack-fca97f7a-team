import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { ReactNode } from 'react'
import type { Explanation } from './types'
import { ru } from './ru'

function safeLink(href: string | undefined): string | null {
  if (!href) return null
  try {
    const url = new URL(href)
    return url.protocol === 'https:' || url.protocol === 'http:' ? url.href : null
  } catch {
    return null
  }
}

export default function AssistantText({ answer, children }: { answer: Explanation, children?: ReactNode }) {
  return <>
    <span className={`answer-badge ${answer.backend === 'llm' ? 'answer-badge-llm' : 'answer-badge-computed'}`}>
      {answer.backend === 'llm' ? ru.aiExplanation : ru.computed}
    </span>
    <div className="assistant-prose">
      <ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml disallowedElements={['img']} components={{
        a: ({ href, children }) => {
          const url = safeLink(href)
          return url ? <a href={url} target="_blank" rel="noopener noreferrer">{children}</a> : <span>{children}</span>
        },
        table: ({ children }) => <div className="table-scroll markdown-table"><table>{children}</table></div>,
      }}>{answer.text}</ReactMarkdown>
    </div>
    {children}
    {answer.notes && answer.notes.length > 0 && <aside className="answer-notes" aria-label={ru.limitations}>
      <strong>{ru.limitations}</strong>
      <ul>{answer.notes.map((note, index) => <li key={`${index}-${note}`}>{note}</li>)}</ul>
    </aside>}
    {answer.warning && <p className="message-warning" role="status">{answer.warning}</p>}
  </>
}
