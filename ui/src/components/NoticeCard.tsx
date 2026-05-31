import {
  Database,
  Eye,
  Layers,
  PenLine,
  Search,
  Sparkles,
  Upload,
  Bell,
  Zap,
} from 'lucide-react'
import type { Notice } from '@/lib/types'
import { CAPABILITY_COLORS } from '@/lib/utils'

const ICONS: Record<string, React.ReactNode> = {
  ingest_event_batch:        <Upload size={10} />,
  build_event_context:       <Sparkles size={10} />,
  find_similar_assets:       <Search size={10} />,
  score_assets_with_vision:  <Eye size={10} />,
  propose_review_queue:      <Layers size={10} />,
  draft_campaigns_for_queue: <PenLine size={10} />,
  request_human_approval:    <Bell size={10} />,
  execute_approved_campaigns:<Zap size={10} />,
  record_outcomes:           <Database size={10} />,
}

interface Props {
  notice: Notice
  isNew?: boolean
}

export function NoticeCard({ notice, isNew }: Props) {
  const borderColor = CAPABILITY_COLORS[notice.capability] ?? 'border-l-border-bright'
  const icon = ICONS[notice.capability]

  return (
    <div
      className={`
        border-l-2 ${borderColor} bg-surface-2 rounded-r-md px-3 py-2
        flex items-start gap-2.5
        ${isNew ? 'animate-slide-up' : ''}
      `}
    >
      <span className="mt-px text-text-secondary shrink-0">{icon}</span>
      <span className="font-mono text-[10px] text-text-secondary leading-relaxed flex-1 min-w-0 break-words">
        {notice.text}
      </span>
    </div>
  )
}
