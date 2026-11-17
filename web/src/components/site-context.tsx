"use client";

/** Which site (config/sites/<name>) tools run against. Remembered between visits. */
import { createContext, type ReactNode, useContext, useEffect, useMemo, useState } from "react";

import { useSites } from "@/lib/queries";

const STORAGE_KEY = "seo-toolkit.site";

interface SiteState {
  site: string | undefined;
  setSite: (name: string) => void;
}

const SiteContext = createContext<SiteState>({ site: undefined, setSite: () => {} });

export function SiteProvider({ children }: { children: ReactNode }) {
  const sites = useSites();
  const [chosen, setChosen] = useState<string | undefined>(undefined);

  useEffect(() => {
    setChosen(window.localStorage.getItem(STORAGE_KEY) ?? undefined);
  }, []);

  const value = useMemo<SiteState>(() => {
    const names = sites.data?.sites.map((s) => s.name) ?? [];
    const site = chosen && names.includes(chosen) ? chosen : sites.data?.default || undefined;
    return {
      site,
      setSite: (name) => {
        window.localStorage.setItem(STORAGE_KEY, name);
        setChosen(name);
      },
    };
  }, [chosen, sites.data]);

  return <SiteContext.Provider value={value}>{children}</SiteContext.Provider>;
}

export function useCurrentSite(): SiteState {
  return useContext(SiteContext);
}
