'use client'

import type {
  ApprovalItem,
  AtlasState,
  Decision,
  ExecutionEvidence,
  PipelinePhase,
} from '@/lib/types'
import { ApprovalBatch } from './ApprovalBatch'
import { EvidenceSection } from './EvidenceSection'

interface Props {
  phase: PipelinePhase
  approvalId: string | null
  approvalItems: ApprovalItem[]
  isRedraftRound: boolean
  evidence: ExecutionEvidence | null
  atlasState: AtlasState | null
  mockupUrls: Record<string, string>
  onSubmitDecisions: (decisions: Record<string, Decision>) => void
}

export function ContentPane({
  phase,
  approvalId,
  approvalItems,
  isRedraftRound,
  evidence,
  atlasState,
  mockupUrls,
  onSubmitDecisions,
}: Props) {
  // Idle
  if (phase === 'idle') {
    return (
      <div className="flex-1 flex items-center justify-center px-6 py-12">
        <div className="text-center">
          <div
            className="w-px h-16 bg-gradient-to-b from-transparent via-border to-transparent mx-auto mb-6"
          />
          <p className="font-mono text-[10px] tracking-widest uppercase text-text-muted">
            Enter an event below to begin
          </p>
        </div>
      </div>
    )
  }

  // Pipeline running (no approval yet)
  if (phase === 'running') {
    return (
      <div className="flex-1 flex items-center justify-center px-6 py-8">
        <div className="text-center space-y-3">
          <div className="flex items-center gap-1.5 justify-center">
            {[0, 1, 2].map((i) => (
              <span
                key={i}
                className="w-1 h-1 rounded-full bg-accent/40"
                style={{
                  animation: 'pulseDot 1.4s ease-in-out infinite',
                  animationDelay: `${i * 0.2}s`,
                }}
              />
            ))}
          </div>
          <p className="font-mono text-[10px] tracking-widest text-text-muted uppercase">
            Pipeline running
          </p>
        </div>
      </div>
    )
  }

  // Awaiting approval
  if ((phase === 'awaiting_approval' || phase === 'redrafting') && approvalId && approvalItems.length > 0) {
    return (
      <ApprovalBatch
        key={approvalId}
        approvalId={approvalId}
        items={approvalItems}
        phase={phase}
        isRedraftRound={isRedraftRound}
        onSubmit={onSubmitDecisions}
      />
    )
  }

  // Executing
  if (phase === 'executing') {
    return (
      <div className="flex-1 flex items-center justify-center px-6 py-8">
        <div className="text-center space-y-3">
          <div className="w-5 h-5 border-2 border-border border-t-accent rounded-full animate-spin-slow mx-auto" />
          <p className="font-mono text-[10px] tracking-widest text-text-muted uppercase">
            Dispatching campaigns
          </p>
        </div>
      </div>
    )
  }

  // Complete — show evidence
  if (phase === 'complete' && evidence) {
    return (
      <EvidenceSection
        evidence={evidence}
        atlasState={atlasState}
        mockupUrls={mockupUrls}
      />
    )
  }

  return null
}
