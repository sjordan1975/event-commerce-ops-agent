'use client'

import { ExternalLink, Package } from 'lucide-react'
import type { AtlasState, ExecutionEvidence } from '@/lib/types'

interface Props {
  evidence: ExecutionEvidence
  atlasState: AtlasState | null
  mockupUrls: Record<string, string>
}

function ShopifyCard({
  product,
  mockupUrl,
}: {
  product: ExecutionEvidence['shopifyProducts'][0]
  mockupUrl?: string
}) {
  return (
    <div className="border border-border rounded-lg p-4 bg-surface flex gap-4">
      {/* Mockup thumbnail */}
      <div className="w-20 h-20 shrink-0 rounded-md bg-surface-3 border border-border overflow-hidden flex items-center justify-center">
        {mockupUrl ? (
          /* eslint-disable-next-line @next/next/no-img-element */
          <img
            src={mockupUrl}
            alt={product.title}
            className="w-full h-full object-cover animate-fade-in"
          />
        ) : (
          <div className="flex flex-col items-center gap-1">
            <div className="w-4 h-4 border-2 border-border border-t-accent rounded-full animate-spin-slow" />
            <span className="font-mono text-[8px] text-text-muted">rendering</span>
          </div>
        )}
      </div>

      {/* Product info */}
      <div className="flex-1 min-w-0">
        <div className="flex items-start gap-2 mb-1.5">
          <span className="font-mono text-[9px] tracking-widest uppercase text-accent/70 shrink-0 mt-0.5">
            {product.productType}
          </span>
        </div>
        <p className="text-xs font-semibold text-text-primary leading-snug mb-2">
          {product.title}
        </p>
        <a
          href={product.url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 font-mono text-[10px] text-text-secondary hover:text-accent transition-colors"
        >
          <ExternalLink size={9} />
          View on Shopify
        </a>
        <p className="font-mono text-[9px] text-text-muted mt-1">
          Draft · {product.productId.split('/').pop()}
        </p>
      </div>
    </div>
  )
}

function SocialPostCard({
  post,
}: {
  post: ExecutionEvidence['socialPosts'][0]
}) {
  return (
    <div className="border border-border rounded-lg p-3 bg-surface flex gap-3">
      {/* Photo */}
      <div className="w-14 h-14 shrink-0 rounded-md overflow-hidden bg-surface-3 border border-border">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={post.photoUrl}
          alt="social post"
          className="w-full h-full object-cover"
          loading="lazy"
        />
      </div>
      {/* Content */}
      <div className="flex-1 min-w-0">
        <p className="text-[11px] text-text-secondary leading-relaxed mb-1">
          {post.caption}
        </p>
        <p className="font-mono text-[9px] text-text-muted leading-relaxed">
          {post.hashtags.join(' ')}
        </p>
        <span className="inline-flex items-center gap-1 mt-1.5 font-mono text-[8px] tracking-widest uppercase text-status-green/70 border border-status-green/20 rounded px-1.5 py-0.5 bg-status-green-dim">
          queued in atlas
        </span>
      </div>
    </div>
  )
}

function AtlasStatePanel({ state }: { state: AtlasState }) {
  const rows: Array<{ label: string; value: React.ReactNode }> = [
    { label: 'events',    value: state.events },
    { label: 'assets',    value: state.assets },
    { label: 'campaigns', value: state.campaigns },
    {
      label: 'approvals',
      value: (
        <span className="flex gap-2">
          <span>{state.approvals.total} total</span>
          <span className="text-status-green">{state.approvals.approved} approved</span>
          <span className="text-status-red">{state.approvals.rejected} rejected</span>
          {state.approvals.edit_requested > 0 && (
            <span className="text-status-amber">{state.approvals.edit_requested} edited</span>
          )}
        </span>
      ),
    },
    {
      label: 'performance',
      value: (
        <span className="flex gap-2">
          <span>{state.performance.total} docs</span>
          <span className="text-status-amber">{state.performance.metrics_status}</span>
          <span className="text-text-muted">· 7-day window open</span>
        </span>
      ),
    },
  ]

  return (
    <div className="border border-border rounded-lg p-4 bg-surface">
      <div className="flex items-center gap-2 mb-3">
        <Package size={12} className="text-text-secondary" />
        <span className="font-mono text-[9px] tracking-widest uppercase text-text-secondary select-none">
          Atlas State
        </span>
      </div>
      <div className="space-y-2">
        {rows.map((row) => (
          <div key={row.label} className="flex items-start gap-4">
            <span className="font-mono text-[10px] text-text-secondary w-20 shrink-0 select-none">
              {row.label}
            </span>
            <span className="font-mono text-[10px] text-text-primary flex-1 min-w-0">
              {row.value}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

export function EvidenceSection({ evidence, atlasState, mockupUrls }: Props) {
  return (
    <div className="px-6 pt-5 pb-6 flex flex-col gap-6 animate-fade-in">
      {/* Shopify products */}
      {evidence.shopifyProducts.length > 0 && (
        <div>
          <div className="flex items-center gap-3 mb-3">
            <div className="h-px flex-1 bg-border" />
            <span className="font-mono text-[9px] tracking-[0.2em] uppercase text-text-secondary select-none">
              Shopify Products Created
            </span>
            <div className="h-px flex-1 bg-border" />
          </div>
          <div className="grid grid-cols-1 gap-3">
            {evidence.shopifyProducts.map((p) => (
              <ShopifyCard
                key={p.assetId}
                product={p}
                mockupUrl={mockupUrls[p.assetId]}
              />
            ))}
          </div>
        </div>
      )}

      {/* Social posts */}
      {evidence.socialPosts.length > 0 && (
        <div>
          <div className="flex items-center gap-3 mb-3">
            <div className="h-px flex-1 bg-border" />
            <span className="font-mono text-[9px] tracking-[0.2em] uppercase text-text-secondary select-none">
              Social Queue — {evidence.socialPosts.length} Posts
            </span>
            <div className="h-px flex-1 bg-border" />
          </div>
          <div className="flex flex-col gap-2">
            {evidence.socialPosts.map((p) => (
              <SocialPostCard key={p.assetId} post={p} />
            ))}
          </div>
        </div>
      )}

      {/* Atlas state */}
      {atlasState && (
        <div>
          <div className="flex items-center gap-3 mb-3">
            <div className="h-px flex-1 bg-border" />
            <span className="font-mono text-[9px] tracking-[0.2em] uppercase text-text-secondary select-none">
              Database State
            </span>
            <div className="h-px flex-1 bg-border" />
          </div>
          <AtlasStatePanel state={atlasState} />
        </div>
      )}
    </div>
  )
}
