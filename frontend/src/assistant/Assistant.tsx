import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import type { Explanation, QuestionAnswer } from '../types'
import AssistantText from '../AssistantText'
import { localTime, ru } from '../ru'
import Icon from '../ui/Icon'

export interface AssistantMessage { id: number, question: string, text: string, backend: 'local' | 'llm' | 'template', warning?: string | null, richAnswer?: QuestionAnswer }

function AnswerContent({ answer }: { answer: QuestionAnswer }) {
  return <AssistantText answer={answer}>
    {answer.selection && <p className="answer-selection"><strong>{ru.selectedPeriod}</strong> {localTime(answer.selection.start, 'Asia/Almaty')} — {localTime(answer.selection.end, 'Asia/Almaty')}</p>}
    {answer.tool_results?.filter(result => result.table && result.table.columns.length > 0).map((result, index) => <div className="table-scroll chat-table" key={`${result.tool}-${index}`}>
      <table><caption>{ru.calculationTable}</caption><thead><tr>{result.table!.columns.map((column, i) => <th scope="col" key={i}>{column}</th>)}</tr></thead><tbody>{result.table!.rows.map((row, i) => <tr key={i}>{row.map((cell, j) => <td key={j}>{cell}</td>)}</tr>)}</tbody></table>
    </div>)}
    {answer.model && <small className="explanation-meta">{answer.model}</small>}
  </AssistantText>
}
export type AgentPhase = 'idle' | 'restoring' | 'refreshing' | 'forecast' | 'analyzing' | 'answering' | 'ready' | 'warning'
const phaseLabels: Record<AgentPhase, string> = { idle: 'Готов исследовать', restoring: 'Открываем сохранённый прогноз', refreshing: 'Обновляем погоду', forecast: 'Запрос погоды и прогноз ML', analyzing: 'Готовим объяснение', answering: 'Ответ по прогнозу', ready: 'Прогноз готов', warning: 'Нужно внимание' }

export function Samal({ phase, small = false }: { phase: AgentPhase, small?: boolean }) {
  const reduced = useReducedMotion()
  const busy = ['forecast', 'restoring', 'refreshing', 'analyzing', 'answering'].includes(phase)
  return <motion.span className={`samal-entity ${small ? 'samal-small' : ''} phase-${phase}`} aria-hidden="true" initial={false}
    animate={{ y: reduced || small ? 0 : [0, -1.8, 0] }} transition={reduced || small ? { duration: 0 } : { duration: 10, ease: 'easeInOut', repeat: Infinity }}>
    <motion.span className="samal-core" initial={false} animate={{ opacity: reduced ? .95 : [.8, 1, .8] }} transition={reduced ? { duration: 0 } : { duration: 9, ease: 'easeInOut', repeat: Infinity }} />
    <motion.svg viewBox="0 0 100 100" initial={{ rotate: 0 }} animate={{ rotate: reduced ? 0 : 360 }} transition={reduced ? { duration: 0 } : { duration: busy ? 3.5 : 42, ease: 'linear', repeat: Infinity }}><defs><linearGradient id={small ? 'samal-small-gradient' : 'samal-gradient'}><stop stopColor="#eee2c6" /><stop offset="1" stopColor="#8cbaa9" stopOpacity=".25" /></linearGradient></defs>{[0, 120, 240].map(degrees => <path key={degrees} d="M50 48 C24 39 26 15 42 11 C49 9 57 17 52 27 C47 36 46 40 50 48Z" transform={`rotate(${degrees} 50 50)`} fill={`url(#${small ? 'samal-small-gradient' : 'samal-gradient'})`} stroke="#e7e3d4" strokeOpacity=".22" strokeWidth=".6" />)}</motion.svg><span className="samal-eyes"><i /><i /></span>
  </motion.span>
}

export default function Assistant({ open, onOpenChange, phase, context, explanation, explanationError, messages, draft, onDraftChange, pending, error, onCommand, hasForecast, summaryDeferred, onLoadExplanation }: { open: boolean, onOpenChange: (open: boolean) => void, phase: AgentPhase, context: string, explanation: Explanation | null, explanationError: string, messages: AssistantMessage[], draft: string, onDraftChange: (draft: string) => void, pending: string, error: string, onCommand: (text: string) => void, hasForecast: boolean, summaryDeferred: boolean, onLoadExplanation?: () => void }) {
  const [mobile, setMobile] = useState(() => window.matchMedia('(max-width: 600px)').matches)
  const panel = useRef<HTMLElement>(null)
  const input = useRef<HTMLTextAreaElement>(null)
  const launcher = useRef<HTMLButtonElement>(null)
  const scroll = useRef<HTMLDivElement>(null)
  const reduced = useReducedMotion()
  const busy = ['forecast', 'restoring', 'refreshing', 'answering'].includes(phase)
  const closeRef = useRef(onOpenChange)
  closeRef.current = onOpenChange
  useEffect(() => {
    const media = window.matchMedia('(max-width: 600px)')
    const update = () => setMobile(media.matches)
    media.addEventListener('change', update)
    return () => media.removeEventListener('change', update)
  }, [])
  useEffect(() => {
    if (!open) return
    const frame = requestAnimationFrame(() => input.current?.focus())
    function key(event: KeyboardEvent) {
      if (event.key === 'Escape') { event.preventDefault(); closeRef.current(false) }
      if (event.key !== 'Tab' || !mobile) return
      const elements = Array.from(panel.current?.querySelectorAll<HTMLElement>('button:not(:disabled),textarea:not(:disabled),a[href],summary') || [])
      const first = elements[0], last = elements.at(-1)
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
    }
    document.addEventListener('keydown', key)
    return () => { cancelAnimationFrame(frame); document.removeEventListener('keydown', key); launcher.current?.focus() }
  }, [open, mobile])
  useEffect(() => { if (scroll.current) scroll.current.scrollTop = scroll.current.scrollHeight }, [messages, pending, explanation, open])
  const submit = (text: string) => { if (!text.trim()) return; onCommand(text.trim()); onDraftChange('') }
  const suggestions = hasForecast ? ['Почему снизилось здесь?', 'Покажи минимум завтра', 'Покажи самое сильное падение'] : ['Покажи турбину 1', 'Покажи турбину 2 завтра', 'Что доступно в прогнозе?']
  return <div className={`assistant-root ${open ? 'assistant-open' : ''}`}>
    <AnimatePresence>{open && <>
      <motion.div className="assistant-scrim" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => onOpenChange(false)} aria-hidden="true" />
      <motion.section ref={panel} id="samal-panel" className="assistant-panel" role="dialog" aria-modal={mobile ? true : undefined} aria-label="Samal — помощник по прогнозу"
        initial={{ opacity: 0, scale: reduced ? 1 : .82, y: reduced ? 0 : 30 }} animate={{ opacity: 1, scale: 1, y: 0 }} exit={{ opacity: 0, scale: reduced ? 1 : .82, y: reduced ? 0 : 30 }} transition={{ type: 'spring', stiffness: 350, damping: 36 }}>
        <header className="assistant-header"><Samal phase={phase} small /><div><h2>Samal</h2><span role="status">{phaseLabels[phase]}</span></div><button className="icon-button" onClick={() => onOpenChange(false)} aria-label="Свернуть Samal"><Icon name="close" /></button></header>
        <div className="assistant-context"><span className="status-dot" />{context}</div>
        <div className="assistant-conversation" ref={scroll} role="log" aria-live="polite" aria-relevant="additions text">
          <div className="assistant-intro"><span className="eyebrow">Ветер становится понятнее</span><p>{hasForecast ? 'Выберите момент. Я помогу увидеть, что меняется.' : 'От Земли до одного часа прогноза. Выберите турбину или попросите меня показать её.'}</p></div>
          {explanation && <details className="assistant-summary"><summary>Объяснение прогноза <Icon name="chevron" size={14} /></summary><AssistantText answer={explanation} />{explanation.model && <small className="explanation-meta">{explanation.model}</small>}</details>}
          {!explanation && summaryDeferred && <p className="assistant-warning">Открыт сохранённый прогноз. Объяснение загружается только по вашему запросу.</p>}
          {onLoadExplanation && <button className="secondary-button assistant-load-summary" onClick={onLoadExplanation}>{explanationError ? 'Повторить объяснение' : 'Получить объяснение'}<Icon name="arrow" size={15} /></button>}
          {explanationError && <p className="assistant-warning">{explanationError} Числовой прогноз сохранён.</p>}
          {messages.map(message => <div className="assistant-exchange" key={message.id}><p className="assistant-question">{message.question}</p><div className="assistant-answer">{message.richAnswer ? <AnswerContent answer={message.richAnswer} /> : <><span>{message.backend === 'local' ? 'Локальное действие · данные прогноза' : message.backend === 'llm' ? 'Объяснение ИИ' : 'Расчётный ответ — ИИ недоступен'}</span><p>{message.text}</p>{message.warning && <small>{message.warning}</small>}</>}</div></div>)}
          {pending && <div className="assistant-exchange"><p className="assistant-question">{pending}</p><p className="assistant-pending" role="status"><span />{phaseLabels[phase]}</p></div>}
          {error && <div className="error-banner" role="alert">{error}</div>}
        </div>
        <div className="assistant-suggestions" aria-label="Примеры команд">{suggestions.map(text => <button key={text} disabled={busy} onClick={() => submit(text)}>{text}<Icon name="arrow" size={13} /></button>)}</div>
        <form className="assistant-form" onSubmit={event => { event.preventDefault(); submit(draft) }}><label className="visually-hidden" htmlFor="samal-question">Вопрос или команда Samal</label><textarea ref={input} id="samal-question" rows={1} placeholder="Спросите о ветре…" value={draft} maxLength={500} onChange={event => onDraftChange(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); if (!busy) submit(draft) } }} /><button type="submit" disabled={!draft.trim() || busy} aria-label="Отправить вопрос"><Icon name="arrow" size={19} /></button></form>
        <p className="assistant-footnote">Навигация — локальные команды. Числа — модель ML.</p>
      </motion.section>
    </>}</AnimatePresence>
    <motion.button ref={launcher} className="samal-launcher" whileTap={reduced ? undefined : { scale: .97 }} transition={{ type: 'spring', stiffness: 400, damping: 40 }} onClick={() => onOpenChange(!open)} aria-expanded={open} aria-controls="samal-panel" aria-label={open ? 'Свернуть чат с Samal' : 'Открыть чат с Samal — спросить о прогнозе'} tabIndex={open ? -1 : 0}><Samal phase={phase} /><span className="samal-launcher-copy"><span><Icon name="chat" size={15} />Чат с Samal</span><small>{phase === 'idle' || phase === 'ready' ? 'Спросить о прогнозе' : phaseLabels[phase]}</small></span></motion.button>
  </div>
}
