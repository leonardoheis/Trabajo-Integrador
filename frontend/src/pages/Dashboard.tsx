import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Upload, FileText, CheckCircle, Clock, AlertCircle } from 'lucide-react'
import { getJobs } from '../api/client'
import { JobRecord, JobStatus, DocumentType } from '../types'
import StatusBadge from '../components/StatusBadge'

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString('es-AR', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function truncateId(id: string): string {
  return id.length > 8 ? `${id.slice(0, 8)}…` : id
}

export default function Dashboard() {
  const [jobs, setJobs] = useState<JobRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getJobs(50, 0)
      .then(setJobs)
      .catch(() => setError('Error al cargar los datos'))
      .finally(() => setLoading(false))
  }, [])

  const total = jobs.length
  const done = jobs.filter((j) => j.status === JobStatus.DONE).length
  const pending = jobs.filter((j) =>
    [JobStatus.PENDING, JobStatus.INGESTING, JobStatus.ANALYZING, JobStatus.ORCHESTRATING, JobStatus.ROUTING].includes(j.status)
  ).length
  const failed = jobs.filter((j) => j.status === JobStatus.FAILED).length

  const byCategory = jobs.reduce<Record<string, number>>((acc, j) => {
    if (j.document_type) {
      acc[j.document_type] = (acc[j.document_type] ?? 0) + 1
    }
    return acc
  }, {})

  const recentJobs = [...jobs].sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()).slice(0, 5)

  const CATEGORY_LABELS: Record<DocumentType, string> = {
    [DocumentType.INVOICE]: 'Factura',
    [DocumentType.CONTRACT]: 'Contrato',
    [DocumentType.REPORT]: 'Reporte',
    [DocumentType.IDENTIFICATION]: 'Identificación',
    [DocumentType.FORM]: 'Formulario',
    [DocumentType.LETTER]: 'Carta',
    [DocumentType.RECEIPT]: 'Recibo',
    [DocumentType.OTHER]: 'Otro',
  }

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>
          <p className="text-sm text-gray-500 mt-1">Resumen general del sistema de clasificación</p>
        </div>
        <Link
          to="/upload"
          className="inline-flex items-center gap-2 bg-indigo-600 hover:bg-indigo-700 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors"
        >
          <Upload className="w-4 h-4" />
          Subir documento
        </Link>
      </div>

      {error && (
        <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">
          {error}
        </div>
      )}

      {/* Stats cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <div className="bg-white rounded-xl border border-gray-200 p-5 flex items-center gap-4">
          <div className="p-2 bg-indigo-50 rounded-lg">
            <FileText className="w-6 h-6 text-indigo-600" />
          </div>
          <div>
            <p className="text-sm text-gray-500">Total procesados</p>
            <p className="text-2xl font-bold text-gray-900">{loading ? '—' : total}</p>
          </div>
        </div>

        <div className="bg-white rounded-xl border border-gray-200 p-5 flex items-center gap-4">
          <div className="p-2 bg-green-50 rounded-lg">
            <CheckCircle className="w-6 h-6 text-green-600" />
          </div>
          <div>
            <p className="text-sm text-gray-500">Completados</p>
            <p className="text-2xl font-bold text-green-700">{loading ? '—' : done}</p>
          </div>
        </div>

        <div className="bg-white rounded-xl border border-gray-200 p-5 flex items-center gap-4">
          <div className="p-2 bg-yellow-50 rounded-lg">
            <Clock className="w-6 h-6 text-yellow-600" />
          </div>
          <div>
            <p className="text-sm text-gray-500">En proceso</p>
            <p className="text-2xl font-bold text-yellow-700">{loading ? '—' : pending}</p>
          </div>
        </div>

        <div className="bg-white rounded-xl border border-gray-200 p-5 flex items-center gap-4">
          <div className="p-2 bg-red-50 rounded-lg">
            <AlertCircle className="w-6 h-6 text-red-600" />
          </div>
          <div>
            <p className="text-sm text-gray-500">Fallidos</p>
            <p className="text-2xl font-bold text-red-700">{loading ? '—' : failed}</p>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Recent jobs */}
        <div className="lg:col-span-2 bg-white rounded-xl border border-gray-200">
          <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-gray-900">Últimos documentos</h2>
            <Link to="/jobs" className="text-xs text-indigo-600 hover:underline">
              Ver todos
            </Link>
          </div>
          <div className="divide-y divide-gray-50">
            {loading ? (
              <div className="p-8 text-center text-gray-400 text-sm">Cargando...</div>
            ) : recentJobs.length === 0 ? (
              <div className="p-8 text-center text-gray-400 text-sm">No hay documentos aún</div>
            ) : (
              recentJobs.map((job) => (
                <Link
                  key={job.job_id}
                  to={`/jobs/${job.job_id}`}
                  className="flex items-center justify-between px-5 py-3 hover:bg-gray-50 transition-colors"
                >
                  <div className="flex items-center gap-3 min-w-0">
                    <FileText className="w-4 h-4 text-gray-400 flex-shrink-0" />
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-gray-900 truncate">{job.filename}</p>
                      <p className="text-xs text-gray-400">
                        {truncateId(job.job_id)} · {formatDate(job.created_at)}
                      </p>
                    </div>
                  </div>
                  <StatusBadge status={job.status} />
                </Link>
              ))
            )}
          </div>
        </div>

        {/* By category */}
        <div className="bg-white rounded-xl border border-gray-200">
          <div className="px-5 py-4 border-b border-gray-100">
            <h2 className="text-sm font-semibold text-gray-900">Por categoría</h2>
          </div>
          <div className="p-5 space-y-3">
            {loading ? (
              <div className="text-center text-gray-400 text-sm py-4">Cargando...</div>
            ) : Object.keys(byCategory).length === 0 ? (
              <div className="text-center text-gray-400 text-sm py-4">Sin datos</div>
            ) : (
              Object.entries(byCategory)
                .sort((a, b) => b[1] - a[1])
                .map(([type, count]) => (
                  <div key={type}>
                    <div className="flex items-center justify-between text-sm mb-1">
                      <span className="text-gray-600">{CATEGORY_LABELS[type as DocumentType] ?? type}</span>
                      <span className="font-semibold text-gray-900">{count}</span>
                    </div>
                    <div className="w-full bg-gray-100 rounded-full h-1.5">
                      <div
                        className="bg-indigo-500 h-1.5 rounded-full"
                        style={{ width: `${total > 0 ? (count / total) * 100 : 0}%` }}
                      />
                    </div>
                  </div>
                ))
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
