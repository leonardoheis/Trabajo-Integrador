import { useEffect, useState, useMemo } from 'react'
import { Download, Search, RefreshCw } from 'lucide-react'
import { getAuditLog } from '../api/client'
import { AuditEntry } from '../types'

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

function truncateId(id: string): string {
  return id.length > 12 ? `${id.slice(0, 12)}…` : id
}

export default function AuditPage() {
  const [entries, setEntries] = useState<AuditEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')

  const fetchLog = async () => {
    setLoading(true)
    try {
      const data = await getAuditLog(500)
      setEntries(data)
      setError(null)
    } catch {
      setError('Error al cargar el audit log')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchLog()
  }, [])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return entries
    return entries.filter(
      (e) =>
        e.job_id.toLowerCase().includes(q) ||
        e.event.toLowerCase().includes(q)
    )
  }, [entries, search])

  const handleDownload = () => {
    const jsonl = filtered.map((e) => JSON.stringify(e)).join('\n')
    const blob = new Blob([jsonl], { type: 'application/x-ndjson' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `audit_log_${new Date().toISOString().slice(0, 10)}.jsonl`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Audit Log</h1>
          <p className="text-sm text-gray-500 mt-1">
            {loading ? 'Cargando...' : `${filtered.length} evento${filtered.length !== 1 ? 's' : ''}${search ? ' (filtrados)' : ''}`}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={fetchLog}
            className="inline-flex items-center gap-1.5 text-sm text-gray-600 hover:text-gray-900 px-3 py-1.5 border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            Actualizar
          </button>
          <button
            onClick={handleDownload}
            disabled={filtered.length === 0}
            className="inline-flex items-center gap-1.5 bg-indigo-600 hover:bg-indigo-700 disabled:bg-indigo-300 disabled:cursor-not-allowed text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors"
          >
            <Download className="w-4 h-4" />
            Descargar JSONL
          </button>
        </div>
      </div>

      {/* Search */}
      <div className="mb-4 relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" />
        <input
          type="text"
          placeholder="Filtrar por Job ID o evento..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="w-full pl-9 pr-4 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-300 focus:border-indigo-400"
        />
        {search && (
          <button
            onClick={() => setSearch('')}
            className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 text-xs"
          >
            Limpiar
          </button>
        )}
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">
          {error}
        </div>
      )}

      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200">
                <th className="text-left px-4 py-3 font-semibold text-gray-600 w-8">#</th>
                <th className="text-left px-4 py-3 font-semibold text-gray-600">Fecha/Hora</th>
                <th className="text-left px-4 py-3 font-semibold text-gray-600">Job ID</th>
                <th className="text-left px-4 py-3 font-semibold text-gray-600">Evento</th>
                <th className="text-left px-4 py-3 font-semibold text-gray-600">Detalle</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {loading ? (
                <tr>
                  <td colSpan={5} className="text-center py-10 text-gray-400">
                    Cargando...
                  </td>
                </tr>
              ) : filtered.length === 0 ? (
                <tr>
                  <td colSpan={5} className="text-center py-10 text-gray-400">
                    {search ? 'Sin resultados para la búsqueda.' : 'No hay eventos en el log.'}
                  </td>
                </tr>
              ) : (
                filtered.map((entry) => (
                  <tr key={entry.id} className="hover:bg-gray-50 transition-colors">
                    <td className="px-4 py-2.5 text-gray-400 text-xs">{entry.id}</td>
                    <td className="px-4 py-2.5 text-gray-500 whitespace-nowrap text-xs">
                      {formatDate(entry.timestamp)}
                    </td>
                    <td className="px-4 py-2.5 font-mono text-xs text-indigo-600">
                      {truncateId(entry.job_id)}
                    </td>
                    <td className="px-4 py-2.5 font-medium text-gray-900">{entry.event}</td>
                    <td className="px-4 py-2.5 text-gray-500 text-xs max-w-xs">
                      {entry.detail ? (
                        <code className="break-all whitespace-pre-wrap text-xs text-gray-500">
                          {JSON.stringify(entry.detail, null, 0).slice(0, 120)}
                          {JSON.stringify(entry.detail).length > 120 ? '…' : ''}
                        </code>
                      ) : (
                        '—'
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
