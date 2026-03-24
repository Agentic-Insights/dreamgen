"use client";

import { useState, useEffect } from "react";
import { Sliders, RotateCcw } from "lucide-react";
import { api, GenerationConfig } from "@/lib/api";
import { cn } from "@/lib/utils";

interface AdvancedControlsProps {
  onConfigChange?: (config: Partial<GenerationConfig>) => void;
  seed?: number | null;
  onSeedChange?: (seed: number | null) => void;
}

export default function AdvancedControls({
  onConfigChange,
  seed = null,
  onSeedChange,
}: AdvancedControlsProps) {
  const [config, setConfig] = useState<GenerationConfig>({
    width: 1024,
    height: 1024,
    num_inference_steps: 4,
    guidance_scale: 0.0,
    true_cfg_scale: 1.0,
    ollama_temperature: 0.7,
  });
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    loadConfig();
  }, []);

  const loadConfig = async () => {
    setIsLoading(true);
    try {
      const currentConfig = await api.getGenerationConfig();
      setConfig(currentConfig);
    } catch (error) {
      console.error('Failed to load config:', error);
    } finally {
      setIsLoading(false);
    }
  };

  const updateConfig = async (updates: Partial<GenerationConfig>) => {
    const newConfig = { ...config, ...updates };
    setConfig(newConfig);

    try {
      await api.setGenerationConfig(updates);
      onConfigChange?.(updates);
    } catch (error) {
      console.error('Failed to update config:', error);
    }
  };

  const resetToDefaults = async () => {
    const defaults: Partial<GenerationConfig> = {
      width: 1024,
      height: 1024,
      num_inference_steps: 4,
      guidance_scale: 0.0,
      true_cfg_scale: 1.0,
      ollama_temperature: 0.7,
    };
    await updateConfig(defaults);
  };

  const generateRandomSeed = () => {
    onSeedChange?.(Math.floor(Math.random() * 2147483647));
  };

  if (isLoading) {
    return <div className="p-4 text-sm text-muted-foreground">Loading...</div>;
  }

  return (
    <div className="space-y-4">
      {/* Seed Control */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <label className="text-xs font-medium">Seed</label>
          <button
            onClick={generateRandomSeed}
            className="text-xs text-primary hover:underline"
          >
            Random
          </button>
        </div>
        <input
          type="number"
          value={seed ?? ''}
          onChange={(e) => onSeedChange?.(e.target.value ? parseInt(e.target.value, 10) : null)}
          placeholder="Random (leave empty)"
          className="w-full px-2 py-1.5 bg-background border border-input rounded-md text-xs focus:outline-none focus:ring-2 focus:ring-primary/50"
        />
        <p className="text-xs text-muted-foreground">
          Use same seed for reproducible results
        </p>
      </div>

      {/* Dimensions */}
      <div className="space-y-3">
        <div>
          <div className="flex items-center justify-between mb-1">
            <label className="text-xs font-medium">Width</label>
            <span className="text-xs text-muted-foreground">{config.width}px</span>
          </div>
          <input
            type="range"
            min="256"
            max="2048"
            step="64"
            value={config.width}
            onChange={(e) => updateConfig({ width: parseInt(e.target.value) })}
            className="w-full"
          />
        </div>

        <div>
          <div className="flex items-center justify-between mb-1">
            <label className="text-xs font-medium">Height</label>
            <span className="text-xs text-muted-foreground">{config.height}px</span>
          </div>
          <input
            type="range"
            min="256"
            max="2048"
            step="64"
            value={config.height}
            onChange={(e) => updateConfig({ height: parseInt(e.target.value) })}
            className="w-full"
          />
        </div>
      </div>

      {/* Inference Steps */}
      <div>
        <div className="flex items-center justify-between mb-1">
          <label className="text-xs font-medium">Inference Steps</label>
          <span className="text-xs text-muted-foreground">{config.num_inference_steps}</span>
        </div>
        <input
          type="range"
          min="1"
          max="50"
          step="1"
          value={config.num_inference_steps}
          onChange={(e) => updateConfig({ num_inference_steps: parseInt(e.target.value) })}
          className="w-full"
        />
        <p className="text-xs text-muted-foreground mt-1">
          More steps = better quality, slower generation
        </p>
      </div>

      {/* Guidance Scale */}
      <div>
        <div className="flex items-center justify-between mb-1">
          <label className="text-xs font-medium">Guidance Scale</label>
          <span className="text-xs text-muted-foreground">{config.guidance_scale?.toFixed(1) ?? '0.0'}</span>
        </div>
        <input
          type="range"
          min="0"
          max="20"
          step="0.5"
          value={config.guidance_scale}
          onChange={(e) => updateConfig({ guidance_scale: parseFloat(e.target.value) })}
          className="w-full"
        />
        <p className="text-xs text-muted-foreground mt-1">
          How closely to follow the prompt (0 for Schnell)
        </p>
      </div>

      {/* True CFG Scale */}
      <div>
        <div className="flex items-center justify-between mb-1">
          <label className="text-xs font-medium">True CFG Scale</label>
          <span className="text-xs text-muted-foreground">{config.true_cfg_scale?.toFixed(1) ?? '1.0'}</span>
        </div>
        <input
          type="range"
          min="1"
          max="10"
          step="0.1"
          value={config.true_cfg_scale}
          onChange={(e) => updateConfig({ true_cfg_scale: parseFloat(e.target.value) })}
          className="w-full"
        />
      </div>

      {/* Ollama Temperature */}
      <div>
        <div className="flex items-center justify-between mb-1">
          <label className="text-xs font-medium">Prompt Creativity</label>
          <span className="text-xs text-muted-foreground">{config.ollama_temperature?.toFixed(2) ?? '0.70'}</span>
        </div>
        <input
          type="range"
          min="0"
          max="2"
          step="0.1"
          value={config.ollama_temperature}
          onChange={(e) => updateConfig({ ollama_temperature: parseFloat(e.target.value) })}
          className="w-full"
        />
        <p className="text-xs text-muted-foreground mt-1">
          Lower = more focused, Higher = more creative prompts
        </p>
      </div>

      {/* Reset Button */}
      <button
        onClick={resetToDefaults}
        className="w-full px-3 py-2 bg-muted hover:bg-muted/80 rounded-md text-sm flex items-center justify-center gap-2 transition-colors"
      >
        <RotateCcw className="w-3.5 h-3.5" />
        Reset to Defaults
      </button>
    </div>
  );
}
