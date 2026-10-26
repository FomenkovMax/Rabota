/** Скелетон: мерцающие плашки на месте будущего контента (вместо «Загрузка…»). */
export function Skeleton({ blocks = [72, 160, 120] }: { blocks?: number[] }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }} aria-busy="true" aria-label="Загрузка">
      {blocks.map((h, i) => <div key={i} className="skeleton" style={{ height: h }} />)}
    </div>
  );
}
