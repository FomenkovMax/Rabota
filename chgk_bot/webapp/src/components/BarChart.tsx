/** Столбики по дням: синий — сыграно, зелёный — взято. Чистый SVG (Recharts не тянем ради одного графика). */
export function BarChart({ data }: { data: { date: string; played: number; correct: number }[] }) {
  const W = 320, H = 120, mx = Math.max(1, ...data.map((d) => d.played));
  const bw = W / data.length;
  return (
    <svg viewBox={`0 0 ${W} ${H + 18}`} width="100%" role="img" aria-label="Сыграно и взято по дням">
      {data.map((d, i) => {
        const h = (H * d.played) / mx, hc = (H * d.correct) / mx, x = i * bw + 3, w = bw - 6;
        return (
          <g key={d.date}>
            <rect x={x} y={H - 1.5} width={w} height={1.5} fill="#3c4e8c" />
            {d.played > 0 && <rect x={x} y={H - h} width={w} height={h} rx={3} fill="#3c4e8c" />}
            {d.correct > 0 && <rect x={x} y={H - hc} width={w} height={hc} rx={3} fill="var(--ok)" />}
            {(i === 0 || i === data.length - 1) && (
              <text x={x + w / 2} y={H + 14} textAnchor="middle" fontSize="10" fill="var(--text-dim)">{d.date.slice(8)}.{d.date.slice(5, 7)}</text>
            )}
          </g>
        );
      })}
    </svg>
  );
}
