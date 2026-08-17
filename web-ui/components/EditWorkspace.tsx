"use client";
/* eslint-disable @next/next/no-img-element */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle, Check, CircleStop, GitBranch, History, ImagePlus, Loader2,
  MemoryStick, RefreshCw, RotateCcw, Send, ShieldCheck, UploadCloud, X,
} from "lucide-react";

import {
  API_BASE, api, replayRequestFromMageEditJob, type CreateMageEditRequest,
  type MageEditCapabilities, type MageEditJob, type MageEditVariant,
} from "@/lib/api";
import { cn } from "@/lib/utils";

export interface EditSource {
  imageUrl: string;
  sourcePath?: string;
  prompt?: string;
  parentJobId?: string;
}

interface EditWorkspaceProps {
  initialSource?: EditSource | null;
  onSourceConsumed?: () => void;
}

const imageUrl = (path?: string | null) => {
  if (!path) return "";
  return path.startsWith("http") || path.startsWith("blob:") ? path : `${API_BASE}${path}`;
};

export default function EditWorkspace({ initialSource, onSourceConsumed }: EditWorkspaceProps) {
  const [capabilities, setCapabilities] = useState<MageEditCapabilities | null>(null);
  const [jobs, setJobs] = useState<MageEditJob[]>([]);
  const [selectedJob, setSelectedJob] = useState<MageEditJob | null>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [source, setSource] = useState<EditSource | null>(initialSource ?? null);
  const [previews, setPreviews] = useState<string[]>(initialSource ? [initialSource.imageUrl] : []);
  const [command, setCommand] = useState("");
  const [variant, setVariant] = useState<MageEditVariant["id"]>("turbo");
  const [seed, setSeed] = useState(42);
  const [steps, setSteps] = useState(4);
  const [guidance, setGuidance] = useState(1);
  const [maxSize, setMaxSize] = useState(1024);
  const [negativePrompt, setNegativePrompt] = useState("");
  const [compare, setCompare] = useState(50);
  const [submitting, setSubmitting] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    try {
      const [caps, history] = await Promise.all([
        api.getMageEditCapabilities(), api.getMageEditJobs(),
      ]);
      setCapabilities(caps);
      setJobs(history.jobs);
      setSelectedJob((current) => current
        ? history.jobs.find((job) => job.id === current.id) ?? current
        : history.jobs[0] ?? null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not load the edit workspace");
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => {
    const active = jobs.some((job) => ["queued", "running", "cancelling"].includes(job.status));
    if (!active) return;
    const timer = window.setInterval(() => void refresh(), 2500);
    return () => window.clearInterval(timer);
  }, [jobs, refresh]);
  useEffect(() => {
    if (!initialSource) return;
    setSource(initialSource);
    setPreviews([initialSource.imageUrl]);
    setFiles([]);
    setSelectedJob(null);
    onSourceConsumed?.();
  }, [initialSource, onSourceConsumed]);
  useEffect(() => {
    if (!selectedJob || selectedJob.backend !== "mage-flow-edit") return;
    try {
      const saved = replayRequestFromMageEditJob(selectedJob);
      setCommand(saved.command);
      setVariant(saved.variant);
      setSeed(saved.seed);
      setSteps(saved.steps);
      setGuidance(saved.guidance);
      setMaxSize(saved.max_size);
      setNegativePrompt(saved.negative_prompt ?? "");
    } catch {
      // Legacy jobs remain inspectable; Retry surfaces the precise missing-settings error.
    }
  }, [selectedJob]);
  useEffect(() => () => {
    previews.filter((preview) => preview.startsWith("blob:")).forEach(URL.revokeObjectURL);
  }, [previews]);

  const selectedVariant = useMemo(
    () => capabilities?.variants.find((item) => item.id === variant),
    [capabilities, variant]
  );
  const resultUrl = imageUrl(selectedJob?.edited_path);
  const sourceUrl = imageUrl(
    selectedJob?.original_path || selectedJob?.source_path || previews[0] || source?.imageUrl,
  );
  const activeJobs = jobs.filter((job) => ["queued", "running", "cancelling"].includes(job.status));
  const activeJob = activeJobs.find((job) => job.status === "running" || job.status === "cancelling") ?? activeJobs[0];
  const queuedCount = activeJobs.filter((job) => job.status === "queued").length;
  const runningCount = activeJobs.filter((job) => job.status === "running" || job.status === "cancelling").length;
  const selectedLineage = selectedJob?.metadata.edit_lineage;
  const diagnosticJob = Boolean(selectedJob && (
    selectedJob.backend !== "mage-flow-edit"
    || (
      typeof selectedLineage === "object"
      && selectedLineage !== null
      && (selectedLineage as Record<string, unknown>).diagnostic_fixture === true
    )
  ));

  const chooseVariant = (id: MageEditVariant["id"]) => {
    const next = capabilities?.variants.find((item) => item.id === id);
    setVariant(id);
    if (next) {
      setSteps(next.default_steps);
      setGuidance(next.default_guidance);
    }
  };

  const downloadModel = async () => {
    setDownloading(true);
    setError(null);
    try {
      await api.downloadMageEditModel(variant);
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not download the pinned mirror");
    } finally {
      setDownloading(false);
    }
  };

  const chooseFiles = (next: File[]) => {
    if (!next.length || next.length > 3 || next.some((item) => !item.type.startsWith("image/"))) {
      setError("Choose between one and three supported image files.");
      return;
    }
    setFiles(next);
    setSource(null);
    setPreviews(next.map((item) => URL.createObjectURL(item)));
    setSelectedJob(null);
    setError(null);
  };

  const resolveFiles = async (preferredUrls: string[] = sourceUrl ? [sourceUrl] : []) => {
    if (files.length && preferredUrls.length <= 1 && preferredUrls[0] === sourceUrl) return files;
    if (!preferredUrls.length) throw new Error("Choose at least one source image first.");
    return Promise.all(preferredUrls.map(async (preferredUrl, index) => {
      const response = await fetch(preferredUrl);
      if (!response.ok) throw new Error("Could not read a selected local source image.");
      const blob = await response.blob();
      return new File([blob], `dreamgen-edit-source-${index + 1}.png`, { type: blob.type || "image/png" });
    }));
  };

  const queueEdit = async (
    parent?: MageEditJob | null,
    preferredUrls?: string[],
  ) => {
    const request: CreateMageEditRequest = {
      command: command.trim(), variant, seed, steps, guidance, max_size: maxSize,
      negative_prompt: negativePrompt, vl_cond_long_edge: 384,
      source_path: source?.sourcePath,
    };
    if (!request.command.trim()) return setError("Describe the change you want to make.");
    const requestVariant = capabilities?.variants.find((item) => item.id === request.variant);
    if (!requestVariant?.ready) return setError("This pinned mirror checkpoint is not ready locally.");
    setSubmitting(true);
    setError(null);
    try {
      const sourceFiles = await resolveFiles(preferredUrls);
      const job = await api.createMageEditJob(sourceFiles, {
        ...request,
        command: request.command.trim(),
        parent_job_id: parent?.id,
      });
      setJobs((current) => [job, ...current]);
      setSelectedJob(job);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not queue edit");
    } finally {
      setSubmitting(false);
    }
  };

  const retry = async () => {
    if (!selectedJob) return;
    setSubmitting(true);
    setError(null);
    try {
      const job = await api.retryMageEditJob(selectedJob.id);
      setJobs((current) => [job, ...current]);
      setSelectedJob(job);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not recover retry settings");
    } finally {
      setSubmitting(false);
    }
  };

  const decide = async (decision: "approved" | "rejected") => {
    if (!selectedJob) return;
    try {
      const updated = await api.decideMageEditJob(selectedJob.id, decision);
      setSelectedJob(updated);
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not record decision");
    }
  };

  const publish = async () => {
    if (!selectedJob?.edited_path || selectedJob.decision_state !== "approved") return;
    try {
      await api.updatePublicationState(selectedJob.edited_path.replace(/^\/images\//, ""), "published");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not publish derivative");
    }
  };

  const branch = () => {
    if (!selectedJob?.edited_path) return;
    setSource({ imageUrl: selectedJob.edited_path, parentJobId: selectedJob.id });
    setPreviews([selectedJob.edited_path]);
    setFiles([]);
    setCommand("");
    setSelectedJob(null);
  };

  return (
    <div className="h-full overflow-y-auto" data-testid="mage-edit-workspace">
      <div className="mx-auto max-w-[1700px] p-3 sm:p-5">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-primary/30 bg-card/80 p-3">
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-[0.22em] text-primary">Edit workspace</div>
            <h1 className="mt-0.5 text-xl font-semibold sm:text-2xl">Command an image transformation</h1>
            <p className="mt-1 hidden max-w-3xl text-sm text-muted-foreground sm:block">
              Microsoft Mage-Flow-Edit · pinned Comfy-Org mirror · local and private until approval and publish.
            </p>
          </div>
          <div className="flex max-w-full flex-nowrap gap-2 overflow-x-auto text-xs sm:flex-wrap">
            <span className="status-pill"><MemoryStick className="h-3.5 w-3.5" />{capabilities?.gpu.name || "GPU unavailable"}</span>
            <span className="status-pill">{capabilities?.gpu.vram_total_mb ? `${Math.round(capabilities.gpu.vram_total_mb / 1024)} GB VRAM` : "VRAM unknown"}</span>
            {capabilities?.gpu.vram_free_mb ? <span className="status-pill">{Math.round(capabilities.gpu.vram_free_mb / 1024)} GB free</span> : null}
            <span className="status-pill">{capabilities?.model_loaded ? "model loaded" : "model unloaded"}</span>
            <span className="status-pill">queue {activeJobs.length} · {runningCount ? `${runningCount} running` : queuedCount ? `${queuedCount} waiting` : "idle"}</span>
          </div>
        </div>

        {capabilities && !capabilities.available && (
          <div className="mb-4 flex gap-3 rounded-xl border border-amber-400/40 bg-amber-400/10 p-4 text-sm" data-testid="edit-unavailable">
            <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-300" />
            <div>
              <div className="font-semibold text-amber-200">Pinned mirror is not enabled</div>
              <p className="mt-1 text-muted-foreground">{capabilities.access_note}</p>
              <p className="mt-2 font-mono text-xs">Action: enable the exact Comfy-Org revision shown in provenance.</p>
            </div>
          </div>
        )}

        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
          <section className="order-2 space-y-4 rounded-xl border border-border/70 bg-card/75 p-4">
            <div className="flex items-center justify-between"><h2 className="font-semibold">Next edit · Source & command</h2><span className="text-xs text-muted-foreground">original stays immutable</span></div>
            <button type="button" onClick={() => fileInput.current?.click()} onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); chooseFiles(Array.from(event.dataTransfer.files)); }} className="flex min-h-36 w-full items-center justify-center overflow-hidden rounded-xl border border-dashed border-primary/40 bg-background/60">
              {previews[0] ? <img src={imageUrl(previews[0])} alt="Primary edit source" className="max-h-56 w-full object-contain" /> : <span className="flex flex-col items-center gap-2 text-sm text-muted-foreground"><ImagePlus className="h-7 w-7" />Choose or drop 1–3 local images</span>}
            </button>
            <input ref={fileInput} className="hidden" type="file" accept="image/*" multiple onChange={(event) => chooseFiles(Array.from(event.target.files ?? []))} />
            {previews.length > 1 && <div className="grid grid-cols-3 gap-2" aria-label="Edit references">
              {previews.map((item, index) => <div key={item} className="rounded-lg border bg-background/60 p-1"><img src={imageUrl(item)} alt={`Reference ${index + 1}`} className="h-16 w-full rounded object-cover" /><div className="mt-1 text-center text-[10px] text-muted-foreground">{index === 0 ? "primary" : `reference ${index + 1}`}</div></div>)}
            </div>}
            <p className="text-[11px] text-muted-foreground">One primary image plus up to two additional references. Output shape follows the primary.</p>
            <textarea value={command} onChange={(event) => setCommand(event.target.value)} rows={5} placeholder="Replace the background with a field of sunflowers…" className="w-full rounded-xl border bg-background/70 p-3 text-sm outline-none focus:border-primary" />
            <div className="grid grid-cols-3 gap-2">
              {capabilities?.variants.map((item) => <button key={item.id} type="button" onClick={() => chooseVariant(item.id)} className={cn("rounded-lg border p-2 text-left text-xs", variant === item.id ? "border-primary bg-primary/10" : "border-border/70")}><div className="font-semibold">{item.label}</div><div className="mt-1 text-muted-foreground">{item.default_steps} steps{item.ready ? " · ready" : " · unavailable"}</div></button>)}
            </div>
            {selectedVariant?.available && !selectedVariant.cached && <button type="button" disabled={downloading} onClick={() => void downloadModel()} className="flex w-full items-center justify-center gap-2 rounded-lg border border-primary/40 px-3 py-2 text-xs"><UploadCloud className="h-4 w-4" />{downloading ? "Downloading pinned mirror…" : `Download ${selectedVariant.label} mirror`}</button>}
            <div className="grid grid-cols-2 gap-3 text-xs">
              <label>Seed<input type="number" value={seed} onChange={(e) => setSeed(Number(e.target.value))} className="mt-1 w-full rounded-lg border bg-background p-2" /></label>
              <label>Longest side<select value={maxSize} onChange={(e) => setMaxSize(Number(e.target.value))} className="mt-1 w-full rounded-lg border bg-background p-2">
                <option value={512}>512</option><option value={768}>768</option>
                <option value={1024}>1024 · 4090 default</option>
                <option value={1536}>1536 · tight on 24 GB</option>
                <option value={2048}>2048 · experimental on 24 GB</option>
              </select></label>
              <label>Steps<input type="number" min={1} max={50} value={steps} onChange={(e) => setSteps(Number(e.target.value))} className="mt-1 w-full rounded-lg border bg-background p-2" /></label>
              <label>CFG<input type="number" min={1} max={10} step="0.5" value={guidance} onChange={(e) => setGuidance(Number(e.target.value))} className="mt-1 w-full rounded-lg border bg-background p-2" /></label>
            </div>
            <label className="block text-xs">Negative prompt<input value={negativePrompt} onChange={(e) => setNegativePrompt(e.target.value)} placeholder="Optional; used when CFG > 1" className="mt-1 w-full rounded-lg border bg-background p-2" /></label>
            {error && <div className="rounded-lg border border-destructive/40 bg-destructive/10 p-2 text-xs text-destructive">{error}</div>}
            <button type="button" disabled={submitting || !selectedVariant?.ready || !sourceUrl} onClick={() => void queueEdit(source?.parentJobId ? jobs.find((job) => job.id === source.parentJobId) : null)} className="flex w-full items-center justify-center gap-2 rounded-xl bg-primary px-4 py-3 font-semibold text-primary-foreground disabled:cursor-not-allowed disabled:bg-muted disabled:text-muted-foreground disabled:opacity-70">
              {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />} {selectedVariant?.ready ? "Queue edit" : "Checkpoint unavailable"}
            </button>
          </section>

          <section className="order-1 rounded-xl border border-border/70 bg-card/75 p-3 sm:p-4 xl:col-span-2">
            <div className="mb-2 flex items-center justify-between"><h2 className="font-semibold">Result · Compare</h2>{selectedJob && <span className="status-pill">v{selectedJob.version} · {diagnosticJob ? "diagnostic fixture" : selectedJob.status}</span>}</div>
            <div className="relative flex h-[min(62vh,620px)] min-h-[360px] items-center justify-center overflow-hidden rounded-xl border bg-black/35" data-testid="edit-compare">
              {sourceUrl ? <img src={sourceUrl} alt="Original" className="h-full w-full object-contain" /> : <div className="text-sm text-muted-foreground">Choose a source to begin</div>}
              {resultUrl && <div className="absolute inset-0 overflow-hidden" style={{ clipPath: `inset(0 ${100 - compare}% 0 0)` }}><img src={resultUrl} alt="Edited result" className="h-full w-full object-contain" /></div>}
              {sourceUrl && !resultUrl && <div className="absolute left-3 top-3 z-20 rounded-md border border-border bg-background/90 px-2 py-1 font-mono text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Original preview · no edit output</div>}
              {diagnosticJob && <div className="absolute left-3 top-3 z-20 rounded-md border border-amber-300/60 bg-amber-950/90 px-2 py-1 font-mono text-[10px] font-bold uppercase tracking-wide text-amber-100">Diagnostic fixture · not model output</div>}
              {activeJob && <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-background/80 backdrop-blur-sm"><Loader2 className="h-8 w-8 animate-spin text-primary" /><div className="font-medium">{activeJob.status === "queued" ? "Queued locally" : "Editing on GPU"}</div><div className="text-xs text-muted-foreground">{selectedVariant?.repository} · {steps} steps</div><button onClick={() => void api.cancelMageEditJob(activeJob.id).then(refresh)} className="flex items-center gap-2 rounded-lg border px-3 py-2 text-xs"><CircleStop className="h-4 w-4" />Cancel</button></div>}
            </div>
            {resultUrl && <input aria-label="Before and after comparison" type="range" min={0} max={100} value={compare} onChange={(e) => setCompare(Number(e.target.value))} className="mt-3 w-full" />}
            {diagnosticJob && <div className="mt-3 rounded-lg border border-amber-400/40 bg-amber-400/10 p-3 text-xs text-amber-100">Diagnostic mock fixture for layout validation only. It is not Mage-Flow-Edit output and cannot be approved or published.</div>}
            {selectedJob?.status === "succeeded" && <div className="mt-4 flex flex-wrap gap-2">
              <button disabled={Boolean(diagnosticJob)} onClick={() => void decide("approved")} className="flex items-center gap-2 rounded-lg bg-emerald-500 px-3 py-2 text-xs font-semibold text-black disabled:opacity-35"><Check className="h-4 w-4" />Approve</button>
              <button disabled={Boolean(diagnosticJob)} onClick={() => void decide("rejected")} className="flex items-center gap-2 rounded-lg border border-rose-400/50 px-3 py-2 text-xs disabled:opacity-35"><X className="h-4 w-4" />Reject</button>
              <button data-testid="retry-edit" disabled={Boolean(diagnosticJob)} onClick={() => void retry()} className="flex items-center gap-2 rounded-lg border px-3 py-2 text-xs disabled:opacity-35"><RotateCcw className="h-4 w-4" />Retry exact settings</button>
              <button disabled={Boolean(diagnosticJob)} onClick={branch} className="flex items-center gap-2 rounded-lg border px-3 py-2 text-xs disabled:opacity-35"><GitBranch className="h-4 w-4" />Branch from result</button>
              <button disabled={Boolean(diagnosticJob) || selectedJob.decision_state !== "approved"} onClick={() => void publish()} className="ml-auto flex items-center gap-2 rounded-lg border border-primary/40 px-3 py-2 text-xs disabled:opacity-35"><UploadCloud className="h-4 w-4" />Publish to gallery</button>
            </div>}
            {selectedJob?.status === "failed" && <div className="mt-3 rounded-lg border border-destructive/40 p-3 text-xs text-destructive">{selectedJob.error}</div>}
          </section>

          <aside className="order-3 rounded-xl border border-border/70 bg-card/75 p-4">
            <div className="mb-3 flex items-center justify-between"><h2 className="flex items-center gap-2 font-semibold"><History className="h-4 w-4" />Versions</h2><button onClick={() => void refresh()} aria-label="Refresh edit history"><RefreshCw className="h-4 w-4" /></button></div>
            <div className="space-y-2">
              {jobs.length ? jobs.map((job) => <button key={job.id} onClick={() => setSelectedJob(job)} className={cn("w-full rounded-lg border p-3 text-left text-xs", selectedJob?.id === job.id ? "border-primary bg-primary/10" : "border-border/70")}><div className="flex justify-between"><span className="font-semibold">v{job.version} · {job.status}</span>{job.decision_state === "approved" && <ShieldCheck className="h-4 w-4 text-emerald-400" />}</div><p className="mt-1 line-clamp-2 text-muted-foreground">{job.prompt}</p><div className="mt-2 font-mono text-[10px] text-muted-foreground">{job.id.slice(0,8)} · {job.parent_job_id ? "branch" : "root"}</div></button>) : <div className="rounded-lg border border-dashed p-5 text-center text-xs text-muted-foreground">No edit versions yet.</div>}
            </div>
            <div className="mt-4 border-t pt-4 text-[11px] text-muted-foreground">
              <div className="font-semibold text-foreground">Immutable provenance</div>
              <p className="mt-1">Source and derivative hashes, Microsoft upstream identity, Comfy-Org artifact path/revision/SHA-256, configuration source, settings, timing, VRAM, parent, and decisions are retained in hash-linked manifests.</p>
              {selectedVariant && <p className="mt-2 break-all font-mono text-[10px]">{selectedVariant.artifact_repository}@{selectedVariant.verified_revision}<br />{selectedVariant.artifact_path}<br />sha256:{selectedVariant.artifact_sha256}</p>}
            </div>
          </aside>
        </div>
      </div>
    </div>
  );
}
