import { useCallback, useEffect, useState } from "react";
import { getSettings, setSettings } from "../api";
import type { PluginSettings } from "../types";

export function useSettings() {
  const [settings, setLocal] = useState<PluginSettings | null>(null);

  const refresh = useCallback(async () => {
    setLocal(await getSettings());
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const save = useCallback(async (patch: Partial<PluginSettings>) => {
    const updated = await setSettings(patch);
    setLocal(updated);
    return updated;
  }, []);

  return { settings, refresh, save };
}
