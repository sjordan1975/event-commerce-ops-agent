export type Capability =
  | 'ingest_event_batch'
  | 'build_event_context'
  | 'find_similar_assets'
  | 'score_assets_with_vision'
  | 'propose_review_queue'
  | 'draft_campaigns_for_queue'
  | 'request_human_approval'
  | 'execute_approved_campaigns'
  | 'record_outcomes'

export type CapabilityStatus = 'pending' | 'running' | 'complete' | 'failed'

export interface CapabilityStep {
  capability: Capability
  label: string
  status: CapabilityStatus
  resultSummary?: string
  strategyExcerpt?: string
}

export interface Notice {
  id: string
  capability: Capability
  text: string
  timestamp: number
}

export interface ChatMessage {
  id: string
  role: 'coordinator' | 'operator'
  text: string
  timestamp: number
}

export interface Decision {
  decision: 'approved' | 'rejected' | 'edit_requested'
  notes?: string
}

export interface ApprovalItem {
  assetId: string
  approvalId: string
  channel: 'shopify' | 'social'
  productType: 'poster' | 'tshirt' | null
  queueType: 'exploitation' | 'discovery'
  photoUrl: string
  filename: string
  copyDraft: {
    headline: string | null
    caption: string
    hashtags: string[]
  }
  agentReasoning: string
  scores: {
    quality: number
    emotional: number
    social: number
    merch: number
    identity: number
  }
}

export interface ShopifyProduct {
  assetId: string
  productId: string
  title: string
  url: string
  productType: 'poster' | 'tshirt'
  photoUrl: string
  mockupUrl?: string
}

export interface SocialPost {
  assetId: string
  photoUrl: string
  caption: string
  hashtags: string[]
  status: 'queued'
}

export interface AtlasState {
  events: number
  assets: number
  campaigns: number
  approvals: {
    total: number
    approved: number
    rejected: number
    edit_requested: number
  }
  performance: {
    total: number
    metrics_status: string
  }
}

export interface ExecutionEvidence {
  mode: 'live' | 'preview'
  shopifyProducts: ShopifyProduct[]
  socialPosts: SocialPost[]
}

export interface McpHealth {
  status: 'connected' | 'reconnecting' | 'unavailable'
  toolsDiscovered: number
  lastSuccessfulCall: string | null
  reconnectAttempts: number
  serverVersion: string
  error: string | null
}

export type PipelinePhase =
  | 'idle'
  | 'running'
  | 'awaiting_approval'
  | 'redrafting'
  | 'executing'
  | 'complete'
  | 'error'

export interface EventMeta {
  event_id: string
  name: string
  home_team: string
  away_team: string
  outcome_type: 'upset_victory' | 'expected_win' | 'draw' | 'extra_time_win'
  final_score: string
  timeliness: number
  timeliness_label: string
}

export interface EventSession {
  meta: EventMeta
  capabilitySteps: CapabilityStep[]
}

// ── Raw fixture shapes (JSON) ──────────────────────────────────

export interface FixtureCapability {
  capability: Capability
  label: string
  result_summary: string
  strategy_summary?: string
  delay_ms: number
}

export interface FixtureItem {
  asset_id: string
  approval_id: string
  channel: 'shopify' | 'social'
  product_type: 'poster' | 'tshirt' | null
  queue_type: 'exploitation' | 'discovery'
  photo_url: string
  filename: string
  copy_draft: {
    headline: string | null
    caption: string
    hashtags: string[]
  }
  agent_reasoning: string
  scores: {
    quality: number
    emotional: number
    social: number
    merch: number
    identity: number
  }
}

export interface FixtureShopifyProduct {
  asset_id: string
  product_id: string
  title: string
  url: string
  photo_url: string
  mockup_url: string
  product_type: 'poster' | 'tshirt'
}

export interface FixtureMcpHealthTransition {
  delay_ms: number
  status: McpHealth['status']
  tools_discovered: number
  reconnect_attempts: number
  server_version: string
  error: string | null
}

export interface EventFixture {
  event: EventMeta
  messages: Array<{ id: string; role: 'coordinator' | 'operator'; text: string }>
  capabilities: FixtureCapability[]
  approval: {
    approval_id: string
    items: FixtureItem[]
  }
  redraft_items: FixtureItem[]
  execution_evidence: {
    mode?: 'live' | 'preview'
    shopify_products: FixtureShopifyProduct[]
    social_posts: Array<{
      asset_id: string
      photo_url: string
      caption: string
      hashtags: string[]
    }>
    atlas_state: AtlasState
  }
  mcp_health_transitions?: FixtureMcpHealthTransition[]
}
