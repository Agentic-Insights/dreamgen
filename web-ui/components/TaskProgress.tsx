"use client";

import { Loader2 } from "lucide-react";

import { cn } from "@/lib/utils";
import type { ProgressSnapshot } from "@/lib/task-progress";

interface TaskProgressProps {
  progress: ProgressSnapshot;
  className?: string;
  compact?: boolean;
}

export default function TaskProgress({
  progress,
  className,
  compact = false,
}: TaskProgressProps) {
  const progressValue = Math.max(0, Math.min(100, Math.round(progress.progress)));
  const width = `${progressValue}%`;

  if (compact) {
    return (
      <div className={cn("w-full space-y-2", className)}>
        <div className="flex items-center gap-2 text-sm text-foreground">
          <Loader2 className="h-4 w-4 animate-spin text-primary" />
          <span className="font-medium">{progress.title}</span>
          <span className="ml-auto text-xs text-muted-foreground">{width}</span>
        </div>
        <div
          className="h-1.5 overflow-hidden rounded-full bg-muted"
          role="progressbar"
          aria-label={progress.title}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={progressValue}
        >
          <div
            className="h-full rounded-full bg-primary transition-[width] duration-500 ease-out"
            style={{ width }}
          />
        </div>
        <p className="text-xs leading-5 text-muted-foreground">{progress.detail}</p>
      </div>
    );
  }

  return (
    <div className={cn("mx-auto max-w-md text-center", className)}>
      <Loader2 className="mx-auto mb-4 h-14 w-14 animate-spin text-primary" />
      <p className="text-sm font-medium text-foreground">{progress.title}</p>
      <p className="mt-2 text-xs leading-6 text-muted-foreground">{progress.detail}</p>
      <div
        className="mt-4 overflow-hidden rounded-full bg-muted"
        role="progressbar"
        aria-label={progress.title}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={progressValue}
      >
        <div
          className="flex h-2.5 items-center justify-end rounded-full bg-primary pr-2 text-[10px] font-medium text-primary-foreground transition-[width] duration-500 ease-out"
          style={{ width: `max(${width}, 3.5rem)` }}
        >
          {width}
        </div>
      </div>
    </div>
  );
}
