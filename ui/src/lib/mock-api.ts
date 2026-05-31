import type {
  ApprovalItem,
  AtlasState,
  Capability,
  EventFixture,
  ExecutionEvidence,
  FixtureItem,
} from './types'
import { sleep } from './utils'

function itemFromFixture(fi: FixtureItem): ApprovalItem {
  return {
    assetId: fi.asset_id,
    approvalId: fi.approval_id,
    channel: fi.channel,
    productType: fi.product_type,
    queueType: fi.queue_type,
    photoUrl: fi.photo_url,
    filename: fi.filename,
    copyDraft: fi.copy_draft,
    agentReasoning: fi.agent_reasoning,
    scores: fi.scores,
  }
}

export interface PipelineCallbacks {
  onMessage: (role: 'coordinator' | 'operator', text: string) => void
  onNotice: (capability: Capability, text: string) => void
  onCapabilityStart: (capability: Capability) => void
  onCapabilityComplete: (
    capability: Capability,
    resultSummary: string,
    strategyExcerpt?: string
  ) => void
  onApprovalReady: (approvalId: string, items: ApprovalItem[]) => void
}

export interface ExecutionCallbacks {
  onCapabilityStart: (capability: Capability) => void
  onCapabilityComplete: (capability: Capability, resultSummary: string) => void
  onNotice: (capability: Capability, text: string) => void
  onExecutionEvidence: (evidence: ExecutionEvidence) => void
  onMockupResolved: (assetId: string, mockupUrl: string) => void
  onAtlasState: (state: AtlasState) => void
  onPipelineComplete: () => void
}

// Simulate capabilities 1–6 then surface the approval gate
export async function simulatePipeline(
  fixture: EventFixture,
  cb: PipelineCallbacks,
  signal: AbortSignal
): Promise<void> {
  // Coordinator messages first (staggered 400ms apart)
  for (const msg of fixture.messages) {
    await sleep(msg.role === 'operator' ? 200 : 400, signal)
    cb.onMessage(msg.role, msg.text)
  }

  await sleep(600, signal)

  // Fire each capability step
  for (const cap of fixture.capabilities) {
    cb.onCapabilityStart(cap.capability)
    cb.onNotice(cap.capability, `${cap.label}...`)
    await sleep(cap.delay_ms, signal)
    cb.onCapabilityComplete(cap.capability, cap.result_summary, cap.strategy_summary)
  }

  await sleep(500, signal)

  // Open HITL gate
  cb.onCapabilityStart('request_human_approval')
  cb.onApprovalReady(
    fixture.approval.approval_id,
    fixture.approval.items.map(itemFromFixture)
  )
}

// Simulate redraft of edit-requested items
export async function simulateRedraft(
  fixture: EventFixture,
  onApprovalReady: (approvalId: string, items: ApprovalItem[]) => void,
  signal: AbortSignal
): Promise<void> {
  await sleep(1800, signal)
  const redraftItems = fixture.redraft_items.map(itemFromFixture)
  onApprovalReady(fixture.approval.approval_id + '-r1', redraftItems)
}

// Simulate execution (capabilities 8–9) + evidence
export async function simulateExecution(
  fixture: EventFixture,
  approved: number,
  cb: ExecutionCallbacks,
  signal: AbortSignal
): Promise<void> {
  // execute_approved_campaigns
  cb.onCapabilityStart('execute_approved_campaigns')
  cb.onNotice('execute_approved_campaigns', `Executing ${approved} approved campaigns...`)
  await sleep(1600, signal)
  cb.onCapabilityComplete(
    'execute_approved_campaigns',
    `${approved} campaigns dispatched · Shopify + Printful + social`
  )

  // Emit evidence WITHOUT mockup URLs (they resolve async)
  const evidence: ExecutionEvidence = {
    shopifyProducts: fixture.execution_evidence.shopify_products.map((p) => ({
      assetId: p.asset_id,
      productId: p.product_id,
      title: p.title,
      url: p.url,
      productType: p.product_type,
      // mockupUrl intentionally absent — resolves via onMockupResolved below
    })),
    socialPosts: fixture.execution_evidence.social_posts.map((p) => ({
      assetId: p.asset_id,
      photoUrl: p.photo_url,
      caption: p.caption,
      hashtags: p.hashtags,
      status: 'queued' as const,
    })),
  }
  cb.onExecutionEvidence(evidence)

  // Staggered mockup resolution (2s base + 600ms per product)
  fixture.execution_evidence.shopify_products.forEach((p, i) => {
    const delay = 2000 + i * 600
    sleep(delay, signal)
      .then(() => cb.onMockupResolved(p.asset_id, p.mockup_url))
      .catch(() => {/* aborted */})
  })

  // record_outcomes
  await sleep(800, signal)
  cb.onCapabilityStart('record_outcomes')
  cb.onNotice('record_outcomes', 'Writing provenance records to Atlas...')
  await sleep(900, signal)
  cb.onCapabilityComplete(
    'record_outcomes',
    `Provenance logged · ${approved} assets · 7-day measurement window open`
  )

  await sleep(400, signal)
  cb.onAtlasState(fixture.execution_evidence.atlas_state)
  await sleep(200, signal)
  cb.onPipelineComplete()
}
