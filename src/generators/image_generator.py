"""
Image generator using Flux 1.1 transformers model.
"""

import gc
import logging
import os
import platform
import time
import traceback
from pathlib import Path
from typing import Literal, Optional, Tuple

import torch
from diffusers import DiffusionPipeline
from PIL import Image

from ..plugins import plugin_manager, register_lora_plugin
from ..plugins.lora import get_lora_path
from ..utils.config import Config
from ..utils.error_handler import ModelError, handle_errors
from ..utils.memory_manager import MemoryManager
from ..utils.metrics import GenerationMetrics

# Configure logging
logging.getLogger("transformers").setLevel(logging.WARNING)
logging.getLogger("diffusers").setLevel(logging.WARNING)
logging.getLogger("accelerate").setLevel(logging.WARNING)

# Create a dedicated logger for this module
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)  # Set to DEBUG level for more detailed logging


class ImageGenerator:
    def __init__(self, config: Config):
        """Initialize the image generator with configurable parameters.

        Args:
            model_variant: Which Flux model variant to use (full model path)
            cpu_only: Whether to force CPU-only mode
            height: Height of generated images (default from env or 768)
            width: Width of generated images (default from env or 1360)
            num_inference_steps: Number of denoising steps (default from env or 50)
            guidance_scale: Guidance scale for generation (default from env or 7.5)
            true_cfg_scale: True classifier-free guidance scale (default from env or 1.0)
            max_sequence_length: Max sequence length for text processing (default from env or 512)
        """
        self.config = config
        self.model_name = config.model.flux_model

        # Register Lora plugin with config
        register_lora_plugin(config)

        self.height = config.image.height
        self.width = config.image.width
        self.num_inference_steps = config.image.num_inference_steps
        self.guidance_scale = config.image.guidance_scale
        self.true_cfg_scale = config.image.true_cfg_scale
        self.max_sequence_length = config.model.max_sequence_length
        self.pipe = None

        # Determine available device
        self.device = self._determine_device(config.system.cpu_only)
        self.memory_manager = MemoryManager(self.device)

        if self.device == "cuda":
            logger.info("Using NVIDIA GPU: %s", torch.cuda.get_device_name())
            torch.cuda.set_device(0)
            self.memory_manager.optimize_memory_usage()
        elif self.device == "mps":
            logger.info("Using Apple Silicon GPU: %s", platform.processor())
            self.memory_manager.optimize_memory_usage()
        else:
            logger.warning("Running on CPU. This will be significantly slower.")

    def _flush_memory(self) -> None:
        """Aggressive memory cleanup optimized for RTX 4090."""
        logger.debug("Performing aggressive memory cleanup")
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.reset_max_memory_allocated()
        logger.debug("Memory cleanup completed")

    def _determine_device(self, cpu_only: bool) -> Literal["cpu", "cuda", "mps"]:
        """Determine the appropriate device to use based on availability."""
        if cpu_only:
            return "cpu"

        # Check for CUDA (NVIDIA GPUs)
        if torch.cuda.is_available():
            return "cuda"

        # Check for MPS (Apple Silicon)
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"

        # If we got here and cpu_only is False, warn the user
        if not cpu_only:
            logger.warning(
                "No GPU acceleration available (neither CUDA nor MPS). "
                "Consider using --cpu-only flag for better error handling."
            )

        return "cpu"

    def initialize(self, force_reinit: bool = False):
        """Initialize the Flux diffusion pipeline."""
        if force_reinit and self.pipe is not None:
            logger.debug("Force reinitialization requested, cleaning up existing pipeline")
            self.cleanup()

        if self.pipe is None:
            logger.info("Initializing diffusion pipeline")
            # Check and optimize memory before loading
            is_critical, status = self.memory_manager.check_memory_pressure()
            if is_critical:
                logger.warning(f"Memory status: {status}")
                self.memory_manager.optimize_memory_usage()

            logger.info(f"Loading model on {self.device}...")

            # Set memory management environment variables
            os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "max_split_size_mb:512"
            logger.debug("Set PYTORCH_CUDA_ALLOC_CONF to max_split_size_mb:512")

            # Determine appropriate torch dtype based on device and model
            if self.device == "cuda":
                # Use float16 for better compatibility across models
                torch_dtype = torch.float16
                logger.debug("Using torch.float16 for CUDA device")
            elif self.device == "mps":
                # MPS works better with float32 for most models, but can use float16 for some
                torch_dtype = torch.float16 if self.config.system.mps_use_fp16 else torch.float32
                logger.debug(
                    f"Using {'torch.float16' if self.config.system.mps_use_fp16 else 'torch.float32'} for MPS device"
                )
            else:
                torch_dtype = torch.float32
                logger.debug("Using torch.float32 for CPU device")

            # Get HF token if available
            hf_token = os.environ.get("HF_TOKEN")
            logger.debug(f"HF token available: {hf_token is not None}")

            try:
                # Load model with memory optimizations
                logger.info(f"Loading model from {self.model_name}")
                try:
                    self.pipe = DiffusionPipeline.from_pretrained(
                        self.model_name,
                        torch_dtype=torch_dtype,
                        use_auth_token=(
                            hf_token
                            if hf_token and hf_token != "your_hugging_face_token_here"
                            else None
                        ),
                    )
                    logger.debug("Model loaded successfully")
                except OSError as e:
                    # Check for Windows paging file error
                    if "paging file is too small" in str(e) or "os error 1455" in str(e).lower():
                        logger.error(
                            "\n" + "=" * 60 + "\n"
                            "MEMORY ERROR: Insufficient memory to load Flux model\n"
                            "=" * 60 + "\n"
                            "The Flux model requires ~15GB of RAM to load.\n\n"
                            "Solutions:\n"
                            "1. Use mock mode: Add --mock flag\n"
                            "2. Increase Windows virtual memory:\n"
                            "   - Open System Properties > Advanced > Performance Settings\n"
                            "   - Advanced tab > Virtual Memory > Change\n"
                            "   - Set to 32GB or more\n"
                            "3. Use a smaller model like SDXL or SD 1.5\n"
                            "4. Run in Docker with proper memory limits\n"
                            "=" * 60
                        )
                        raise RuntimeError(
                            "Insufficient memory for Flux model. Use --mock flag or increase virtual memory."
                        ) from e
                    raise

                # Enable sequential CPU offload for better memory management with Flux
                if self.device == "cuda":
                    logger.info("Enabling sequential CPU offload for memory optimization")
                    self.pipe.enable_sequential_cpu_offload()
                    logger.debug("Sequential CPU offload enabled")
                # Move model to device if not using CPU offloading
                elif self.device != "cpu":
                    logger.debug(f"Moving model to {self.device}")
                    try:
                        self.pipe.to(self.device)
                        logger.debug("Model moved to device successfully")
                    except ValueError as e:
                        if "model offloading" in str(e) or "sequential model offloading" in str(e):
                            logger.warning("CPU offloading detected, skipping device move")
                            # Continue without moving to device as it's already handled by offloading
                        else:
                            raise

                # Load random Lora if selected through plugin system
                logger.info("Checking for Lora plugins")
                try:
                    plugin_results = plugin_manager.execute_plugins()
                    logger.debug(f"Plugin results: {plugin_results}")

                    for result in plugin_results:
                        if result.name == "lora" and result.value:
                            logger.info(f"Found Lora plugin with value: {result.value}")
                            try:
                                lora_path = get_lora_path(result.value, self.config)
                                logger.debug(f"Lora path: {lora_path}")

                                if lora_path:
                                    logger.info(f"Loading Lora: {result.value} from {lora_path}")
                                    # Basic Lora loading without extra parameters
                                    try:
                                        self.pipe.load_lora_weights(str(lora_path))
                                        logger.info("Lora weights loaded successfully")
                                    except Exception as lora_load_error:
                                        logger.error(
                                            f"Error loading Lora weights: {str(lora_load_error)}"
                                        )
                                        logger.error(f"Traceback: {traceback.format_exc()}")
                                else:
                                    logger.warning(f"Could not find Lora path for: {result.value}")
                            except Exception as lora_path_error:
                                logger.error(f"Error getting Lora path: {str(lora_path_error)}")
                                logger.error(f"Traceback: {traceback.format_exc()}")
                except Exception as plugin_error:
                    logger.error(f"Error executing plugins: {str(plugin_error)}")
                    logger.error(f"Traceback: {traceback.format_exc()}")

                # Set up device-specific optimizations
                if self.device in ["cuda", "mps"]:
                    logger.info("Setting up GPU optimizations")
                    self._setup_gpu_optimizations()
                    # Final memory cleanup after all optimizations
                    self._flush_memory()

            except Exception as model_load_error:
                logger.error(f"Error loading model: {str(model_load_error)}")
                logger.error(f"Traceback: {traceback.format_exc()}")
                raise

    def _setup_gpu_optimizations(self):
        """Set up GPU-specific optimizations for the pipeline."""
        try:
            # Attention slicing works on both CUDA and MPS
            logger.debug("Enabling attention slicing")
            self.pipe.enable_attention_slicing()
            logger.info("Enabled attention slicing")

            # VAE tiling works on both CUDA and MPS
            logger.debug("Enabling VAE tiling")
            self.pipe.enable_vae_tiling()
            logger.info("Enabled VAE tiling")

            # xformers is CUDA-specific
            if self.device == "cuda":
                try:
                    logger.debug("Attempting to enable xformers memory efficient attention")
                    self.pipe.enable_xformers_memory_efficient_attention()
                    logger.info("Enabled xformers memory efficient attention")
                except Exception as xformers_error:
                    logger.warning(f"Xformers optimization not available: {str(xformers_error)}")

                # RTX 4090 specific optimizations
                try:
                    logger.debug("Applying RTX 4090 specific optimizations")

                    # Enable VAE slicing for memory efficiency
                    if hasattr(self.pipe, "enable_vae_slicing"):
                        self.pipe.enable_vae_slicing()
                        logger.debug("Enabled VAE slicing for RTX 4090")

                    # Set channels_last memory format for better tensor performance
                    if hasattr(self.pipe, "unet") and self.pipe.unet is not None:
                        self.pipe.unet.to(memory_format=torch.channels_last)
                        logger.debug("Set UNet to channels_last memory format")

                    # Apply memory flush
                    self._flush_memory()
                    logger.info("Applied RTX 4090 specific optimizations")

                except Exception as rtx_error:
                    logger.warning(f"RTX 4090 optimizations not fully available: {str(rtx_error)}")

            # Print memory info if available
            allocated, reserved, total = self.memory_manager.get_gpu_memory_info()
            if total > 0:
                logger.debug(
                    f"GPU Memory: {allocated:.2f} GB allocated, {reserved:.2f} GB reserved (Total: {total:.2f} GB)"
                )
                logger.info(
                    f"GPU Memory: {allocated:.2f} GB allocated, {reserved:.2f} GB reserved (Total: {total:.2f} GB)"
                )
        except Exception as opt_error:
            logger.error(f"Error setting up GPU optimizations: {str(opt_error)}")
            logger.error(f"Traceback: {traceback.format_exc()}")

    async def generate(self, prompt: str, seed: Optional[int] = None) -> Image.Image:
        """Generate an image and return it as PIL Image for API compatibility.

        Args:
            prompt: The prompt to generate from
            seed: Optional random seed for reproducibility

        Returns:
            PIL Image object
        """
        # Create a temporary path for the image
        from ..utils.storage import StorageManager

        storage = StorageManager()
        output_path = storage.get_output_path(prompt)

        # Generate the image using the existing method
        await self.generate_image(prompt, output_path, force_reinit=False)

        # Load and return the image
        return Image.open(output_path)

    @handle_errors(
        error_type=ModelError,
        retries=1,
    )
    async def generate_image(
        self, prompt: str, output_path: Path, force_reinit: bool = False
    ) -> Tuple[Path, float, str]:
        """Generate an image from the given prompt."""
        metrics = GenerationMetrics(prompt=prompt, model_name=self.model_name)
        start_time = time.time()

        try:
            logger.info(f"Starting image generation with prompt: {prompt[:50]}...")

            # Check memory and initialize
            is_critical, memory_status = self.memory_manager.check_memory_pressure()
            logger.debug(f"Memory status: {memory_status}")
            if is_critical:
                logger.warning(f"Critical memory pressure detected: {memory_status}")
                force_reinit = True

            logger.debug(f"Initializing model (force_reinit={force_reinit})")
            self.initialize(force_reinit)

            # Log model and generation parameters
            logger.info(f"Model: {self.model_name}, Device: {self.device}")
            logger.debug(
                f"Parameters: steps={self.num_inference_steps}, guidance={self.guidance_scale}, "
                f"true_cfg={self.true_cfg_scale}, size={self.width}x{self.height}"
            )

            # Generate image
            logger.info("Starting inference...")
            try:
                with (
                    torch.inference_mode(),
                    torch.amp.autocast(self.device, enabled=self.device in ["cuda", "mps"]),
                ):
                    logger.debug("Entering inference mode with autocast")

                    # Log memory before inference
                    if self.device == "cuda":
                        allocated = torch.cuda.memory_allocated() / 1024**3
                        reserved = torch.cuda.memory_reserved() / 1024**3
                        logger.debug(
                            f"GPU Memory before inference: {allocated:.2f} GB allocated, {reserved:.2f} GB reserved"
                        )

                    # Run inference with detailed error handling
                    try:
                        logger.debug("Calling pipe with prompt")
                        image = self.pipe(
                            prompt=prompt,
                            prompt_2=prompt,
                            num_inference_steps=self.num_inference_steps,
                            guidance_scale=self.guidance_scale,
                            true_cfg_scale=self.true_cfg_scale,
                            height=self.height,
                            width=self.width,
                            max_sequence_length=self.max_sequence_length,
                        ).images[0]
                        logger.debug("Pipe call completed successfully")
                    except Exception as inference_error:
                        logger.error(f"Error during inference: {str(inference_error)}")
                        logger.error(f"Traceback: {traceback.format_exc()}")
                        raise
            except Exception as outer_error:
                logger.error(f"Error in inference context: {str(outer_error)}")
                logger.error(f"Traceback: {traceback.format_exc()}")
                raise

            # Log memory after inference
            if self.device == "cuda":
                allocated = torch.cuda.memory_allocated() / 1024**3
                reserved = torch.cuda.memory_reserved() / 1024**3
                logger.debug(
                    f"GPU Memory after inference: {allocated:.2f} GB allocated, {reserved:.2f} GB reserved"
                )

            # Save image
            logger.info(f"Saving image to {output_path}")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                image.save(output_path)
                logger.debug("Image saved successfully")

                # Also save prompt to text file
                with open(output_path.with_suffix(".txt"), "w") as f:
                    f.write(prompt)
                logger.debug("Prompt saved to text file")
            except Exception as save_error:
                logger.error(f"Error saving image: {str(save_error)}")
                raise

            # Update metrics
            metrics.generation_time = time.time() - start_time
            if self.device == "cuda":
                metrics.gpu_memory_peak = torch.cuda.max_memory_allocated() / 1024**3
                logger.debug(f"GPU memory peak: {metrics.gpu_memory_peak:.2f} GB")

            logger.info(f"Image generation completed in {metrics.generation_time:.2f} seconds")
            return output_path, metrics.generation_time, self.model_name.split("/")[-1]

        except Exception as e:
            metrics.success = False
            metrics.error = str(e)
            logger.error(f"Image generation failed: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise
        finally:
            logger.debug("Running memory optimization in finally block")
            self.memory_manager.optimize_memory_usage()

    def cleanup(self):
        """Clean up resources."""
        logger.info("Cleaning up resources")
        if self.pipe is not None:
            logger.debug("Deleting pipeline")
            try:
                del self.pipe
                self.pipe = None
                logger.debug("Pipeline deleted")
            except Exception as cleanup_error:
                logger.error(f"Error during cleanup: {str(cleanup_error)}")

            logger.debug("Optimizing memory usage")
            self.memory_manager.optimize_memory_usage()
