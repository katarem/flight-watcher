import { useId } from 'react'

/** Minigráfica del precio mínimo por comprobación (decorativa: el dato está en el texto de al lado).
 *  SVG propio para no cargar la librería de gráficas en el panel. */
export function Sparkline({ data, width = 112, height = 40 }: { data: { d: string; p: number }[]; width?: number; height?: number }) {
  const id = useId().replace(/:/g, '')
  if (data.length < 2) return null
  const values = data.map((x) => x.p)
  const lo = Math.min(...values)
  const span = Math.max(...values) - lo || 1
  const pts = values.map((v, i) => [(i / (values.length - 1)) * width, 3 + (1 - (v - lo) / span) * (height - 6)])
  const line = pts.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ')
  const color = values[values.length - 1] <= values[0] ? 'var(--fw-deal)' : 'var(--fw-danger)'
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden="true" className="overflow-visible">
      <defs>
        <linearGradient id={`g${id}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity={0.3} />
          <stop offset="100%" stopColor={color} stopOpacity={0} />
        </linearGradient>
      </defs>
      <path d={`${line} L${width},${height} L0,${height} Z`} fill={`url(#g${id})`} />
      <path d={line} fill="none" stroke={color} strokeWidth={1.75} strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={pts[pts.length - 1][0]} cy={pts[pts.length - 1][1]} r={2.5} fill={color} />
    </svg>
  )
}
