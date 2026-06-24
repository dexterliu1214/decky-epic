import { metacriticColor } from "../util/format";

export function MetacriticBadge({ score, size = 28 }: { score: number | null | undefined; size?: number }) {
  const label = score == null ? "–" : `${score}`;
  return (
    <div
      style={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        minWidth: size,
        height: size,
        padding: "0 6px",
        borderRadius: 4,
        background: metacriticColor(score),
        color: "#fff",
        fontWeight: 700,
        fontSize: size * 0.5,
        lineHeight: 1,
      }}
      title={score == null ? "No Metacritic score" : `Metacritic ${score}`}
    >
      {label}
    </div>
  );
}
