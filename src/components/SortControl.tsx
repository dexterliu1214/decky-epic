import { Dropdown } from "@decky/ui";
import type { SortMode } from "../types";

const OPTIONS: { data: SortMode; label: string }[] = [
  { data: "metacritic", label: "Metacritic ↓" },
  { data: "steam", label: "Steam reviews ↓" },
  { data: "title", label: "Title A–Z" },
  { data: "installed", label: "Installed first" },
];

export function SortControl({ value, onChange }: { value: SortMode; onChange: (m: SortMode) => void }) {
  return (
    <div style={{ minWidth: 220 }}>
      <Dropdown
        rgOptions={OPTIONS.map((o) => ({ data: o.data, label: o.label }))}
        selectedOption={value}
        onChange={(o) => onChange(o.data as SortMode)}
        strDefaultLabel="Sort by"
      />
    </div>
  );
}
