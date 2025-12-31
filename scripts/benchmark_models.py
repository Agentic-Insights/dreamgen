#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "torch",
#     "loguru",
#     "rich",
#     "python-dotenv",
# ]
# ///
"""
Benchmark script for comparing FLUX vs Z-Image generation performance.

Usage:
    uv run scripts/benchmark_models.py
    uv run scripts/benchmark_models.py --models zimage
    uv run scripts/benchmark_models.py --iterations 5 --warmup 2
"""

import argparse
import gc
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import torch
from rich.console import Console
from rich.table import Table

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

console = Console()


@dataclass
class BenchmarkResult:
    """Results from a single benchmark run."""

    model: str
    iteration: int
    generation_time: float
    peak_vram_gb: float
    seed: int


@dataclass
class BenchmarkSummary:
    """Summary statistics for a model."""

    model: str
    avg_time: float
    min_time: float
    max_time: float
    std_dev: float
    avg_vram_gb: float
    peak_vram_gb: float
    iterations: int


def get_vram_usage() -> float:
    """Get current VRAM usage in GB."""
    if torch.cuda.is_available():
        return torch.cuda.max_memory_allocated() / (1024**3)
    return 0.0


def reset_vram_stats():
    """Reset VRAM tracking statistics."""
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()
        torch.cuda.empty_cache()
        gc.collect()


def benchmark_flux(config, prompt: str, seed: int) -> tuple[float, float]:
    """Benchmark FLUX generation."""
    from src.generators.image_generator import ImageGenerator

    gen = ImageGenerator(config)
    gen.load_model()

    reset_vram_stats()
    start = time.perf_counter()

    # Generate image synchronously for benchmarking
    import asyncio

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(gen.generate_image(prompt, Path("/tmp/benchmark_flux.png")))
    finally:
        loop.close()

    elapsed = time.perf_counter() - start
    vram = get_vram_usage()

    gen.cleanup()
    return elapsed, vram


def benchmark_zimage(config, prompt: str, seed: int) -> tuple[float, float]:
    """Benchmark Z-Image generation."""
    from src.generators.zimage_generator import ZImageGenerator

    gen = ZImageGenerator(config)
    gen.load_model()

    reset_vram_stats()
    start = time.perf_counter()

    # Generate image synchronously for benchmarking
    import asyncio

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(gen.generate(prompt, seed=seed))
    finally:
        loop.close()

    elapsed = time.perf_counter() - start
    vram = get_vram_usage()

    gen.cleanup()
    return elapsed, vram


def run_benchmark(
    models: list[str],
    iterations: int = 3,
    warmup: int = 1,
    prompt: Optional[str] = None,
) -> dict[str, BenchmarkSummary]:
    """Run benchmarks for specified models."""
    from src.utils.config import Config

    config = Config()

    if prompt is None:
        prompt = (
            "A majestic snow leopard resting on a rocky mountain ledge at sunset, "
            "photorealistic, detailed fur, golden hour lighting"
        )

    results: dict[str, list[BenchmarkResult]] = {m: [] for m in models}

    for model in models:
        console.print(f"\n[bold cyan]Benchmarking {model.upper()}[/bold cyan]")

        # Update config for model
        config.model.image_model = model

        # Determine benchmark function
        if model == "flux":
            bench_fn = benchmark_flux
        elif model == "zimage":
            bench_fn = benchmark_zimage
        else:
            console.print(f"[red]Unknown model: {model}[/red]")
            continue

        # Warmup runs
        if warmup > 0:
            console.print(f"  Warming up ({warmup} iterations)...")
            for i in range(warmup):
                try:
                    bench_fn(config, prompt, seed=42 + i)
                    console.print(f"    Warmup {i + 1}/{warmup} complete")
                except Exception as e:
                    console.print(f"[red]    Warmup failed: {e}[/red]")
                    break

        # Benchmark runs
        console.print(f"  Running benchmark ({iterations} iterations)...")
        for i in range(iterations):
            seed = 1000 + i
            try:
                elapsed, vram = bench_fn(config, prompt, seed)
                result = BenchmarkResult(
                    model=model,
                    iteration=i + 1,
                    generation_time=elapsed,
                    peak_vram_gb=vram,
                    seed=seed,
                )
                results[model].append(result)
                console.print(
                    f"    Iteration {i + 1}/{iterations}: {elapsed:.2f}s, VRAM: {vram:.2f}GB"
                )
            except Exception as e:
                console.print(f"[red]    Iteration {i + 1} failed: {e}[/red]")

    # Calculate summaries
    summaries = {}
    for model, model_results in results.items():
        if not model_results:
            continue

        times = [r.generation_time for r in model_results]
        vrams = [r.peak_vram_gb for r in model_results]

        summaries[model] = BenchmarkSummary(
            model=model,
            avg_time=statistics.mean(times),
            min_time=min(times),
            max_time=max(times),
            std_dev=statistics.stdev(times) if len(times) > 1 else 0.0,
            avg_vram_gb=statistics.mean(vrams),
            peak_vram_gb=max(vrams),
            iterations=len(model_results),
        )

    return summaries


def print_results(summaries: dict[str, BenchmarkSummary]):
    """Print benchmark results in a nice table."""
    console.print("\n[bold green]Benchmark Results[/bold green]\n")

    table = Table(title="Model Performance Comparison")
    table.add_column("Model", style="cyan")
    table.add_column("Avg Time (s)", justify="right")
    table.add_column("Min Time (s)", justify="right")
    table.add_column("Max Time (s)", justify="right")
    table.add_column("Std Dev", justify="right")
    table.add_column("Avg VRAM (GB)", justify="right")
    table.add_column("Peak VRAM (GB)", justify="right")
    table.add_column("Iterations", justify="right")

    for model, summary in summaries.items():
        table.add_row(
            model.upper(),
            f"{summary.avg_time:.2f}",
            f"{summary.min_time:.2f}",
            f"{summary.max_time:.2f}",
            f"{summary.std_dev:.2f}",
            f"{summary.avg_vram_gb:.2f}",
            f"{summary.peak_vram_gb:.2f}",
            str(summary.iterations),
        )

    console.print(table)

    # Determine winner
    if len(summaries) > 1:
        fastest = min(summaries.values(), key=lambda s: s.avg_time)
        console.print(f"\n[bold green]Fastest model: {fastest.model.upper()}[/bold green]")

        # Show comparison
        if "flux" in summaries and "zimage" in summaries:
            flux_time = summaries["flux"].avg_time
            zimage_time = summaries["zimage"].avg_time
            diff = abs(flux_time - zimage_time)
            pct = (diff / max(flux_time, zimage_time)) * 100

            if flux_time < zimage_time:
                console.print(f"  FLUX is {diff:.2f}s ({pct:.1f}%) faster than Z-Image")
            else:
                console.print(f"  Z-Image is {diff:.2f}s ({pct:.1f}%) faster than FLUX")

            # Note on Z-Image advantages
            console.print("\n[dim]Note: Z-Image excels at bilingual text rendering (EN/ZH)[/dim]")


def main():
    parser = argparse.ArgumentParser(description="Benchmark image generation models")
    parser.add_argument(
        "--models",
        nargs="+",
        default=["flux", "zimage"],
        choices=["flux", "zimage"],
        help="Models to benchmark (default: both)",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=3,
        help="Number of benchmark iterations per model (default: 3)",
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=1,
        help="Number of warmup iterations (default: 1)",
    )
    parser.add_argument(
        "--prompt",
        type=str,
        default=None,
        help="Custom prompt for benchmarking",
    )

    args = parser.parse_args()

    console.print("[bold]Image Generation Model Benchmark[/bold]")
    console.print(f"Models: {', '.join(args.models)}")
    console.print(f"Iterations: {args.iterations}")
    console.print(f"Warmup: {args.warmup}")

    if not torch.cuda.is_available():
        console.print("[yellow]Warning: CUDA not available, running on CPU[/yellow]")

    try:
        summaries = run_benchmark(
            models=args.models,
            iterations=args.iterations,
            warmup=args.warmup,
            prompt=args.prompt,
        )
        print_results(summaries)
    except Exception as e:
        console.print(f"[red]Benchmark failed: {e}[/red]")
        raise


if __name__ == "__main__":
    main()
