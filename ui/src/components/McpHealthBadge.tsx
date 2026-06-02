'use client'

import { useEffect, useRef, useState } from 'react'
import type { McpHealth } from '@/lib/types'

interface Props {
  health: McpHealth
}

function statusLabel(status: McpHealth['status']): string {
  switch (status) {
    case 'connected':    return 'connected'
    case 'reconnecting': return 'reconnecting'
    case 'unavailable':  return 'unavailable'
  }
}

function dotClass(status: McpHealth['status']): string {
  switch (status) {
    case 'connected':    return 'bg-status-green'
    case 'reconnecting': return 'bg-status-amber animate-pulse-dot'
    case 'unavailable':  return 'bg-status-red'
  }
}

function relativeTime(iso: string | null): string {
  if (!iso) return '—'
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
  if (diff < 5)  return 'just now'
  if (diff < 60) return `${diff}s ago`
  return `${Math.floor(diff / 60)}m ago`
}

function DetailRow({ label, value, dim }: { label: string; value: string; dim?: boolean }) {
  return (
    <div className="flex items-start gap-3">
      <span className="font-mono text-[10px] text-text-muted shrink-0" style={{ width: 148 }}>
        {label}
      </span>
      <span className={`font-mono text-[10px] ${dim ? 'text-text-muted' : 'text-text-secondary'}`}>
        {value}
      </span>
    </div>
  )
}

export function McpHealthBadge({ health }: Props) {
  const [open, setOpen] = useState(false)
  const wrapperRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    function handler(e: MouseEvent) {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  useEffect(() => {
    if (!open) return
    function handler(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false)
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [open])

  return (
    <div ref={wrapperRef} className="relative">
      {/* Detail popover — opens upward */}
      {open && (
        <div
          className="absolute bottom-full left-0 right-0 mb-1 mx-2 rounded-lg border border-border-bright bg-surface-2 p-4 shadow-2xl animate-fade-in"
          style={{ zIndex: 50 }}
        >
          {/* Header */}
          <div className="flex items-center gap-2 mb-3">
            <span className={`w-2 h-2 rounded-full shrink-0 ${dotClass(health.status)}`} />
            <span className="font-mono text-xs text-text-primary">
              MongoDB MCP — {statusLabel(health.status)}
            </span>
          </div>
          <div className="h-px bg-border mb-3" />

          {/* Detail rows */}
          <div className="flex flex-col gap-2">
            <DetailRow label="Tools discovered"     value={health.toolsDiscovered > 0 ? String(health.toolsDiscovered) : '—'} />
            <DetailRow label="Last successful call" value={relativeTime(health.lastSuccessfulCall)} />
            <DetailRow label="Reconnect attempts"  value={String(health.reconnectAttempts)} />
            <DetailRow label="Server version"       value={health.serverVersion} />
            {health.error && (
              <div className="flex items-start gap-3">
                <span className="font-mono text-[10px] text-text-muted shrink-0" style={{ width: 148 }}>Error</span>
                <span className="font-mono text-[10px] text-status-red">{health.error}</span>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Collapsed badge row */}
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 px-4 py-3 hover:bg-surface-2 transition-colors text-left"
        aria-label="MCP connection health"
      >
        <span className={`w-2 h-2 rounded-full shrink-0 ${dotClass(health.status)}`} />
        <span className="font-mono text-xs text-text-secondary">MongoDB MCP</span>
        {health.toolsDiscovered > 0 && (
          <span className="font-mono text-xs text-text-muted ml-auto">
            {health.toolsDiscovered} tools
          </span>
        )}
        {health.status !== 'connected' && health.toolsDiscovered === 0 && (
          <span className="font-mono text-[10px] text-text-muted ml-auto uppercase tracking-wide">
            {statusLabel(health.status)}
          </span>
        )}
      </button>
    </div>
  )
}
