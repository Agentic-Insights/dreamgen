"""
Centralized error handling for the image generation system.
"""

import functools
import logging
from pathlib import Path
from typing import Callable, Optional, Type

# Create logs directory
log_dir = Path("logs")
log_dir.mkdir(parents=True, exist_ok=True)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler(log_dir / "error.log"), logging.StreamHandler()],
)

logger = logging.getLogger(__name__)


class ImageGenError(Exception):
    """Base exception class for image generation errors."""

    pass


class ModelError(ImageGenError):
    """Errors related to model loading or inference."""

    pass


class PromptError(ImageGenError):
    """Errors related to prompt generation or validation."""

    pass


class ResourceError(ImageGenError):
    """Errors related to system resources (memory, GPU, etc)."""

    pass


def handle_errors(
    error_type: Optional[Type[Exception]] = None,
    retries: int = 0,
    cleanup_func: Optional[Callable] = None,
):
    """
    Decorator for handling errors in image generation functions.

    Args:
        error_type: Specific type of error to catch
        retries: Number of retry attempts
        cleanup_func: Function to call for cleanup on error
    """

    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            attempts = retries + 1

            for attempt in range(attempts):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    logger.error(f"Error in {func.__name__}: {str(e)}")

                    if cleanup_func:
                        try:
                            cleanup_func()
                        except Exception as cleanup_error:
                            logger.error(f"Error during cleanup: {str(cleanup_error)}")

                    if attempt < retries:
                        logger.info(f"Retrying {func.__name__} (attempt {attempt + 2}/{attempts})")
                        continue

                    if error_type and isinstance(e, error_type):
                        raise
                    raise ImageGenError(f"Failed after {attempts} attempts: {str(e)}") from e

        return wrapper

    return decorator
