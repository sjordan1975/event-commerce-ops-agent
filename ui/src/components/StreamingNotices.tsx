'use client'

import { useEffect, useRef } from 'react'
import type { Notice } from '@/lib/types'
import { NoticeCard } from './NoticeCard'

interface Props {
  notices: Notice[]
}

export function StreamingNotices({ notices }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null)
  const prevLen = useRef(0)

  useEffect(() => {
    if (notices.length > prevLen.current) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
      prevLen.current = notices.length
    }
  }, [notices.length])

  return (
    <aside className="w-72 border-r border-border bg-surface flex flex-col overflow-hidden shrink-0">
      {/* Column header */}
      <div className="px-4 pt-4 pb-3 border-b border-border shrink-0">
        <span className="font-mono text-[9px] tracking-[0.25em] uppercase text-text-secondary select-none">
          Live Agent Feed
        </span>
      </div>

      {/* Feed */}
      <div
        className="flex-1 overflow-y-auto px-3 py-3 flex flex-col gap-2 relative"
        style={{
          maskImage: 'linear-gradient(to bottom, transparent, black 18%)',
          WebkitMaskImage: 'linear-gradient(to bottom, transparent, black 18%)',
        }}
      >
        {notices.length === 0 ? (
          <div className="flex-1 flex items-center justify-center">
            <span className="font-mono text-[10px] text-text-muted text-center leading-relaxed">
              Agent events will appear here<br />once the pipeline starts
            </span>
          </div>
        ) : (
          notices.map((n, i) => (
            <NoticeCard
              key={n.id}
              notice={n}
              isNew={i >= notices.length - 1}
            />
          ))
        )}
        <div ref={bottomRef} />
      </div>
    </aside>
  )
}
