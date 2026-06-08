import type {
  ApprovalItem,
  AtlasState,
  Capability,
  EventFixture,
  ExecutionEvidence,
  FixtureItem,
  FixtureMcpHealthTransition,
  McpHealth,
} from './types'
import { sleep } from './utils'

// Boot sequence: unavailable → reconnecting → connected on app load
export const DEFAULT_MOCK_HEALTH: McpHealth = {
  status: 'unavailable',
  toolsDiscovered: 0,
  lastSuccessfulCall: null,
  reconnectAttempts: 0,
  serverVersion: '1.11.0',
  error: 'No active session',
}

const BOOT_SEQUENCE: Array<{ delayMs: number; patch: Partial<McpHealth> }> = [
  { delayMs: 0,    patch: { status: 'unavailable', toolsDiscovered: 0, reconnectAttempts: 0, error: 'No active session' } },
  { delayMs: 1400, patch: { status: 'reconnecting', reconnectAttempts: 1, error: null } },
  { delayMs: 3100, patch: { status: 'connected', toolsDiscovered: 43, reconnectAttempts: 1, error: null } },
]

export async function runMcpHealthBoot(
  onHealthChange: (h: McpHealth) => void,
  signal: AbortSignal
): Promise<void> {
  let current: McpHealth = { ...DEFAULT_MOCK_HEALTH }
  for (const step of BOOT_SEQUENCE) {
    await sleep(step.delayMs, signal)
    current = {
      ...current,
      ...step.patch,
      lastSuccessfulCall: step.patch.status === 'connected' ? new Date().toISOString() : current.lastSuccessfulCall,
    }
    onHealthChange(current)
  }
}

function healthFromTransition(t: FixtureMcpHealthTransition, prev: McpHealth): McpHealth {
  return {
    status: t.status,
    toolsDiscovered: t.tools_discovered,
    lastSuccessfulCall: t.status === 'connected' ? new Date().toISOString() : prev.lastSuccessfulCall,
    reconnectAttempts: t.reconnect_attempts,
    serverVersion: t.server_version,
    error: t.error,
  }
}

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
  onHealthChange?: (health: McpHealth) => void
  getCurrentHealth?: () => McpHealth
}

export interface ExecutionCallbacks {
  onCapabilityStart: (capability: Capability) => void
  onCapabilityComplete: (capability: Capability, resultSummary: string) => void
  onNotice: (capability: Capability, text: string) => void
  onExecutionEvidence: (evidence: ExecutionEvidence) => void
  onMockupResolved: (assetId: string, mockupUrl: string) => void
  onAtlasState: (state: AtlasState) => void
  onPipelineComplete: () => void
  // Fired when coordinator redrafts edit_requested items and re-suspends for approval (live path only)
  onApprovalReady?: (approvalId: string, items: ApprovalItem[]) => void
}

// Simulate capabilities 1–6 then surface the approval gate
export async function simulatePipeline(
  fixture: EventFixture,
  cb: PipelineCallbacks,
  signal: AbortSignal
): Promise<void> {
  // Fire mid-pipeline health transitions concurrently (fire-and-forget)
  if (cb.onHealthChange && fixture.mcp_health_transitions?.length) {
    for (const t of fixture.mcp_health_transitions) {
      const transition = t
      sleep(transition.delay_ms, signal)
        .then(() => {
          const prev = cb.getCurrentHealth?.() ?? DEFAULT_MOCK_HEALTH
          cb.onHealthChange!(healthFromTransition(transition, prev))
        })
        .catch(() => {/* aborted */})
    }
  }

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
    `${approved} campaigns dispatched · Shopify + social`
  )

  // Emit evidence WITHOUT mockup URLs (they resolve async)
  const evidence: ExecutionEvidence = {
    mode: fixture.execution_evidence.mode ?? 'preview',
    shopifyProducts: fixture.execution_evidence.shopify_products.map((p) => ({
      assetId: p.asset_id,
      productId: p.product_id,
      title: p.title,
      url: p.url,
      productType: p.product_type,
      photoUrl: p.photo_url,
      // mockupUrl intentionally absent — resolves via onMockupResolved below
    })),
    socialPosts: fixture.execution_evidence.social_posts.map((p) => ({
      assetId: p.asset_id,
      photoUrl: p.photo_url,
      headline: (p as { headline?: string }).headline,
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
