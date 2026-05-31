import type { EventMeta, PipelinePhase } from '@/lib/types'
import { outcomeLabel } from '@/lib/utils'

const PHASE_LABELS: Partial<Record<PipelinePhase, string>> = {
  idle:               'ready',
  running:            'running pipeline',
  awaiting_approval:  'awaiting review',
  redrafting:         'redrafting',
  executing:          'dispatching',
  complete:           'complete',
}

interface Props {
  phase: PipelinePhase
  activeEventMeta: EventMeta | null
  sessionCount: number
}

export function EventHeader({ phase, activeEventMeta, sessionCount }: Props) {
  const eventMeta = activeEventMeta
  const phaseLabel = PHASE_LABELS[phase] ?? phase
  const isActive = phase !== 'idle'

  return (
    <header className="py-3 border-b border-border flex items-center px-6 shrink-0 gap-3">
      {/* Wordmark */}
      <span className="font-mono text-[11px] tracking-[0.25em] text-accent uppercase select-none">
        Fieldhouse
      </span>

      <span className="text-border-bright select-none">·</span>

      {/* Event badge or idle state */}
      {eventMeta ? (
        <>
          <span className="font-sans text-xs font-semibold text-text-primary leading-normal">
            {eventMeta.name}
          </span>
          {eventMeta.final_score && (
            <>
              <span className="text-border-bright">·</span>
              <span className="font-mono text-[10px] text-text-secondary">
                {eventMeta.final_score}
              </span>
            </>
          )}
          {(() => {
            const { label, cls } = outcomeLabel(eventMeta.outcome_type)
            return (
              <span className={`font-mono text-[9px] tracking-[0.15em] uppercase border rounded px-1.5 py-0.5 ${cls}`}>
                {label}
              </span>
            )
          })()}
        </>
      ) : sessionCount > 0 ? (
        <span className="font-mono text-xs text-text-secondary">
          {sessionCount} event{sessionCount > 1 ? 's' : ''} complete
        </span>
      ) : (
        <span className="font-mono text-xs text-text-secondary">
          no active event
        </span>
      )}

      {/* Spacer */}
      <div className="flex-1" />

      {/* Phase indicator */}
      <div className="flex items-center gap-2">
        {isActive && (
          <span
            className="w-1.5 h-1.5 rounded-full shrink-0"
            style={{
              backgroundColor:
                phase === 'awaiting_approval' ? '#F59E0B'
                : phase === 'complete'         ? '#1DB954'
                : '#CCFF47',
              animation: phase === 'complete' ? 'none' : 'pulseDot 1.4s ease-in-out infinite',
            }}
          />
        )}
        <span className="font-mono text-[10px] tracking-widest uppercase text-text-secondary select-none">
          {phaseLabel}
        </span>
      </div>
    </header>
  )
}
