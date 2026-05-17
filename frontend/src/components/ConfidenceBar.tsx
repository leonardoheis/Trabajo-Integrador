interface ConfidenceBarProps {
  value: number // 0 to 1
  className?: string
}

function getColor(value: number): string {
  const pct = value * 100
  if (pct >= 85) return 'bg-green-500'
  if (pct >= 60) return 'bg-yellow-400'
  return 'bg-red-500'
}

function getLabelColor(value: number): string {
  const pct = value * 100
  if (pct >= 85) return 'text-green-700'
  if (pct >= 60) return 'text-yellow-700'
  return 'text-red-700'
}

export default function ConfidenceBar({ value, className = '' }: ConfidenceBarProps) {
  const pct = Math.round(value * 100)
  const barColor = getColor(value)
  const labelColor = getLabelColor(value)

  return (
    <div className={`w-full ${className}`}>
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs text-gray-500">Confianza</span>
        <span className={`text-sm font-semibold ${labelColor}`}>{pct}%</span>
      </div>
      <div className="w-full bg-gray-200 rounded-full h-2.5 overflow-hidden">
        <div
          className={`h-2.5 rounded-full transition-all duration-500 ${barColor}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  )
}
