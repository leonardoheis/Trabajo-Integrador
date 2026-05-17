import { useCallback, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Upload, FileText, X, AlertCircle } from 'lucide-react'
import { uploadDocument } from '../api/client'

const ACCEPTED_TYPES: Record<string, string> = {
  'application/pdf': 'PDF',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'DOCX',
  'image/jpeg': 'JPG',
  'image/png': 'PNG',
  'image/tiff': 'TIFF',
}

const ACCEPTED_EXTENSIONS = '.pdf,.docx,.jpg,.jpeg,.png,.tiff,.tif'

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export default function UploadPage() {
  const navigate = useNavigate()
  const inputRef = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [dragOver, setDragOver] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const validateFile = (f: File): string | null => {
    if (!Object.keys(ACCEPTED_TYPES).includes(f.type)) {
      return `Tipo de archivo no soportado: ${f.type || f.name.split('.').pop()}. Use PDF, DOCX, JPG, PNG o TIFF.`
    }
    if (f.size > 50 * 1024 * 1024) {
      return 'El archivo supera el límite de 50 MB.'
    }
    return null
  }

  const handleFile = (f: File) => {
    const err = validateFile(f)
    if (err) {
      setError(err)
      setFile(null)
      return
    }
    setError(null)
    setFile(f)
  }

  const onDrop = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setDragOver(false)
    const dropped = e.dataTransfer.files[0]
    if (dropped) handleFile(dropped)
  }, [])

  const onDragOver = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setDragOver(true)
  }

  const onDragLeave = () => setDragOver(false)

  const onInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selected = e.target.files?.[0]
    if (selected) handleFile(selected)
  }

  const handleUpload = async () => {
    if (!file) return
    setUploading(true)
    setError(null)
    try {
      const { job_id } = await uploadDocument(file)
      navigate(`/jobs/${job_id}`)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Error desconocido al subir el archivo.'
      setError(`Error al subir: ${msg}`)
      setUploading(false)
    }
  }

  const fileTypeLabel = file ? (ACCEPTED_TYPES[file.type] ?? file.name.split('.').pop()?.toUpperCase() ?? 'Desconocido') : ''

  return (
    <div className="max-w-2xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Subir documento</h1>
        <p className="text-sm text-gray-500 mt-1">PDF, DOCX, JPG, PNG o TIFF · Máximo 50 MB</p>
      </div>

      {/* Dropzone */}
      <div
        onDrop={onDrop}
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        onClick={() => !file && inputRef.current?.click()}
        className={`relative border-2 border-dashed rounded-xl p-10 text-center transition-colors cursor-pointer ${
          dragOver
            ? 'border-indigo-400 bg-indigo-50'
            : file
            ? 'border-green-400 bg-green-50 cursor-default'
            : 'border-gray-300 bg-gray-50 hover:border-indigo-300 hover:bg-indigo-50'
        }`}
      >
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPTED_EXTENSIONS}
          className="hidden"
          onChange={onInputChange}
        />

        {file ? (
          <div className="flex flex-col items-center gap-3">
            <FileText className="w-12 h-12 text-green-500" />
            <div>
              <p className="text-base font-semibold text-gray-900 break-all">{file.name}</p>
              <p className="text-sm text-gray-500 mt-0.5">
                {fileTypeLabel} · {formatSize(file.size)}
              </p>
            </div>
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation()
                setFile(null)
                setError(null)
                if (inputRef.current) inputRef.current.value = ''
              }}
              className="mt-1 inline-flex items-center gap-1 text-xs text-red-500 hover:text-red-700 transition-colors"
            >
              <X className="w-3 h-3" />
              Quitar archivo
            </button>
          </div>
        ) : (
          <div className="flex flex-col items-center gap-3">
            <Upload className={`w-12 h-12 ${dragOver ? 'text-indigo-500' : 'text-gray-400'}`} />
            <div>
              <p className="text-base font-medium text-gray-700">
                Arrastrá y soltá tu archivo aquí
              </p>
              <p className="text-sm text-gray-400 mt-0.5">o hacé clic para seleccionar</p>
            </div>
            <p className="text-xs text-gray-400">PDF · DOCX · JPG · PNG · TIFF</p>
          </div>
        )}
      </div>

      {/* Error */}
      {error && (
        <div className="mt-4 flex items-start gap-2 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
          <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      {/* Upload button */}
      <div className="mt-6 flex justify-end">
        <button
          type="button"
          disabled={!file || uploading}
          onClick={handleUpload}
          className="inline-flex items-center gap-2 bg-indigo-600 hover:bg-indigo-700 disabled:bg-indigo-300 disabled:cursor-not-allowed text-white px-6 py-2.5 rounded-lg text-sm font-medium transition-colors"
        >
          {uploading ? (
            <>
              <svg className="animate-spin w-4 h-4" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
              </svg>
              Subiendo...
            </>
          ) : (
            <>
              <Upload className="w-4 h-4" />
              Subir documento
            </>
          )}
        </button>
      </div>
    </div>
  )
}
