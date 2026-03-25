"use client";

import { startTransition, useCallback, useEffect, useRef, useState } from "react";
import Image from "next/image";
import {
  Bot,
  Clock3,
  Cpu,
  GalleryHorizontalEnd,
  Image as ImageIcon,
  Loader2,
  Play,
  Settings as SettingsIcon,
  Sparkles,
  Square,
  Wand2,
} from "lucide-react";
import { AnimatePresence, motion } from "framer-motion";

import Gallery from "@/components/Gallery";
import Settings from "@/components/Settings";
import { API_BASE, api, GenerateResponse, SystemStatus } from "@/lib/api";
import { cn } from "@/lib/utils";
import galleryCache from "@/lib/cache";

type TabId = "generate" | "gallery" | "settings" | "playground";

type CadenceOption = {
  label: string;
  minutes: number;
  description: string;
};

type RecentImage = {
  path: string;
  prompt: string;
  created_at: string;
};

type HeroNote = {
  label: string;
  value: string;
};

const CADENCE_OPTIONS: CadenceOption[] = [
  { label: "5 min", minutes: 5, description: "Fast drip" },
  { label: "15 min", minutes: 15, description: "Steady stream" },
  { label: "1 hour", minutes: 60, description: "Background rhythm" },
  { label: "3 hours", minutes: 180, description: "Slow drift" },
  { label: "Daily", minutes: 1440, description: "One image a day" },
];

const STORAGE_KEYS = {
  promptSeed: "dreamgen.promptSeed",
  cadenceMinutes: "dreamgen.cadenceMinutes",
  sessionLoop: "dreamgen.sessionLoop",
};

const readString = (key: string, fallback: string) => {
  if (typeof window === "undefined") return fallback;
  return window.localStorage.getItem(key) ?? fallback;
};

const readNumber = (key: string, fallback: number) => {
  if (typeof window === "undefined") return fallback;
  const raw = window.localStorage.getItem(key);
  const value = raw ? Number(raw) : NaN;
  return Number.isFinite(value) ? value : fallback;
};

const readBoolean = (key: string, fallback: boolean) => {
  if (typeof window === "undefined") return fallback;
  const raw = window.localStorage.getItem(key);
  if (raw === null) return fallback;
  return raw === "true";
};

const formatCountdown = (target: Date | null) => {
  if (!target) return "Not scheduled";

  const diffMs = target.getTime() - Date.now();
  if (diffMs <= 0) return "Running now";

  const totalSeconds = Math.ceil(diffMs / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;

  if (hours > 0) return `${hours}h ${minutes}m ${seconds}s`;
  if (minutes > 0) return `${minutes}m ${seconds}s`;
  return `${seconds}s`;
};

const truncatePrompt = (prompt: string, max = 88) =>
  prompt.length > max ? `${prompt.slice(0, max).trim()}...` : prompt;

const HERO_NOTES: HeroNote[] = [
  { label: "Local-first", value: "Tiny fallback is ready immediately." },
  { label: "Recurring", value: "Loop runs while this tab stays open." },
  { label: "Entropy", value: "Plugins keep the feed from going flat." },
];

export default function Home() {
  const [activeTab, setActiveTab] = useState<TabId>("generate");
  const [promptSeed, setPromptSeed] = useState("");
  const [cadenceMinutes, setCadenceMinutes] = useState(60);
  const [loopEnabled, setLoopEnabled] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [currentImage, setCurrentImage] = useState<GenerateResponse | null>(null);
  const [recentImages, setRecentImages] = useState<RecentImage[]>([]);
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [nextRunAt, setNextRunAt] = useState<Date | null>(null);
  const [, setClockTick] = useState(Date.now());
  const [sessionCount, setSessionCount] = useState(0);
  const [logs, setLogs] = useState<string[]>(["DreamGen is ready."]);
  const [showLogs, setShowLogs] = useState(false);

  const promptSeedRef = useRef(promptSeed);
  const cadenceMinutesRef = useRef(cadenceMinutes);
  const isGeneratingRef = useRef(isGenerating);
  const runGenerationRef = useRef<(source: "manual" | "loop") => Promise<void>>(
    async () => {}
  );

  const cadence =
    CADENCE_OPTIONS.find((option) => option.minutes === cadenceMinutes) ?? CADENCE_OPTIONS[2];
  const currentBackend =
    currentImage?.metadata.backend && currentImage.metadata.backend !== "unknown"
      ? currentImage.metadata.backend
      : status?.backend ?? "unknown";
  const currentPluginCount =
    currentImage?.metadata.plugins_used?.length && currentImage.metadata.plugins_used.length > 0
      ? currentImage.metadata.plugins_used.length
      : status?.active_plugins?.length ?? 0;
  const isSmokeBackend = currentBackend === "smoke-test";

  const addLog = (message: string, type: "info" | "error" = "info") => {
    const timestamp = new Date().toLocaleTimeString();
    const prefix = type === "error" ? "[ERROR]" : "[INFO]";
    startTransition(() => {
      setLogs((prev) => [...prev.slice(-11), `${timestamp} ${prefix} ${message}`]);
    });
  };

  const loadRecentImages = useCallback(async () => {
    try {
      const response = await api.getGallery(6, 0);
      const latestImage = response.images[0];
      startTransition(() => {
        setRecentImages(response.images);
        if (latestImage) {
          setCurrentImage((existing) =>
            existing ??
            ({
              id: latestImage.path,
              prompt: latestImage.prompt,
              image_path: latestImage.path,
              metadata: {
                backend: status?.backend ?? "unknown",
                plugins_used: status?.active_plugins ?? [],
              },
              created_at: latestImage.created_at,
            } satisfies GenerateResponse)
          );
        }
      });
    } catch (error) {
      console.error("Failed to load recent images:", error);
    }
  }, [status?.active_plugins, status?.backend]);

  runGenerationRef.current = async (source: "manual" | "loop") => {
    if (isGeneratingRef.current) return;

    isGeneratingRef.current = true;
    setIsGenerating(true);
    const activeCadence =
      CADENCE_OPTIONS.find((option) => option.minutes === cadenceMinutesRef.current) ??
      CADENCE_OPTIONS[2];

    addLog(
      source === "manual"
        ? "Generating image now."
        : `Loop tick fired. Next image requested with ${activeCadence.label.toLowerCase()} cadence.`
    );

    try {
      const response = await api.generate({
        prompt: promptSeedRef.current.trim() || undefined,
        enable_plugins: true,
      });

      startTransition(() => {
        setCurrentImage(response);
        setSessionCount((count) => count + 1);
      });

      addLog(`Image created with ${response.metadata.backend}.`);
      await galleryCache.clear();
      await loadRecentImages();
    } catch (error) {
      const errorMsg = error instanceof Error ? error.message : "Unknown error";
      addLog(`Generation failed: ${errorMsg}`, "error");
    } finally {
      isGeneratingRef.current = false;
      setIsGenerating(false);
    }
  };

  useEffect(() => {
    setPromptSeed(readString(STORAGE_KEYS.promptSeed, ""));
    setCadenceMinutes(readNumber(STORAGE_KEYS.cadenceMinutes, 60));
    setLoopEnabled(readBoolean(STORAGE_KEYS.sessionLoop, false));
  }, [loadRecentImages]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(STORAGE_KEYS.promptSeed, promptSeed);
    promptSeedRef.current = promptSeed;
  }, [promptSeed]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(STORAGE_KEYS.cadenceMinutes, String(cadenceMinutes));
    cadenceMinutesRef.current = cadenceMinutes;
  }, [cadenceMinutes]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(STORAGE_KEYS.sessionLoop, String(loopEnabled));
  }, [loopEnabled]);

  useEffect(() => {
    isGeneratingRef.current = isGenerating;
  }, [isGenerating]);

  useEffect(() => {
    api.getStatus().then(setStatus).catch(console.error);
    loadRecentImages();

    api.connectWebSocket((data) => {
      if (typeof data !== "object" || data === null || !("type" in data)) return;

      const msg = data as Record<string, unknown>;
      if (msg.type === "model_loading") {
        addLog(String(msg.message ?? "Loading model..."));
      } else if (msg.type === "generation_completed") {
        addLog(`Saved ${String(msg.image_path ?? "image")}.`);
      } else if (msg.type === "generation_error") {
        addLog(`Backend error: ${String(msg.error ?? "unknown")}`, "error");
      }
    });

    return () => {
      api.disconnectWebSocket();
    };
  }, [loadRecentImages]);

  useEffect(() => {
    if (!loopEnabled) {
      setNextRunAt(null);
      return;
    }

    const firstRun = new Date(Date.now() + cadenceMinutes * 60 * 1000);
    setNextRunAt(firstRun);
  }, [loopEnabled, cadenceMinutes]);

  useEffect(() => {
    if (!loopEnabled || !nextRunAt) return;

    const intervalId = window.setInterval(() => {
      setClockTick(Date.now());
      if (Date.now() >= nextRunAt.getTime() && !isGeneratingRef.current) {
        void runGenerationRef.current("loop");
        setNextRunAt(new Date(Date.now() + cadenceMinutes * 60 * 1000));
      }
    }, 1000);

    return () => {
      window.clearInterval(intervalId);
    };
  }, [cadenceMinutes, loopEnabled, nextRunAt]);

  const tabs = [
    { id: "generate" as const, label: "Generator", icon: Sparkles },
    { id: "gallery" as const, label: "Gallery", icon: ImageIcon },
    { id: "settings" as const, label: "Settings", icon: SettingsIcon },
    { id: "playground" as const, label: "Advanced", icon: Wand2 },
  ];

  return (
    <div className="relative flex h-screen overflow-hidden bg-background">
      <div className="pointer-events-none absolute inset-0">
        <div className="absolute inset-0 bg-[linear-gradient(hsl(var(--border)/0.08)_1px,transparent_1px),linear-gradient(90deg,hsl(var(--border)/0.08)_1px,transparent_1px)] bg-[size:72px_72px] opacity-[0.14]" />
        <div className="absolute -left-24 top-24 h-80 w-80 rounded-full bg-primary/10 blur-3xl" />
        <div className="absolute right-0 top-0 h-72 w-72 rounded-full bg-accent/10 blur-3xl" />
      </div>

      <div className="relative z-10 flex h-full w-full flex-col overflow-hidden">
      <header className="border-b border-border/80 bg-card/80 backdrop-blur-xl">
        <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4 sm:px-6">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-2xl border border-border/80 bg-background/70 shadow-[0_12px_30px_rgba(0,0,0,0.18)]">
              <Image src="/logo_mark.png" alt="DreamGen" width={22} height={22} />
            </div>
            <div>
              <div className="text-base font-semibold tracking-tight text-foreground">DreamGen</div>
              <div className="text-[11px] uppercase tracking-[0.22em] text-muted-foreground/85">
                recurring local image generator
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2 text-xs">
            <span className="status-pill">
              <span className={cn("h-1.5 w-1.5 rounded-full", status?.status === "ready" ? "bg-primary" : "bg-amber-400")} />
              {status?.status === "ready" ? "API ready" : "Connecting"}
            </span>
            <span className="status-pill hidden sm:inline-flex">
              GPU {status?.gpu_available ? "online" : "offline"}
            </span>
            <span className="status-pill hidden md:inline-flex capitalize">
              {status?.backend ?? "unknown"}
            </span>
          </div>
        </div>
      </header>

      <div className="border-b border-border/70 bg-muted/20">
        <div className="mx-auto flex max-w-7xl gap-2 overflow-x-auto px-3 py-3 sm:px-6">
          {tabs.map((tab) => {
            const Icon = tab.icon;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={cn(
                  "flex items-center gap-2 rounded-full border px-3 py-2 text-sm transition whitespace-nowrap",
                  activeTab === tab.id
                    ? "border-border/80 bg-card/90 text-foreground shadow-[0_8px_30px_rgba(0,0,0,0.18)]"
                    : "border-transparent text-muted-foreground hover:border-border/60 hover:bg-card/40 hover:text-foreground"
                )}
              >
                <Icon className="h-4 w-4" />
                {tab.label}
              </button>
            );
          })}
        </div>
      </div>

      <main className="flex-1 overflow-hidden">
        <AnimatePresence mode="wait">
          {activeTab === "generate" && (
            <motion.div
              key="generate"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              className="h-full overflow-y-auto"
            >
              <div className="mx-auto grid max-w-7xl gap-6 px-4 py-6 sm:px-6 lg:grid-cols-[390px_minmax(0,1fr)]">
                <section className="space-y-5">
                  <div className="ambient-panel rounded-3xl border border-border/80 p-5">
                    <div className="mb-4 flex items-start justify-between gap-4">
                      <div>
                        <div className="mb-3 inline-flex rounded-full border border-primary/20 bg-primary/10 px-3 py-1 text-[11px] uppercase tracking-[0.22em] text-primary">
                          recurring image feed
                        </div>
                        <h1 className="text-3xl font-semibold tracking-tight text-foreground">
                          Make images on a rhythm
                        </h1>
                        <p className="mt-3 max-w-md text-sm leading-6 text-muted-foreground">
                          Leave the prompt blank for full entropy, or give DreamGen a seed phrase.
                          Start the session loop and it keeps creating while this page stays open.
                        </p>
                      </div>
                      <div className="rounded-[1.25rem] border border-border/80 bg-background/80 px-3 py-3 text-right shadow-[0_12px_30px_rgba(0,0,0,0.16)]">
                        <div className="text-[11px] uppercase tracking-wide text-muted-foreground">
                          Session
                        </div>
                        <div className="text-2xl font-semibold tracking-tight text-foreground">{sessionCount}</div>
                      </div>
                    </div>

                    <div className="mb-5 grid gap-2">
                      {HERO_NOTES.map((note) => (
                        <div
                          key={note.label}
                          className="flex items-start gap-3 rounded-2xl border border-border/70 bg-background/55 px-4 py-2.5"
                        >
                          <span className="mt-1 h-2 w-2 rounded-full bg-primary" />
                          <div>
                            <p className="text-xs uppercase tracking-[0.2em] text-muted-foreground">
                              {note.label}
                            </p>
                            <p className="mt-1 text-sm leading-5 text-foreground/90">{note.value}</p>
                          </div>
                        </div>
                      ))}
                    </div>

                    <div className="space-y-4">
                      <div className="rounded-2xl border border-primary/20 bg-primary/10 px-4 py-3">
                        <div className="text-[11px] uppercase tracking-[0.22em] text-primary">
                          Start Here
                        </div>
                        <p className="mt-2 text-sm leading-6 text-foreground/90">
                          Use <span className="font-medium text-foreground">Generate now</span> for one
                          image, or <span className="font-medium text-foreground">Start loop</span> to let
                          DreamGen keep building the feed.
                        </p>
                      </div>

                      <div>
                        <label className="mb-2 block text-xs font-medium uppercase tracking-wide text-muted-foreground">
                          Theme seed
                        </label>
                        <textarea
                          value={promptSeed}
                          onChange={(event) => setPromptSeed(event.target.value)}
                          rows={3}
                          placeholder="Optional: brutalist gardens, retrofuturist machinery, haunted motel, etc."
                          className="w-full rounded-2xl border border-input/80 bg-background/80 px-3 py-3 text-sm leading-6 outline-none transition focus:border-primary focus:ring-2 focus:ring-primary/20"
                        />
                        <p className="mt-2 text-xs text-muted-foreground">
                          Empty means fully AI-generated prompts with your active plugins.
                        </p>
                      </div>

                      <div>
                        <label className="mb-2 block text-xs font-medium uppercase tracking-wide text-muted-foreground">
                          Cadence
                        </label>
                        <div className="grid grid-cols-2 gap-2">
                          {CADENCE_OPTIONS.map((option) => (
                            <button
                              key={option.minutes}
                              onClick={() => setCadenceMinutes(option.minutes)}
                              className={cn(
                                "rounded-2xl border px-3 py-3 text-left transition",
                                cadenceMinutes === option.minutes
                                  ? "border-primary/40 bg-primary/12 shadow-[0_8px_24px_rgba(39,229,166,0.1)]"
                                  : "border-border/70 bg-background/45 hover:border-primary/30 hover:bg-muted/35"
                              )}
                            >
                              <div className="text-sm font-medium text-foreground">{option.label}</div>
                              <div className="text-xs text-muted-foreground">{option.description}</div>
                            </button>
                          ))}
                        </div>
                      </div>

                      <div className="grid grid-cols-2 gap-3">
                        <button
                          onClick={() => void runGenerationRef.current("manual")}
                          disabled={isGenerating}
                          className="flex items-center justify-center gap-2 rounded-2xl bg-primary px-4 py-3 text-sm font-medium text-primary-foreground shadow-[0_16px_40px_rgba(39,229,166,0.18)] transition hover:translate-y-[-1px] hover:opacity-95 disabled:opacity-50"
                        >
                          {isGenerating ? (
                            <>
                              <Loader2 className="h-4 w-4 animate-spin" />
                              Working...
                            </>
                          ) : (
                            <>
                              <Sparkles className="h-4 w-4" />
                              Generate now
                            </>
                          )}
                        </button>

                        <button
                          onClick={() => setLoopEnabled((value) => !value)}
                          className={cn(
                            "flex items-center justify-center gap-2 rounded-2xl border px-4 py-3 text-sm font-medium transition",
                            loopEnabled
                              ? "border-destructive/40 bg-destructive/10 text-foreground hover:bg-destructive/15"
                              : "border-border/70 bg-background/75 text-foreground hover:border-primary/30 hover:bg-muted/50"
                          )}
                        >
                          {loopEnabled ? (
                            <>
                              <Square className="h-4 w-4" />
                              Stop loop
                            </>
                          ) : (
                            <>
                              <Play className="h-4 w-4" />
                              Start loop
                            </>
                          )}
                        </button>
                      </div>
                    </div>
                  </div>

                  <div className="ambient-panel rounded-3xl border border-border/80 p-5">
                    <div className="mb-4 flex items-center gap-2">
                      <Clock3 className="h-4 w-4 text-primary" />
                      <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                        Loop status
                      </h2>
                    </div>

                    <div className="grid grid-cols-2 gap-3">
                      <div className="rounded-2xl border border-border/60 bg-background/70 p-4">
                        <div className="text-[11px] uppercase tracking-wide text-muted-foreground">
                          Mode
                        </div>
                        <div className="mt-2 text-lg font-semibold text-foreground">
                          {loopEnabled ? "Running" : "Idle"}
                        </div>
                      </div>
                      <div className="rounded-2xl border border-border/60 bg-background/70 p-4">
                        <div className="text-[11px] uppercase tracking-wide text-muted-foreground">
                          Next run
                        </div>
                        <div className="mt-2 text-lg font-semibold text-foreground">
                          {loopEnabled ? formatCountdown(nextRunAt) : "Not scheduled"}
                        </div>
                      </div>
                    </div>

                    <div className="mt-3 rounded-2xl border border-border/60 bg-background/65 px-4 py-3 text-sm text-muted-foreground">
                      Cadence: <span className="font-medium text-foreground">{cadence.label}</span>
                      <span className="ml-2 text-muted-foreground/80">{cadence.description}</span>
                    </div>

                    <div className="mt-4 rounded-2xl border border-dashed border-border/80 px-4 py-3 text-xs leading-6 text-muted-foreground">
                      Session loop runs while this browser tab stays open. For true background jobs,
                      use <code className="mx-1 rounded bg-background px-1 py-0.5">uv run dreamgen loop</code>.
                    </div>
                  </div>

                  <div className="ambient-panel rounded-3xl border border-border/80 p-5">
                    <div className="mb-4 flex items-center gap-2">
                      <Bot className="h-4 w-4 text-primary" />
                      <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                        Active engine
                      </h2>
                    </div>

                    <div className="space-y-3 text-sm">
                      <div className="flex items-center justify-between rounded-2xl border border-border/60 bg-background/70 px-4 py-3">
                        <span className="text-muted-foreground">Backend</span>
                        <span className="font-medium capitalize text-foreground">
                          {status?.backend ?? "unknown"}
                        </span>
                      </div>
                      <div className="flex items-center justify-between rounded-2xl border border-border/60 bg-background/70 px-4 py-3">
                        <span className="text-muted-foreground">GPU</span>
                        <span className="font-medium text-foreground">
                          {status?.gpu_available ? "Available" : "Unavailable"}
                        </span>
                      </div>
                      <div className="flex items-center justify-between rounded-2xl border border-border/60 bg-background/70 px-4 py-3">
                        <span className="text-muted-foreground">Entropy plugins</span>
                        <span className="font-medium text-foreground">
                          {status?.active_plugins?.length ?? 0} active
                        </span>
                      </div>
                    </div>
                  </div>
                </section>

                <section className="grid content-start gap-6">
                  <div className="ambient-panel rounded-[2rem] border border-border/80 p-5">
                    <div className="mb-4 flex items-center justify-between gap-4">
                      <div>
                        <div className="text-xs uppercase tracking-[0.2em] text-muted-foreground">
                          Current output
                        </div>
                        <div className="mt-1 text-lg font-semibold text-foreground">
                          {currentImage ? "Latest generation" : "Waiting for first image"}
                        </div>
                        <div className="mt-3 flex flex-wrap gap-2">
                          <span className="status-pill capitalize">{currentBackend}</span>
                          <span className="status-pill">{currentPluginCount} plugins</span>
                          {isSmokeBackend ? (
                            <span className="status-pill">smoke-test quality</span>
                          ) : null}
                        </div>
                      </div>
                      <a
                        href="/playground"
                        className="rounded-full border border-border/80 bg-background/75 px-3 py-2 text-xs text-muted-foreground transition hover:border-primary/30 hover:text-foreground"
                      >
                        Open advanced playground
                      </a>
                    </div>

                    <div className="min-h-[420px] rounded-[1.5rem] border border-border/70 bg-background/70 p-4">
                      <AnimatePresence mode="wait">
                        {isGenerating ? (
                          <motion.div
                            key="loading"
                            initial={{ opacity: 0, scale: 0.96 }}
                            animate={{ opacity: 1, scale: 1 }}
                            exit={{ opacity: 0, scale: 0.96 }}
                            className="text-center"
                          >
                            <Loader2 className="mx-auto mb-4 h-16 w-16 animate-spin text-primary" />
                            <p className="text-sm text-foreground">DreamGen is creating a new image.</p>
                            <p className="mt-2 text-xs text-muted-foreground">
                              Small fallback is ready faster. FLUX can take longer on first load.
                            </p>
                          </motion.div>
                        ) : currentImage ? (
                          <motion.div
                            key={currentImage.id}
                            initial={{ opacity: 0, scale: 0.97 }}
                            animate={{ opacity: 1, scale: 1 }}
                            exit={{ opacity: 0, scale: 0.97 }}
                            className="flex w-full flex-col items-center"
                          >
                            <div className="flex min-h-[380px] w-full items-center justify-center rounded-[1.75rem] border border-border/60 bg-[radial-gradient(circle_at_top,hsl(var(--accent)/0.08),transparent_22rem)] px-4 py-6">
                              {/* Backend-served generated files are not routed through Next image optimization. */}
                              {/* eslint-disable-next-line @next/next/no-img-element */}
                              <img
                                src={`${API_BASE}${currentImage.image_path}`}
                                alt="Generated image"
                                className="max-h-[68vh] max-w-full rounded-2xl object-contain shadow-[0_24px_80px_rgba(0,0,0,0.34)]"
                              />
                            </div>
                            <div className="mt-4 w-full max-w-5xl rounded-2xl border border-border/60 bg-background/80 px-4 py-3">
                              <p className="text-center text-sm leading-7 text-muted-foreground">
                                {currentImage.prompt}
                              </p>
                            </div>
                          </motion.div>
                        ) : (
                          <div className="text-center">
                            <ImageIcon className="mx-auto mb-4 h-16 w-16 text-muted-foreground/30" />
                            <p className="text-sm text-muted-foreground">
                              Use the controls on the left to generate once or start the loop.
                            </p>
                            <div className="mt-6 grid gap-3 text-left sm:grid-cols-3">
                              <div className="rounded-2xl border border-border/60 bg-card/70 p-4">
                                <div className="text-xs uppercase tracking-[0.2em] text-muted-foreground">
                                  First run
                                </div>
                                <p className="mt-2 text-sm text-foreground/90">
                                  Small fallback gives usable first images before FLUX is ready.
                                </p>
                              </div>
                              <div className="rounded-2xl border border-border/60 bg-card/70 p-4">
                                <div className="text-xs uppercase tracking-[0.2em] text-muted-foreground">
                                  Prompt seed
                                </div>
                                <p className="mt-2 text-sm text-foreground/90">
                                  Give it a loose theme or leave it empty for maximum entropy.
                                </p>
                              </div>
                              <div className="rounded-2xl border border-border/60 bg-card/70 p-4">
                                <div className="text-xs uppercase tracking-[0.2em] text-muted-foreground">
                                  Continuous
                                </div>
                                <p className="mt-2 text-sm text-foreground/90">
                                  Use the session loop here, or run the CLI loop for background jobs.
                                </p>
                              </div>
                            </div>
                          </div>
                        )}
                      </AnimatePresence>
                    </div>
                  </div>

                  <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
                    <div className="ambient-panel rounded-3xl border border-border/80 p-5">
                      <div className="mb-4 flex items-center justify-between gap-3">
                        <div className="flex items-center gap-2">
                          <GalleryHorizontalEnd className="h-4 w-4 text-primary" />
                          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                            Recent outputs
                          </h2>
                        </div>
                        <button
                          onClick={() => void loadRecentImages()}
                          className="text-xs text-muted-foreground transition hover:text-foreground"
                        >
                          refresh
                        </button>
                      </div>

                      {recentImages.length > 0 ? (
                        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                          {recentImages.map((image) => (
                            <button
                              key={image.path}
                              onClick={() => {
                                setCurrentImage({
                                  id: image.path,
                                  prompt: image.prompt,
                                  image_path: image.path,
                                  metadata: {
                                    backend: status?.backend ?? "unknown",
                                    plugins_used: status?.active_plugins ?? [],
                                  },
                                  created_at: image.created_at,
                                });
                              }}
                              className="overflow-hidden rounded-2xl border border-border bg-background text-left transition hover:border-primary/40 hover:bg-muted/30"
                            >
                              {/* Backend-served generated files are not routed through Next image optimization. */}
                              {/* eslint-disable-next-line @next/next/no-img-element */}
                              <img
                                src={`${API_BASE}${image.path}`}
                                alt="Recent generation"
                                className="h-36 w-full object-cover"
                              />
                              <div className="p-3">
                                <p className="text-xs text-muted-foreground">
                                  {new Date(image.created_at).toLocaleString()}
                                </p>
                                <p className="mt-1 text-xs text-foreground">
                                  {truncatePrompt(image.prompt)}
                                </p>
                              </div>
                            </button>
                          ))}
                        </div>
                      ) : (
                        <div className="rounded-2xl bg-background px-4 py-10 text-center text-sm text-muted-foreground">
                          No recent images yet.
                        </div>
                      )}
                    </div>

                    <div className="ambient-panel rounded-3xl border border-border/80 p-5">
                      <button
                        onClick={() => setShowLogs((value) => !value)}
                        className="mb-4 flex w-full items-center justify-between gap-3"
                      >
                        <div className="flex items-center gap-2">
                          <Cpu className="h-4 w-4 text-primary" />
                          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                            Session log
                          </h2>
                        </div>
                        <span className="text-xs text-muted-foreground">
                          {showLogs ? "hide" : "show"}
                        </span>
                      </button>

                      {showLogs ? (
                        <div className="space-y-2 rounded-2xl border border-border/60 bg-background/80 p-4 font-mono text-xs">
                          {logs.map((log, index) => (
                            <div
                              key={`${log}-${index}`}
                              className={cn(
                                "break-words",
                                log.includes("[ERROR]") ? "text-destructive" : "text-primary"
                              )}
                            >
                              {log}
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className="rounded-2xl border border-border/60 bg-background/70 px-4 py-10 text-center text-sm text-muted-foreground">
                          Logs hidden.
                        </div>
                      )}
                    </div>
                  </div>
                </section>
              </div>
            </motion.div>
          )}

          {activeTab === "gallery" && (
            <motion.div
              key="gallery"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              className="h-full"
            >
              <Gallery />
            </motion.div>
          )}

          {activeTab === "settings" && (
            <motion.div
              key="settings"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              className="h-full"
            >
              <Settings systemStatus={status} />
            </motion.div>
          )}

          {activeTab === "playground" && (
            <motion.div
              key="playground"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              className="h-full"
            >
              <iframe src="/playground" className="h-full w-full border-0" title="Advanced playground" />
            </motion.div>
          )}
        </AnimatePresence>
      </main>

      <footer className="border-t border-border bg-muted/50">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-3 px-4 py-2 text-xs text-muted-foreground sm:px-6">
          <span>
            {status?.status === "ready" ? "Ready to generate" : "Connecting to backend"}
          </span>
          <span>
            {loopEnabled
              ? `Loop active, next run in ${formatCountdown(nextRunAt)}`
              : "Loop stopped"}
          </span>
        </div>
      </footer>
      </div>
    </div>
  );
}
