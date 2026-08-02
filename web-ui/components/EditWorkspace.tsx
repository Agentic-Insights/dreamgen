"use client";
/* eslint-disable @next/next/no-img-element */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle, Check, CircleStop, GitBranch, History, ImagePlus, Loader2,
  MemoryStick, RefreshCw, RotateCcw, Send, ShieldCheck, UploadCloud, X,
} from "lucide-react";

import {
  API_BASE, api, type MageEditCapabilities, type MageEditJob, type MageEditVariant,
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
  const [file, setFile] = useState<File | null>(null);
  const [source, setSource] = useState<EditSource | null>(initialSource ?? null);
  const [preview, setPreview] = useState(initialSource?.imageUrl ?? "");
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
    setPreview(initialSource.imageUrl);
    setFile(null);
    setSelectedJob(null);
    onSourceConsumed?.();
  }, [initialSource, onSourceConsumed]);
  useEffect(() => () => {
    if (preview.startsWith("blob:")) URL.revokeObjectURL(preview);
  }, [preview]);

  const selectedVariant = useMemo(
    () => capabilities?.variants.find((item) => item.id === variant),
    [capabilities, variant]
  );
  const resultUrl = imageUrl(selectedJob?.edited_path);
  const sourceUrl = imageUrl(selectedJob?.original_path || preview || source?.imageUrl);
  const activeJobs = jobs.filter((job) => ["queued", "running", "cancelling"].includes(job.status));
  const activeJob = activeJobs.find((job) => job.status === "running" || job.status === "cancelling") ?? activeJobs[0];
  const queuedCount = activeJobs.filter((job) => job.status === "queued").length;
  const runningCount = activeJobs.filter((job) => job.status === "running" || job.status === "cancelling").length;
  const diagnosticJob = selectedJob && selectedJob.backend !== "mage-flow-edit";

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
      setError(reason instanceof Error ? reason.message : "Could not download official model");
    } finally {
      setDownloading(false);
    }
  };

  const chooseFile = (next: File) => {
    if (preview.startsWith("blob:")) URL.revokeObjectURL(preview);
    setFile(next);
    setSource(null);
    setPreview(URL.createObjectURL(next));
    setSelectedJob(null);
    setError(null);
  };

  const resolveFile = async (preferredUrl = sourceUrl) => {
    if (file && preferredUrl === sourceUrl) return file;
    if (!preferredUrl) throw new Error("Choose a source image first.");
    const response = await fetch(preferredUrl);
    if (!response.ok) throw new Error("Could not read the selected local source image.");
    const blob = await response.blob();
    return new File([blob], "dreamgen-edit-source.png", { type: blob.type || "image/png" });
  };

  const queueEdit = async (parent?: MageEditJob | null, preferredUrl?: string) => {
    if (!command.trim()) return setError("Describe the change you want to make.");
    if (!selectedVariant?.ready) return setError("This official checkpoint is not ready locally.");
    setSubmitting(true);
    setError(null);
    try {
      const sourceFile = await resolveFile(preferredUrl);
      const job = await api.createMageEditJob(sourceFile, {
        command: command.trim(), variant, seed, steps, guidance, max_size: maxSize,
        negative_prompt: negativePrompt, vl_cond_long_edge: 384,
        source_path: source?.sourcePath, parent_job_id: parent?.id,
      });
      setJobs((current) => [job, ...current]);
      setSelectedJob(job);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not queue edit");
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
    setPreview(selectedJob.edited_path);
    setFile(null);
    setCommand("");
    setSelectedJob(null);
  };

  return (
    <div className="h-full overflow-y-auto" data-testid="mage-edit-workspace">
      <div className="mx-auto max-w-[1700px] p-3 sm:p-5">
        <div className="mb-4 flex flex-wrap items-start justify-between gap-4 rounded-xl border border-primary/30 bg-card/80 p-4">
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-[0.22em] text-primary">Edit workspace</div>
            <h1 className="mt-1 text-2xl font-semibold">Command an image transformation</h1>
            <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
              Microsoft Mage-Flow-Edit · local, versioned, and private until you explicitly approve and publish.
            </p>
          </div>
          <div className="flex flex-wrap gap-2 text-xs">
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
              <div className="font-semibold text-amber-200">Official checkpoints are not available locally</div>
              <p className="mt-1 text-muted-foreground">{capabilities.access_note}</p>
              <p className="mt-2 font-mono text-xs">Action: restore Microsoft repository access, run hf auth login, then pin the verified 40-character revision.</p>
            </div>
          </div>
        )}

        <div className="grid gap-4 xl:grid-cols-[360px_minmax(0,1fr)_300px]">
          <section className="space-y-4 rounded-xl border border-border/70 bg-card/75 p-4">
            <div className="flex items-center justify-between"><h2 className="font-semibold">1 · Source & command</h2><span className="text-xs text-muted-foreground">original stays immutable</span></div>
            <button type="button" onClick={() => fileInput.current?.click()} onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); const dropped = event.dataTransfer.files?.[0]; if (dropped?.type.startsWith("image/")) chooseFile(dropped); else setError("Drop a supported image file."); }} className="flex min-h-36 w-full items-center justify-center overflow-hidden rounded-xl border border-dashed border-primary/40 bg-background/60">
              {preview ? <img src={imageUrl(preview)} alt="Edit source" className="max-h-56 w-full object-contain" /> : <span className="flex flex-col items-center gap-2 text-sm text-muted-foreground"><ImagePlus className="h-7 w-7" />Choose or drop a local image</span>}
            </button>
            <input ref={fileInput} className="hidden" type="file" accept="image/*" onChange={(event) => event.target.files?.[0] && chooseFile(event.target.files[0])} />
            <textarea value={command} onChange={(event) => setCommand(event.target.value)} rows={5} placeholder="Replace the background with a field of sunflowers…" className="w-full rounded-xl border bg-background/70 p-3 text-sm outline-none focus:border-primary" />
            <div className="grid grid-cols-3 gap-2">
              {capabilities?.variants.map((item) => <button key={item.id} type="button" onClick={() => chooseVariant(item.id)} className={cn("rounded-lg border p-2 text-left text-xs", variant === item.id ? "border-primary bg-primary/10" : "border-border/70")}><div className="font-semibold">{item.label}</div><div className="mt-1 text-muted-foreground">{item.default_steps} steps{item.ready ? " · ready" : " · unavailable"}</div></button>)}
            </div>
            {selectedVariant?.available && !selectedVariant.cached && <button type="button" disabled={downloading} onClick={() => void downloadModel()} className="flex w-full items-center justify-center gap-2 rounded-lg border border-primary/40 px-3 py-2 text-xs"><UploadCloud className="h-4 w-4" />{downloading ? "Downloading official checkpoint…" : `Download ${selectedVariant.label}`}</button>}
            <div className="grid grid-cols-2 gap-3 text-xs">
              <label>Seed<input type="number" value={seed} onChange={(e) => setSeed(Number(e.target.value))} className="mt-1 w-full rounded-lg border bg-background p-2" /></label>
              <label>Longest side<select value={maxSize} onChange={(e) => setMaxSize(Number(e.target.value))} className="mt-1 w-full rounded-lg border bg-background p-2">{[512,768,1024,1536,2048].map((size) => <option key={size}>{size}</option>)}</select></label>
              <label>Steps<input type="number" min={1} max={50} value={steps} onChange={(e) => setSteps(Number(e.target.value))} className="mt-1 w-full rounded-lg border bg-background p-2" /></label>
              <label>CFG<input type="number" min={1} max={10} step="0.5" value={guidance} onChange={(e) => setGuidance(Number(e.target.value))} className="mt-1 w-full rounded-lg border bg-background p-2" /></label>
            </div>
            <label className="block text-xs">Negative prompt<input value={negativePrompt} onChange={(e) => setNegativePrompt(e.target.value)} placeholder="Optional; used when CFG > 1" className="mt-1 w-full rounded-lg border bg-background p-2" /></label>
            {error && <div className="rounded-lg border border-destructive/40 bg-destructive/10 p-2 text-xs text-destructive">{error}</div>}
            <button type="button" disabled={submitting || !selectedVariant?.ready || !preview} onClick={() => void queueEdit(source?.parentJobId ? jobs.find((job) => job.id === source.parentJobId) : null)} className="flex w-full items-center justify-center gap-2 rounded-xl bg-primary px-4 py-3 font-semibold text-primary-foreground disabled:cursor-not-allowed disabled:opacity-45">
              {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />} Queue edit
            </button>
          </section>

          <section className="rounded-xl border border-border/70 bg-card/75 p-4">
            <div className="mb-3 flex items-center justify-between"><h2 className="font-semibold">2 · Compare</h2>{selectedJob && <span className="status-pill">v{selectedJob.version} · {diagnosticJob ? "diagnostic fixture" : selectedJob.status}</span>}</div>
            <div className="relative flex min-h-[420px] items-center justify-center overflow-hidden rounded-xl border bg-black/35" data-testid="edit-compare">
              {sourceUrl ? <img src={sourceUrl} alt="Original" className="max-h-[68vh] w-full object-contain" /> : <div className="text-sm text-muted-foreground">Choose a source to begin</div>}
              {resultUrl && <div className="absolute inset-0 overflow-hidden" style={{ clipPath: `inset(0 ${100 - compare}% 0 0)` }}><img src={resultUrl} alt="Edited result" className="h-full w-full object-contain" /></div>}
              {activeJob && <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-background/80 backdrop-blur-sm"><Loader2 className="h-8 w-8 animate-spin text-primary" /><div className="font-medium">{activeJob.status === "queued" ? "Queued locally" : "Editing on GPU"}</div><div className="text-xs text-muted-foreground">{selectedVariant?.repository} · {steps} steps</div><button onClick={() => void api.cancelMageEditJob(activeJob.id).then(refresh)} className="flex items-center gap-2 rounded-lg border px-3 py-2 text-xs"><CircleStop className="h-4 w-4" />Cancel</button></div>}
            </div>
            {resultUrl && <input aria-label="Before and after comparison" type="range" min={0} max={100} value={compare} onChange={(e) => setCompare(Number(e.target.value))} className="mt-3 w-full" />}
            {diagnosticJob && <div className="mt-3 rounded-lg border border-amber-400/40 bg-amber-400/10 p-3 text-xs text-amber-100">Diagnostic mock fixture for layout validation only. It is not Mage-Flow-Edit output and cannot be approved or published.</div>}
            {selectedJob?.status === "succeeded" && <div className="mt-4 flex flex-wrap gap-2">
              <button disabled={Boolean(diagnosticJob)} onClick={() => void decide("approved")} className="flex items-center gap-2 rounded-lg bg-emerald-500 px-3 py-2 text-xs font-semibold text-black disabled:opacity-35"><Check className="h-4 w-4" />Approve</button>
              <button disabled={Boolean(diagnosticJob)} onClick={() => void decide("rejected")} className="flex items-center gap-2 rounded-lg border border-rose-400/50 px-3 py-2 text-xs disabled:opacity-35"><X className="h-4 w-4" />Reject</button>
              <button disabled={Boolean(diagnosticJob)} onClick={() => void queueEdit(selectedJob, sourceUrl)} className="flex items-center gap-2 rounded-lg border px-3 py-2 text-xs disabled:opacity-35"><RotateCcw className="h-4 w-4" />Retry</button>
              <button disabled={Boolean(diagnosticJob)} onClick={branch} className="flex items-center gap-2 rounded-lg border px-3 py-2 text-xs disabled:opacity-35"><GitBranch className="h-4 w-4" />Branch from result</button>
              <button disabled={Boolean(diagnosticJob) || selectedJob.decision_state !== "approved"} onClick={() => void publish()} className="ml-auto flex items-center gap-2 rounded-lg border border-primary/40 px-3 py-2 text-xs disabled:opacity-35"><UploadCloud className="h-4 w-4" />Publish to gallery</button>
            </div>}
            {selectedJob?.status === "failed" && <div className="mt-3 rounded-lg border border-destructive/40 p-3 text-xs text-destructive">{selectedJob.error}</div>}
          </section>

          <aside className="rounded-xl border border-border/70 bg-card/75 p-4">
            <div className="mb-3 flex items-center justify-between"><h2 className="flex items-center gap-2 font-semibold"><History className="h-4 w-4" />Versions</h2><button onClick={() => void refresh()} aria-label="Refresh edit history"><RefreshCw className="h-4 w-4" /></button></div>
            <div className="space-y-2">
              {jobs.length ? jobs.map((job) => <button key={job.id} onClick={() => setSelectedJob(job)} className={cn("w-full rounded-lg border p-3 text-left text-xs", selectedJob?.id === job.id ? "border-primary bg-primary/10" : "border-border/70")}><div className="flex justify-between"><span className="font-semibold">v{job.version} · {job.status}</span>{job.decision_state === "approved" && <ShieldCheck className="h-4 w-4 text-emerald-400" />}</div><p className="mt-1 line-clamp-2 text-muted-foreground">{job.prompt}</p><div className="mt-2 font-mono text-[10px] text-muted-foreground">{job.id.slice(0,8)} · {job.parent_job_id ? "branch" : "root"}</div></button>) : <div className="rounded-lg border border-dashed p-5 text-center text-xs text-muted-foreground">No edit versions yet.</div>}
            </div>
            <div className="mt-4 border-t pt-4 text-[11px] text-muted-foreground">
              <div className="font-semibold text-foreground">Immutable provenance</div>
              <p className="mt-1">Source and derivative SHA-256 hashes, command, official model/revision, settings, timing, VRAM, parent, and decisions are retained in hash-linked manifests.</p>
            </div>
          </aside>
        </div>
      </div>
    </div>
  );
}
