"""
Command-line interface for the continuous image generation system.
"""

import asyncio
import os
import sys
from pathlib import Path
from typing import Optional

# Fix Windows Unicode handling
if sys.platform == "win32":
    import locale

    if sys.stdout.encoding != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    if sys.stderr.encoding != "utf-8":
        sys.stderr.reconfigure(encoding="utf-8")

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

from ..generators.factory import get_available_models, get_image_generator
from ..generators.prompt_generator import PromptGenerator
from ..plugins import ensure_initialized, plugin_manager
from .config import Config
from .logging_config import setup_logging
from .metrics import MetricsCollector
from .storage import StorageManager
from .troubleshoot import SystemDiagnostics

# Initialize rich console for better output
console = Console()
app = typer.Typer(
    help="DreamGen - Your AI Image Generation Companion",
    no_args_is_help=True,
    rich_markup_mode="rich",
)


# Initialize app state
class AppState:
    def __init__(self):
        self.config: Optional[Config] = None


app.state = AppState()

# Plugin management subcommands
plugins_app = typer.Typer(help="Manage prompt plugins")
app.add_typer(plugins_app, name="plugins")


@plugins_app.command("list")
def list_plugins() -> None:
    """Display available plugins and their status."""
    ensure_initialized(app.state.config)
    table = Table("Name", "Enabled", "Description")
    for name, info in plugin_manager.plugins.items():
        table.add_row(name, "yes" if info.enabled else "no", info.description)
    console.print(table)


@plugins_app.command("enable")
def enable_plugin(name: str) -> None:
    """Enable a plugin by name."""
    ensure_initialized(app.state.config)
    if name not in plugin_manager.plugins:
        console.print(f"[red]Plugin '{name}' not found[/red]")
        raise typer.Exit(1)
    plugin_manager.enable_plugin(name)
    console.print(f"[green]Enabled plugin:[/green] {name}")


@plugins_app.command("disable")
def disable_plugin(name: str) -> None:
    """Disable a plugin by name."""
    ensure_initialized(app.state.config)
    if name not in plugin_manager.plugins:
        console.print(f"[red]Plugin '{name}' not found[/red]")
        raise typer.Exit(1)
    plugin_manager.disable_plugin(name)
    console.print(f"[yellow]Disabled plugin:[/yellow] {name}")


def version_callback(value: bool):
    """Display version information."""
    if value:
        console.print(
            Panel.fit(
                "[bold green]Continuous Image Generator[/bold green]\n"
                "Version: 0.1.0\n"
                "Using: Ollama for prompts, Flux 1.1 for images"
            )
        )
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-v",
        callback=version_callback,
        help="Show version information and exit",
        is_eager=True,
    ),
    config_file: Optional[Path] = typer.Option(
        None, "--config", "-c", help="Path to configuration file"
    ),
    debug: bool = typer.Option(
        False,
        "--debug",
        help="Enable verbose logging to console",
    ),
):
    """
    🎨 Continuous Image Generation System

    Generate AI images using Ollama for prompts and Flux for image generation.
    Run `uv run imagegen generate` for CLI usage or `uv run imagegen web` to
    start the browser UI.
    """
    if config_file and config_file.exists():
        app.state.config = Config.from_file(config_file)
    else:
        if config_file and not config_file.exists():
            console.print(
                f"[yellow]Warning: Config file {config_file} not found, using defaults[/yellow]"
            )
        app.state.config = Config()

    # Configure logging after configuration is loaded
    setup_logging(app.state.config.system.log_dir, verbose=debug)


@app.command(help="Generate a single image with optional interactive prompt refinement")
def generate(
    interactive: bool = typer.Option(
        False, "--interactive", "-i", help="Enable interactive mode with prompt feedback"
    ),
    prompt: Optional[str] = typer.Option(
        None, "--prompt", "-p", help="Provide a custom prompt for direct inference"
    ),
    model: Optional[str] = typer.Option(
        None,
        "--model",
        "-m",
        help="Image generation model to use (flux, zimage). Defaults to IMAGE_MODEL from .env",
    ),
    mock: bool = typer.Option(
        False,
        "--mock",
        help="Use mock image generator (no GPU required, generates placeholder images)",
    ),
    mps_use_fp16: bool = typer.Option(
        False,
        "--mps-use-fp16",
        help="Use float16 precision on Apple Silicon (may improve performance)",
    ),
) -> None:
    """Generate a single image using AI-generated prompts or a custom prompt."""

    async def _generate() -> None:
        try:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                TimeElapsedColumn(),
                console=console,
                transient=True,  # Hide finished tasks
            ) as progress:
                try:
                    # Update config with CLI options
                    app.state.config.system.mps_use_fp16 = mps_use_fp16

                    # Override model if specified via CLI
                    if model:
                        available = get_available_models()
                        if model not in available:
                            console.print(
                                f"[red]Error: Model '{model}' not available.[/red]\n"
                                f"Available models: {', '.join(available)}\n\n"
                                f"Note: Z-Image requires diffusers from source:\n"
                                f"  pip install git+https://github.com/huggingface/diffusers"
                            )
                            raise typer.Exit(1)
                        app.state.config.model.image_model = model
                        console.print(f"[cyan]Using model:[/cyan] {model}")

                    # Initialize components
                    init_task = progress.add_task("[cyan]Initializing components...", total=None)
                    prompt_gen = PromptGenerator(app.state.config)

                    # Use factory to create image generator
                    if mock:
                        console.print(
                            "[yellow]Using mock image generator (no GPU required)[/yellow]"
                        )
                    image_gen = get_image_generator(app.state.config, mock=mock)

                    storage = StorageManager()
                    metrics = MetricsCollector(app.state.config.system.log_dir / "metrics")
                    progress.remove_task(init_task)

                    # Start metrics collection
                    metrics.start_batch()

                    # Use provided prompt or generate one
                    if prompt:
                        generated_prompt = prompt
                        console.print(
                            Panel(
                                f"[bold]Using provided prompt:[/bold]\n\n{generated_prompt}",
                                title="Custom Prompt",
                                border_style="blue",
                            )
                        )
                    else:
                        prompt_task = progress.add_task(
                            "[cyan]Generating creative prompt...", total=None
                        )
                        if interactive:
                            generated_prompt = await prompt_gen.get_prompt_with_feedback()
                        else:
                            generated_prompt = await prompt_gen.generate_prompt()
                        progress.remove_task(prompt_task)
                        console.print(
                            Panel(
                                f"[bold]Generated prompt:[/bold]\n\n{generated_prompt}",
                                title="AI Prompt",
                                border_style="green",
                            )
                        )

                    # Get output path
                    output_path = storage.get_output_path(generated_prompt)

                    # Generate image
                    image_task = progress.add_task("[cyan]Generating image...", total=None)
                    output_path, gen_time, model_name = await image_gen.generate_image(
                        generated_prompt, output_path
                    )
                    progress.remove_task(image_task)

                    # Show success message with details
                    console.print(
                        Panel(
                            f"[bold green]Image generated successfully![/bold green]\n\n"
                            f"📁 Saved to: {output_path}\n"
                            f"📝 Prompt saved to: {output_path.with_suffix('.txt')}\n\n"
                            f"[dim]Model: {model_name}\n"
                            f"Time: {gen_time:.1f}s\n"
                            f"Prompt: {generated_prompt}[/dim]",
                            title="Success",
                            border_style="green",
                        )
                    )

                    # End metrics collection
                    metrics.end_batch()

                    # Cleanup
                    prompt_gen.cleanup()
                    image_gen.cleanup()

                except Exception as e:
                    console.print(f"[red]Error: {str(e)}[/red]")
                    raise
        except Exception as e:
            console.print(f"[red]Error: {str(e)}[/red]")
            raise typer.Exit(1)

    try:
        asyncio.run(_generate())
    except KeyboardInterrupt:
        print("\nOperation cancelled by user")


@app.command(help="Run system diagnostics and troubleshooting")
def diagnose(
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Show detailed diagnostic information"
    ),
    check_env: bool = typer.Option(
        True, "--check-env/--no-check-env", help="Check environment variables"
    ),
    fix: bool = typer.Option(False, "--fix", help="Attempt to fix common issues automatically"),
) -> None:
    """Run diagnostics to troubleshoot system compatibility and configuration issues."""
    console = Console()

    try:
        # Initialize diagnostics with config if available
        diagnostics = SystemDiagnostics(app.state.config)

        # Run and print diagnostics
        diagnostics.print_diagnostics(verbose=verbose, check_env=check_env)

        # If fix flag is set, attempt to fix common issues
        if fix:
            console.print("\n[bold cyan]Attempting to fix common issues...[/bold cyan]")
            diag_results = diagnostics.run_diagnostics()
            fixed = diagnostics.fix_common_issues(diag_results)

            if fixed:
                console.print("\n[bold green]Fixed Issues:[/bold green]")
                for i, fix_msg in enumerate(fixed, 1):
                    console.print(f"{i}. {fix_msg}")
            else:
                console.print("\n[yellow]No automatic fixes were applied.[/yellow]")

            # Suggest manual fixes
            suggested_fixes = diagnostics.suggest_fixes(diag_results)
            if suggested_fixes:
                console.print("\n[bold yellow]Suggested Manual Fixes:[/bold yellow]")
                for i, fix_msg in enumerate(suggested_fixes, 1):
                    console.print(f"{i}. {fix_msg}")

    except Exception as e:
        console.print(f"[red]Error running diagnostics: {str(e)}[/red]")
        raise typer.Exit(1)


@app.command(help="Generate multiple images in a batch with configurable settings")
def loop(
    batch_size: int = typer.Option(
        5, "--batch-size", "-b", help="Number of images to generate per run", min=1, max=100
    ),
    interval: Optional[int] = typer.Option(
        None, "--interval", "-n", help="Interval in seconds between generations", min=0
    ),
    mock: bool = typer.Option(
        False,
        "--mock",
        help="Use mock image generator (no GPU required, generates placeholder images)",
    ),
    mps_use_fp16: bool = typer.Option(
        False,
        "--mps-use-fp16",
        help="Use float16 precision on Apple Silicon (may improve performance)",
    ),
) -> None:
    """Generate a batch of images with unique prompts."""

    async def _loop() -> None:
        try:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                MofNCompleteColumn(),
                TimeElapsedColumn(),
                console=console,
                transient=True,  # Hide finished tasks
            ) as progress:
                try:
                    # Update config with CLI options
                    app.state.config.system.mps_use_fp16 = mps_use_fp16

                    # Initialize components
                    init_task = progress.add_task("[cyan]Initializing models...", total=None)
                    prompt_gen = PromptGenerator(app.state.config)
                    if mock:
                        console.print(
                            "[yellow]Using mock image generator (no GPU required)[/yellow]"
                        )
                    # Use factory to create image generator
                    image_gen = get_image_generator(app.state.config, mock=mock)
                    storage = StorageManager()
                    metrics = MetricsCollector(app.state.config.system.log_dir / "metrics")
                    progress.remove_task(init_task)

                    # Start metrics collection
                    metrics.start_batch()

                    console.print(
                        f"\n[bold]Starting batch generation of {batch_size} images...[/bold]"
                    )

                    batch_task = progress.add_task("[cyan]Generating images", total=batch_size)

                    for i in range(batch_size):
                        try:
                            # Generate prompt
                            prompt = await prompt_gen.generate_prompt()
                            console.print(
                                Panel(
                                    f"[bold]Generated prompt for image {i+1}:[/bold]\n\n{prompt}",
                                    title=f"Prompt {i+1}/{batch_size}",
                                    border_style="blue",
                                )
                            )

                            # Get output path and generate
                            output_path = storage.get_output_path(prompt)
                            force_reinit = i > 0 and i % 5 == 0  # Reinit every 5 images
                            output_path, gen_time, model_name = await image_gen.generate_image(
                                prompt, output_path, force_reinit=force_reinit
                            )

                            console.print(
                                f"[green]✓[/green] Image {i+1} generated in {gen_time:.1f}s using {model_name}\n"
                                f"   📁 {output_path}"
                            )

                            progress.update(batch_task, advance=1)

                            # Always wait at least 1 second between generations
                            wait_time = max(1, interval or 0)
                            if i < batch_size - 1:
                                await asyncio.sleep(wait_time)

                        except Exception as e:
                            console.print(f"[red]Error generating image {i+1}: {str(e)}[/red]")
                            if i < batch_size - 1:
                                console.print("[yellow]Attempting recovery...[/yellow]")
                                await asyncio.sleep(2)  # Wait for cleanup
                                console.print("[yellow]Continuing with next image...[/yellow]")
                                continue
                            raise

                    # End metrics collection and show summary
                    metrics.end_batch()
                    perf_metrics = metrics.get_performance_metrics()

                    console.print(
                        Panel(
                            f"[bold green]Batch generation complete![/bold green]\n"
                            f"Successfully created {batch_size} images using {model_name}\n\n"
                            f"[dim]Performance Metrics:\n"
                            f"Average Generation Time: {perf_metrics.get('avg_generation_time', 0):.1f}s\n"
                            f"Average GPU Memory: {perf_metrics.get('avg_gpu_memory', 0):.1f} GB\n"
                            f"Success Rate: {perf_metrics.get('success_rate', 0)*100:.1f}%[/dim]",
                            title="Success",
                            border_style="green",
                        )
                    )

                    # Final cleanup
                    prompt_gen.cleanup()
                    image_gen.cleanup()

                except Exception as e:
                    console.print(f"[red]Error: {str(e)}[/red]")
                    raise
        except Exception as e:
            console.print(f"[red]Error: {str(e)}[/red]")
            raise typer.Exit(1)

    try:
        asyncio.run(_loop())
    except KeyboardInterrupt:
        console.print("\n[yellow]Operation cancelled by user[/yellow]")
        raise typer.Exit(0)
    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]", err=True)
        raise typer.Exit(1)
