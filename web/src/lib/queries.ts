"use client";

/** Data hooks for every page. Polling and cache updates happen here, so pages stay simple. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, type Run, type RunStatus, type SiteConfig, toApiError, unwrap } from "./api";

export const isActive = (run?: Pick<Run, "status">) =>
  run?.status === "queued" || run?.status === "running";

// --- Sites ---------------------------------------------------------------------------

export function useSites() {
  return useQuery({ queryKey: ["sites"], queryFn: () => unwrap(api.GET("/api/sites")) });
}

export function useSite(name: string | undefined) {
  return useQuery({
    queryKey: ["site", name],
    queryFn: () => unwrap(api.GET("/api/sites/{name}", { params: { path: { name: name! } } })),
    enabled: Boolean(name),
  });
}

export function useSaveSite(existingName?: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (site: SiteConfig) =>
      existingName
        ? unwrap(api.PUT("/api/sites/{name}", { params: { path: { name: existingName } }, body: site }))
        : unwrap(api.POST("/api/sites", { body: site })),
    onSuccess: (site) => {
      queryClient.invalidateQueries({ queryKey: ["sites"] });
      queryClient.setQueryData(["site", site.name], site);
      queryClient.invalidateQueries({ queryKey: ["checks"] });
    },
  });
}

export function useDeleteSite() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (name: string) => {
      // 204 No Content: there's no body to unwrap, so check the status directly
      const { error, response } = await api.DELETE("/api/sites/{name}", { params: { path: { name } } });
      if (!response.ok) throw toApiError(response.status, error);
    },
    onSuccess: (_, name) => {
      queryClient.removeQueries({ queryKey: ["site", name] });
      queryClient.invalidateQueries({ queryKey: ["sites"] });
      queryClient.invalidateQueries({ queryKey: ["checks"] });
    },
  });
}

// --- Tools ---------------------------------------------------------------------------

export function useTools() {
  return useQuery({ queryKey: ["tools"], queryFn: () => unwrap(api.GET("/api/tools")) });
}

export function useTool(group: string, name: string) {
  return useQuery({
    queryKey: ["tool", group, name],
    queryFn: () =>
      unwrap(api.GET("/api/tools/{group}/{name}", { params: { path: { group, name } } })),
  });
}

// --- Runs ----------------------------------------------------------------------------

export interface RunFilters {
  tool_id?: string;
  status?: RunStatus;
  site?: string;
  limit?: number;
}

export function useRuns(filters: RunFilters = {}) {
  const query = { limit: 20, ...filters };
  return useQuery({
    queryKey: ["runs", query],
    queryFn: () => unwrap(api.GET("/api/runs", { params: { query } })),
    placeholderData: (previous) => previous, // keep the table while filters change
    // Keep history fresh while something is running
    refetchInterval: (q) => (q.state.data?.some(isActive) ? 2000 : false),
  });
}

/** One run, polled twice a second until it finishes. */
export function useRun(runId: string | null) {
  const queryClient = useQueryClient();
  return useQuery({
    queryKey: ["run", runId],
    queryFn: async () => {
      const run = await unwrap(
        api.GET("/api/runs/{run_id}", { params: { path: { run_id: runId! } } }),
      );
      if (!isActive(run)) queryClient.invalidateQueries({ queryKey: ["runs"] });
      return run;
    },
    enabled: Boolean(runId),
    refetchInterval: (query) => (isActive(query.state.data) ? 500 : false),
  });
}

export function useRunRows(run: Run | undefined) {
  return useQuery({
    queryKey: ["rows", run?.id],
    queryFn: () =>
      unwrap(api.GET("/api/runs/{run_id}/rows", { params: { path: { run_id: run!.id } } })),
    enabled: run?.status === "done",
    staleTime: Infinity, // a finished run's results never change
  });
}

export function useStartRun() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      tool_id: string;
      inputs: Record<string, unknown>;
      site?: string;
      refresh?: boolean;
    }) => unwrap(api.POST("/api/runs", { body: { refresh: false, ...body } })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["runs"] }),
  });
}

// --- Setup ---------------------------------------------------------------------------

export function useChecks(site: string | undefined) {
  return useQuery({
    queryKey: ["checks", site],
    queryFn: () => unwrap(api.GET("/api/setup", { params: { query: { site } } })),
  });
}

/** One real call to each configured API. Can take up to a minute. */
export function useLiveChecks() {
  return useMutation({ mutationFn: () => unwrap(api.POST("/api/setup/live")) });
}
