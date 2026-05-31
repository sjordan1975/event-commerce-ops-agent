'use client'

import { useState } from 'react'
import { CheckCircle, XCircle, Pencil } from 'lucide-react'
import type { ApprovalItem, Decision, PipelinePhase } from '@/lib/types'
import { AssetCard } from './AssetCard'

interface Props {
  approvalId: string
  items: ApprovalItem[]
  phase: PipelinePhase
  isRedraftRound: boolean
  onSubmit: (decisions: Record<string, Decision>) => void
}

export function ApprovalBatch({ approvalId, items, phase, isRedraftRound, onSubmit }: Props) {
  const [decisions, setDecisions] = useState<Record<string, Decision>>({})
  const [submitted, setSubmitted] = useState(false)

  const shopifyItems = items.filter((i) => i.channel === 'shopify')
  const socialItems  = items.filter((i) => i.channel === 'social')

  const decisionedCount = Object.keys(decisions).length
  const approvedCount   = Object.values(decisions).filter((d) => d.decision === 'approved').length
  const rejectedCount   = Object.values(decisions).filter((d) => d.decision === 'rejected').length
  const editCount       = Object.values(decisions).filter((d) => d.decision === 'edit_requested').length
  const allDecisioned   = decisionedCount >= items.length

  function handleDecision(approvalId: string, decision: Decision) {
    setDecisions((prev) => ({ ...prev, [approvalId]: decision }))
  }

  function handleSubmit() {
    if (!allDecisioned) return
    setSubmitted(true)
    onSubmit(decisions)
  }

  if (submitted && phase === 'redrafting') {
    return (
      <div className="flex flex-col items-center justify-center h-48 gap-3 animate-fade-in">
        <div className="w-6 h-6 border-2 border-border border-t-accent rounded-full animate-spin-slow" />
        <p className="font-mono text-xs text-text-secondary tracking-wide">
          Redrafting {editCount} item{editCount > 1 ? 's' : ''}…
        </p>
      </div>
    )
  }

  if (submitted && phase === 'executing') {
    return (
      <div className="flex flex-col items-center justify-center h-48 gap-3 animate-fade-in">
        <div className="w-6 h-6 border-2 border-border border-t-accent rounded-full animate-spin-slow" />
        <p className="font-mono text-xs text-text-secondary tracking-wide">
          Reviewing decisions…
        </p>
      </div>
    )
  }

  return (
    <div className="flex flex-col">
      {/* Section header */}
      <div className="px-6 pt-5 pb-3 flex items-center gap-3">
        <h2 className="font-mono text-[10px] tracking-widest uppercase text-text-secondary select-none">
          {isRedraftRound ? 'Redraft Review' : 'Review Queue'}
        </h2>
        <span className="font-mono text-[10px] text-text-muted">·</span>
        <span className="font-mono text-[10px] text-text-muted">
          {items.length} item{items.length > 1 ? 's' : ''}
        </span>
        <span className="font-mono text-[10px] text-text-muted">·</span>
        <span className="font-mono text-[10px] text-text-muted select-none">
          {approvalId}
        </span>
      </div>

      <div className="px-6 flex flex-col gap-6 pb-6">
        {/* Shopify group */}
        {shopifyItems.length > 0 && (
          <div>
            <div className="flex items-center gap-3 mb-3">
              <div className="h-px flex-1 bg-border" />
              <span className="font-mono text-[9px] tracking-[0.2em] uppercase text-text-secondary select-none">
                Shopify — {shopifyItems.length} item{shopifyItems.length > 1 ? 's' : ''}
              </span>
              <div className="h-px flex-1 bg-border" />
            </div>
            <div className="flex flex-col gap-3">
              {shopifyItems.map((item) => (
                <AssetCard
                  key={item.assetId}
                  item={item}
                  currentDecision={decisions[item.approvalId]}
                  onDecision={handleDecision}
                />
              ))}
            </div>
          </div>
        )}

        {/* Social group */}
        {socialItems.length > 0 && (
          <div>
            <div className="flex items-center gap-3 mb-3">
              <div className="h-px flex-1 bg-border" />
              <span className="font-mono text-[9px] tracking-[0.2em] uppercase text-text-secondary select-none">
                Social Only — {socialItems.length} item{socialItems.length > 1 ? 's' : ''}
              </span>
              <div className="h-px flex-1 bg-border" />
            </div>
            <div className="flex flex-col gap-3">
              {socialItems.map((item) => (
                <AssetCard
                  key={item.assetId}
                  item={item}
                  currentDecision={decisions[item.approvalId]}
                  onDecision={handleDecision}
                />
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Sticky submit bar */}
      <div className="sticky bottom-0 bg-bg border-t border-border px-6 py-3 flex items-center gap-4">
        {/* Decision counts */}
        <div className="flex items-center gap-3 font-mono text-[10px] select-none">
          {approvedCount > 0 && (
            <span className="flex items-center gap-1 text-status-green">
              <CheckCircle size={10} /> {approvedCount} approved
            </span>
          )}
          {rejectedCount > 0 && (
            <span className="flex items-center gap-1 text-status-red">
              <XCircle size={10} /> {rejectedCount} rejected
            </span>
          )}
          {editCount > 0 && (
            <span className="flex items-center gap-1 text-status-amber">
              <Pencil size={10} /> {editCount} edit requested
            </span>
          )}
          {decisionedCount === 0 && (
            <span className="text-text-muted">
              Review each asset to enable submit
            </span>
          )}
        </div>

        <div className="flex-1" />

        {/* Progress indicator */}
        <span className="font-mono text-[10px] text-text-secondary">
          {decisionedCount}/{items.length}
        </span>

        {/* Submit button */}
        <button
          onClick={handleSubmit}
          disabled={!allDecisioned}
          className={`font-mono text-[11px] tracking-wider uppercase px-5 py-2 rounded border transition-all ${
            allDecisioned
              ? 'border-accent text-accent bg-accent-dim hover:bg-accent/15 cursor-pointer'
              : 'border-border text-text-muted cursor-not-allowed opacity-50'
          }`}
        >
          Submit Decisions
        </button>
      </div>
    </div>
  )
}
