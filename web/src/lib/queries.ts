"use client";

/** Data hooks for every page. Polling and cache updates happen here, so pages stay simple. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  api,
  type DocumentRecord,
  type Draft,
  type Run,
  type RunStatus,
  type SiteConfig,
  toApiError,
  unwrap,
} from "./api";

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

/** A finished run's written report (Markdown), e.g. a content plan. */
export function useRunReport(run: Run | undefined) {
  return useQuery({
    queryKey: ["report", run?.id],
    queryFn: async () => {
      const response = await fetch(`/api/runs/${encodeURIComponent(run!.id)}/report`);
      if (!response.ok) throw toApiError(response.status, await response.json().catch(() => null));
      return response.text();
    },
    enabled: run?.status === "done" && Boolean(run.report),
    staleTime: Infinity,
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

// --- Content editor ------------------------------------------------------------------

export function useDocuments() {
  return useQuery({
    queryKey: ["documents"],
    queryFn: () => unwrap(api.GET("/api/documents")),
  });
}

export function useDocument(id: string) {
  return useQuery({
    queryKey: ["document", id],
    queryFn: () => unwrap(api.GET("/api/documents/{doc_id}", { params: { path: { doc_id: id } } })),
    staleTime: Infinity, // the editor holds the live copy; this is only the starting point
  });
}

export function useCreateDocument() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { keyword: string; site?: string; pages: string[]; import_url?: string | null }) =>
      unwrap(api.POST("/api/documents", { body })),
    onSuccess: (doc) => {
      queryClient.setQueryData(["document", doc.id], doc);
      queryClient.invalidateQueries({ queryKey: ["documents"] });
    },
  });
}

export function useDeleteDocument() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      const { error, response } = await api.DELETE("/api/documents/{doc_id}", {
        params: { path: { doc_id: id } },
      });
      if (!response.ok) throw toApiError(response.status, error);
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["documents"] }),
  });
}

/** Save the draft. The saved record isn't written back into the editor (it already has it). */
export function useSaveDocument(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (draft: Draft) =>
      unwrap(api.PUT("/api/documents/{doc_id}", { params: { path: { doc_id: id } }, body: draft })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["documents"] }),
  });
}

/** The draft's brief, polled while it's being built. */
export function useBrief(id: string) {
  return useQuery({
    queryKey: ["brief", id],
    queryFn: () =>
      unwrap(api.GET("/api/documents/{doc_id}/brief", { params: { path: { doc_id: id } } })),
    refetchInterval: (query) => (isActive(query.state.data?.run ?? undefined) ? 1000 : false),
  });
}

export function useRebuildBrief(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (pages: string[]) =>
      unwrap(
        api.POST("/api/documents/{doc_id}/brief", {
          params: { path: { doc_id: id } },
          body: { pages },
        }),
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["brief", id] }),
  });
}

/**
 * The live score for what's in the editor. `version` is the draft's fingerprint, so each
 * version is scored once and the last score stays on screen while the next one loads.
 */
export function useScore(id: string, draft: Draft, version: string, ready: boolean) {
  return useQuery({
    queryKey: ["score", id, version],
    queryFn: () =>
      unwrap(
        api.POST("/api/documents/{doc_id}/score", { params: { path: { doc_id: id } }, body: draft }),
      ),
    enabled: ready,
    placeholderData: (previous) => previous,
    staleTime: Infinity,
  });
}

/** Ask Gemini whether each question is answered. Saves the draft too. */
export function useCheckAnswers(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (draft: Draft) =>
      unwrap(
        api.POST("/api/documents/{doc_id}/check-answers", {
          params: { path: { doc_id: id } },
          body: draft,
        }),
      ),
    onSuccess: (doc: DocumentRecord) => {
      queryClient.invalidateQueries({ queryKey: ["score", id] });
      queryClient.invalidateQueries({ queryKey: ["documents"] });
      queryClient.setQueryData(["document", id], doc);
    },
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
