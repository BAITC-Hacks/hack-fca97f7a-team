import { useEffect, useRef } from 'react'
import type { ReactNode } from 'react'
import { AnimatePresence, motion, useDragControls, useReducedMotion } from 'motion/react'
import Icon from './Icon'

export default function Sheet({ open, title, subtitle, onClose, children, className = '' }: { open: boolean, title: string, subtitle?: string, onClose: () => void, children: ReactNode, className?: string }) {
  const ref = useRef<HTMLElement>(null)
  const trigger = useRef<HTMLElement | null>(null)
  const closeRef = useRef(onClose)
  closeRef.current = onClose
  const reduced = useReducedMotion()
  const drag = useDragControls()
  useEffect(() => {
    if (!open) return
    trigger.current = document.activeElement as HTMLElement
    const frame = requestAnimationFrame(() => ref.current?.querySelector<HTMLButtonElement>('button')?.focus())
    function key(event: KeyboardEvent) {
      if (event.key === 'Escape') { event.preventDefault(); closeRef.current(); return }
      if (event.key !== 'Tab') return
      const focusable = Array.from(ref.current?.querySelectorAll<HTMLElement>('button:not(:disabled),a[href],input:not(:disabled),select:not(:disabled),textarea:not(:disabled),summary,[tabindex="0"]') || []).filter(element => element.getClientRects().length > 0)
      if (!focusable.length) return
      const first = focusable[0], last = focusable[focusable.length - 1]
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
    }
    document.addEventListener('keydown', key)
    return () => { cancelAnimationFrame(frame); document.removeEventListener('keydown', key); trigger.current?.focus() }
  }, [open])
  return <AnimatePresence>{open && <div className={`sheet-layer ${className}`}>
    <motion.div className="sheet-scrim" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: .18 }} onClick={onClose} aria-hidden="true" />
    <motion.section ref={ref} className="sheet" role="dialog" aria-modal="true" aria-label={title}
      initial={{ y: reduced ? 0 : '100%', opacity: reduced ? 0 : 1 }} animate={{ y: 0, opacity: 1 }} exit={{ y: reduced ? 0 : '100%', opacity: reduced ? 0 : 1 }}
      transition={{ type: 'spring', stiffness: 330, damping: 37 }} drag={reduced ? false : 'y'} dragListener={false} dragControls={drag} dragConstraints={{ top: 0, bottom: 0 }} dragElastic={{ top: 0, bottom: .65 }}
      onDragEnd={(_, info) => { if (info.offset.y + info.velocity.y * .18 > 130) onClose() }}>
      <div className="sheet-handle" onPointerDown={event => drag.start(event)} aria-hidden="true"><span /></div>
      <header className="sheet-header"><div>{subtitle && <span className="eyebrow">{subtitle}</span>}<h2>{title}</h2></div><button className="icon-button" onClick={onClose} aria-label="Закрыть панель"><Icon name="close" /></button></header>
      <div className="sheet-body">{children}</div>
    </motion.section>
  </div>}</AnimatePresence>
}
