"use client";

import { Clock3, Copy, Play, RefreshCcw, RotateCcw, Settings2, XCircle } from "lucide-react";

import { API_BASE, type GenerationJob } from "@/lib/api";
import { cn } from "@/lib/utils";

interface QueueHistoryProps {
  jobs: GenerationJob[];
  isLoading?: boolean;
  onRefresh: () => void;
  onCopyPrompt: (prompt: string) => void;
  onBranch: (job: GenerationJob) => void;
  onRerun: (job: GenerationJob) => void;
}

const STATUS_STYLES: Record<GenerationJob["status"], string> = {
  queued: "border-amber-400/35 bg-amber-400/10 text-amber-200",
  running: "border-primary/40 bg-primary/12 text-primary",
  succeeded: "border-emerald-400/35 bg-emerald-400/10 text-emerald-200",
  failed: "border-destructive/40 bg-destructive/10 text-destructive",
  cancelled: "border-muted-foreground/30 bg-muted/60 text-muted-foreground",
};

const isActiveJob = (job: GenerationJob) => job.status === "queued" || job.status === "running";

const formatTime = (value?: string | null) => {
  if (!value) return "pending";
  return new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
};

const jobPrompt = (job: GenerationJob) => job.prompt || job.request.prompt || "";

const truncate = (value: string, max = 86) =>
  value.length > max ? `${value.slice(0, max).trim()}...` : value;

const formatDuration = (seconds?: number | null) => {
  if (seconds === null || seconds === undefined) return "timing pending";
  return seconds < 60 ? `${seconds.toFixed(2)}s` : `${Math.floor(seconds / 60)}m ${(seconds % 60).toFixed(0)}s`;
};

export default function QueueHistory({
  jobs,
  isLoading = false,
  onRefresh,
  onCopyPrompt,
  onBranch,
  onRerun,
}: QueueHistoryProps) {
  const activeJobs = jobs.filter(isActiveJob);
  const recentJobs = jobs.filter((job) => !isActiveJob(job)).slice(0, 5);

  return (
    <div className="ambient-panel rounded-[1.75rem] border border-border/80 p-5">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div>
          <div className="text-xs uppercase tracking-[0.2em] text-muted-foreground">
            Queue
          </div>
          <h2 className="mt-1 text-lg font-semibold text-foreground">Jobs and reruns</h2>
        </div>
        <button
          onClick={onRefresh}
          className="inline-flex h-9 w-9 items-center justify-center rounded-full border border-border/70 text-muted-foreground transition hover:border-primary/40 hover:text-foreground"
          title="Refresh jobs"
        >
          <RefreshCcw className={cn("h-4 w-4", isLoading && "animate-spin")} />
        </button>
      </div>

      <div className="grid gap-3">
        <div className="rounded-2xl border border-border/60 bg-background/78 px-4 py-3">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2 text-sm font-medium text-foreground">
              <Clock3 className="h-4 w-4 text-primary" />
              {activeJobs.length} active
            </div>
            <span className="text-xs text-muted-foreground">{jobs.length} loaded</span>
          </div>
          {activeJobs.length > 0 ? (
            <div className="mt-3 space-y-2">
              {activeJobs.map((job) => (
                <div key={job.id} className="space-y-2">
                  <div className="flex items-center justify-between gap-3 text-xs">
                    <span className="truncate text-foreground">
                      {truncate(jobPrompt(job) || job.request.meta_prompt || "Generated prompt job", 58)}
                    </span>
                    <span className="shrink-0 text-muted-foreground">{job.progress}%</span>
                  </div>
                  <div
                    className="h-1.5 overflow-hidden rounded-full bg-muted"
                    role="progressbar"
                    aria-label={`Job ${job.status} progress`}
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-valuenow={Math.max(0, Math.min(100, job.progress))}
                  >
                    <div
                      className="h-full rounded-full bg-primary transition-[width] duration-500"
                      style={{ width: `${Math.max(4, Math.min(100, job.progress))}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="mt-2 text-sm leading-6 text-muted-foreground">
              No queued or running jobs.
            </div>
          )}
        </div>

        {recentJobs.length > 0 ? (
          <div className="space-y-3">
            {recentJobs.map((job) => {
              const prompt = jobPrompt(job);
              const imagePath = job.relative_image_path;
              return (
                <div
                  key={job.id}
                  className="rounded-2xl border border-border/60 bg-background/78 p-3"
                >
                  <div className="flex gap-3">
                    {imagePath ? (
                      // Backend-served generated files are not routed through Next image optimization.
                      // eslint-disable-next-line @next/next/no-img-element
                      <img
                        src={`${API_BASE}${imagePath}`}
                        alt="Generated job artifact"
                        className="h-14 w-14 shrink-0 rounded-xl object-cover"
                      />
                    ) : (
                      <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-xl border border-border/60 bg-muted/50">
                        <XCircle className="h-5 w-5 text-muted-foreground" />
                      </div>
                    )}
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center justify-between gap-2">
                        <span
                          className={cn(
                            "rounded-full border px-2 py-0.5 text-[11px] capitalize",
                            STATUS_STYLES[job.status]
                          )}
                        >
                          {job.status}
                        </span>
                        <span className="shrink-0 text-[11px] text-muted-foreground">
                          {formatTime(job.completed_at ?? job.updated_at)}
                        </span>
                      </div>
                      <p className="mt-2 text-sm leading-6 text-foreground">
                        {truncate(prompt || job.request.meta_prompt || job.error || "No prompt recorded")}
                      </p>
                      <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
                        <span>{job.backend ?? "backend pending"}</span>
                        <span>{job.model_name ?? "model pending"}</span>
                        <span>{formatDuration(job.generation_time)}</span>
                        {job.request.seed !== null && job.request.seed !== undefined ? (
                          <span>seed {job.request.seed}</span>
                        ) : null}
                        {job.request.recipe_id ? <span>{job.request.recipe_id}</span> : null}
                      </div>
                    </div>
                  </div>

                  <div className="mt-3 grid grid-cols-3 gap-2">
                    <button
                      onClick={() => onBranch(job)}
                      className="inline-flex items-center justify-center gap-2 rounded-xl border border-border/70 px-3 py-2 text-xs text-muted-foreground transition hover:border-primary/40 hover:text-foreground"
                    >
                      <Settings2 className="h-3.5 w-3.5" />
                      Branch settings
                    </button>
                    <button
                      onClick={() => onCopyPrompt(prompt)}
                      disabled={!prompt}
                      className="inline-flex items-center justify-center gap-2 rounded-xl border border-border/70 px-3 py-2 text-xs text-muted-foreground transition hover:border-primary/40 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      <Copy className="h-3.5 w-3.5" />
                      Copy prompt
                    </button>
                    <button
                      onClick={() => onRerun(job)}
                      className="inline-flex items-center justify-center gap-2 rounded-xl bg-primary px-3 py-2 text-xs text-primary-foreground transition hover:opacity-95"
                    >
                      {job.status === "failed" ? (
                        <Play className="h-3.5 w-3.5" />
                      ) : (
                        <RotateCcw className="h-3.5 w-3.5" />
                      )}
                      Rerun
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="rounded-2xl border border-border/60 bg-background/78 px-4 py-8 text-center text-sm text-muted-foreground">
            Completed jobs will appear here after generation.
          </div>
        )}
      </div>
    </div>
  );
}
