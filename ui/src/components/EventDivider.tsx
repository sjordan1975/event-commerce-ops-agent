import type { EventMeta } from '@/lib/types'
import { outcomeLabel } from '@/lib/utils'

interface Props {
  meta: EventMeta
  index: number
}

export function EventDivider({ meta, index }: Props) {
  const { label, cls } = outcomeLabel(meta.outcome_type)
  return (
    <div className="flex items-center gap-4 py-5 select-none">
      <div className="flex-1 h-px bg-border" />
      <div className="flex items-center gap-2 shrink-0">
        <span className="font-mono text-[10px] tracking-widest text-text-secondary uppercase">
          Event {index + 1}
        </span>
        <span className="text-border-bright">·</span>
        <span className="font-sans text-xs font-semibold text-text-primary">
          {meta.name}
        </span>
        <span className="text-border-bright">·</span>
        <span className={`font-mono text-[9px] tracking-widest uppercase border rounded px-1.5 py-0.5 ${cls}`}>
          {label}
        </span>
      </div>
      <div className="flex-1 h-px bg-border" />
    </div>
  )
}
