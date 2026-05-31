'use client'

import { useState } from 'react'
import { Check, X, Pencil } from 'lucide-react'
import type { ApprovalItem, Decision } from '@/lib/types'
import { ScoreBar } from './ScoreBar'

function ChannelBadge({ channel, productType }: { channel: string; productType: string | null }) {
  const label =
    channel === 'shopify' && productType
      ? `Shopify · ${productType.charAt(0).toUpperCase() + productType.slice(1)}`
      : 'Social Only'
  const cls =
    channel === 'shopify'
      ? 'text-accent border-accent/30 bg-accent/5'
      : 'text-[#3B82F6] border-[#3B82F6]/30 bg-[#3B82F6]/5'
  return (
    <span className={`font-mono text-[9px] tracking-widest uppercase border rounded px-1.5 py-0.5 ${cls}`}>
      {label}
    </span>
  )
}

function QueueBadge({ type }: { type: string }) {
  const cls =
    type === 'exploitation'
      ? 'text-[#F97316] border-[#F97316]/30 bg-[#F97316]/5'
      : 'text-[#9B59B6] border-[#9B59B6]/30 bg-[#9B59B6]/5'
  return (
    <span className={`font-mono text-[9px] tracking-widest uppercase border rounded px-1.5 py-0.5 ${cls}`}>
      {type}
    </span>
  )
}

interface Props {
  item: ApprovalItem
  onDecision: (approvalId: string, decision: Decision) => void
  currentDecision?: Decision
}

export function AssetCard({ item, onDecision, currentDecision }: Props) {
  const [editNote, setEditNote] = useState('')
  const [showEditField, setShowEditField] = useState(
    currentDecision?.decision === 'edit_requested'
  )

  const dec = currentDecision?.decision

  const borderCls =
    dec === 'approved'       ? 'border-status-green/40'
    : dec === 'rejected'     ? 'border-status-red/40'
    : dec === 'edit_requested' ? 'border-status-amber/40'
    : 'border-border'

  function decide(decision: Decision['decision']) {
    if (decision === 'edit_requested') {
      setShowEditField(true)
      onDecision(item.approvalId, { decision, notes: editNote })
    } else {
      setShowEditField(false)
      onDecision(item.approvalId, { decision })
    }
  }

  function handleEditNoteChange(val: string) {
    setEditNote(val)
    onDecision(item.approvalId, { decision: 'edit_requested', notes: val })
  }

  return (
    <div
      className={`border rounded-lg p-4 bg-surface transition-all duration-200 ${borderCls} ${
        dec === 'rejected' ? 'opacity-55' : ''
      }`}
    >
      {/* Badges */}
      <div className="flex gap-2 flex-wrap mb-3">
        <ChannelBadge channel={item.channel} productType={item.productType} />
        <QueueBadge type={item.queueType} />
      </div>

      {/* Main content: photo + text */}
      <div className="flex gap-4 mb-4">
        {/* Thumbnail */}
        <div className="w-28 h-28 shrink-0 rounded-md overflow-hidden bg-surface-3 border border-border">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={item.photoUrl}
            alt={item.filename}
            className="w-full h-full object-cover"
            loading="lazy"
          />
        </div>

        {/* Text content */}
        <div className="flex-1 min-w-0">
          <p className="font-mono text-[9px] text-text-muted mb-2 tracking-wide select-none">
            {item.filename}
          </p>

          {/* Copy draft */}
          <div className="mb-3">
            <p className="font-mono text-[9px] tracking-widest uppercase text-text-secondary mb-1 select-none">
              Copy Draft
            </p>
            {item.copyDraft.headline && (
              <p className="text-sm font-semibold text-text-primary leading-snug mb-0.5">
                &ldquo;{item.copyDraft.headline}&rdquo;
              </p>
            )}
            <p className="text-xs text-text-secondary leading-relaxed">
              {item.copyDraft.caption}
            </p>
            <p className="font-mono text-[10px] text-text-muted mt-1 leading-relaxed">
              {item.copyDraft.hashtags.join(' ')}
            </p>
          </div>

          {/* Agent reasoning */}
          <div>
            <p className="font-mono text-[9px] tracking-widest uppercase text-text-secondary mb-1 select-none">
              Agent Reasoning
            </p>
            <p className="text-[11px] text-text-secondary leading-relaxed">
              {item.agentReasoning}
            </p>
          </div>
        </div>
      </div>

      {/* Score bars */}
      <div className="space-y-1.5 pt-3 border-t border-border mb-4">
        <ScoreBar label="quality"   value={item.scores.quality}   />
        <ScoreBar label="emotional" value={item.scores.emotional} />
        <ScoreBar label="social"    value={item.scores.social}    />
        <ScoreBar label="merch"     value={item.scores.merch}     />
        <ScoreBar label="identity"  value={item.scores.identity}  />
      </div>

      {/* Decision buttons */}
      <div className="flex gap-2">
        {/* Approve */}
        <button
          onClick={() => decide('approved')}
          className={`flex-1 flex items-center justify-center gap-1.5 py-1.5 px-3 rounded border text-[11px] font-mono transition-all ${
            dec === 'approved'
              ? 'border-status-green bg-status-green-dim text-status-green'
              : 'border-border text-text-secondary hover:border-status-green hover:text-status-green hover:bg-status-green-dim'
          }`}
        >
          <Check size={11} />
          {dec === 'approved' ? 'Approved' : 'Approve'}
        </button>

        {/* Reject */}
        <button
          onClick={() => decide('rejected')}
          className={`flex-1 flex items-center justify-center gap-1.5 py-1.5 px-3 rounded border text-[11px] font-mono transition-all ${
            dec === 'rejected'
              ? 'border-status-red bg-status-red-dim text-status-red'
              : 'border-border text-text-secondary hover:border-status-red hover:text-status-red hover:bg-status-red-dim'
          }`}
        >
          <X size={11} />
          {dec === 'rejected' ? 'Rejected' : 'Reject'}
        </button>

        {/* Edit request */}
        <button
          onClick={() => decide('edit_requested')}
          className={`flex-1 flex items-center justify-center gap-1.5 py-1.5 px-3 rounded border text-[11px] font-mono transition-all ${
            dec === 'edit_requested'
              ? 'border-status-amber bg-status-amber-dim text-status-amber'
              : 'border-border text-text-secondary hover:border-status-amber hover:text-status-amber hover:bg-status-amber-dim'
          }`}
        >
          <Pencil size={11} />
          {dec === 'edit_requested' ? 'Edit Requested' : 'Request Edit'}
        </button>
      </div>

      {/* Edit note field */}
      {showEditField && (
        <div className="mt-3 animate-fade-in">
          <textarea
            value={editNote}
            onChange={(e) => handleEditNoteChange(e.target.value)}
            placeholder="Describe what to change..."
            rows={2}
            className="w-full bg-surface-3 border border-status-amber/30 rounded-md px-3 py-2 text-xs text-text-primary placeholder-text-secondary resize-none font-sans outline-none focus:border-status-amber/60 transition-colors"
          />
        </div>
      )}
    </div>
  )
}
