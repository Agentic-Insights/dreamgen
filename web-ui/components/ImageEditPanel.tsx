"use client";

import { useEffect, useMemo, useState } from "react";
import { CheckCircle2, FileImage, Loader2, WandSparkles, X } from "lucide-react";

import { API_BASE, api, type EditResponse } from "@/lib/api";

export interface ImageEditTarget {
  imageUrl: string;
  sourcePath?: string;
  prompt?: string;
}

interface ImageEditPanelProps {
  target?: ImageEditTarget | null;
  onClose: () => void;
  onCompleted?: (response: EditResponse) => void;
}

export default function ImageEditPanel({ target, onClose, onCompleted }: ImageEditPanelProps) {
  const [file, setFile] = useState<File | null>(null);
  const [prompt, setPrompt] = useState(target?.prompt ? `Edit this image: ${target.prompt}` : "");
  const [strength, setStrength] = useState(0.8);
  const [backend, setBackend] = useState<"mock" | "auto">("mock");
  const [previewUrl, setPreviewUrl] = useState(target?.imageUrl || "");
  const [result, setResult] = useState<EditResponse | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setPreviewUrl(target?.imageUrl || "");
    setPrompt(target?.prompt ? `Edit this image: ${target.prompt}` : "");
    setFile(null);
    setResult(null);
  }, [target]);

  const sourceUrl = useMemo(() => {
    if (file) return URL.createObjectURL(file);
    if (!previewUrl) return "";
    return previewUrl.startsWith("http") ? previewUrl : `${API_BASE}${previewUrl}`;
  }, [file, previewUrl]);

  useEffect(() => () => {
    if (file && sourceUrl.startsWith("blob:")) URL.revokeObjectURL(sourceUrl);
  }, [file, sourceUrl]);

  const submit = async () => {
    if (!prompt.trim()) {
      setError("Add an instruction for the edit.");
      return;
    }
    setIsSubmitting(true);
    setError(null);
    try {
      let sourceFile = file;
      if (!sourceFile && sourceUrl) {
        const response = await fetch(sourceUrl);
        if (!response.ok) throw new Error("Could not load the source image");
        const blob = await response.blob();
        sourceFile = new File([blob], "dreamgen-source.png", { type: blob.type || "image/png" });
      }
      if (!sourceFile) throw new Error("Choose an image or open an existing output first");
      const editResponse = await api.editImage(sourceFile, {
        prompt: prompt.trim(),
        strength,
        backend,
        source_path: target?.sourcePath,
      });
      setResult(editResponse);
      onCompleted?.(editResponse);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Image editing failed");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/75 p-4 backdrop-blur-sm" role="dialog" aria-modal="true" aria-label="Edit image">
      <div className="max-h-[92vh] w-full max-w-4xl overflow-y-auto rounded-2xl border border-border bg-background shadow-2xl">
        <div className="flex items-start justify-between gap-4 border-b border-border p-5">
          <div>
            <div className="flex items-center gap-2 text-xs uppercase tracking-[0.18em] text-primary"><WandSparkles className="h-4 w-4" /> Creative edit</div>
            <h2 className="mt-1 text-xl font-semibold text-foreground">Branch from an image</h2>
            <p className="mt-1 text-sm text-muted-foreground">The source, instruction, backend, and result stay linked in a durable edit job.</p>
          </div>
          <button type="button" onClick={onClose} className="rounded-lg border border-border p-2 text-muted-foreground hover:bg-muted" aria-label="Close edit panel"><X className="h-4 w-4" /></button>
        </div>

        <div className="grid gap-5 p-5 lg:grid-cols-[1fr_1.1fr]">
          <div className="space-y-4">
            <div className="overflow-hidden rounded-xl border border-border bg-black/70">
              {sourceUrl ? <img src={sourceUrl} alt="Edit source" className="max-h-[360px] w-full object-contain" /> : <div className="flex h-64 items-center justify-center text-muted-foreground"><FileImage className="h-10 w-10" /></div>}
            </div>
            <label className="block rounded-xl border border-dashed border-border p-4 text-sm text-muted-foreground hover:border-primary/50">
              <span className="font-medium text-foreground">Upload another source</span>
              <input type="file" accept="image/*" className="mt-2 block w-full text-xs" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
            </label>
          </div>

          <div className="space-y-4">
            <label className="block text-sm font-medium text-foreground">Instruction
              <textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} rows={5} placeholder="Add a warm neon sign and preserve the composition" className="mt-2 w-full rounded-xl border border-input bg-background px-3 py-3 text-sm leading-6 outline-none focus:border-primary" />
            </label>
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="text-sm text-foreground">Backend
                <select value={backend} onChange={(event) => setBackend(event.target.value as "mock" | "auto")} className="mt-2 h-10 w-full rounded-lg border border-input bg-background px-3 text-sm">
                  <option value="mock">Mock / deterministic</option>
                  <option value="auto">Configured local editor</option>
                </select>
              </label>
              <label className="text-sm text-foreground">Strength <span className="text-muted-foreground">{strength.toFixed(2)}</span>
                <input type="range" min="0" max="1" step="0.05" value={strength} onChange={(event) => setStrength(Number(event.target.value))} className="mt-4 w-full" />
              </label>
            </div>
            {error && <div className="rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive" role="alert">{error}</div>}
            <button type="button" onClick={() => void submit()} disabled={isSubmitting} className="inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-xl bg-primary px-4 py-3 text-sm font-medium text-primary-foreground disabled:opacity-60">
              {isSubmitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <WandSparkles className="h-4 w-4" />}
              {isSubmitting ? "Editing..." : "Create linked edit"}
            </button>

            {result && (
              <div className="rounded-xl border border-emerald-400/35 bg-emerald-400/10 p-4" role="status">
                <div className="flex items-center gap-2 text-sm font-medium text-emerald-200"><CheckCircle2 className="h-4 w-4" /> Edit completed</div>
                <div className="mt-3 grid grid-cols-2 gap-2 text-xs text-muted-foreground">
                  <span>Job {result.metadata.job_id ? String(result.metadata.job_id).slice(0, 12) : result.id.slice(0, 12)}</span>
                  <span>{String(result.metadata.backend ?? "editor")}</span>
                </div>
                <img src={`${API_BASE}${result.edited_path}`} alt="Edited result" className="mt-3 max-h-56 w-full rounded-lg object-contain" />
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
