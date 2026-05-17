import { JobStatus } from '../types'

interface StatusBadgeProps {
  status: JobStatus
  className?: string
}

const STATUS_CONFIG: Record<JobStatus, { label: string; classes: string }> = {
  [JobStatus.PENDING]: {
    label: 'Pendiente',
    classes: 'bg-gray-100 text-gray-700 border-gray-300',
  },
  [JobStatus.INGESTING]: {
    label: 'Ingresando',
    classes: 'bg-blue-100 text-blue-700 border-blue-300',
  },
  [JobStatus.ANALYZING]: {
    label: 'Analizando',
    classes: 'bg-purple-100 text-purple-700 border-purple-300',
  },
  [JobStatus.ORCHESTRATING]: {
    label: 'Orquestando',
    classes: 'bg-yellow-100 text-yellow-700 border-yellow-300',
  },
  [JobStatus.ROUTING]: {
    label: 'Enrutando',
    classes: 'bg-orange-100 text-orange-700 border-orange-300',
  },
  [JobStatus.DONE]: {
    label: 'Completado',
    classes: 'bg-green-100 text-green-700 border-green-300',
  },
  [JobStatus.FAILED]: {
    label: 'Fallido',
    classes: 'bg-red-100 text-red-700 border-red-300',
  },
}

export default function StatusBadge({ status, className = '' }: StatusBadgeProps) {
  const config = STATUS_CONFIG[status] ?? {
    label: status,
    classes: 'bg-gray-100 text-gray-700 border-gray-300',
  }

  return (
    <span
      className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium border ${config.classes} ${className}`}
    >
      {config.label}
    </span>
  )
}
