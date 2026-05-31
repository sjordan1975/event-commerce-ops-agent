'use client'

import { usePipeline } from '@/hooks/usePipeline'
import { ActivityTimeline } from './ActivityTimeline'
import { ChatBar } from './ChatBar'
import { ContentPane } from './ContentPane'
import { EventHeader } from './EventHeader'
import { StreamingNotices } from './StreamingNotices'

export function AppShell() {
  const {
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
    sendMessage,
    submitDecisions,
  } = usePipeline()

  return (
    <div className="h-full flex flex-col">
      <EventHeader
        phase={phase}
        activeEventMeta={activeEventMeta}
        sessionCount={sessions.length}
      />

      <div className="flex-1 flex overflow-hidden">
        {/* Left: streaming notices */}
        <StreamingNotices notices={notices} />

        {/* Right: timeline + content + chat */}
        <div className="flex-1 flex flex-col overflow-hidden">
          {/* Scrollable zone: timeline + content pane */}
          <div className="flex-1 overflow-y-auto">
            <ActivityTimeline sessions={sessions} activeSteps={activeSteps} />
            <ContentPane
              phase={phase}
              approvalId={approvalId}
              approvalItems={approvalItems}
              isRedraftRound={isRedraftRound}
              evidence={evidence}
              atlasState={atlasState}
              mockupUrls={mockupUrls}
              onSubmitDecisions={submitDecisions}
            />
          </div>

          {/* Chat bar — pinned to bottom */}
          <ChatBar messages={messages} phase={phase} onSend={sendMessage} />
        </div>
      </div>
    </div>
  )
}
