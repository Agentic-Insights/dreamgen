const normalizeBase = (value: string | undefined, fallback: string) =>
  (value || fallback).replace(/\/$/, '');

export const API_BASE = normalizeBase(
  process.env.NEXT_PUBLIC_API_URL,
  'http://localhost:25800'
);

const WS_BASE = normalizeBase(
  process.env.NEXT_PUBLIC_WS_URL,
  API_BASE.replace(/^http/, 'ws')
);

export interface GenerateRequest {
  prompt?: string;
  meta_prompt?: string;
  use_mock?: boolean;
  enable_plugins?: boolean;
  seed?: number;
  recipe_id?: string;
  experiment_label?: string;
  prompt_family?: string;
  quality_flags?: string[];
  client_request_id?: string;
}

export interface ExperimentMetadata {
  id?: string;
  label?: string | null;
  prompt_family?: string | null;
  prompt?: {
    source?: string;
    meta_prompt?: string | null;
    final?: string;
    model?: string | null;
  };
  pipeline?: {
    configured_backend?: string;
    resolved_backend?: string;
    model?: string;
    prompt_model?: string | null;
  };
  parameters?: {
    seed?: number | null;
    width?: number | null;
    height?: number | null;
    steps?: number | null;
    guidance_scale?: number | null;
    true_cfg_scale?: number | null;
  };
  enhancers?: {
    plugins?: string[];
    loras?: string[];
    lora_application_probability?: number | null;
  };
  timing?: {
    generation_seconds?: number;
  };
  diagnostic?: boolean;
  quality_flags?: string[];
}

export interface GenerateResponse {
  id: string;
  prompt: string;
  image_path: string;
  metadata: {
    backend: string;
    model?: string;
    generation_time?: number;
    experiment?: ExperimentMetadata;
    quality_flags?: string[];
    plugins_used: string[];
    seed?: number;
    provider?: string;
    ollama_model?: string | null;
    lora_backend?: string | null;
    using_diffsynth?: boolean;
    selected_lora?: string | null;
  };
  created_at: string;
}

export interface PluginInfo {
  name: string;
  enabled: boolean;
  description: string;
  order: number;
  category?: 'entropy' | 'context' | 'style' | 'operational' | string;
  kind?: 'prompt' | 'guard' | string;
  phase?: string;
}

export interface SystemStatus {
  status: string;
  backend: string;
  plugins_enabled: boolean;
  active_plugins: string[];
  gpu_available: boolean;
  ollama_available: boolean;
  configured_backend: string;
  resolved_backend: string;
  active_backend_label: string;
  active_model: string;
  active_model_id: string;
  active_model_status: string;
  preferred_backend: string;
  preferred_model: string;
  preferred_model_id: string;
  preferred_model_status: string;
  fallback_backend: string;
  fallback_model: string;
  fallback_model_id: string;
  fallback_reason?: string | null;
}

export interface ModelInfo {
  backend?: string;
  id: string;
  name: string;
  type: string;
  status:
    | 'not_downloaded'
    | 'not_configured'
    | 'configured'
    | 'downloading'
    | 'ready'
    | 'partial'
    | 'runtime_unavailable'
    | 'incompatible_runtime'
    | 'runtime_error'
    | 'revision_mismatch';
  size: number;
  incomplete_files: number;
  path?: string;
  downloadable?: boolean;
  reason?: string;
  source_url?: string;
  implementation_url?: string;
  license?: string;
  research_only?: boolean;
  verified_revision?: string;
  runtime?: {
    reachable?: boolean;
    ready?: boolean;
    loaded?: boolean;
    status?: string;
    reason?: string;
    source_sha?: string;
    model_revision?: string;
    verified_model_revision?: string;
    attention?: string;
  };
}

export interface ModelStatus {
  models: ModelInfo[];
  cache_dir: string;
  configured_backend: string;
  resolved_backend: string;
  active_backend?: string;
  active_backend_label?: string;
  active_model?: string;
  active_model_id?: string;
  active_model_status?: string;
  preferred_backend?: string;
  preferred_model?: string;
  preferred_model_id?: string;
  preferred_model_status?: string;
  fallback_backend?: string;
  fallback_model?: string;
  fallback_model_id?: string;
  fallback_reason?: string | null;
  memory: {
    system: { total_gb: number; available_gb: number; percent_used: number };
    cuda: { available: boolean; device?: string; total_gb?: number; free_gb?: number; allocated_gb?: number; reserved_gb?: number };
  };
  recommended: { backend: string; width: number; height: number; reason: string };
  selection_path: string;
}

export interface HFTokenStatus {
  configured: boolean;
  source?: 'environment' | 'file';
}

export interface EditRequest {
  prompt: string;
  strength?: number;
  backend?: 'auto' | 'mock' | 'qwen';
  source_path?: string;
}

export interface EditResponse {
  id: string;
  prompt: string;
  original_path: string;
  edited_path: string;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface MageEditVariant {
  id: 'base' | 'aligned' | 'turbo';
  label: string;
  repository: string;
  default_steps: number;
  default_guidance: number;
  verified_revision?: string | null;
  available: boolean;
  ready?: boolean;
  cached?: boolean;
  availability_reason?: string | null;
}

export interface MageEditCapabilities {
  feature: string;
  official_name: string;
  source_repository: string;
  source_revision: string;
  license: string;
  research_only: boolean;
  target_hardware: string;
  available: boolean;
  model_loaded: boolean;
  loaded_model_id?: string | null;
  runtime_status?: string;
  runtime_reason?: string | null;
  access_note: string;
  gpu: {
    available: boolean;
    name?: string | null;
    vram_total_mb?: number | null;
    vram_free_mb?: number | null;
  };
  variants: MageEditVariant[];
}

export interface MageEditJob {
  id: string;
  status: 'queued' | 'running' | 'cancelling' | 'cancelled' | 'succeeded' | 'failed';
  prompt: string;
  backend: string;
  source_path?: string | null;
  original_path?: string | null;
  edited_path?: string | null;
  root_job_id: string;
  parent_job_id?: string | null;
  version: number;
  decision_state: 'pending' | 'approved' | 'rejected';
  manifest_path?: string | null;
  metadata: Record<string, unknown>;
  error?: string | null;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
}

export interface CreateMageEditRequest {
  command: string;
  variant: MageEditVariant['id'];
  seed: number;
  steps: number;
  guidance: number;
  max_size: number;
  negative_prompt?: string;
  vl_cond_long_edge?: number;
  source_path?: string;
  parent_job_id?: string;
}

export interface PromptResponse {
  prompt: string;
}

type WebSocketSubscriber = (data: unknown) => void;

export interface OllamaModel {
  name: string;
  size: number;
  modified: string;
  digest: string;
  format: string;
  family: string;
  capabilities: string[];
  can_prompt: boolean;
  can_vision: boolean;
  can_image: boolean;
}

export interface OllamaModelsResponse {
  models: OllamaModel[];
  current: string | null;
  configured_prompt: string;
  current_image: string | null;
  configured_image: string;
  host: string;
  version: string;
}

export interface GenerationConfig {
  width: number;
  height: number;
  num_inference_steps: number;
  guidance_scale: number;
  true_cfg_scale: number;
  ollama_temperature: number;
  ollama_model?: string;
  prompt_model?: string;
  configured_prompt_model?: string;
  image_backend?: string;
  image_model?: string;
  resolved_image_backend?: string;
  active_image_model?: string;
  active_image_model_id?: string;
  preferred_image_model?: string;
  preferred_image_model_status?: string;
  fallback_reason?: string | null;
  ollama_image_model?: string;
  pipeline?: {
    prompt: {
      provider: string;
      model: string;
      configured_model?: string;
    };
    image: {
      backend: string;
      model: string;
    };
  };
  enabled_loras?: string[];
  available_loras?: string[];
  lora_application_probability?: number;
  entropy_level?: 'calm' | 'strange' | 'wild';
  lora_dir?: string;
  zimage_model_path?: string;
  zimage_native_available?: boolean;
  mageflow_model?: string;
  mageflow_revision?: string;
  mageflow_url?: string;
  mageflow_steps?: number;
  mageflow_cfg?: number;
  qwen_image_model?: string;
  qwen_prompt_magic?: boolean;
  qwen_device_map?: string;
  qwen_lightning?: boolean;
  ernie_image_model?: string;
  ernie_prompt_enhancer?: boolean;
}

export interface GenerationEvent {
  timestamp: string;
  type: string;
  id?: string;
  task?: string;
  client_request_id?: string | null;
  progress?: number | null;
  label?: string | null;
  detail?: string | null;
  error?: string;
  name?: string;
  payload?: Record<string, unknown>;
}

export interface GenerationEventsResponse {
  events: GenerationEvent[];
  total: number;
  limit: number;
}

export interface GenerationMetricsResponse {
  events: number;
  completed_generations: number;
  phase_averages_ms: Record<string, Record<string, number>>;
  otel_enabled: boolean;
  jsonl_path: string;
}

export type GenerationJobStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled';

export interface GenerationJobRequest {
  prompt?: string | null;
  meta_prompt?: string | null;
  seed?: number | null;
  publication_state?: string;
  metadata?: Record<string, unknown>;
  recipe_id?: string | null;
  recipe_version?: number | null;
  config_overrides?: Record<string, unknown>;
}

export interface GenerationJob {
  id: string;
  status: GenerationJobStatus;
  request: GenerationJobRequest;
  client_request_id?: string | null;
  created_at: string;
  updated_at: string;
  started_at?: string | null;
  completed_at?: string | null;
  progress: number;
  prompt?: string | null;
  backend?: string | null;
  model_name?: string | null;
  image_path?: string | null;
  relative_image_path?: string | null;
  generation_time?: number | null;
  error?: string | null;
  attempts: number;
  metadata: Record<string, unknown>;
}

export interface GenerationJobsResponse {
  jobs: GenerationJob[];
  limit: number;
  offset: number;
}

export interface CreateGenerationJobRequest {
  prompt?: string;
  meta_prompt?: string;
  seed?: number;
  recipe_id?: string;
  publication_state?: string;
  experiment_label?: string;
  prompt_family?: string;
  quality_flags?: string[];
  client_request_id?: string;
  metadata?: Record<string, unknown>;
  config_overrides?: Record<string, unknown>;
}

export type PublicationState = 'draft' | 'published' | 'hidden' | 'featured' | 'rejected';

export interface GalleryPublication {
  id: string;
  state: PublicationState;
  publishable: boolean;
  quality_flags: string[];
}

export interface GalleryCatalogEntry {
  id: string;
  path: string;
  image_url?: string;
  prompt: string;
  created_at: string;
  updated_at: string;
  publication_state: PublicationState;
  publishable: boolean;
  quality_flags: string[];
  metadata: Record<string, unknown>;
  size?: number;
}

export interface GalleryCatalogResponse {
  assets: GalleryCatalogEntry[];
  total: number;
  limit: number;
  offset: number;
}

export interface GallerySyncStatus {
  bucket: string;
  approved_states: string[];
  catalog_present: boolean;
  output_present: boolean;
  ready: boolean;
  needs_publish: boolean;
  upload_images: number;
  upload_files: number;
  skipped_assets: number;
  delete_objects: number;
  preview_assets: Array<{ key: string; reason: string }>;
  skipped_preview: Array<{ key: string; reason: string }>;
  command: string;
  message: string;
}

export interface GalleryFacets {
  backends: string[];
  models: string[];
  prompt_families: string[];
  quality_flags: string[];
  publication_states: string[];
}

export interface GalleryCatalogFilters {
  backend?: string;
  model?: string;
  prompt_family?: string;
  quality_flag?: string;
  search?: string;
}

const extractErrorMessage = async (response: Response, fallback: string) => {
  try {
    const data = await response.json();
    if (typeof data?.detail === 'string' && data.detail.trim()) return data.detail;
    if (typeof data?.error === 'string' && data.error.trim()) return data.error;
    if (typeof data?.message === 'string' && data.message.trim()) return data.message;
    if (typeof data?.detail?.message === 'string' && data.detail.message.trim()) {
      return data.detail.message;
    }
  } catch {
    // Ignore invalid/non-JSON error payloads and fall back to the generic label.
  }

  return fallback;
};

export class ImageGenAPI {
  private baseUrl: string;
  private ws: WebSocket | null = null;
  private intentionalClose: boolean = false;
  private subscribers: Set<WebSocketSubscriber> = new Set();
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(baseUrl: string = API_BASE) {
    this.baseUrl = baseUrl;
  }

  async getStatus(): Promise<SystemStatus> {
    const response = await fetch(`${this.baseUrl}/api/status`);
    if (!response.ok) throw new Error(await extractErrorMessage(response, 'Failed to get status'));
    return response.json();
  }

  async getPlugins(): Promise<PluginInfo[]> {
    const response = await fetch(`${this.baseUrl}/api/plugins`);
    if (!response.ok) throw new Error(await extractErrorMessage(response, 'Failed to get plugins'));
    return response.json();
  }

  async togglePlugin(pluginName: string): Promise<{ plugin: string; enabled: boolean }> {
    const response = await fetch(`${this.baseUrl}/api/plugins/${pluginName}/toggle`, {
      method: 'POST',
    });
    if (!response.ok) throw new Error(await extractErrorMessage(response, 'Failed to toggle plugin'));
    return response.json();
  }

  async setPluginOrder(orderedNames: string[]): Promise<{ ordered_names: string[] }> {
    const response = await fetch(`${this.baseUrl}/api/plugins/order`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ ordered_names: orderedNames }),
    });
    if (!response.ok) throw new Error(await extractErrorMessage(response, 'Failed to update plugin order'));
    return response.json();
  }

  async generate(request: GenerateRequest): Promise<GenerateResponse> {
    const response = await fetch(`${this.baseUrl}/api/generate`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(request),
    });
    if (!response.ok) throw new Error(await extractErrorMessage(response, 'Failed to generate image'));
    return response.json();
  }

  async getGenerationEvents(limit: number = 25): Promise<GenerationEventsResponse> {
    const response = await fetch(`${this.baseUrl}/api/generation/events?limit=${limit}`);
    if (!response.ok) throw new Error(await extractErrorMessage(response, 'Failed to get generation events'));
    return response.json();
  }

  async getGenerationJobs(
    limit: number = 12,
    offset: number = 0,
    status?: GenerationJobStatus
  ): Promise<GenerationJobsResponse> {
    const params = new URLSearchParams({
      limit: String(limit),
      offset: String(offset),
    });
    if (status) params.set('status', status);

    const response = await fetch(`${this.baseUrl}/api/jobs?${params.toString()}`);
    if (!response.ok) throw new Error(await extractErrorMessage(response, 'Failed to get generation jobs'));
    return response.json();
  }

  async createGenerationJob(request: CreateGenerationJobRequest): Promise<GenerationJob> {
    const response = await fetch(`${this.baseUrl}/api/jobs`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(request),
    });
    if (!response.ok) throw new Error(await extractErrorMessage(response, 'Failed to create generation job'));
    return response.json();
  }

  async getGallery(limit: number = 50, offset: number = 0, timeoutMs: number = 20000) {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

    try {
      const response = await fetch(
        `${this.baseUrl}/api/gallery?limit=${limit}&offset=${offset}`,
        { signal: controller.signal }
      );
      clearTimeout(timeoutId);

      if (!response.ok) throw new Error(await extractErrorMessage(response, 'Failed to get gallery'));
      return response.json();
    } catch (error) {
      clearTimeout(timeoutId);
      if (error instanceof Error && error.name === 'AbortError') {
        throw new Error(`Gallery request timed out after ${Math.round(timeoutMs / 1000)}s`);
      }
      throw error;
    }
  }

  async getGalleryCatalog(
    limit: number = 100,
    offset: number = 0,
    state?: PublicationState | 'all',
    timeoutMs: number = 20000,
    filters: GalleryCatalogFilters = {}
  ): Promise<GalleryCatalogResponse> {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
    const params = new URLSearchParams({
      limit: String(limit),
      offset: String(offset),
    });
    if (state && state !== 'all') params.set('state', state);
    if (filters.backend) params.set('backend', filters.backend);
    if (filters.model) params.set('model', filters.model);
    if (filters.prompt_family) params.set('prompt_family', filters.prompt_family);
    if (filters.quality_flag) params.set('quality_flag', filters.quality_flag);
    if (filters.search) params.set('search', filters.search);

    try {
      const response = await fetch(`${this.baseUrl}/api/gallery/catalog?${params.toString()}`, {
        signal: controller.signal,
      });
      clearTimeout(timeoutId);

      if (!response.ok) throw new Error(await extractErrorMessage(response, 'Failed to get gallery catalog'));
      return response.json();
    } catch (error) {
      clearTimeout(timeoutId);
      if (error instanceof Error && error.name === 'AbortError') {
        throw new Error(`Gallery catalog request timed out after ${Math.round(timeoutMs / 1000)}s`);
      }
      throw error;
    }
  }

  async getGallerySyncStatus(limit: number = 10): Promise<GallerySyncStatus> {
    const response = await fetch(`${this.baseUrl}/api/gallery/sync/status?limit=${limit}`);
    if (!response.ok) throw new Error(await extractErrorMessage(response, 'Failed to get gallery sync status'));
    return response.json();
  }

  async getGalleryFacets(): Promise<GalleryFacets> {
    const response = await fetch(`${this.baseUrl}/api/gallery/facets`);
    if (!response.ok) throw new Error(await extractErrorMessage(response, 'Failed to get gallery facets'));
    return response.json();
  }

  async updatePublicationState(
    imagePath: string,
    state: PublicationState
  ): Promise<GalleryCatalogEntry> {
    const response = await fetch(`${this.baseUrl}/api/gallery/publication/${encodeURIComponent(imagePath)}`, {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ state }),
    });
    if (!response.ok) throw new Error(await extractErrorMessage(response, 'Failed to update publication state'));
    return response.json();
  }

  async deleteImage(imagePath: string) {
    const response = await fetch(`${this.baseUrl}/api/gallery/${encodeURIComponent(imagePath)}`, {
      method: 'DELETE',
    });
    if (!response.ok) throw new Error(await extractErrorMessage(response, 'Failed to delete image'));
    return response.json();
  }

  async generatePrompt(metaPrompt?: string, clientRequestId?: string): Promise<PromptResponse> {
    const response = await fetch(`${this.baseUrl}/api/prompt`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        meta_prompt: metaPrompt,
        client_request_id: clientRequestId,
      }),
    });
    if (!response.ok) throw new Error(await extractErrorMessage(response, 'Failed to generate prompt'));
    return response.json();
  }

  private connectSocket(): void {
    if (this.ws || this.subscribers.size === 0) return;

    const wsBase = process.env.NEXT_PUBLIC_WS_URL
      ? normalizeBase(process.env.NEXT_PUBLIC_WS_URL, WS_BASE)
      : this.baseUrl.replace(/^http/, 'ws');

    try {
      this.ws = new WebSocket(`${wsBase}/ws`);

      this.ws.onopen = () => {
        console.log('WebSocket connected');
        if (this.reconnectTimer) {
          clearTimeout(this.reconnectTimer);
          this.reconnectTimer = null;
        }
        for (const subscriber of this.subscribers) {
          subscriber({ type: 'connection_open' });
        }
      };

      this.ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          for (const subscriber of this.subscribers) {
            subscriber(data);
          }
        } catch (error) {
          console.warn('Failed to parse WebSocket message:', error instanceof Error ? error.message : 'Unknown error');
        }
      };

      this.ws.onerror = () => {
        // WebSocket error events don't contain much useful information
        // Just log a simple message instead of trying to log the event object
        console.warn('WebSocket connection error occurred');
      };

      this.ws.onclose = (event) => {
        console.log('WebSocket disconnected');
        this.ws = null;
        // Only reconnect if it wasn't an intentional closure
        if (!this.intentionalClose && event.code !== 1000 && this.subscribers.size > 0) {
          // Attempt reconnection after 3 seconds
          this.reconnectTimer = setTimeout(() => this.connectSocket(), 3000);
        }
        this.intentionalClose = false;
      };
    } catch (error) {
      console.error('Failed to create WebSocket connection:', error instanceof Error ? error.message : 'Unknown error');
      // Retry connection after 3 seconds
      if (this.subscribers.size > 0) {
        this.reconnectTimer = setTimeout(() => this.connectSocket(), 3000);
      }
    }
  }

  subscribeWebSocket(onMessage: WebSocketSubscriber): () => void {
    this.subscribers.add(onMessage);
    this.connectSocket();

    return () => {
      this.subscribers.delete(onMessage);
      if (this.subscribers.size === 0) {
        this.disconnectWebSocket();
      }
    };
  }

  connectWebSocket(onMessage: WebSocketSubscriber): void {
    this.subscribeWebSocket(onMessage);
  }

  disconnectWebSocket(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.ws) {
      this.intentionalClose = true;
      this.ws.close(1000, 'Client disconnect');
      this.ws = null;
    }
  }

  sendWebSocketMessage(message: unknown): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(message));
    }
  }

  async getModelStatus(): Promise<ModelStatus> {
    const response = await fetch(`${this.baseUrl}/api/models/status`);
    if (!response.ok) throw new Error(await extractErrorMessage(response, 'Failed to get model status'));
    return response.json();
  }

  async downloadModel(modelId: string): Promise<{ message: string; model_id: string }> {
    const response = await fetch(`${this.baseUrl}/api/models/${encodeURIComponent(modelId)}/download`, {
      method: 'POST',
    });
    if (!response.ok) throw new Error(await extractErrorMessage(response, 'Failed to start model download'));
    return response.json();
  }

  async unloadModels(): Promise<{
    message: string;
    memory: ModelStatus['memory'];
    mageflow?: { status: string; unloaded: boolean; was_loaded?: boolean; reason?: string };
  }> {
    const response = await fetch(`${this.baseUrl}/api/models/unload`, { method: 'POST' });
    if (!response.ok) throw new Error(await extractErrorMessage(response, 'Failed to unload models'));
    return response.json();
  }

  async getGenerationMetrics(limit: number = 500): Promise<GenerationMetricsResponse> {
    const response = await fetch(`${this.baseUrl}/api/generation/metrics?limit=${limit}`);
    if (!response.ok) throw new Error(await extractErrorMessage(response, 'Failed to get generation metrics'));
    return response.json();
  }

  async bulkUpdatePublicationState(
    imagePaths: string[],
    state: PublicationState
  ): Promise<{ updated: GalleryCatalogEntry[]; failures: Array<{ path: string; error: string }>; state: string }> {
    const response = await fetch(`${this.baseUrl}/api/gallery/publication/bulk`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ image_paths: imagePaths, state }),
    });
    if (!response.ok) throw new Error(await extractErrorMessage(response, 'Failed to update publication states'));
    return response.json();
  }

  async setHFToken(token: string): Promise<{ message: string }> {
    const response = await fetch(`${this.baseUrl}/api/config/hf-token`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ token }),
    });
    if (!response.ok) throw new Error(await extractErrorMessage(response, 'Failed to set HF token'));
    return response.json();
  }

  async getHFTokenStatus(): Promise<HFTokenStatus> {
    const response = await fetch(`${this.baseUrl}/api/config/hf-token-status`);
    if (!response.ok) throw new Error(await extractErrorMessage(response, 'Failed to get HF token status'));
    return response.json();
  }

  async editImage(file: File, request: EditRequest): Promise<EditResponse> {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('prompt', request.prompt);
    if (request.strength !== undefined) {
      formData.append('strength', request.strength.toString());
    }
    if (request.backend) formData.append('backend', request.backend);
    if (request.source_path) formData.append('source_path', request.source_path);

    const response = await fetch(`${this.baseUrl}/api/edit`, {
      method: 'POST',
      body: formData,
    });
    if (!response.ok) throw new Error(await extractErrorMessage(response, 'Failed to edit image'));
    return response.json();
  }

  async getEditJob(jobId: string): Promise<Record<string, unknown>> {
    const response = await fetch(`${this.baseUrl}/api/edit/jobs/${encodeURIComponent(jobId)}`);
    if (!response.ok) throw new Error(await extractErrorMessage(response, 'Failed to get edit job'));
    return response.json();
  }

  async getMageEditCapabilities(): Promise<MageEditCapabilities> {
    const response = await fetch(`${this.baseUrl}/api/edit/capabilities`);
    if (!response.ok) throw new Error(await extractErrorMessage(response, 'Failed to get edit capabilities'));
    return response.json();
  }

  async getMageEditJobs(rootJobId?: string): Promise<{ jobs: MageEditJob[] }> {
    const params = new URLSearchParams();
    if (rootJobId) params.set('root_job_id', rootJobId);
    const response = await fetch(`${this.baseUrl}/api/edit/jobs?${params.toString()}`);
    if (!response.ok) throw new Error(await extractErrorMessage(response, 'Failed to get edit history'));
    return response.json();
  }

  async downloadMageEditModel(variant: MageEditVariant['id']): Promise<Record<string, unknown>> {
    const response = await fetch(`${this.baseUrl}/api/edit/models/${variant}/download`, { method: 'POST' });
    if (!response.ok) throw new Error(await extractErrorMessage(response, 'Failed to download official edit model'));
    return response.json();
  }

  async createMageEditJob(file: File, request: CreateMageEditRequest): Promise<MageEditJob> {
    const formData = new FormData();
    formData.append('file', file);
    for (const [key, value] of Object.entries(request)) {
      if (value !== undefined && value !== '') formData.append(key, String(value));
    }
    const response = await fetch(`${this.baseUrl}/api/edit/jobs`, { method: 'POST', body: formData });
    if (!response.ok) throw new Error(await extractErrorMessage(response, 'Failed to queue edit'));
    return response.json();
  }

  async cancelMageEditJob(jobId: string): Promise<MageEditJob> {
    const response = await fetch(`${this.baseUrl}/api/edit/jobs/${encodeURIComponent(jobId)}/cancel`, { method: 'POST' });
    if (!response.ok) throw new Error(await extractErrorMessage(response, 'Failed to cancel edit'));
    return response.json();
  }

  async decideMageEditJob(jobId: string, decision: 'approved' | 'rejected' | 'pending'): Promise<MageEditJob> {
    const response = await fetch(`${this.baseUrl}/api/edit/jobs/${encodeURIComponent(jobId)}/decision`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ decision }),
    });
    if (!response.ok) throw new Error(await extractErrorMessage(response, 'Failed to record edit decision'));
    return response.json();
  }

  async getOllamaModels(): Promise<OllamaModelsResponse> {
    const response = await fetch(`${this.baseUrl}/api/ollama/models`);
    if (!response.ok) throw new Error(await extractErrorMessage(response, 'Failed to get Ollama models'));
    return response.json();
  }

  async setOllamaModel(model: string): Promise<{ message: string; model: string }> {
    const response = await fetch(`${this.baseUrl}/api/ollama/model`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ model }),
    });
    if (!response.ok) throw new Error(await extractErrorMessage(response, 'Failed to set Ollama model'));
    return response.json();
  }

  async getGenerationConfig(): Promise<GenerationConfig> {
    const response = await fetch(`${this.baseUrl}/api/config/generation`);
    if (!response.ok) throw new Error(await extractErrorMessage(response, 'Failed to get generation config'));
    return response.json();
  }

  async setGenerationConfig(config: Partial<GenerationConfig>): Promise<{ message: string; config: GenerationConfig }> {
    const response = await fetch(`${this.baseUrl}/api/config/generation`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(config),
    });
    if (!response.ok) throw new Error(await extractErrorMessage(response, 'Failed to set generation config'));
    return response.json();
  }
}

export const api = new ImageGenAPI();
