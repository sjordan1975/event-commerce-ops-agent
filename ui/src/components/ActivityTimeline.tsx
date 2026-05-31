'use client'

import {
  CheckCircle,
  Circle,
  Loader2,
  XCircle,
} from 'lucide-react'
import type { CapabilityStep, EventSession } from '@/lib/types'
import { CAPABILITY_LABELS } from '@/lib/utils'
import { EventDivider } from './EventDivider'

function StatusIcon({ status }: { status: CapabilityStep['status'] }) {
  switch (status) {
    case 'complete':
      return <CheckCircle size={13} className="text-status-green shrink-0 mt-px" />
    case 'running':
      return <Loader2 size={13} className="text-accent animate-spin-slow shrink-0 mt-px" />
    case 'failed':
      return <XCircle size={13} className="text-status-red shrink-0 mt-px" />
    default:
      return <Circle size={13} className="text-text-muted shrink-0 mt-px" />
  }
}

function CapabilityRow({ step }: { step: CapabilityStep }) {
  const label = step.label || CAPABILITY_LABELS[step.capability] || step.capability
  const isQueue = step.capability === 'propose_review_queue'

  return (
    <div className="flex gap-3 py-1.5 animate-fade-in">
      <StatusIcon status={step.status} />
      <div className="flex-1 min-w-0">
        <div className="flex items-baseline gap-3 flex-wrap">
          <span
            className={`font-mono text-xs tracking-widest uppercase select-none ${
              step.status === 'complete' ? 'text-text-primary'
              : step.status === 'running' ? 'text-accent'
              : 'text-text-muted'
            }`}
          >
            {label}
          </span>
          {step.resultSummary && (
            <span className="font-mono text-xs text-text-secondary">
              {step.resultSummary}
            </span>
          )}
        </div>
        {/* Strategy excerpt for propose_review_queue */}
        {isQueue && step.strategyExcerpt && (
          <p className="mt-1 text-sm text-text-secondary leading-relaxed font-sans italic border-l-2 border-accent/30 pl-2.5">
            &ldquo;{step.strategyExcerpt}&rdquo;
          </p>
        )}
      </div>
    </div>
  )
}

interface Props {
  sessions: EventSession[]
  activeSteps: CapabilityStep[]
}

export function ActivityTimeline({ sessions, activeSteps }: Props) {
  if (sessions.length === 0 && activeSteps.length === 0) return null

  return (
    <div className="px-6 pt-5 shrink-0">
      {/* Completed sessions */}
      {sessions.map((session, i) => (
        <div key={session.meta.event_id}>
          {i > 0 && <EventDivider meta={session.meta} index={i} />}
          <div className="space-y-0">
            {session.capabilitySteps.map((step) => (
              <CapabilityRow key={step.capability} step={step} />
            ))}
          </div>
        </div>
      ))}

      {/* Divider before active event (if we have prior sessions) */}
      {sessions.length > 0 && activeSteps.length > 0 && (
        <div className="h-px bg-border my-4" />
      )}

      {/* Active steps */}
      {activeSteps.length > 0 && (
        <div className="space-y-0">
          {activeSteps.map((step) => (
            <CapabilityRow key={step.capability} step={step} />
          ))}
        </div>
      )}

      {/* Subtle divider below the timeline */}
      <div className="h-px bg-border mt-4 mb-0" />
    </div>
  )
}
