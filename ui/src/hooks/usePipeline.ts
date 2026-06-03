'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { DEFAULT_MOCK_HEALTH, runMcpHealthBoot, simulateExecution, simulatePipeline, simulateRedraft } from '@/lib/mock-api'
import { pollMcpHealth } from '@/lib/health-api'
import { runPipelineLive, submitDecisionsLive } from '@/lib/live-api'
import type {
  ApprovalItem,
  AtlasState,
  CapabilityStep,
  ChatMessage,
  Decision,
  EventMeta,
  EventSession,
  ExecutionEvidence,
  McpHealth,
  Notice,
  PipelinePhase,
} from '@/lib/types'
import { genId } from '@/lib/utils'

import event1Fixture from '@/mock/event1.json'
import event2Fixture from '@/mock/event2.json'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const FIXTURES: any[] = [event1Fixture, event2Fixture]

export interface PipelineState {
  phase: PipelinePhase
  sessions: EventSession[]
  notices: Notice[]
  messages: ChatMessage[]
  activeSteps: CapabilityStep[]
  activeEventMeta: EventMeta | null
  approvalId: string | null
  approvalItems: ApprovalItem[]
  evidence: ExecutionEvidence | null
  atlasState: AtlasState | null
  mockupUrls: Record<string, string>
  isRedraftRound: boolean
  mcpHealth: McpHealth
}

export function usePipeline() {
  const [phase, setPhase] = useState<PipelinePhase>('idle')
  const [sessions, setSessions] = useState<EventSession[]>([])
  const [notices, setNotices] = useState<Notice[]>([])
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [activeSteps, setActiveSteps] = useState<CapabilityStep[]>([])
  const [activeEventMeta, setActiveEventMeta] = useState<EventMeta | null>(null)
  const [approvalId, setApprovalId] = useState<string | null>(null)
  const [approvalItems, setApprovalItems] = useState<ApprovalItem[]>([])
  const [evidence, setEvidence] = useState<ExecutionEvidence | null>(null)
  const [atlasState, setAtlasState] = useState<AtlasState | null>(null)
  const [mockupUrls, setMockupUrls] = useState<Record<string, string>>({})
  const [isRedraftRound, setIsRedraftRound] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  const [mcpHealth, setMcpHealth] = useState<McpHealth>(DEFAULT_MOCK_HEALTH)
  const mcpHealthRef = useRef<McpHealth>(DEFAULT_MOCK_HEALTH)
  const setMcpHealthTracked = useCallback((h: McpHealth) => {
    mcpHealthRef.current = h
    setMcpHealth(h)
  }, [])

  const abortRef = useRef<AbortController | null>(null)
  const bootAbortRef = useRef<AbortController | null>(null)
  const eventIndexRef = useRef(0)
  const sessionIdRef = useRef<string | null>(null)
  const lastMessageRef = useRef<string>('')
  // Store steps for the current active run so we can push to session on complete
  const activeStepsRef = useRef<CapabilityStep[]>([])

  // Health source: real poll when API URL is configured, mock boot sequence otherwise
  useEffect(() => {
    const ctrl = new AbortController()
    bootAbortRef.current = ctrl
    const apiUrl = process.env.NEXT_PUBLIC_API_URL
    if (apiUrl) {
      pollMcpHealth(apiUrl, setMcpHealthTracked, ctrl.signal)
    } else {
      runMcpHealthBoot(setMcpHealthTracked, ctrl.signal).catch(() => {/* aborted */})
    }
    return () => ctrl.abort()
  }, [setMcpHealthTracked])

  function addNotice(capability: Parameters<Notice['capability'] extends infer T ? (t: T) => void : never>[0], text: string) {
    setNotices((prev) => [
      ...prev,
      { id: genId(), capability: capability as Notice['capability'], text, timestamp: Date.now() },
    ])
  }

  function addMessage(role: ChatMessage['role'], text: string) {
    setMessages((prev) => [
      ...prev,
      { id: genId(), role, text, timestamp: Date.now() },
    ])
  }

  function updateStep(
    capability: CapabilityStep['capability'],
    patch: Partial<CapabilityStep>
  ) {
    setActiveSteps((prev) => {
      const exists = prev.find((s) => s.capability === capability)
      if (exists) {
        const updated = prev.map((s) =>
          s.capability === capability ? { ...s, ...patch } : s
        )
        activeStepsRef.current = updated
        return updated
      }
      // Add new row
      const next = [...prev, { capability, label: patch.label ?? capability, status: 'pending', ...patch } as CapabilityStep]
      activeStepsRef.current = next
      return next
    })
  }

  const sendMessage = useCallback(
    async (text: string) => {
      if (phase !== 'idle' && phase !== 'complete' && phase !== 'error') return

      lastMessageRef.current = text

      // Cancel any previous run
      abortRef.current?.abort()
      const ctrl = new AbortController()
      abortRef.current = ctrl

      const fixture = FIXTURES[eventIndexRef.current % FIXTURES.length]
      const apiUrl = process.env.NEXT_PUBLIC_API_URL

      // Reset active state for new event
      setActiveSteps([])
      activeStepsRef.current = []
      setEvidence(null)
      setAtlasState(null)
      setMockupUrls({})
      setIsRedraftRound(false)
      setErrorMessage(null)
      sessionIdRef.current = null
      setActiveEventMeta(apiUrl ? null : fixture.event)
      setPhase('running')

      addMessage('operator', text)

      const pipelineCallbacks = {
        onMessage: (role: 'coordinator' | 'operator', msg: string) => addMessage(role, msg),
        onNotice: (cap: Parameters<typeof addNotice>[0], t: string) => addNotice(cap, t),
        onCapabilityStart: (cap: Parameters<typeof updateStep>[0]) =>
          updateStep(cap, { status: 'running', label: '' }),
        onCapabilityComplete: (
          cap: Parameters<typeof updateStep>[0],
          resultSummary: string,
          strategyExcerpt?: string,
        ) => updateStep(cap, { status: 'complete', resultSummary, strategyExcerpt }),
        onApprovalReady: (apId: string, items: ApprovalItem[]) => {
          setApprovalId(apId)
          setApprovalItems(items)
          setPhase('awaiting_approval')
        },
        onEventMeta: (meta: import('@/lib/types').EventMeta) => setActiveEventMeta(meta),
        onHealthChange: setMcpHealthTracked,
        getCurrentHealth: () => mcpHealthRef.current,
      }

      try {
        if (apiUrl) {
          const { sessionId } = await runPipelineLive(apiUrl, text, pipelineCallbacks, ctrl.signal)
          sessionIdRef.current = sessionId
        } else {
          await simulatePipeline(fixture, pipelineCallbacks, ctrl.signal)
        }
      } catch (e) {
        if ((e as Error).name === 'AbortError') return
        setErrorMessage((e as Error).message || 'Something went wrong')
        setPhase('error')
      }
    },
    [phase]
  )

  const retryLast = useCallback(() => {
    sendMessage(lastMessageRef.current)
  }, [sendMessage])

  const submitDecisions = useCallback(
    async (decisions: Record<string, Decision>) => {
      const hasEdits = Object.values(decisions).some(
        (d) => d.decision === 'edit_requested'
      )

      abortRef.current?.abort()
      const ctrl = new AbortController()
      abortRef.current = ctrl

      const fixture = FIXTURES[eventIndexRef.current % FIXTURES.length]
      const apiUrl = process.env.NEXT_PUBLIC_API_URL
      const liveSessionId = sessionIdRef.current

      // Mock-only redraft path (live path: coordinator handles redraft internally)
      if (!liveSessionId && hasEdits && !isRedraftRound && fixture.redraft_items.length > 0) {
        setPhase('redrafting')
        updateStep('request_human_approval', {
          status: 'running',
          label: 'Awaiting your review',
          resultSummary: 'Redrafting edit-requested items...',
        })
        try {
          await simulateRedraft(
            fixture,
            (apId, items) => {
              setApprovalId(apId)
              setApprovalItems(items)
              setIsRedraftRound(true)
              setPhase('awaiting_approval')
            },
            ctrl.signal
          )
        } catch (e) {
          if ((e as Error).name !== 'AbortError') throw e
        }
        return
      }

      const approvedCount = Object.values(decisions).filter(
        (d) => d.decision === 'approved'
      ).length

      updateStep('request_human_approval', {
        status: 'complete',
        label: 'Awaiting your review',
        resultSummary: `${approvedCount} approved · decisions submitted`,
      })
      setPhase('executing')

      const executionCallbacks = {
        onCapabilityStart: (cap: Parameters<typeof updateStep>[0]) =>
          updateStep(cap, { status: 'running', label: '' }),
        onCapabilityComplete: (cap: Parameters<typeof updateStep>[0], resultSummary: string) =>
          updateStep(cap, { status: 'complete', resultSummary }),
        onNotice: (cap: Parameters<typeof addNotice>[0], t: string) => addNotice(cap, t),
        onExecutionEvidence: (ev: import('@/lib/types').ExecutionEvidence) => setEvidence(ev),
        onMockupResolved: (assetId: string, url: string) =>
          setMockupUrls((prev) => ({ ...prev, [assetId]: url })),
        onAtlasState: (s: import('@/lib/types').AtlasState) => setAtlasState(s),
        onPipelineComplete: () => {
          setPhase('complete')
          sessionIdRef.current = null
          setSessions((prev) => [
            ...prev,
            { meta: fixture.event, capabilitySteps: activeStepsRef.current },
          ])
          eventIndexRef.current += 1
          setActiveSteps([])
          activeStepsRef.current = []
          setApprovalItems([])
          setApprovalId(null)
          setIsRedraftRound(false)
          setActiveEventMeta(null)
        },
      }

      try {
        if (apiUrl && liveSessionId) {
          await submitDecisionsLive(apiUrl, liveSessionId, decisions, executionCallbacks, ctrl.signal)
        } else {
          await simulateExecution(fixture, approvedCount, executionCallbacks, ctrl.signal)
        }
      } catch (e) {
        if ((e as Error).name === 'AbortError') return
        setErrorMessage((e as Error).message || 'Something went wrong')
        setPhase('error')
      }
    },
    [isRedraftRound]
  )

  return {
    phase,
    sessions,
    notices,
    messages,
    activeSteps,
    activeEventMeta,
    approvalId,
    approvalItems,
    evidence,
    atlasState,
    mockupUrls,
    isRedraftRound,
    mcpHealth,
    errorMessage,
    sendMessage,
    submitDecisions,
    retryLast,
  }
}
