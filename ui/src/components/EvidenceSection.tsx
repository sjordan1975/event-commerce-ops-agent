'use client'

import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import {
  Bookmark,
  ExternalLink,
  Heart,
  MessageCircle,
  MoreHorizontal,
  Package,
  Send,
  X,
} from 'lucide-react'
import type { AtlasState, ExecutionEvidence } from '@/lib/types'

interface Props {
  evidence: ExecutionEvidence
  atlasState: AtlasState | null
  mockupUrls: Record<string, string>
}

// ── Instagram-style post mock ─────────────────────────────────────────────────

type SocialPost = ExecutionEvidence['socialPosts'][0]

function SocialPostMock({ post, onClose }: { post: SocialPost; onClose: () => void }) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  return createPortal(
    <div
      className="fixed inset-0 z-[9999] flex items-center justify-center"
      style={{ background: 'rgba(0,0,0,0.88)' }}
      onClick={onClose}
    >
      <div
        className="bg-white rounded-xl overflow-hidden shadow-2xl animate-fade-in"
        style={{ width: 390 }}
        onClick={e => e.stopPropagation()}
      >
        {/* Profile row */}
        <div className="flex items-center gap-3 px-4 py-3 border-b border-gray-100">
          <div
            className="w-9 h-9 rounded-full flex items-center justify-center shrink-0"
            style={{ background: '#0A0A0A' }}
          >
            <span className="font-mono text-xs font-bold" style={{ color: '#CCFF47' }}>F</span>
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-black text-sm font-semibold leading-none">fieldhouse</p>
            <p className="text-gray-400 text-xs mt-0.5">Sponsored</p>
          </div>
          <MoreHorizontal size={18} className="text-gray-400 shrink-0" />
        </div>

        {/* Photo */}
        <div style={{ aspectRatio: '1 / 1' }}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={post.photoUrl}
            alt="social post preview"
            className="w-full h-full object-cover"
          />
        </div>

        {/* Action row */}
        <div className="px-4 pt-3 pb-4">
          <div className="flex items-center gap-4 mb-3">
            <Heart size={24} className="text-black" strokeWidth={1.5} />
            <MessageCircle size={24} className="text-black" strokeWidth={1.5} />
            <Send size={24} className="text-black" strokeWidth={1.5} />
            <div className="flex-1" />
            <Bookmark size={24} className="text-black" strokeWidth={1.5} />
          </div>

          {/* Likes */}
          <p className="text-black text-sm font-semibold mb-1">1,247 likes</p>

          {/* Caption */}
          <p className="text-black text-sm leading-relaxed">
            <span className="font-semibold">fieldhouse</span>{' '}
            {post.headline && <span className="font-semibold">{post.headline} </span>}
            {post.caption}
          </p>

          {/* Hashtags */}
          <p className="text-sm mt-1 leading-relaxed" style={{ color: '#0095f6' }}>
            {post.hashtags.join(' ')}
          </p>

          {/* Timestamp */}
          <p className="text-gray-400 text-xs uppercase tracking-wide mt-2">
            2 minutes ago
          </p>
        </div>
      </div>
    </div>,
    document.body
  )
}

// ── Preview badge ─────────────────────────────────────────────────────────────

function PreviewBadge() {
  return (
    <div className="inline-flex items-center gap-1.5 font-mono text-[9px] tracking-wide uppercase px-2 py-0.5 rounded bg-status-amber-dim border border-status-amber/20 text-status-amber self-start mb-2">
      <span>⚠</span>
      <span>Preview · live Shopify/Printful not configured</span>
    </div>
  )
}

// ── Shopify product mock lightbox ─────────────────────────────────────────────

type ShopifyProduct = ExecutionEvidence['shopifyProducts'][0]

function ShopifyProductMock({
  product,
  photoUrl,
  onClose,
}: {
  product: ShopifyProduct
  photoUrl: string
  onClose: () => void
}) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  const isPoster = product.productType === 'poster'

  return createPortal(
    <div
      className="fixed inset-0 z-[9999] flex items-center justify-center"
      style={{ background: 'rgba(0,0,0,0.92)' }}
      onClick={onClose}
    >
      {isPoster ? (
        /* ── Poster: white print frame ──────────────────────────────────── */
        <div
          className="animate-fade-in"
          style={{ background: 'white', padding: '3%', boxShadow: '0 24px 80px rgba(0,0,0,0.7)', width: 'min(80vw, 520px)', maxHeight: '90vh', overflow: 'hidden' }}
          onClick={e => e.stopPropagation()}
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={photoUrl}
            alt={product.title}
            style={{ width: '100%', display: 'block', aspectRatio: '3/4', objectFit: 'cover' }}
          />
          <div style={{ paddingTop: '4%', paddingBottom: '3%', textAlign: 'center' }}>
            <p style={{ fontFamily: 'var(--font-jetbrains, monospace)', fontSize: 12, color: '#111', marginBottom: 5, lineHeight: 1.4 }}>
              {product.title}
            </p>
            <p style={{ fontFamily: 'var(--font-jetbrains, monospace)', fontSize: 9, color: '#bbb', textTransform: 'uppercase', letterSpacing: '0.25em' }}>
              fieldhouse
            </p>
          </div>
        </div>
      ) : (
        /* ── T-shirt: AI-generated mockup image displayed directly ──── */
        <div
          className="animate-fade-in"
          style={{ maxWidth: 'min(75vw, 480px)', maxHeight: '85vh' }}
          onClick={e => e.stopPropagation()}
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={photoUrl}
            alt={product.title}
            style={{ maxWidth: '100%', maxHeight: '85vh', objectFit: 'contain', display: 'block' }}
          />
        </div>
      )}

      {/* Label — bottom-center, same pattern as AssetCard lightbox */}
      <div className="absolute bottom-6 left-1/2 -translate-x-1/2 flex flex-col items-center gap-1">
        <span className="font-mono text-xs text-white/50 uppercase tracking-[0.2em]">
          {product.productType} · preview
        </span>
        <span className="font-mono text-xs text-white/30">
          preview-#{product.productId.split('/').pop()}
        </span>
      </div>

      {/* Close button — absolute top-right, same pattern as AssetCard lightbox */}
      <button
        className="absolute top-5 right-6 text-white/40 hover:text-white/80 transition-colors"
        onClick={onClose}
        aria-label="Close"
      >
        <X size={20} />
      </button>
    </div>,
    document.body
  )
}

// ── Card components ───────────────────────────────────────────────────────────

function ShopifyCard({
  product,
  mockupUrl,
  mode,
}: {
  product: ShopifyProduct
  mockupUrl?: string
  mode: 'live' | 'preview'
}) {
  const [mockOpen, setMockOpen] = useState(false)
  const isResolved = !!mockupUrl

  return (
    <>
      {mockOpen && mockupUrl && (
        <ShopifyProductMock
          product={product}
          photoUrl={mockupUrl}
          onClose={() => setMockOpen(false)}
        />
      )}

      <div className="border border-border rounded-lg p-4 bg-surface flex gap-4">
        {/* Mockup thumbnail — spinner until resolved, then real image in both modes */}
        <div
          className="shrink-0 rounded-md bg-surface-3 border border-border overflow-hidden flex items-center justify-center"
          style={{ width: 100, height: 100 }}
        >
          {!isResolved ? (
            <div className="flex flex-col items-center gap-1.5">
              <div className="w-5 h-5 border-2 border-border border-t-accent rounded-full animate-spin-slow" />
              <span className="font-mono text-xs text-text-muted">rendering</span>
            </div>
          ) : (
            /* eslint-disable-next-line @next/next/no-img-element */
            <img
              src={product.photoUrl}
              alt={product.title}
              className="w-full h-full object-cover animate-fade-in"
            />
          )}
        </div>

        {/* Product info */}
        <div className="flex-1 min-w-0 flex flex-col">
          <span className="font-mono text-xs tracking-widest uppercase text-accent/70 block mb-1">
            {product.productType}{mode === 'preview' ? ' · preview' : ''}
          </span>
          {mode === 'preview' && <PreviewBadge />}
          <p className="text-sm font-semibold text-text-primary leading-snug mb-2">
            {product.headline || product.title}
          </p>
          {mode === 'live' ? (
            <>
              <a
                href={product.url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 font-mono text-xs text-text-secondary hover:text-accent transition-colors"
              >
                <ExternalLink size={11} />
                View on Shopify
              </a>
              <p className="font-mono text-xs text-text-muted mt-1">
                Draft · {product.productId.split('/').pop()}
              </p>
            </>
          ) : (
            <>
              <p className="font-mono text-xs text-text-muted mb-1.5">
                preview-#{product.productId.split('/').pop()}
              </p>
              {isResolved && (
                <button
                  onClick={() => setMockOpen(true)}
                  className="inline-flex items-center gap-1 font-mono text-xs text-text-secondary hover:text-accent transition-colors self-start"
                >
                  <ExternalLink size={10} />
                  View mock
                </button>
              )}
            </>
          )}
        </div>
      </div>
    </>
  )
}

function SocialPostCard({ post }: { post: SocialPost }) {
  const [mockOpen, setMockOpen] = useState(false)

  return (
    <>
      {mockOpen && (
        <SocialPostMock post={post} onClose={() => setMockOpen(false)} />
      )}

      <div className="border border-border rounded-lg p-3 bg-surface flex gap-4">
        {/* Photo */}
        <div
          className="shrink-0 rounded-md overflow-hidden bg-surface-3 border border-border"
          style={{ width: 100, height: 100 }}
        >
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
          {post.headline && (
            <p className="text-sm font-semibold text-text-primary leading-snug mb-1">
              {post.headline}
            </p>
          )}
          <p className="text-sm text-text-secondary leading-relaxed mb-1">
            {post.caption}
          </p>
          <p className="font-mono text-xs text-text-muted leading-relaxed">
            {post.hashtags.join(' ')}
          </p>
          <div className="mt-2 flex flex-col gap-1.5">
            <span className="inline-flex items-center gap-1 font-mono text-xs tracking-widest uppercase text-status-green/80 border border-status-green/20 rounded px-1.5 py-0.5 bg-status-green-dim self-start">
              queued in atlas
            </span>
            <button
              onClick={() => setMockOpen(true)}
              className="inline-flex items-center gap-1 font-mono text-xs text-text-secondary hover:text-accent transition-colors self-start"
            >
              <ExternalLink size={10} />
              View mock
            </button>
          </div>
        </div>
      </div>
    </>
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
        <span className="flex gap-3 flex-wrap">
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
        <span className="flex gap-3 flex-wrap">
          <span>{state.performance.total} docs</span>
          <span className="text-status-amber">{state.performance.metrics_status}</span>
          <span className="text-text-muted">· 7-day window open</span>
        </span>
      ),
    },
  ]

  return (
    <div className="border border-border rounded-lg p-4 bg-surface">
      <div className="flex items-center gap-2 mb-4">
        <Package size={13} className="text-text-secondary" />
        <span className="font-mono text-xs tracking-widest uppercase text-text-secondary select-none">
          Atlas State
        </span>
      </div>
      <div className="space-y-2.5">
        {rows.map((row) => (
          <div key={row.label} className="flex items-start gap-6">
            <span className="font-mono text-xs text-text-secondary w-24 shrink-0 select-none">
              {row.label}
            </span>
            <span className="font-mono text-xs text-text-primary flex-1 min-w-0">
              {row.value}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

export function EvidenceSection({ evidence, atlasState, mockupUrls }: Props) {
  const { mode } = evidence

  return (
    <div className="px-6 pt-5 pb-6 flex flex-col gap-6 animate-fade-in">
      {/* Shopify products */}
      {evidence.shopifyProducts.length > 0 && (
        <div>
          <div className="flex items-center gap-3 mb-3">
            <div className="h-px flex-1 bg-border" />
            <span className="font-mono text-xs tracking-[0.2em] uppercase text-text-secondary select-none">
              {mode === 'preview' ? 'Shopify Products · Preview' : 'Shopify Products Created'}
            </span>
            <div className="h-px flex-1 bg-border" />
          </div>
          <div className="grid grid-cols-1 gap-3">
            {evidence.shopifyProducts.map((p) => (
              <ShopifyCard
                key={p.assetId}
                product={p}
                mockupUrl={mockupUrls[p.assetId]}
                mode={mode}
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
            <span className="font-mono text-xs tracking-[0.2em] uppercase text-text-secondary select-none">
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
            <span className="font-mono text-xs tracking-[0.2em] uppercase text-text-secondary select-none">
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
