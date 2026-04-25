export type ProgressSnapshot = {
  progress: number;
  title: string;
  detail: string;
};

type UnknownRecord = Record<string, unknown>;

export const INITIAL_PROMPT_PROGRESS: ProgressSnapshot = {
  progress: 12,
  title: "Preparing prompt generation",
  detail: "Collecting your meta prompt and warming up the prompt model.",
};

export const INITIAL_IMAGE_PROGRESS: ProgressSnapshot = {
  progress: 8,
  title: "Preparing image request",
  detail: "Collecting the prompt, active plugins, and runtime settings.",
};

const PROMPT_FALLBACK_STEPS: ProgressSnapshot[] = [
  INITIAL_PROMPT_PROGRESS,
  {
    progress: 34,
    title: "Building prompt context",
    detail: "Gathering plugin context and preparing the prompt request.",
  },
  {
    progress: 58,
    title: "Generating prompt",
    detail: "Asking Ollama to draft the next image prompt.",
  },
  {
    progress: 82,
    title: "Refining prompt",
    detail: "Finalizing the wording before it appears in the editor.",
  },
  {
    progress: 94,
    title: "Wrapping up prompt",
    detail: "Waiting for the generated prompt to come back from the backend.",
  },
];

const IMAGE_FALLBACK_STEPS: ProgressSnapshot[] = [
  INITIAL_IMAGE_PROGRESS,
  {
    progress: 22,
    title: "Building prompt context",
    detail: "Collecting plugin context and preparing the prompt for this run.",
  },
  {
    progress: 38,
    title: "Generating prompt",
    detail: "Turning the current theme into a final prompt for the image model.",
  },
  {
    progress: 56,
    title: "Preparing backend",
    detail: "Loading the selected image backend and checking runtime resources.",
  },
  {
    progress: 74,
    title: "Rendering image",
    detail: "The backend is synthesizing the image now.",
  },
  {
    progress: 90,
    title: "Finalizing output",
    detail: "Saving metadata and writing the image to the gallery.",
  },
];

const clampProgress = (value: number) => Math.max(0, Math.min(100, Math.round(value)));

export const createClientRequestId = (prefix: string) => {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return `${prefix}-${crypto.randomUUID()}`;
  }

  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
};

export const getTaskProgressUpdate = (
  data: unknown,
  task: "prompt_generation" | "image_generation",
  clientRequestId: string | null
): ProgressSnapshot | null => {
  if (!clientRequestId || typeof data !== "object" || data === null) return null;

  const msg = data as UnknownRecord;
  if (msg.type !== "task_progress" || msg.task !== task) return null;
  if (msg.client_request_id !== clientRequestId) return null;

  const progress =
    typeof msg.progress === "number" ? clampProgress(msg.progress) : clampProgress(0);
  const title =
    typeof msg.label === "string" && msg.label.trim()
      ? msg.label
      : typeof msg.message === "string" && msg.message.trim()
        ? msg.message
        : task === "prompt_generation"
          ? "Generating prompt"
          : "Generating image";
  const detail =
    typeof msg.detail === "string" && msg.detail.trim()
      ? msg.detail
      : typeof msg.message === "string" && msg.message.trim()
        ? msg.message
        : "Working...";

  return { progress, title, detail };
};

export const getFallbackProgress = (
  task: "prompt_generation" | "image_generation",
  current: ProgressSnapshot
): ProgressSnapshot => {
  const steps = task === "prompt_generation" ? PROMPT_FALLBACK_STEPS : IMAGE_FALLBACK_STEPS;
  const next = steps.find((step) => step.progress > current.progress);

  if (next) return next;

  if (current.progress >= 96) return current;

  return {
    ...current,
    progress: clampProgress(current.progress + 1),
  };
};
