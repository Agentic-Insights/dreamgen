#!/usr/bin/env python3
"""
Script to install CUDA-enabled PyTorch for Windows with RTX 4090
"""

import subprocess
import sys

import torch


def check_cuda():
    """Check if CUDA is available"""
    try:
        cuda_available = torch.cuda.is_available()
        if cuda_available:
            device_name = torch.cuda.get_device_name(0)
            torch_version = torch.__version__
            print("✓ CUDA is available")
            print(f"  Device: {device_name}")
            print(f"  PyTorch version: {torch_version}")
            return True
        else:
            print("✗ CUDA is NOT available")
            print(f"  PyTorch version: {torch.__version__}")
            return False
    except Exception as e:
        print(f"Error checking CUDA: {e}")
        return False


def install_cuda_pytorch():
    """Install CUDA-enabled PyTorch"""
    print("Installing CUDA-enabled PyTorch...")

    # Uninstall existing torch packages
    print("Uninstalling existing torch packages...")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "uv",
            "pip",
            "uninstall",
            "torch",
            "torchvision",
            "torchaudio",
        ],
        check=False,
    )

    # Install CUDA version
    print("Installing CUDA 12.4 compatible PyTorch...")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "uv",
            "pip",
            "install",
            "torch",
            "torchvision",
            "torchaudio",
            "--index-url",
            "https://download.pytorch.org/whl/cu124",
            "--force-reinstall",
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print(f"Error installing PyTorch: {result.stderr}")
        return False

    print("PyTorch installation complete!")
    return True


def main():
    print("=== PyTorch CUDA Setup ===\n")

    # Check current status
    print("Current status:")
    cuda_available = check_cuda()

    if not cuda_available:
        print("\nInstalling CUDA-enabled PyTorch...")
        if install_cuda_pytorch():
            print("\n✓ Installation complete!")
            print("\nNew status:")
            check_cuda()
        else:
            print("\n✗ Installation failed!")
            sys.exit(1)
    else:
        print("\n✓ CUDA PyTorch is already installed!")


if __name__ == "__main__":
    main()
