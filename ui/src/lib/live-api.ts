/**
 * Live SSE pipeline API — replaces mock-api simulation when NEXT_PUBLIC_API_URL is set.
 *
 * Two exported functions mirror the mock-api callback interfaces so usePipeline
 * can swap between live and mock paths without touching state management.
 *
 * SSE frames arrive as: data: {"type": "...", "payload": {...}}\n\n
 *
 * Uses fetch + ReadableStream (not EventSource) because both endpoints are POST.
 * The parser buffers across chunk boundaries so split frames are handled correctly.
 */

import type { ApprovalItem, AtlasState, Decision, EventMeta, ExecutionEvidence } from './types'
import type { ExecutionCallbacks, PipelineCallbacks } from './mock-api'

// Rewrite a local filesystem path to go through the backend image proxy.
// HTTP/HTTPS and data: URLs are returned unchanged.
function rewritePhotoUrl(url: string, apiUrl: string): string {
  if (!url || url.startsWith('http://') || url.startsWith('https://') || url.startsWith('data:')) {
    return url
  }
  return `${apiUrl}/api/image?path=${encodeURIComponent(url)}`
}

// ---------------------------------------------------------------------------
// SSE stream reader
// ---------------------------------------------------------------------------

async function* readSseStream(
  response: Response,
  signal: AbortSignal,
): AsyncGenerator<{ type: string; payload: unknown }> {
  if (!response.body) return

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  try {
    while (true) {
      if (signal.aborted) break

      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })

      // Split on double-newline (SSE frame boundary); keep trailing partial frame.
      const frames = buffer.split('\n\n')
      buffer = frames.pop() ?? ''

      for (const frame of frames) {
        const dataLine = frame
          .split('\n')
          .find((l) => l.startsWith('data:'))
        if (!dataLine) continue
        const raw = dataLine.slice('data:'.length).trim()
        if (!raw) continue
        try {
          yield JSON.parse(raw) as { type: string; payload: unknown }
          // Yield to the event loop so React can flush state updates between frames
          // when all events arrive in a single SSE chunk (the typical live-backend case).
          await new Promise((r) => setTimeout(r, 0))
        } catch {
          // malformed frame — skip
        }
      }
    }
  } finally {
    reader.releaseLock()
  }
}

// ---------------------------------------------------------------------------
// Turn 1: run pipeline → approval_ready
// ---------------------------------------------------------------------------

type LivePipelineCallbacks = PipelineCallbacks & {
  onEventMeta?: (meta: EventMeta) => void
}

export async function runPipelineLive(
  apiUrl: string,
  message: string,
  callbacks: LivePipelineCallbacks,
  signal: AbortSignal,
): Promise<{ sessionId: string }> {
  const response = await fetch(`${apiUrl}/api/pipeline/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message }),
    signal,
  })

  if (!response.ok) {
    throw new Error(`pipeline/run failed: ${response.status} ${response.statusText}`)
  }

  let sessionId = ''

  for await (const event of readSseStream(response, signal)) {
    if (signal.aborted) break

    switch (event.type) {
      case 'session_started': {
        const p = event.payload as { session_id: string }
        sessionId = p.session_id
        break
      }
      case 'capability_started': {
        const p = event.payload as { capability: string }
        callbacks.onCapabilityStart(p.capability as Parameters<typeof callbacks.onCapabilityStart>[0])
        break
      }
      case 'capability_completed': {
        const p = event.payload as { capability: string; resultSummary: string; strategyExcerpt?: string; eventMeta?: EventMeta }
        callbacks.onCapabilityComplete(
          p.capability as Parameters<typeof callbacks.onCapabilityComplete>[0],
          p.resultSummary,
          p.strategyExcerpt,
        )
        if (p.resultSummary) {
          callbacks.onNotice(
            p.capability as Parameters<typeof callbacks.onNotice>[0],
            p.resultSummary,
          )
        }
        if (p.eventMeta && callbacks.onEventMeta) {
          callbacks.onEventMeta(p.eventMeta)
        }
        break
      }
      case 'coordinator_message': {
        const p = event.payload as { role: 'coordinator' | 'operator'; text: string }
        callbacks.onMessage(p.role, p.text)
        break
      }
      case 'approval_ready': {
        const p = event.payload as { approvalId: string; items: ApprovalItem[]; eventMeta?: EventMeta }
        if (p.eventMeta && callbacks.onEventMeta) {
          callbacks.onEventMeta(p.eventMeta)
        }
        const items = p.items.map((item) => ({
          ...item,
          photoUrl: rewritePhotoUrl(item.photoUrl, apiUrl),
        }))
        callbacks.onApprovalReady(p.approvalId, items)
        break
      }
      case 'error': {
        const p = event.payload as { message: string }
        throw new Error(p.message || 'Pipeline error')
      }
    }
  }

  return { sessionId }
}

// ---------------------------------------------------------------------------
// Turn 2: submit decisions → pipeline_complete
// ---------------------------------------------------------------------------

export async function submitDecisionsLive(
  apiUrl: string,
  sessionId: string,
  decisions: Record<string, Decision>,
  callbacks: ExecutionCallbacks,
  signal: AbortSignal,
): Promise<void> {
  const response = await fetch(`${apiUrl}/api/pipeline/decisions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId, decisions }),
    signal,
  })

  if (!response.ok) {
    throw new Error(`pipeline/decisions failed: ${response.status} ${response.statusText}`)
  }

  for await (const event of readSseStream(response, signal)) {
    if (signal.aborted) break

    switch (event.type) {
      case 'session_started':
        // no-op for Turn 2 (session_id already known)
        break
      case 'capability_started': {
        const p = event.payload as { capability: string }
        callbacks.onCapabilityStart(p.capability as Parameters<typeof callbacks.onCapabilityStart>[0])
        break
      }
      case 'capability_completed': {
        const p = event.payload as { capability: string; resultSummary: string }
        callbacks.onCapabilityComplete(
          p.capability as Parameters<typeof callbacks.onCapabilityComplete>[0],
          p.resultSummary,
        )
        if (p.resultSummary) {
          callbacks.onNotice(
            p.capability as Parameters<typeof callbacks.onNotice>[0],
            p.resultSummary,
          )
        }
        break
      }
      case 'coordinator_message':
        // coordinator commentary during execution — not surfaced in execution callbacks
        break
      case 'approval_ready': {
        // Coordinator redrafted edit_requested items and re-suspended for a second review round
        const p = event.payload as { approvalId: string; items: ApprovalItem[]; eventMeta?: EventMeta }
        const items = p.items.map((item) => ({
          ...item,
          photoUrl: rewritePhotoUrl(item.photoUrl, apiUrl),
        }))
        callbacks.onApprovalReady?.(p.approvalId, items)
        break
      }
      case 'execution_evidence': {
        const p = event.payload as ExecutionEvidence
        const evidence: ExecutionEvidence = {
          ...p,
          shopifyProducts: p.shopifyProducts.map((sp) => ({
            ...sp,
            photoUrl: rewritePhotoUrl(sp.photoUrl, apiUrl),
          })),
          socialPosts: p.socialPosts.map((post) => ({
            ...post,
            photoUrl: rewritePhotoUrl(post.photoUrl, apiUrl),
          })),
        }
        callbacks.onExecutionEvidence(evidence)
        break
      }
      case 'mockup_resolved': {
        const p = event.payload as { assetId: string; mockupUrl: string }
        callbacks.onMockupResolved(p.assetId, p.mockupUrl)
        break
      }
      case 'atlas_state': {
        const p = event.payload as AtlasState
        callbacks.onAtlasState(p)
        break
      }
      case 'pipeline_complete': {
        callbacks.onPipelineComplete()
        break
      }
      case 'error': {
        const p = event.payload as { message: string }
        throw new Error(p.message || 'Pipeline error')
      }
    }
  }
}
