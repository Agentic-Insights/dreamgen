"""Abstract base class for image generators."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import torch


@dataclass
class GenerationResult:
    """Result from image generation."""

    image_path: Path
    prompt: str
    model: str
    seed: int
    steps: int
    metadata: dict


class ImageGenerator(ABC):
    """Abstract base class for all image generators.

    This defines the interface that all generators (FLUX, Z-Image, etc.)
    must implement to ensure consistent behavior across different models.
    """

    def __init__(self, config):
        """Initialize the generator with configuration.

        Args:
            config: Configuration object containing model settings
        """
        self.config = config
        self.pipe = None
        self.device = self._get_device()

    def _get_device(self) -> str:
        """Determine the best available device.

        Returns:
            Device string: 'cuda', 'mps', or 'cpu'
        """
        if self.config.system.cpu_only:
            return "cpu"

        if torch.cuda.is_available():
            return "cuda"

        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"

        return "cpu"

    @abstractmethod
    def load_model(self):
        """Load the model into memory.

        This should initialize self.pipe with the appropriate pipeline.
        Must be implemented by subclasses.
        """
        pass

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        negative_prompt: Optional[str] = None,
        height: Optional[int] = None,
        width: Optional[int] = None,
        num_inference_steps: Optional[int] = None,
        guidance_scale: Optional[float] = None,
        seed: Optional[int] = None,
        **kwargs,
    ) -> GenerationResult:
        """Generate an image from a text prompt.

        Args:
            prompt: Text description of the image to generate
            negative_prompt: What to avoid in the image (optional)
            height: Image height in pixels
            width: Image width in pixels
            num_inference_steps: Number of denoising steps
            guidance_scale: How closely to follow the prompt
            seed: Random seed for reproducibility
            **kwargs: Additional model-specific parameters

        Returns:
            GenerationResult with image path and metadata

        Must be implemented by subclasses.
        """
        pass

    def cleanup(self):
        """Clean up GPU memory and resources.

        This should be called after generation to free up memory.
        Can be overridden by subclasses for model-specific cleanup.
        """
        if self.pipe is not None:
            del self.pipe
            self.pipe = None

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()

    def get_model_info(self) -> dict:
        """Get information about the current model.

        Returns:
            Dictionary with model name, type, device, etc.

        Can be overridden by subclasses to provide more details.
        """
        return {
            "device": self.device,
            "model_type": self.__class__.__name__,
        }

    def __del__(self):
        """Cleanup when generator is destroyed."""
        self.cleanup()
