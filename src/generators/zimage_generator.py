"""Z-Image generator implementation using native Z-Image API."""

import asyncio
import gc
import hashlib
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import torch
from loguru import logger

from .base_generator import GenerationResult, ImageGenerator


class ZImageGenerator(ImageGenerator):
    """Z-Image text-to-image generator using native implementation.

    Uses Tongyi-MAI/Z-Image-Turbo for high-quality photorealistic generation
    with excellent bilingual text rendering capabilities.

    Features:
    - 6B parameter single-stream DiT architecture
    - 8-step inference (fast generation)
    - Superior Chinese and English text rendering
    - 16GB VRAM compatible
    """

    def __init__(self, config):
        """Initialize Z-Image generator.

        Args:
            config: Configuration object with Z-Image settings
        """
        super().__init__(config)
        self.model_path = Path(config.model.zimage_model_path)
        self.attention_backend = config.model.zimage_attention
        self.compile_model = config.model.zimage_compile
        self.components = None  # Will hold transformer, vae, text_encoder, tokenizer, scheduler

    def _get_zimage_src_path(self) -> Path:
        """Get the path to Z-Image source code."""
        # Look for Z-Image in ref-repos relative to project root
        project_root = Path(__file__).parent.parent.parent
        zimage_src = project_root / "ref-repos" / "Z-Image" / "src"
        if zimage_src.exists():
            return zimage_src
        raise ImportError(
            f"Z-Image source not found at {zimage_src}. "
            "Clone Z-Image repo: git clone https://github.com/Tongyi-MAI/Z-Image ref-repos/Z-Image"
        )

    def load_model(self):
        """Load Z-Image model components into memory."""
        # Add Z-Image source to path
        zimage_src = self._get_zimage_src_path()
        if str(zimage_src) not in sys.path:
            sys.path.insert(0, str(zimage_src))

        try:
            from utils import load_from_local_dir, set_attention_backend
        except ImportError as e:
            logger.error(
                f"Failed to import Z-Image utilities: {e}\n"
                "Make sure Z-Image repo is cloned to ref-repos/Z-Image"
            )
            raise

        logger.info(f"Loading Z-Image model from: {self.model_path}")
        logger.info(f"Device: {self.device}")
        logger.info(f"Attention backend: {self.attention_backend}")
        logger.info(f"Compile: {self.compile_model}")

        if not self.model_path.exists():
            raise FileNotFoundError(
                f"Z-Image model not found at {self.model_path}. "
                "Download from HuggingFace: huggingface-cli download Tongyi-MAI/Z-Image-Turbo --local-dir <path>"
            )

        # Load all components
        self.components = load_from_local_dir(
            model_dir=self.model_path,
            device=self.device,
            dtype=torch.bfloat16,
            verbose=True,
            compile=self.compile_model,
        )

        # Set attention backend
        set_attention_backend(self.attention_backend)
        logger.info(f"Set attention backend to: {self.attention_backend}")

        logger.info("Z-Image model loaded successfully")

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
        """Generate an image using Z-Image.

        Args:
            prompt: Text description of the image
            negative_prompt: Unused (Z-Image Turbo doesn't use negative prompts)
            height: Image height (default: 1024)
            width: Image width (default: 1024)
            num_inference_steps: Number of steps (default: 8 for Turbo)
            guidance_scale: Unused (Z-Image Turbo uses 0.0)
            seed: Random seed for reproducibility
            **kwargs: Additional parameters

        Returns:
            GenerationResult with generated image
        """
        if self.components is None:
            self.load_model()

        # Import generate function
        zimage_src = self._get_zimage_src_path()
        if str(zimage_src) not in sys.path:
            sys.path.insert(0, str(zimage_src))
        from zimage import generate as zimage_generate

        # Apply defaults from config
        height = height or self.config.image.height
        width = width or self.config.image.width
        num_inference_steps = num_inference_steps or 8  # Z-Image Turbo default
        seed = seed if seed is not None else torch.randint(0, 2**32, (1,)).item()

        # Z-Image Turbo uses guidance_scale=0.0 (fixed)
        guidance_scale = 0.0

        # Negative prompts not used in Turbo variant
        if negative_prompt:
            logger.warning(
                "Z-Image Turbo doesn't use negative prompts, ignoring negative_prompt parameter"
            )

        logger.info(f"Generating image with Z-Image: {prompt[:100]}...")
        logger.info(f"Parameters: {width}x{height}, steps={num_inference_steps}, seed={seed}")

        # Create generator for reproducibility
        generator = torch.Generator(device=self.device).manual_seed(seed)

        # Generate in separate thread to avoid blocking
        loop = asyncio.get_event_loop()
        images = await loop.run_in_executor(
            None,
            lambda: zimage_generate(
                prompt=prompt,
                **self.components,
                height=height,
                width=width,
                num_inference_steps=num_inference_steps,
                guidance_scale=guidance_scale,
                generator=generator,
            ),
        )

        image = images[0]

        # Save image
        output_path = self._save_image(image, prompt, seed)

        # Create metadata
        metadata = {
            "model": "Z-Image-Turbo",
            "model_path": str(self.model_path),
            "height": height,
            "width": width,
            "steps": num_inference_steps,
            "guidance_scale": guidance_scale,
            "attention_backend": self.attention_backend,
            "compiled": self.compile_model,
            "device": self.device,
        }

        logger.info(f"Image saved to: {output_path}")

        return GenerationResult(
            image_path=output_path,
            prompt=prompt,
            model="zimage",
            seed=seed,
            steps=num_inference_steps,
            metadata=metadata,
        )

    def _save_image(self, image, prompt: str, seed: int) -> Path:
        """Save generated image to output directory.

        Args:
            image: PIL Image to save
            prompt: Prompt used for generation
            seed: Seed used for generation

        Returns:
            Path to saved image
        """
        # Create output directory structure (week-based organization)
        now = datetime.now()
        year_dir = self.config.system.output_dir / str(now.year)
        week_num = now.isocalendar()[1]
        week_dir = year_dir / f"week_{week_num:02d}"
        week_dir.mkdir(parents=True, exist_ok=True)

        # Generate filename with timestamp and hash
        timestamp = now.strftime("%Y%m%d_%H%M%S")
        prompt_hash = hashlib.md5(prompt.encode()).hexdigest()[:8]
        filename = f"image_{timestamp}_{prompt_hash}.png"
        output_path = week_dir / filename

        # Save image
        image.save(output_path)

        # Save prompt to text file
        prompt_file = output_path.with_suffix(".txt")
        with open(prompt_file, "w", encoding="utf-8") as f:
            f.write(prompt)

        return output_path

    async def generate_image(
        self,
        prompt: str,
        output_path: Path,
        force_reinit: bool = False,
    ) -> tuple[Path, float, str]:
        """Generate an image from the given prompt (CLI-compatible interface).

        This method provides compatibility with the existing CLI which expects
        the (Path, float, str) return signature.

        Args:
            prompt: Text description of the image
            output_path: Ignored (Z-Image uses its own output path logic)
            force_reinit: Whether to force model reinitialization

        Returns:
            Tuple of (output_path, generation_time, model_name)
        """
        import time

        start_time = time.time()

        if force_reinit and self.components is not None:
            self.cleanup()
            self.components = None

        result = await self.generate(prompt=prompt)

        generation_time = time.time() - start_time

        return (result.image_path, generation_time, "Z-Image-Turbo")

    def cleanup(self):
        """Clean up GPU memory after generation."""
        if self.components is not None:
            # Delete component references
            for key in list(self.components.keys()):
                del self.components[key]
            self.components = None

        super().cleanup()

        # Additional cleanup
        gc.collect()

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()

    def get_model_info(self) -> dict:
        """Get Z-Image model information.

        Returns:
            Dictionary with model details
        """
        info = super().get_model_info()
        info.update(
            {
                "model_name": "Z-Image-Turbo",
                "model_path": str(self.model_path),
                "parameters": "6B",
                "architecture": "Single-Stream DiT (S3-DiT)",
                "inference_steps": 8,
                "attention_backend": self.attention_backend,
                "compiled": self.compile_model,
                "features": [
                    "Photorealistic generation",
                    "Bilingual text rendering (EN/ZH)",
                    "Fast inference (8 steps)",
                    "16GB VRAM compatible",
                ],
            }
        )
        return info
