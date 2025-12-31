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
                "Make sure Z-Image repo is cloned:\n"
                "  git clone https://github.com/Tongyi-MAI/Z-Image ref-repos/Z-Image"
            )
            raise ImportError(
                "Z-Image not available. Clone Z-Image repo to ref-repos/Z-Image"
            ) from e

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

    # Check if Z-Image is available (look for ref-repos/Z-Image/src)
    from pathlib import Path

    project_root = Path(__file__).parent.parent.parent
    zimage_src = project_root / "ref-repos" / "Z-Image" / "src"
    if zimage_src.exists() and (zimage_src / "zimage").exists():
        models.append("zimage")
        logger.debug("Z-Image available")
    else:
        logger.debug("Z-Image not available (clone repo to ref-repos/Z-Image)")

    return models
