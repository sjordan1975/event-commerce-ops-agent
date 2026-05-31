interface Props {
  label: string
  value: number
  max?: number
}

export function ScoreBar({ label, value, max = 5 }: Props) {
  const pct = Math.min(100, (value / max) * 100)
  return (
    <div className="flex items-center gap-3 group">
      <span className="w-14 font-mono text-[9px] tracking-[0.15em] uppercase text-text-secondary shrink-0 select-none">
        {label}
      </span>
      <div className="flex-1 h-[2px] bg-border rounded-full overflow-hidden">
        <div
          className="h-full bg-accent rounded-full transition-all duration-700 ease-out"
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="w-6 font-mono text-[10px] text-text-secondary text-right shrink-0 tabular-nums">
        {value.toFixed(1)}
      </span>
    </div>
  )
}
