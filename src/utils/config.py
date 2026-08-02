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

    image_backend: str
    smoke_test_model: str
    small_sd_model: str
    turbo_model: str
    mageflow_model: str
    mageflow_revision: str
    mageflow_url: str
    mageflow_steps: int
    mageflow_cfg: float
    mageflow_timeout_seconds: float
    zimage_model_path: Path
    zimage_attention: str
    zimage_compile: bool
    qwen_image_model: str
    qwen_prompt_magic: bool
    qwen_device_map: str
    qwen_lightning: bool
    qwen_lightning_lora: str
    qwen_lightning_weight: str
    ernie_image_model: str
    ernie_prompt_enhancer: bool
    ollama_model: str
    ollama_image_model: str
    ollama_temperature: float
    flux_model: str
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
    entropy_level: str = "strange"


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
                override=False
            )  # Load from default .env in current directory only if not explicitly overridden

        # Plugin configuration
        enabled_plugins_str = os.getenv("ENABLED_PLUGINS", "")
        enabled_plugins = [p.strip() for p in enabled_plugins_str.split(",") if p.strip()]

        plugin_order_str = os.getenv("PLUGIN_ORDER")
        plugin_order: Dict[str, int] = {}
        if plugin_order_str:
            for item in plugin_order_str.split(","):
                if ":" in item:
                    name, order = item.split(":", 1)
                    name = name.strip()
                    try:
                        plugin_order[name] = int(order.strip())
                    except ValueError:
                        continue

        if not plugin_order and enabled_plugins:
            plugin_order = {name: index for index, name in enumerate(enabled_plugins, start=1)}

        entropy_level = os.getenv("DREAM_ENTROPY_LEVEL", os.getenv("ENTROPY_LEVEL", "strange"))
        entropy_level = entropy_level.strip().lower()
        if entropy_level not in {"calm", "strange", "wild"}:
            entropy_level = "strange"

        self.plugins = PluginConfig(
            enabled_plugins=enabled_plugins,
            plugin_order=plugin_order,
            entropy_level=entropy_level,
        )

        # Lora configuration
        enabled_loras_str = os.getenv("ENABLED_LORAS")
        enabled_loras = (
            [lora_name.strip() for lora_name in enabled_loras_str.split(",") if lora_name.strip()]
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
        use_mock_generator = os.getenv("USE_MOCK_GENERATOR", "false").lower()
        configured_backend = os.getenv("IMAGE_BACKEND")
        legacy_image_model = os.getenv("IMAGE_MODEL", "").strip().lower()
        if use_mock_generator in ("true", "1", "yes", "on"):
            image_backend = "mock"
        elif configured_backend:
            image_backend = configured_backend
        elif legacy_image_model in {"flux", "ollama", "zimage", "qwen", "ernie"}:
            image_backend = legacy_image_model
        else:
            image_backend = "zimage"

        if image_backend == "tiny":
            image_backend = "smoke"

        smoke_test_model = os.getenv(
            "SMOKE_TEST_MODEL", "hf-internal-testing/tiny-stable-diffusion-torch"
        )
        small_sd_model = os.getenv("SMALL_SD_MODEL", "segmind/tiny-sd")
        turbo_model = os.getenv("TURBO_MODEL", "stabilityai/sd-turbo")
        mageflow_model = os.getenv("MAGEFLOW_MODEL", "microsoft/Mage-Flow")
        mageflow_revision = os.getenv(
            "MAGEFLOW_MODEL_REVISION",
            "faca09c18c1c19458e7fbc3f7bce6f7a7d4d01a9",
        )
        mageflow_url = os.getenv("MAGEFLOW_URL", "http://localhost:25801").rstrip("/")
        mageflow_steps = int(os.getenv("MAGEFLOW_STEPS", "20"))
        mageflow_cfg = float(os.getenv("MAGEFLOW_CFG", "5.0"))
        mageflow_timeout_seconds = float(os.getenv("MAGEFLOW_TIMEOUT_SECONDS", "1800"))
        zimage_model_path = Path(os.getenv("ZIMAGE_MODEL_PATH", "ckpts/Z-Image-Turbo"))
        zimage_attention = os.getenv("ZIMAGE_ATTENTION", "_sdpa")
        zimage_compile = os.getenv("ZIMAGE_COMPILE", "false").lower() in (
            "true",
            "1",
            "yes",
            "on",
        )
        qwen_image_model = os.getenv("QWEN_IMAGE_MODEL", "diffusers/qwen-image-nf4")
        qwen_prompt_magic = os.getenv("QWEN_IMAGE_PROMPT_MAGIC", "true").lower() in (
            "true",
            "1",
            "yes",
            "on",
        )
        qwen_device_map = os.getenv("QWEN_IMAGE_DEVICE_MAP", "balanced")
        qwen_lightning = os.getenv("QWEN_IMAGE_LIGHTNING", "false").lower() in (
            "true",
            "1",
            "yes",
            "on",
        )
        qwen_lightning_lora = os.getenv(
            "QWEN_IMAGE_LIGHTNING_LORA", "lightx2v/Qwen-Image-Lightning"
        )
        qwen_lightning_weight = os.getenv(
            "QWEN_IMAGE_LIGHTNING_WEIGHT",
            "Qwen-Image-Lightning-8steps-V1.0.safetensors",
        )
        ernie_image_model = os.getenv("ERNIE_IMAGE_MODEL", "baidu/ERNIE-Image-Turbo")
        ernie_prompt_enhancer = os.getenv("ERNIE_IMAGE_PROMPT_ENHANCER", "true").lower() in (
            "true",
            "1",
            "yes",
            "on",
        )

        legacy_tiny_model = os.getenv("TINY_SD_MODEL")
        if legacy_tiny_model and not os.getenv("SMOKE_TEST_MODEL"):
            smoke_test_model = legacy_tiny_model

        ollama_model = os.getenv("OLLAMA_MODEL")
        if not ollama_model:
            raise ValueError("OLLAMA_MODEL environment variable is required")

        ollama_image_model = os.getenv("OLLAMA_IMAGE_MODEL", "").strip()

        ollama_temp = os.getenv("OLLAMA_TEMPERATURE")
        if not ollama_temp:
            raise ValueError("OLLAMA_TEMPERATURE environment variable is required")

        flux_model = os.getenv("FLUX_MODEL")
        if not flux_model:
            raise ValueError("FLUX_MODEL environment variable is required")

        max_seq_len = os.getenv("MAX_SEQUENCE_LENGTH")
        if not max_seq_len:
            raise ValueError("MAX_SEQUENCE_LENGTH environment variable is required")

        self.model = ModelConfig(
            image_backend=image_backend.lower(),
            smoke_test_model=smoke_test_model,
            small_sd_model=small_sd_model,
            turbo_model=turbo_model,
            mageflow_model=mageflow_model,
            mageflow_revision=mageflow_revision,
            mageflow_url=mageflow_url,
            mageflow_steps=mageflow_steps,
            mageflow_cfg=mageflow_cfg,
            mageflow_timeout_seconds=mageflow_timeout_seconds,
            zimage_model_path=zimage_model_path,
            zimage_attention=zimage_attention,
            zimage_compile=zimage_compile,
            qwen_image_model=qwen_image_model,
            qwen_prompt_magic=qwen_prompt_magic,
            qwen_device_map=qwen_device_map,
            qwen_lightning=qwen_lightning,
            qwen_lightning_lora=qwen_lightning_lora,
            qwen_lightning_weight=qwen_lightning_weight,
            ernie_image_model=ernie_image_model,
            ernie_prompt_enhancer=ernie_prompt_enhancer,
            ollama_model=ollama_model,
            ollama_image_model=ollama_image_model,
            ollama_temperature=float(ollama_temp),
            flux_model=flux_model,
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
        if self.model.image_backend not in {
            "auto",
            "mageflow",
            "flux",
            "ollama",
            "zimage",
            "qwen",
            "ernie",
            "small",
            "turbo",
            "smoke",
            "mock",
        }:
            errors.append(
                f"Invalid image backend: {self.model.image_backend} "
                "(must be one of auto, mageflow, flux, ollama, zimage, qwen, ernie, "
                "small, turbo, smoke, mock)"
            )
        if not (1 <= self.model.mageflow_steps <= 50):
            errors.append(
                f"Invalid Mage-Flow steps: {self.model.mageflow_steps} (must be between 1 and 50)"
            )
        if not (0.0 <= self.model.mageflow_cfg <= 20.0):
            errors.append(
                f"Invalid Mage-Flow CFG: {self.model.mageflow_cfg} (must be between 0.0 and 20.0)"
            )
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
