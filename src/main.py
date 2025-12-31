"""
Main entry point for the continuous image generation system.
"""

from .utils.cli import app
from .utils.config import Config


def main():
    """Main entry point."""
    # Create default config
    config = Config()

    # Set up Typer context with config
    app.state.config = config

    # Run the app
    app()


if __name__ == "__main__":
    main()
