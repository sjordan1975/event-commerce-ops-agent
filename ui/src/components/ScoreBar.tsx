interface Props {
  label: string
  value: number
  max?: number
}

export function ScoreBar({ label, value, max = 5 }: Props) {
  const pct = Math.min(100, (value / max) * 100)
  return (
    <div className="flex items-center gap-3 group">
      <span className="w-16 font-mono text-xs tracking-[0.1em] uppercase text-text-secondary shrink-0 select-none">
        {label}
      </span>
      <div className="flex-1 h-[3px] bg-border rounded-full overflow-hidden">
        <div
          className="h-full bg-accent rounded-full transition-all duration-700 ease-out"
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="w-7 font-mono text-xs text-text-secondary text-right shrink-0 tabular-nums">
        {value.toFixed(1)}
      </span>
    </div>
  )
}
