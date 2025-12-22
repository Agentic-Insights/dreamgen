"""Z-Image generator implementation."""

import asyncio
import gc
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Optional

import torch
from loguru import logger

from .base_generator import GenerationResult, ImageGenerator


class ZImageGenerator(ImageGenerator):
    """Z-Image text-to-image generator.

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
        self.model_id = config.model.zimage_model
        self.attention_backend = config.model.zimage_attention
        self.compile_model = config.model.zimage_compile

    def load_model(self):
        """Load Z-Image model into memory."""
        try:
            from diffusers import ZImagePipeline
        except ImportError:
            logger.error(
                "ZImagePipeline not found. Install diffusers from source:\n"
                "  pip install git+https://github.com/huggingface/diffusers"
            )
            raise

        logger.info(f"Loading Z-Image model: {self.model_id}")
        logger.info(f"Device: {self.device}")
        logger.info(f"Attention backend: {self.attention_backend}")

        self.pipe = ZImagePipeline.from_pretrained(
            self.model_id,
            torch_dtype=torch.bfloat16,  # Z-Image uses bfloat16
            low_cpu_mem_usage=True,
            use_safetensors=True,
        )

        # Move to device
        if self.device == "cuda":
            self.pipe = self.pipe.to("cuda")

            # Enable memory optimizations
            if hasattr(self.pipe, "enable_attention_slicing"):
                self.pipe.enable_attention_slicing(1)
                logger.info("Enabled attention slicing for memory efficiency")

            if hasattr(self.pipe, "enable_vae_tiling"):
                self.pipe.enable_vae_tiling()
                logger.info("Enabled VAE tiling for memory efficiency")

        elif self.device == "mps":
            self.pipe = self.pipe.to("mps")
            # MPS-specific optimizations if any
        else:
            # CPU mode
            logger.warning("Running on CPU - generation will be slow")

        # Model compilation (for H100/H800 optimal performance)
        if self.compile_model and self.device == "cuda":
            logger.info("Compiling model for optimal performance...")
            self.pipe.unet = torch.compile(self.pipe.unet, mode="reduce-overhead", fullgraph=True)
            logger.info("Model compilation complete")

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
        if self.pipe is None:
            self.load_model()

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
        image = await loop.run_in_executor(
            None,
            lambda: self.pipe(
                prompt=prompt,
                height=height,
                width=width,
                num_inference_steps=num_inference_steps,
                guidance_scale=guidance_scale,
                generator=generator,
            ).images[0],
        )

        # Save image
        output_path = self._save_image(image, prompt, seed)

        # Create metadata
        metadata = {
            "model": "Z-Image-Turbo",
            "model_id": self.model_id,
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

    def cleanup(self):
        """Clean up GPU memory after generation."""
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
                "model_id": self.model_id,
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
