import { useEffect, useRef, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { ArrowLeft, CheckCircle, Circle, Loader, AlertCircle, Tag, FolderOpen } from 'lucide-react'
import { getJob, createJobWebSocket } from '../api/client'
import { JobRecord, JobStatus } from '../types'
import StatusBadge from '../components/StatusBadge'
import ConfidenceBar from '../components/ConfidenceBar'

const STAGES: JobStatus[] = [
  JobStatus.PENDING,
  JobStatus.INGESTING,
  JobStatus.ANALYZING,
  JobStatus.ORCHESTRATING,
  JobStatus.ROUTING,
  JobStatus.DONE,
]

const STAGE_LABELS: Record<JobStatus, string> = {
  [JobStatus.PENDING]: 'Pendiente',
  [JobStatus.INGESTING]: 'Ingresando',
  [JobStatus.ANALYZING]: 'Analizando',
  [JobStatus.ORCHESTRATING]: 'Orquestando',
  [JobStatus.ROUTING]: 'Enrutando',
  [JobStatus.DONE]: 'Completado',
  [JobStatus.FAILED]: 'Fallido',
}

function stageIndex(status: JobStatus): number {
  const idx = STAGES.indexOf(status)
  return idx === -1 ? -1 : idx
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString('es-AR', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

export default function JobDetailPage() {
  const { id } = useParams<{ id: string }>()
  const [job, setJob] = useState<JobRecord | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const wsRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    if (!id) return

    getJob(id)
      .then((data) => {
        setJob(data)
        setLoading(false)
      })
      .catch(() => {
        setError('Error al cargar el job')
        setLoading(false)
      })
  }, [id])

  // WebSocket for live updates
  useEffect(() => {
    if (!id) return

    const ws = createJobWebSocket(id)
    wsRef.current = ws

    ws.onmessage = (event: MessageEvent) => {
      try {
        const updated: JobRecord = JSON.parse(event.data as string)
        setJob(updated)
        // Close WS when terminal state reached
        if (updated.status === JobStatus.DONE || updated.status === JobStatus.FAILED) {
          ws.close()
        }
      } catch {
        // Ignore malformed messages
      }
    }

    ws.onerror = () => {
      // WebSocket unavailable — fall back to polling
      ws.close()
    }

    return () => {
      ws.close()
    }
  }, [id])

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader className="w-6 h-6 text-indigo-500 animate-spin" />
      </div>
    )
  }

  if (error || !job) {
    return (
      <div className="max-w-3xl mx-auto px-4 py-8">
        <div className="p-4 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">
          {error ?? 'Job no encontrado'}
        </div>
        <Link to="/jobs" className="mt-4 inline-flex items-center gap-1 text-sm text-indigo-600 hover:underline">
          <ArrowLeft className="w-4 h-4" /> Volver a Jobs
        </Link>
      </div>
    )
  }

  const currentIdx = stageIndex(job.status)
  const isFailed = job.status === JobStatus.FAILED
  const result = job.analysis_result

  return (
    <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      {/* Header */}
      <div className="mb-6">
        <Link to="/jobs" className="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700 mb-3">
          <ArrowLeft className="w-4 h-4" />
          Volver a Jobs
        </Link>
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-xl font-bold text-gray-900 break-all">{job.filename}</h1>
            <p className="text-xs text-gray-400 mt-0.5 font-mono">{job.job_id}</p>
            <p className="text-xs text-gray-400 mt-0.5">Creado: {formatDate(job.created_at)}</p>
          </div>
          <StatusBadge status={job.status} className="flex-shrink-0 text-sm px-3 py-1" />
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Timeline */}
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <h2 className="text-sm font-semibold text-gray-900 mb-4">Progreso</h2>
          <div className="space-y-0">
            {STAGES.map((stage, idx) => {
              const isDone = !isFailed && idx < currentIdx
              const isActive = !isFailed && idx === currentIdx
              const isPending = isFailed ? false : idx > currentIdx

              return (
                <div key={stage} className="flex items-start gap-3">
                  <div className="flex flex-col items-center">
                    <div
                      className={`w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0 ${
                        isDone
                          ? 'bg-green-100 text-green-600'
                          : isActive && !isFailed
                          ? 'bg-indigo-100 text-indigo-600'
                          : 'bg-gray-100 text-gray-400'
                      }`}
                    >
                      {isDone ? (
                        <CheckCircle className="w-4 h-4" />
                      ) : isActive ? (
                        <Loader className="w-3.5 h-3.5 animate-spin" />
                      ) : (
                        <Circle className="w-3.5 h-3.5" />
                      )}
                    </div>
                    {idx < STAGES.length - 1 && (
                      <div
                        className={`w-px flex-1 my-1 ${isDone ? 'bg-green-300' : 'bg-gray-200'}`}
                        style={{ minHeight: '16px' }}
                      />
                    )}
                  </div>
                  <div className="pb-4">
                    <p
                      className={`text-sm font-medium ${
                        isDone
                          ? 'text-green-700'
                          : isActive
                          ? 'text-indigo-700'
                          : isPending
                          ? 'text-gray-400'
                          : 'text-gray-500'
                      }`}
                    >
                      {STAGE_LABELS[stage]}
                    </p>
                  </div>
                </div>
              )
            })}

            {/* Failed state */}
            {isFailed && (
              <div className="flex items-start gap-3 mt-1">
                <div className="w-6 h-6 rounded-full flex items-center justify-center bg-red-100 text-red-600 flex-shrink-0">
                  <AlertCircle className="w-4 h-4" />
                </div>
                <div>
                  <p className="text-sm font-medium text-red-700">Error</p>
                  {job.error_message && (
                    <p className="text-xs text-red-500 mt-0.5 break-all">{job.error_message}</p>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Results */}
        <div className="lg:col-span-2 space-y-4">
          {result ? (
            <>
              {/* Confidence */}
              <div className="bg-white rounded-xl border border-gray-200 p-5">
                <h2 className="text-sm font-semibold text-gray-900 mb-3">Resultado del análisis</h2>
                <ConfidenceBar value={result.confidence} className="mb-4" />
                <div className="grid grid-cols-2 gap-3 text-sm">
                  <div>
                    <p className="text-xs text-gray-400 uppercase tracking-wide">Tipo</p>
                    <p className="text-gray-900 font-medium mt-0.5">{result.document_type ?? '—'}</p>
                  </div>
                  <div>
                    <p className="text-xs text-gray-400 uppercase tracking-wide">Idioma</p>
                    <p className="text-gray-900 font-medium mt-0.5">{result.language ?? '—'}</p>
                  </div>
                  <div>
                    <p className="text-xs text-gray-400 uppercase tracking-wide">Páginas</p>
                    <p className="text-gray-900 font-medium mt-0.5">{result.page_count ?? '—'}</p>
                  </div>
                  {job.output_path && (
                    <div className="col-span-2">
                      <p className="text-xs text-gray-400 uppercase tracking-wide flex items-center gap-1">
                        <FolderOpen className="w-3 h-3" /> Ruta de salida
                      </p>
                      <p className="text-gray-900 font-mono text-xs mt-0.5 break-all">{job.output_path}</p>
                    </div>
                  )}
                </div>
              </div>

              {/* Tags */}
              {result.tags && result.tags.length > 0 && (
                <div className="bg-white rounded-xl border border-gray-200 p-5">
                  <h2 className="text-sm font-semibold text-gray-900 mb-3 flex items-center gap-1.5">
                    <Tag className="w-4 h-4 text-gray-400" />
                    Tags
                  </h2>
                  <div className="flex flex-wrap gap-2">
                    {result.tags.map((tag) => (
                      <span
                        key={tag}
                        className="px-2.5 py-0.5 bg-indigo-50 text-indigo-700 text-xs rounded-full border border-indigo-100"
                      >
                        {tag}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Extracted fields */}
              {result.extracted_fields && Object.keys(result.extracted_fields).length > 0 && (
                <div className="bg-white rounded-xl border border-gray-200 p-5">
                  <h2 className="text-sm font-semibold text-gray-900 mb-3">Campos extraídos</h2>
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b border-gray-100">
                          <th className="text-left py-2 pr-4 text-xs font-semibold text-gray-500 uppercase tracking-wide w-1/3">
                            Campo
                          </th>
                          <th className="text-left py-2 text-xs font-semibold text-gray-500 uppercase tracking-wide">
                            Valor
                          </th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-gray-50">
                        {Object.entries(result.extracted_fields).map(([key, value]) => (
                          <tr key={key}>
                            <td className="py-2 pr-4 text-gray-500 font-medium text-xs">{key}</td>
                            <td className="py-2 text-gray-900 text-xs break-all">
                              {value === null ? '—' : String(value)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </>
          ) : (
            <div className="bg-white rounded-xl border border-gray-200 p-8 text-center text-gray-400 text-sm">
              {isFailed
                ? 'No hay resultados disponibles debido al error.'
                : 'Los resultados aparecerán cuando el análisis termine.'}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
