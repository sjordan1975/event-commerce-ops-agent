'use client'

import { useCallback, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { CheckCircle, Copy, Upload, X } from 'lucide-react'
import { uploadBatch, type UploadResult } from '@/lib/live-api'

interface Props {
  apiUrl: string
}

type UploadState =
  | { status: 'idle' }
  | { status: 'selecting' }
  | { status: 'uploading'; progress: number }
  | { status: 'done'; result: UploadResult }
  | { status: 'error'; message: string }

export function BatchUpload({ apiUrl }: Props) {
  const [open, setOpen] = useState(false)
  const [state, setState] = useState<UploadState>({ status: 'idle' })
  const [files, setFiles] = useState<File[]>([])
  const [copied, setCopied] = useState(false)
  const [dragging, setDragging] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const ACCEPTED = ['image/jpeg', 'image/png', 'image/webp']

  function filterImages(list: FileList | File[]): File[] {
    return Array.from(list).filter((f) => ACCEPTED.includes(f.type))
  }

  function openModal() {
    setState({ status: 'idle' })
    setFiles([])
    setCopied(false)
    setOpen(true)
  }

  function closeModal() {
    setOpen(false)
    setState({ status: 'idle' })
    setFiles([])
  }

  function onFileInput(e: React.ChangeEvent<HTMLInputElement>) {
    if (!e.target.files) return
    setFiles(filterImages(e.target.files))
    setState({ status: 'selecting' })
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault()
    setDragging(false)
    const imgs = filterImages(e.dataTransfer.files)
    if (!imgs.length) return
    setFiles(imgs)
    setState({ status: 'selecting' })
  }

  async function handleUpload() {
    if (!files.length) return
    setState({ status: 'uploading', progress: 0 })
    try {
      const result = await uploadBatch(apiUrl, files)
      setState({ status: 'done', result })
    } catch (err) {
      setState({ status: 'error', message: (err as Error).message })
    }
  }

  const copyPath = useCallback((path: string) => {
    navigator.clipboard.writeText(path)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }, [])

  if (!open) {
    return (
      <button
        onClick={openModal}
        className="w-full flex items-center gap-2 px-4 py-2.5 text-left font-mono text-[10px] tracking-widest uppercase text-text-secondary hover:text-accent transition-colors group"
      >
        <Upload size={11} className="shrink-0 group-hover:text-accent transition-colors" />
        Upload batch
      </button>
    )
  }

  return createPortal(
    <div
      className="fixed inset-0 z-[9999] flex items-center justify-center"
      style={{ background: 'rgba(0,0,0,0.75)' }}
      onClick={closeModal}
    >
      <div
        className="bg-bg border border-border rounded-xl shadow-2xl animate-fade-in flex flex-col"
        style={{ width: 480, maxHeight: '80vh' }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-border shrink-0">
          <span className="font-mono text-[10px] tracking-[0.25em] uppercase text-text-secondary">
            Upload Batch
          </span>
          <button onClick={closeModal} className="text-text-muted hover:text-text-primary transition-colors">
            <X size={16} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4 flex flex-col gap-4">
          {/* Drop zone — shown until done */}
          {state.status !== 'done' && (
            <div
              onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
              onDragLeave={() => setDragging(false)}
              onDrop={onDrop}
              onClick={() => inputRef.current?.click()}
              className={`border-2 border-dashed rounded-lg px-6 py-8 text-center cursor-pointer transition-colors ${
                dragging
                  ? 'border-accent bg-accent/5'
                  : 'border-border hover:border-border-bright hover:bg-surface-2'
              }`}
            >
              <Upload size={20} className="mx-auto mb-2 text-text-muted" />
              <p className="text-sm text-text-secondary">
                Drop images here or <span className="text-accent">browse</span>
              </p>
              <p className="font-mono text-[10px] text-text-muted mt-1">
                JPG · PNG · WebP
              </p>
              <input
                ref={inputRef}
                type="file"
                multiple
                accept="image/jpeg,image/png,image/webp"
                className="hidden"
                onChange={onFileInput}
              />
            </div>
          )}

          {/* File list preview */}
          {(state.status === 'selecting' || state.status === 'uploading') && files.length > 0 && (
            <div className="space-y-1">
              <p className="font-mono text-[10px] tracking-widest uppercase text-text-muted mb-2">
                {files.length} file{files.length !== 1 ? 's' : ''} selected
              </p>
              <div className="max-h-40 overflow-y-auto space-y-1">
                {files.map((f) => (
                  <div key={f.name} className="flex items-center gap-2 font-mono text-xs text-text-secondary">
                    <span className="w-1.5 h-1.5 rounded-full bg-border-bright shrink-0" />
                    <span className="truncate">{f.name}</span>
                    <span className="text-text-muted shrink-0">
                      {(f.size / 1024).toFixed(0)}KB
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Uploading */}
          {state.status === 'uploading' && (
            <div className="flex items-center gap-3">
              <div className="w-4 h-4 border-2 border-border border-t-accent rounded-full animate-spin-slow shrink-0" />
              <span className="font-mono text-xs text-text-secondary">Uploading…</span>
            </div>
          )}

          {/* Done */}
          {state.status === 'done' && (
            <div className="space-y-3">
              <div className="flex items-center gap-2">
                <CheckCircle size={16} className="text-status-green shrink-0" />
                <span className="font-mono text-xs text-status-green">
                  {state.result.count} file{state.result.count !== 1 ? 's' : ''} uploaded
                </span>
              </div>
              <div className="bg-surface-2 border border-border rounded-lg px-4 py-3 flex items-center justify-between gap-3">
                <span className="font-mono text-xs text-text-primary break-all">
                  {state.result.path}
                </span>
                <button
                  onClick={() => copyPath(state.result.path)}
                  className="shrink-0 flex items-center gap-1.5 font-mono text-[10px] tracking-wider uppercase transition-colors text-text-secondary hover:text-accent"
                >
                  {copied ? (
                    <CheckCircle size={12} className="text-status-green" />
                  ) : (
                    <Copy size={12} />
                  )}
                  {copied ? 'Copied' : 'Copy'}
                </button>
              </div>
              {state.result.skipped.length > 0 && (
                <p className="font-mono text-[10px] text-text-muted">
                  {state.result.skipped.length} non-image file{state.result.skipped.length !== 1 ? 's' : ''} skipped
                </p>
              )}
            </div>
          )}

          {/* Error */}
          {state.status === 'error' && (
            <p className="font-mono text-xs text-status-red">{state.message}</p>
          )}
        </div>

        {/* Footer */}
        <div className="px-5 py-3 border-t border-border shrink-0 flex justify-end gap-3">
          <button
            onClick={closeModal}
            className="font-mono text-[10px] tracking-widest uppercase text-text-muted hover:text-text-secondary transition-colors px-3 py-1.5"
          >
            {state.status === 'done' ? 'Close' : 'Cancel'}
          </button>
          {state.status === 'selecting' && (
            <button
              onClick={handleUpload}
              disabled={!files.length}
              className="font-mono text-[10px] tracking-widest uppercase px-4 py-1.5 rounded border border-accent/40 text-accent hover:bg-accent/10 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            >
              Upload {files.length} file{files.length !== 1 ? 's' : ''}
            </button>
          )}
        </div>
      </div>
    </div>,
    document.body
  )
}
