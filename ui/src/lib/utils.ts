import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'
import type { Capability } from './types'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function genId(): string {
  return Math.random().toString(36).slice(2, 10)
}

export function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const t = setTimeout(resolve, ms)
    signal?.addEventListener('abort', () => { clearTimeout(t); reject(new DOMException('Aborted', 'AbortError')) })
  })
}

export const CAPABILITY_LABELS: Record<Capability, string> = {
  ingest_event_batch:        'Batch ingested',
  build_event_context:       'Event context built',
  find_similar_assets:       'Historical matches found',
  score_assets_with_vision:  'Assets scored',
  propose_review_queue:      'Review queue assembled',
  draft_campaigns_for_queue: 'Campaign copy drafted',
  request_human_approval:    'Awaiting your review',
  execute_approved_campaigns:'Dispatching to channels',
  record_outcomes:           'Outcomes recorded',
}

export const CAPABILITY_NOTICE_TEXTS: Record<Capability, string> = {
  ingest_event_batch:        'Indexing image batch to Atlas',
  build_event_context:       'Building event narrative + player context',
  find_similar_assets:       'Running vector similarity search',
  score_assets_with_vision:  'Gemini Vision scoring all assets',
  propose_review_queue:      'LLM assembling strategic review queue',
  draft_campaigns_for_queue: 'Generating copy for queued assets',
  request_human_approval:    'Opening approval gate',
  execute_approved_campaigns:'Dispatching to Shopify, social',
  record_outcomes:           'Writing provenance records to Atlas',
}

// Returns Tailwind classes for capability left-border color
export const CAPABILITY_COLORS: Record<Capability, string> = {
  ingest_event_batch:        'border-l-[#0DCCCC]',
  build_event_context:       'border-l-[#9B59B6]',
  find_similar_assets:       'border-l-[#3B82F6]',
  score_assets_with_vision:  'border-l-[#F97316]',
  propose_review_queue:      'border-l-accent',
  draft_campaigns_for_queue: 'border-l-status-amber',
  request_human_approval:    'border-l-status-amber',
  execute_approved_campaigns:'border-l-status-green',
  record_outcomes:           'border-l-border-bright',
}

export function outcomeLabel(type: string): { label: string; cls: string } {
  switch (type) {
    case 'upset_victory':  return { label: 'Upset Victory', cls: 'text-accent border-accent/30 bg-accent/5' }
    case 'expected_win':   return { label: 'Expected Win',  cls: 'text-status-green border-status-green/30 bg-status-green-dim' }
    case 'draw':           return { label: 'Draw',           cls: 'text-text-secondary border-border-bright bg-surface-3' }
    case 'extra_time_win': return { label: 'Extra Time',    cls: 'text-status-amber border-status-amber/30 bg-status-amber-dim' }
    default:               return { label: type,             cls: 'text-text-secondary border-border-bright bg-surface-3' }
  }
}

export function timelinessLabel(score: number): string {
  if (score >= 0.85) return 'Peak window'
  if (score >= 0.60) return 'Good window'
  if (score >= 0.35) return 'Moderate window'
  return 'Late window'
}
