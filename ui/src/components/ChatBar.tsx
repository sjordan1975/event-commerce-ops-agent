'use client'

import { useEffect, useRef, useState } from 'react'
import { Send } from 'lucide-react'
import type { ChatMessage, PipelinePhase } from '@/lib/types'

interface Props {
  messages: ChatMessage[]
  phase: PipelinePhase
  onSend: (text: string) => void
}

export function ChatBar({ messages, phase, onSend }: Props) {
  const [draft, setDraft] = useState('')
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  const canSend = phase === 'idle' || phase === 'complete' || phase === 'error'

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages.length])

  function autoResize() {
    const el = inputRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${el.scrollHeight}px`
  }

  function handleSend() {
    const text = draft.trim()
    if (!text || !canSend) return
    setDraft('')
    onSend(text)
    // Reset height after clearing
    if (inputRef.current) inputRef.current.style.height = 'auto'
    inputRef.current?.focus()
  }

  function handleKey(e: React.KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="h-64 border-t border-border flex flex-col bg-bg shrink-0">
      {/* Conversation history */}
      <div className="flex-1 overflow-y-auto px-6 py-3 flex flex-col gap-2.5">
        {messages.length === 0 && (
          <div className="flex-1 flex items-end pb-1">
            <span className="font-mono text-[10px] text-text-muted">
              Start by describing an event above
            </span>
          </div>
        )}
        {messages.map((msg) => (
          <div
            key={msg.id}
            className={`flex gap-2.5 animate-fade-in ${
              msg.role === 'operator' ? 'flex-row-reverse' : 'flex-row'
            }`}
          >
            <span
              className={`font-mono text-[9px] tracking-widest uppercase shrink-0 mt-1 select-none ${
                msg.role === 'operator' ? 'text-accent' : 'text-text-muted'
              }`}
            >
              {msg.role === 'operator' ? 'you' : 'agent'}
            </span>
            <div
              className={`max-w-[82%] rounded-lg px-3 py-2 ${
                msg.role === 'operator'
                  ? 'bg-accent-dim border border-accent/20 text-text-primary'
                  : 'bg-surface-2 border border-border text-text-secondary'
              }`}
            >
              <p className="text-xs leading-relaxed whitespace-pre-wrap">{msg.text}</p>
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="px-6 pb-4 shrink-0">
        <div
          className={`flex items-end gap-3 rounded-lg border px-4 py-2.5 transition-all ${
            canSend
              ? 'border-border-bright bg-surface-2 focus-within:border-accent/40 focus-within:shadow-[0_0_0_1px_rgba(204,255,71,0.06)]'
              : 'border-border bg-surface opacity-60 cursor-not-allowed'
          }`}
        >
          <textarea
            ref={inputRef}
            value={draft}
            rows={1}
            onChange={(e) => { setDraft(e.target.value); autoResize() }}
            onKeyDown={handleKey}
            disabled={!canSend}
            placeholder={
              canSend
                ? 'Describe an event — Shift+Enter for new line, Enter to send'
                : 'Pipeline running — waiting for completion...'
            }
            className="flex-1 bg-transparent text-sm text-text-primary placeholder-text-secondary outline-none font-sans disabled:cursor-not-allowed resize-none overflow-hidden min-h-[2rem] max-h-40 leading-relaxed py-0.5"
          />
          <button
            onClick={handleSend}
            disabled={!canSend || !draft.trim()}
            className={`flex items-center gap-1.5 font-mono text-[10px] tracking-wider uppercase transition-all ${
              canSend && draft.trim()
                ? 'text-accent hover:text-accent/70'
                : 'text-text-muted cursor-not-allowed'
            }`}
          >
            <Send size={11} />
            Send
          </button>
        </div>
      </div>
    </div>
  )
}
