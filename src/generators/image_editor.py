"""
Image editor using Qwen-Image-Edit model for image-to-image editing.
"""

import asyncio
import io
import logging
import os
from pathlib import Path
from typing import Union

from huggingface_hub import InferenceClient
from PIL import Image

from ..utils.config import Config
from ..utils.error_handler import ModelError, handle_errors

logger = logging.getLogger(__name__)


class ImageEditor:
    """Image editor for transforming existing images using Qwen-Image-Edit."""

    def __init__(self, config: Config):
        """Initialize the image editor.

        Args:
            config: Configuration object
        """
        self.config = config
        self.model_name = "Qwen/Qwen-Image-Edit"

        # Initialize Inference Client
        hf_token = os.environ.get("HF_TOKEN")
        if not hf_token or hf_token == "your_hugging_face_token_here":
            logger.warning("No HF_TOKEN found. Image editing may not work.")

        self.client = InferenceClient(
            provider="fal-ai",
            api_key=hf_token,
        )

        logger.info(f"Image Editor initialized with model: {self.model_name}")

    @handle_errors(error_type=ModelError, retries=2)
    async def edit_image(
        self, input_image: Union[str, Path, Image.Image, bytes], prompt: str, strength: float = 0.8
    ) -> Image.Image:
        """Edit an image using the specified prompt.

        Args:
            input_image: Input image as file path, PIL Image, or bytes
            prompt: Text prompt describing the desired edits
            strength: Strength of the edit (0.0 to 1.0)

        Returns:
            Edited PIL Image
        """
        logger.info(f"Starting image edit with prompt: {prompt[:50]}...")

        # Convert input to bytes if needed
        if isinstance(input_image, (str, Path)):
            with open(input_image, "rb") as f:
                image_bytes = f.read()
        elif isinstance(input_image, Image.Image):
            # Convert PIL Image to bytes
            buffer = io.BytesIO()
            input_image.save(buffer, format="PNG")
            image_bytes = buffer.getvalue()
        elif isinstance(input_image, bytes):
            image_bytes = input_image
        else:
            raise ValueError(f"Unsupported input image type: {type(input_image)}")

        try:
            # Use the InferenceClient for image editing
            logger.debug("Calling Qwen-Image-Edit model...")

            # Run in thread pool since InferenceClient might be blocking
            loop = asyncio.get_event_loop()
            edited_image = await loop.run_in_executor(
                None,
                lambda: self.client.image_to_image(
                    image_bytes, prompt=prompt, model=self.model_name, strength=strength
                ),
            )

            logger.info("Image edit completed successfully")
            return edited_image

        except Exception as e:
            logger.error(f"Error during image edit: {str(e)}")
            raise ModelError(f"Image editing failed: {str(e)}") from e

    async def batch_edit(
        self, input_images: list, prompts: list, strength: float = 0.8
    ) -> list[Image.Image]:
        """Edit multiple images with different prompts.

        Args:
            input_images: List of input images
            prompts: List of prompts (one per image)
            strength: Edit strength

        Returns:
            List of edited PIL Images
        """
        if len(input_images) != len(prompts):
            raise ValueError("Number of images must match number of prompts")

        logger.info(f"Starting batch edit of {len(input_images)} images")

        # Process images concurrently
        tasks = [
            self.edit_image(image, prompt, strength) for image, prompt in zip(input_images, prompts)
        ]

        edited_images = await asyncio.gather(*tasks, return_exceptions=True)

        # Handle any exceptions
        results = []
        for i, result in enumerate(edited_images):
            if isinstance(result, Exception):
                logger.error(f"Failed to edit image {i}: {result}")
                # You could return the original image or None here
                results.append(None)
            else:
                results.append(result)

        logger.info(
            f"Batch edit completed: {len([r for r in results if r is not None])} successful"
        )
        return results
