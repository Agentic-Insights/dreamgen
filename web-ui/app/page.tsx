"use client";

import { startTransition, useEffect, useRef, useState } from "react";
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

  const addLog = (message: string, type: "info" | "error" = "info") => {
    const timestamp = new Date().toLocaleTimeString();
    const prefix = type === "error" ? "[ERROR]" : "[INFO]";
    startTransition(() => {
      setLogs((prev) => [...prev.slice(-11), `${timestamp} ${prefix} ${message}`]);
    });
  };

  const loadRecentImages = async () => {
    try {
      const response = await api.getGallery(6, 0);
      startTransition(() => {
        setRecentImages(response.images);
      });
    } catch (error) {
      console.error("Failed to load recent images:", error);
    }
  };

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
  }, []);

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
  }, []);

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
    <div className="h-screen bg-background flex flex-col overflow-hidden">
      <header className="border-b border-border bg-card/95 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-7xl items-center justify-between px-4 sm:px-6">
          <div className="flex items-center gap-3">
            <Image src="/logo_mark.png" alt="DreamGen" width={22} height={22} />
            <div>
              <div className="text-sm font-semibold text-foreground">DreamGen</div>
              <div className="text-[11px] text-muted-foreground">
                recurring local image generator
              </div>
            </div>
          </div>

          <div className="flex items-center gap-3 text-xs text-muted-foreground">
            <span>{status?.status === "ready" ? "API ready" : "Connecting..."}</span>
            <span className="hidden sm:inline">GPU {status?.gpu_available ? "yes" : "no"}</span>
            <span className="hidden md:inline capitalize">{status?.backend ?? "unknown"}</span>
          </div>
        </div>
      </header>

      <div className="border-b border-border bg-muted/40">
        <div className="mx-auto flex max-w-7xl gap-1 overflow-x-auto px-3 py-2 sm:px-6">
          {tabs.map((tab) => {
            const Icon = tab.icon;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={cn(
                  "flex items-center gap-2 rounded-full px-3 py-2 text-sm transition-colors whitespace-nowrap",
                  activeTab === tab.id
                    ? "bg-card text-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground"
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
              <div className="mx-auto grid max-w-7xl gap-6 px-4 py-6 sm:px-6 lg:grid-cols-[420px_minmax(0,1fr)]">
                <section className="space-y-5">
                  <div className="rounded-3xl border border-border bg-card p-5">
                    <div className="mb-4 flex items-start justify-between gap-4">
                      <div>
                        <h1 className="text-2xl font-semibold text-foreground">
                          Make images on a rhythm
                        </h1>
                        <p className="mt-2 text-sm text-muted-foreground">
                          Leave the prompt blank for full entropy, or give DreamGen a seed phrase.
                          Start the session loop and it keeps creating while this page stays open.
                        </p>
                      </div>
                      <div className="rounded-2xl border border-border bg-background px-3 py-2 text-right">
                        <div className="text-[11px] uppercase tracking-wide text-muted-foreground">
                          Session
                        </div>
                        <div className="text-xl font-semibold text-foreground">{sessionCount}</div>
                      </div>
                    </div>

                    <div className="space-y-4">
                      <div>
                        <label className="mb-2 block text-xs font-medium uppercase tracking-wide text-muted-foreground">
                          Theme seed
                        </label>
                        <textarea
                          value={promptSeed}
                          onChange={(event) => setPromptSeed(event.target.value)}
                          rows={4}
                          placeholder="Optional: brutalist gardens, retrofuturist machinery, haunted motel, etc."
                          className="w-full rounded-2xl border border-input bg-background px-3 py-3 text-sm outline-none transition focus:border-primary focus:ring-2 focus:ring-primary/20"
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
                                  ? "border-primary bg-primary/8"
                                  : "border-border hover:border-primary/40 hover:bg-muted/40"
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
                          className="flex items-center justify-center gap-2 rounded-2xl bg-primary px-4 py-3 text-sm font-medium text-primary-foreground transition hover:opacity-90 disabled:opacity-50"
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
                              : "border-border bg-background text-foreground hover:border-primary/40 hover:bg-muted/50"
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

                  <div className="rounded-3xl border border-border bg-card p-5">
                    <div className="mb-4 flex items-center gap-2">
                      <Clock3 className="h-4 w-4 text-primary" />
                      <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                        Loop status
                      </h2>
                    </div>

                    <div className="grid grid-cols-2 gap-3">
                      <div className="rounded-2xl bg-background p-4">
                        <div className="text-[11px] uppercase tracking-wide text-muted-foreground">
                          Mode
                        </div>
                        <div className="mt-2 text-lg font-semibold text-foreground">
                          {loopEnabled ? "Running" : "Idle"}
                        </div>
                      </div>
                      <div className="rounded-2xl bg-background p-4">
                        <div className="text-[11px] uppercase tracking-wide text-muted-foreground">
                          Next run
                        </div>
                        <div className="mt-2 text-lg font-semibold text-foreground">
                          {loopEnabled ? formatCountdown(nextRunAt) : "Not scheduled"}
                        </div>
                      </div>
                    </div>

                    <div className="mt-3 rounded-2xl bg-background px-4 py-3 text-sm text-muted-foreground">
                      Cadence: <span className="font-medium text-foreground">{cadence.label}</span>
                      <span className="ml-2 text-muted-foreground/80">{cadence.description}</span>
                    </div>

                    <div className="mt-4 rounded-2xl border border-dashed border-border px-4 py-3 text-xs text-muted-foreground">
                      Session loop runs while this browser tab stays open. For true background jobs,
                      use <code className="mx-1 rounded bg-background px-1 py-0.5">uv run imagegen loop</code>.
                    </div>
                  </div>

                  <div className="rounded-3xl border border-border bg-card p-5">
                    <div className="mb-4 flex items-center gap-2">
                      <Bot className="h-4 w-4 text-primary" />
                      <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                        Active engine
                      </h2>
                    </div>

                    <div className="space-y-3 text-sm">
                      <div className="flex items-center justify-between rounded-2xl bg-background px-4 py-3">
                        <span className="text-muted-foreground">Backend</span>
                        <span className="font-medium capitalize text-foreground">
                          {status?.backend ?? "unknown"}
                        </span>
                      </div>
                      <div className="flex items-center justify-between rounded-2xl bg-background px-4 py-3">
                        <span className="text-muted-foreground">GPU</span>
                        <span className="font-medium text-foreground">
                          {status?.gpu_available ? "Available" : "Unavailable"}
                        </span>
                      </div>
                      <div className="flex items-center justify-between rounded-2xl bg-background px-4 py-3">
                        <span className="text-muted-foreground">Entropy plugins</span>
                        <span className="font-medium text-foreground">
                          {status?.active_plugins?.length ?? 0} active
                        </span>
                      </div>
                    </div>
                  </div>
                </section>

                <section className="grid min-h-[70vh] gap-6 lg:grid-rows-[minmax(0,1fr)_auto]">
                  <div className="rounded-[2rem] border border-border bg-gradient-to-br from-card via-card to-muted/60 p-5">
                    <div className="mb-4 flex items-center justify-between gap-4">
                      <div>
                        <div className="text-xs uppercase tracking-[0.2em] text-muted-foreground">
                          Current output
                        </div>
                        <div className="mt-1 text-lg font-semibold text-foreground">
                          {currentImage ? "Latest generation" : "Waiting for first image"}
                        </div>
                      </div>
                      <a
                        href="/playground"
                        className="rounded-full border border-border bg-background px-3 py-2 text-xs text-muted-foreground transition hover:border-primary/40 hover:text-foreground"
                      >
                        Open advanced playground
                      </a>
                    </div>

                    <div className="flex h-[calc(100%-3rem)] min-h-[420px] items-center justify-center rounded-[1.5rem] border border-border/70 bg-background/70 p-4">
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
                              Tiny fallback is quick. FLUX can take longer on first load.
                            </p>
                          </motion.div>
                        ) : currentImage ? (
                          <motion.div
                            key={currentImage.id}
                            initial={{ opacity: 0, scale: 0.97 }}
                            animate={{ opacity: 1, scale: 1 }}
                            exit={{ opacity: 0, scale: 0.97 }}
                            className="flex h-full w-full flex-col items-center justify-center"
                          >
                            {/* Backend-served generated files are not routed through Next image optimization. */}
                            {/* eslint-disable-next-line @next/next/no-img-element */}
                            <img
                              src={`${API_BASE}${currentImage.image_path}`}
                              alt="Generated image"
                              className="max-h-[calc(100%-4rem)] max-w-full rounded-2xl object-contain shadow-2xl"
                            />
                            <p className="mt-4 max-w-3xl text-center text-sm text-muted-foreground">
                              {currentImage.prompt}
                            </p>
                          </motion.div>
                        ) : (
                          <div className="text-center">
                            <ImageIcon className="mx-auto mb-4 h-16 w-16 text-muted-foreground/30" />
                            <p className="text-sm text-muted-foreground">
                              Generate once or start the loop to begin building your feed.
                            </p>
                          </div>
                        )}
                      </AnimatePresence>
                    </div>
                  </div>

                  <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
                    <div className="rounded-3xl border border-border bg-card p-5">
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

                    <div className="rounded-3xl border border-border bg-card p-5">
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
                        <div className="space-y-2 rounded-2xl bg-background p-4 font-mono text-xs">
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
                        <div className="rounded-2xl bg-background px-4 py-10 text-center text-sm text-muted-foreground">
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
  );
}
