import { createMemo, For } from 'solid-js';

// Dependency-free SVG micro-charts. The geometry is a memo over the series,
// so a refreshed query recomputes one `d` attribute — not a chart library's
// whole scene graph.

export function Sparkline(props: { values: Array<number>; label: string; height?: number }) {
  const geometry = createMemo(() => {
    const v = props.values;
    const max = Math.max(...v, 1);
    const min = Math.min(...v, 0);
    const span = max - min || 1;
    const step = 100 / Math.max(v.length - 1, 1);
    const points = v.map((y, i) => [i * step, 30 - ((y - min) / span) * 26 - 2] as const);
    const line = points.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(2)},${y.toFixed(2)}`).join('');
    const last = points.at(-1) ?? [0, 0];
    return { line, area: `${line}L100,32L0,32Z`, last };
  });

  return (
    <svg
      class="spark"
      viewBox="0 0 100 32"
      preserveAspectRatio="none"
      style={{ height: `${props.height ?? 36}px` }}
      role="img"
      aria-label={props.label}
    >
      <path class="spark-area" d={geometry().area} />
      <path class="spark-line" d={geometry().line} vector-effect="non-scaling-stroke" />
      <circle class="spark-dot" cx={geometry().last[0]} cy={geometry().last[1]} r="1.6" />
    </svg>
  );
}

export function Bars(props: { values: Array<number>; label: string }) {
  const max = createMemo(() => Math.max(...props.values, 1));
  return (
    <div class="bars" role="img" aria-label={props.label}>
      <For each={props.values} keyed={false}>
        {(v) => <span style={{ '--h': `${Math.max(4, (v() / max()) * 100)}%` }} title={String(v())} />}
      </For>
    </div>
  );
}

/** A radial gauge for "used of limit" meters. */
export function Ring(props: { value: number; size?: number }) {
  const r = 15.915;
  return (
    <svg class="ring" viewBox="0 0 36 36" width={props.size ?? 44} height={props.size ?? 44} aria-hidden="true">
      <circle class="ring-track" cx="18" cy="18" r={r} />
      <circle
        class={['ring-fill', { hot: props.value >= 85 }]}
        cx="18"
        cy="18"
        r={r}
        stroke-dasharray={`${props.value} ${100 - props.value}`}
        stroke-dashoffset="25"
      />
    </svg>
  );
}
