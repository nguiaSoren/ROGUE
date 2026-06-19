/**
 * Animated 4-stage pipeline visualization for the home page hero.
 *
 *   [19 sources]  →  [harvest]  →  [reproduce 5-panel]  →  [judge]
 *
 * Pure SVG + CSS animations, server component, zero JS. The "moving pulses"
 * are repeating <circle> elements animated along the connecting paths via
 * SMIL `animateMotion`. SMIL is well supported in modern browsers and
 * doesn't require JS scheduling.
 *
 * The four stage counters come from /api/health (passed in as props).
 */
export function PipelineFlow({
  nSources = 19,
  nPrimitives,
  nConfigs,
  nBreaches,
}: {
  nSources?: number;
  nPrimitives: number | null;
  nConfigs: number | null;
  nBreaches: number | null;
}) {
  const stages = [
    {
      key: "sources",
      label: "open-web sources",
      value: nSources,
      sub: "5 Bright Data products",
      color: "var(--rogue-green)",
      x: 60,
    },
    {
      key: "harvest",
      label: "attack primitives",
      value: nPrimitives,
      sub: "extracted + canonicalized",
      color: "#a78bfa",
      x: 260,
    },
    {
      key: "reproduce",
      label: "panel reps",
      value: nConfigs,
      sub: "model × system prompt",
      color: "#22d3ee",
      x: 460,
    },
    {
      key: "judge",
      label: "breach trials",
      value: nBreaches,
      sub: "auto-judged",
      color: "var(--rogue-red)",
      x: 660,
    },
  ];

  return (
    <div className="w-full overflow-x-auto">
      <svg
        viewBox="0 0 720 200"
        className="w-full min-w-[600px]"
        style={{ height: "auto" }}
        role="img"
        aria-label="ROGUE pipeline: sources to harvest to reproduce to judge"
      >
        <defs>
          {stages.map((s, i) => {
            if (i === stages.length - 1) return null;
            const next = stages[i + 1];
            return (
              <linearGradient
                key={`grad-${s.key}`}
                id={`flow-${s.key}`}
                x1="0"
                y1="0"
                x2="1"
                y2="0"
              >
                <stop offset="0%" stopColor={s.color} stopOpacity={0.6} />
                <stop offset="100%" stopColor={next.color} stopOpacity={0.6} />
              </linearGradient>
            );
          })}
        </defs>

        {/* Connecting lines */}
        {stages.map((s, i) => {
          if (i === stages.length - 1) return null;
          const next = stages[i + 1];
          return (
            <line
              key={`line-${s.key}`}
              x1={s.x + 28}
              y1={100}
              x2={next.x - 28}
              y2={100}
              stroke={`url(#flow-${s.key})`}
              strokeWidth={1.5}
              strokeDasharray="2 4"
            />
          );
        })}

        {/* Traveling pulses along each segment */}
        {stages.map((s, i) => {
          if (i === stages.length - 1) return null;
          const next = stages[i + 1];
          return (
            <circle key={`pulse-${s.key}`} r={3} fill={next.color} opacity={0.9}>
              <animate
                attributeName="opacity"
                values="0;1;1;0"
                dur="2.4s"
                repeatCount="indefinite"
                begin={`${i * 0.6}s`}
              />
              <animateMotion
                dur="2.4s"
                repeatCount="indefinite"
                begin={`${i * 0.6}s`}
                path={`M ${s.x + 28} 100 L ${next.x - 28} 100`}
              />
            </circle>
          );
        })}

        {/* Stage nodes */}
        {stages.map((s) => (
          <g key={s.key}>
            {/* Glow ring */}
            <circle
              cx={s.x}
              cy={100}
              r={24}
              fill="none"
              stroke={s.color}
              strokeWidth={1}
              opacity={0.5}
            >
              <animate
                attributeName="r"
                values="22;28;22"
                dur="2.5s"
                repeatCount="indefinite"
              />
              <animate
                attributeName="opacity"
                values="0.5;0.1;0.5"
                dur="2.5s"
                repeatCount="indefinite"
              />
            </circle>
            {/* Solid node */}
            <circle
              cx={s.x}
              cy={100}
              r={20}
              fill={s.color}
              fillOpacity={0.15}
              stroke={s.color}
              strokeWidth={1.5}
            />
            {/* Count */}
            <text
              x={s.x}
              y={104}
              textAnchor="middle"
              fontSize={16}
              fontWeight={700}
              fill={s.color}
              fontFamily="var(--font-mono, monospace)"
            >
              {s.value ?? ", "}
            </text>
            {/* Label below */}
            <text
              x={s.x}
              y={148}
              textAnchor="middle"
              fontSize={9}
              letterSpacing={2}
              fill="rgba(255,255,255,0.85)"
              fontFamily="var(--font-mono, monospace)"
              style={{ textTransform: "uppercase" }}
            >
              {s.label}
            </text>
            <text
              x={s.x}
              y={162}
              textAnchor="middle"
              fontSize={9}
              fill="rgba(255,255,255,0.45)"
              fontFamily="var(--font-mono, monospace)"
            >
              {s.sub}
            </text>
          </g>
        ))}
      </svg>
    </div>
  );
}
