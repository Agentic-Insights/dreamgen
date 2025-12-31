"""
Configuration management for the image generation system.
"""

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv


@dataclass
class LoraConfig:
    """Lora-specific configuration."""

    lora_dir: Path
    enabled_loras: List[str]
    application_probability: float


@dataclass
class ModelConfig:
    """Model-specific configuration."""

    image_model: str  # "flux" or "zimage"
    ollama_model: str
    ollama_temperature: float
    flux_model: str
    zimage_model: str
    zimage_attention: str
    zimage_compile: bool
    max_sequence_length: int
    lora: LoraConfig


@dataclass
class ImageConfig:
    """Image generation configuration."""

    height: int
    width: int
    num_inference_steps: int
    guidance_scale: float
    true_cfg_scale: float


@dataclass
class PluginConfig:
    """Plugin-related configuration."""

    enabled_plugins: List[str]
    plugin_order: Dict[str, int]


@dataclass
class SystemConfig:
    """System-related configuration."""

    output_dir: Path
    log_dir: Path
    cache_dir: Path
    cpu_only: bool
    mps_use_fp16: bool


class Config:
    def __init__(self, env_file: Optional[Path] = None):
        # Load environment variables from .env file
        if env_file and env_file.exists():
            load_dotenv(env_file, override=True)
        elif env_file is None:
            load_dotenv(
                override=True
            )  # Load from default .env in current directory only if not explicitly overridden

        # Plugin configuration
        enabled_plugins_str = os.getenv("ENABLED_PLUGINS")
        if not enabled_plugins_str:
            raise ValueError("ENABLED_PLUGINS environment variable is required")
        enabled_plugins = [p.strip() for p in enabled_plugins_str.split(",") if p.strip()]

        plugin_order_str = os.getenv("PLUGIN_ORDER")
        if not plugin_order_str:
            raise ValueError("PLUGIN_ORDER environment variable is required")
        plugin_order = {}
        for item in plugin_order_str.split(","):
            if ":" in item:
                name, order = item.split(":", 1)
                plugin_order[name.strip()] = int(order.strip())

        self.plugins = PluginConfig(enabled_plugins=enabled_plugins, plugin_order=plugin_order)

        # Lora configuration
        enabled_loras_str = os.getenv("ENABLED_LORAS")
        enabled_loras = (
            [lora.strip() for lora in enabled_loras_str.split(",") if lora.strip()]
            if enabled_loras_str
            else []
        )

        lora_dir = os.getenv("LORA_DIR")
        if not lora_dir:
            raise ValueError("LORA_DIR environment variable is required")

        lora_prob = os.getenv("LORA_APPLICATION_PROBABILITY")
        if not lora_prob:
            raise ValueError("LORA_APPLICATION_PROBABILITY environment variable is required")

        lora_config = LoraConfig(
            lora_dir=Path(lora_dir),
            enabled_loras=enabled_loras,
            application_probability=float(lora_prob),
        )

        # Model configuration
        image_model = os.getenv("IMAGE_MODEL", "flux")  # Default to flux for backward compat

        ollama_model = os.getenv("OLLAMA_MODEL")
        if not ollama_model:
            raise ValueError("OLLAMA_MODEL environment variable is required")

        ollama_temp = os.getenv("OLLAMA_TEMPERATURE")
        if not ollama_temp:
            raise ValueError("OLLAMA_TEMPERATURE environment variable is required")

        flux_model = os.getenv("FLUX_MODEL")
        if not flux_model:
            raise ValueError("FLUX_MODEL environment variable is required")

        # Z-Image configuration (optional, only required if IMAGE_MODEL=zimage)
        zimage_model = os.getenv("ZIMAGE_MODEL", "Tongyi-MAI/Z-Image-Turbo")
        zimage_attention = os.getenv("ZIMAGE_ATTENTION", "_native_flash")
        zimage_compile = os.getenv("ZIMAGE_COMPILE", "false").lower() in ("true", "1", "yes", "on")

        max_seq_len = os.getenv("MAX_SEQUENCE_LENGTH")
        if not max_seq_len:
            raise ValueError("MAX_SEQUENCE_LENGTH environment variable is required")

        self.model = ModelConfig(
            image_model=image_model,
            ollama_model=ollama_model,
            ollama_temperature=float(ollama_temp),
            flux_model=flux_model,
            zimage_model=zimage_model,
            zimage_attention=zimage_attention,
            zimage_compile=zimage_compile,
            max_sequence_length=int(max_seq_len),
            lora=lora_config,
        )

        # Image configuration
        height = os.getenv("IMAGE_HEIGHT")
        if not height:
            raise ValueError("IMAGE_HEIGHT environment variable is required")

        width = os.getenv("IMAGE_WIDTH")
        if not width:
            raise ValueError("IMAGE_WIDTH environment variable is required")

        steps = os.getenv("NUM_INFERENCE_STEPS")
        if not steps:
            raise ValueError("NUM_INFERENCE_STEPS environment variable is required")

        guidance = os.getenv("GUIDANCE_SCALE")
        if not guidance:
            raise ValueError("GUIDANCE_SCALE environment variable is required")

        cfg_scale = os.getenv("TRUE_CFG_SCALE")
        if not cfg_scale:
            raise ValueError("TRUE_CFG_SCALE environment variable is required")

        self.image = ImageConfig(
            height=int(height),
            width=int(width),
            num_inference_steps=int(steps),
            guidance_scale=float(guidance),
            true_cfg_scale=float(cfg_scale),
        )

        # System configuration
        output_dir = os.getenv("OUTPUT_DIR")
        if not output_dir:
            raise ValueError("OUTPUT_DIR environment variable is required")

        log_dir = os.getenv("LOG_DIR")
        if not log_dir:
            raise ValueError("LOG_DIR environment variable is required")

        cache_dir = os.getenv("CACHE_DIR")
        if not cache_dir:
            raise ValueError("CACHE_DIR environment variable is required")

        cpu_only = os.getenv("CPU_ONLY")
        if not cpu_only:
            raise ValueError("CPU_ONLY environment variable is required")

        mps_fp16 = os.getenv("MPS_USE_FP16")
        if not mps_fp16:
            raise ValueError("MPS_USE_FP16 environment variable is required")

        self.system = SystemConfig(
            output_dir=Path(output_dir),
            log_dir=Path(log_dir),
            cache_dir=Path(cache_dir),
            cpu_only=cpu_only.lower() in ("true", "1", "yes", "on"),
            mps_use_fp16=mps_fp16.lower() in ("true", "1", "yes", "on"),
        )

    @classmethod
    def from_file(cls, config_path: Path) -> "Config":
        """Load configuration from a JSON file."""
        if not config_path.exists():
            return cls()

        with open(config_path) as f:
            data = json.load(f)

        config = cls()
        for section, values in data.items():
            if hasattr(config, section):
                section_config = getattr(config, section)
                for key, value in values.items():
                    if hasattr(section_config, key):
                        if isinstance(value, dict) and key.endswith("_dir"):
                            value = Path(value)
                        setattr(section_config, key, value)

        return config

    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary."""
        return {
            "model": asdict(self.model),
            "image": asdict(self.image),
            "plugins": asdict(self.plugins),
            "system": {
                k: str(v) if isinstance(v, Path) else v for k, v in asdict(self.system).items()
            },
        }

    def save(self, config_path: Path):
        """Save configuration to a JSON file."""
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)

    def validate(self) -> list[str]:
        """
        Validate configuration values.

        Returns:
            list[str]: List of validation errors, empty if valid
        """
        errors = []

        # Validate image dimensions
        if not (128 <= self.image.height <= 2048):
            errors.append(f"Invalid height: {self.image.height} (must be between 128 and 2048)")
        if not (128 <= self.image.width <= 2048):
            errors.append(f"Invalid width: {self.image.width} (must be between 128 and 2048)")

        # Validate model parameters
        if not (1 <= self.image.num_inference_steps <= 150):
            errors.append(
                f"Invalid inference steps: {self.image.num_inference_steps} (must be between 1 and 150)"
            )
        if not (0.0 <= self.image.guidance_scale <= 30.0):
            errors.append(
                f"Invalid guidance scale: {self.image.guidance_scale} (must be between 0.0 and 30.0)"
            )
        if not (1.0 <= self.image.true_cfg_scale <= 10.0):
            errors.append(
                f"Invalid true CFG scale: {self.image.true_cfg_scale} (must be between 1.0 and 10.0)"
            )

        # Validate system paths
        for path_attr in ["output_dir", "log_dir", "cache_dir"]:
            path = getattr(self.system, path_attr)
            try:
                path.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                errors.append(f"Invalid {path_attr}: {path} ({str(e)})")

        return errors
