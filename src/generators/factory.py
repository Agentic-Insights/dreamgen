"""Factory for creating image generators based on configuration."""

from loguru import logger

from ..utils.config import Config
from .base_generator import ImageGenerator


def get_image_generator(config: Config, mock: bool = False) -> ImageGenerator:
    """Create an image generator based on configuration.

    Args:
        config: Configuration object
        mock: If True, return MockImageGenerator regardless of config

    Returns:
        ImageGenerator instance (FLUX, Z-Image, or Mock)

    Raises:
        ValueError: If unknown model type specified
        ImportError: If required dependencies not available
    """
    if mock:
        logger.info("Creating MockImageGenerator (no GPU required)")
        from .mock_image_generator import MockImageGenerator

        return MockImageGenerator(config)

    model_type = config.model.image_model.lower()

    if model_type == "zimage":
        logger.info("Creating ZImageGenerator")
        try:
            from .zimage_generator import ZImageGenerator

            return ZImageGenerator(config)
        except ImportError as e:
            logger.error(
                "Failed to import ZImageGenerator. "
                "Make sure diffusers is installed from source:\n"
                "  pip install git+https://github.com/huggingface/diffusers"
            )
            raise ImportError("ZImagePipeline not available. Install diffusers from source.") from e

    elif model_type == "flux":
        logger.info("Creating FluxImageGenerator")
        # Import the existing ImageGenerator (which is actually FLUX)
        # We'll rename it later for clarity, but for now it works
        from .image_generator import ImageGenerator as FluxImageGenerator

        return FluxImageGenerator(config)

    else:
        raise ValueError(
            f"Unknown image model type: {model_type}. "
            f"Expected 'flux' or 'zimage', got '{model_type}'"
        )


def get_available_models() -> list[str]:
    """Get list of available model types.

    Returns:
        List of model type strings (e.g., ['flux', 'zimage'])
    """
    models = ["flux"]  # FLUX is always available

    # Check if Z-Image is available
    try:
        from diffusers import ZImagePipeline

        models.append("zimage")
        logger.debug("Z-Image available")
    except ImportError:
        logger.debug("Z-Image not available (diffusers from source required)")

    return models
