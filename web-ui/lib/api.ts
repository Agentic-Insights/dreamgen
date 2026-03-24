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
  use_mock?: boolean;
  enable_plugins?: boolean;
  seed?: number;
}

export interface GenerateResponse {
  id: string;
  prompt: string;
  image_path: string;
  metadata: {
    backend: string;
    plugins_used: string[];
    seed?: number;
  };
  created_at: string;
}

export interface PluginInfo {
  name: string;
  enabled: boolean;
  description: string;
  order: number;
}

export interface SystemStatus {
  status: string;
  backend: string;
  plugins_enabled: boolean;
  active_plugins: string[];
  gpu_available: boolean;
  ollama_available: boolean;
}

export interface ModelInfo {
  id: string;
  name: string;
  type: string;
  status: 'not_downloaded' | 'downloading' | 'ready' | 'partial';
  size: number;
  incomplete_files: number;
  path?: string;
}

export interface ModelStatus {
  models: ModelInfo[];
  cache_dir: string;
}

export interface HFTokenStatus {
  configured: boolean;
  source?: 'environment' | 'file';
}

export interface EditRequest {
  prompt: string;
  strength?: number;
}

export interface EditResponse {
  id: string;
  prompt: string;
  original_path: string;
  edited_path: string;
  metadata: {
    model: string;
    strength: number;
  };
  created_at: string;
}

export interface PromptResponse {
  prompt: string;
}

export interface OllamaModel {
  name: string;
  size: number;
  modified: string;
  digest: string;
}

export interface OllamaModelsResponse {
  models: OllamaModel[];
  current: string;
  host: string;
}

export interface GenerationConfig {
  width: number;
  height: number;
  num_inference_steps: number;
  guidance_scale: number;
  true_cfg_scale: number;
  ollama_temperature: number;
}

export class ImageGenAPI {
  private baseUrl: string;
  private ws: WebSocket | null = null;
  private intentionalClose: boolean = false;

  constructor(baseUrl: string = API_BASE) {
    this.baseUrl = baseUrl;
  }

  async getStatus(): Promise<SystemStatus> {
    const response = await fetch(`${this.baseUrl}/api/status`);
    if (!response.ok) throw new Error('Failed to get status');
    return response.json();
  }

  async getPlugins(): Promise<PluginInfo[]> {
    const response = await fetch(`${this.baseUrl}/api/plugins`);
    if (!response.ok) throw new Error('Failed to get plugins');
    return response.json();
  }

  async togglePlugin(pluginName: string): Promise<{ plugin: string; enabled: boolean }> {
    const response = await fetch(`${this.baseUrl}/api/plugins/${pluginName}/toggle`, {
      method: 'POST',
    });
    if (!response.ok) throw new Error('Failed to toggle plugin');
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
    if (!response.ok) throw new Error('Failed to update plugin order');
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
    if (!response.ok) throw new Error('Failed to generate image');
    return response.json();
  }

  async getGallery(limit: number = 50, offset: number = 0) {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 10000); // 10 second timeout

    try {
      const response = await fetch(
        `${this.baseUrl}/api/gallery?limit=${limit}&offset=${offset}`,
        { signal: controller.signal }
      );
      clearTimeout(timeoutId);

      if (!response.ok) throw new Error('Failed to get gallery');
      return response.json();
    } catch (error) {
      clearTimeout(timeoutId);
      if (error instanceof Error && error.name === 'AbortError') {
        throw new Error('Gallery request timed out');
      }
      throw error;
    }
  }

  async deleteImage(imagePath: string) {
    const response = await fetch(`${this.baseUrl}/api/gallery/${encodeURIComponent(imagePath)}`, {
      method: 'DELETE',
    });
    if (!response.ok) throw new Error('Failed to delete image');
    return response.json();
  }

  async generatePrompt(metaPrompt?: string): Promise<PromptResponse> {
    const response = await fetch(`${this.baseUrl}/api/prompt`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ meta_prompt: metaPrompt }),
    });
    if (!response.ok) throw new Error('Failed to generate prompt');
    return response.json();
  }

  connectWebSocket(onMessage: (data: unknown) => void): void {
    const wsBase = process.env.NEXT_PUBLIC_WS_URL
      ? normalizeBase(process.env.NEXT_PUBLIC_WS_URL, WS_BASE)
      : this.baseUrl.replace(/^http/, 'ws');

    try {
      this.ws = new WebSocket(`${wsBase}/ws`);

      this.ws.onopen = () => {
        console.log('WebSocket connected');
      };

      this.ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          onMessage(data);
        } catch (error) {
          console.warn('Failed to parse WebSocket message:', error instanceof Error ? error.message : 'Unknown error');
        }
      };

      this.ws.onerror = (event) => {
        // WebSocket error events don't contain much useful information
        // Just log a simple message instead of trying to log the event object
        console.warn('WebSocket connection error occurred');
      };

      this.ws.onclose = (event) => {
        console.log('WebSocket disconnected');
        // Only reconnect if it wasn't an intentional closure
        if (!this.intentionalClose && event.code !== 1000) {
          // Attempt reconnection after 3 seconds
          setTimeout(() => this.connectWebSocket(onMessage), 3000);
        }
        this.intentionalClose = false;
      };
    } catch (error) {
      console.error('Failed to create WebSocket connection:', error instanceof Error ? error.message : 'Unknown error');
      // Retry connection after 3 seconds
      setTimeout(() => this.connectWebSocket(onMessage), 3000);
    }
  }

  disconnectWebSocket(): void {
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
    if (!response.ok) throw new Error('Failed to get model status');
    return response.json();
  }

  async downloadModel(modelId: string): Promise<{ message: string; model_id: string }> {
    const response = await fetch(`${this.baseUrl}/api/models/${encodeURIComponent(modelId)}/download`, {
      method: 'POST',
    });
    if (!response.ok) throw new Error('Failed to start model download');
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
    if (!response.ok) throw new Error('Failed to set HF token');
    return response.json();
  }

  async getHFTokenStatus(): Promise<HFTokenStatus> {
    const response = await fetch(`${this.baseUrl}/api/config/hf-token-status`);
    if (!response.ok) throw new Error('Failed to get HF token status');
    return response.json();
  }

  async editImage(file: File, request: EditRequest): Promise<EditResponse> {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('prompt', request.prompt);
    if (request.strength !== undefined) {
      formData.append('strength', request.strength.toString());
    }

    const response = await fetch(`${this.baseUrl}/api/edit`, {
      method: 'POST',
      body: formData,
    });
    if (!response.ok) throw new Error('Failed to edit image');
    return response.json();
  }

  async getOllamaModels(): Promise<OllamaModelsResponse> {
    const response = await fetch(`${this.baseUrl}/api/ollama/models`);
    if (!response.ok) throw new Error('Failed to get Ollama models');
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
    if (!response.ok) throw new Error('Failed to set Ollama model');
    return response.json();
  }

  async getGenerationConfig(): Promise<GenerationConfig> {
    const response = await fetch(`${this.baseUrl}/api/config/generation`);
    if (!response.ok) throw new Error('Failed to get generation config');
    return response.json();
  }

  async setGenerationConfig(config: Partial<GenerationConfig>): Promise<{ message: string; config: Partial<GenerationConfig> }> {
    const response = await fetch(`${this.baseUrl}/api/config/generation`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(config),
    });
    if (!response.ok) throw new Error('Failed to set generation config');
    return response.json();
  }
}

export const api = new ImageGenAPI();
