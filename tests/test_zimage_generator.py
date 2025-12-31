"""Tests for Z-Image generator."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import torch

from src.generators.base_generator import GenerationResult
from src.generators.zimage_generator import ZImageGenerator


@pytest.fixture
def mock_config():
    """Create a mock configuration for testing."""
    config = MagicMock()
    config.model.zimage_model = "Tongyi-MAI/Z-Image-Turbo"
    config.model.zimage_attention = "_native_flash"
    config.model.zimage_compile = False
    config.image.height = 1024
    config.image.width = 1024
    config.system.output_dir = Path("/tmp/test_output")
    config.system.cpu_only = False
    return config


@pytest.fixture
def mock_pipe():
    """Create a mock ZImagePipeline."""
    pipe = MagicMock()
    # Mock the __call__ method to return images
    mock_image = MagicMock()
    pipe.return_value.images = [mock_image]
    return pipe


class TestZImageGenerator:
    """Tests for ZImageGenerator class."""

    def test_initialization(self, mock_config):
        """Test generator initialization."""
        gen = ZImageGenerator(mock_config)
        assert gen.model_id == "Tongyi-MAI/Z-Image-Turbo"
        assert gen.attention_backend == "_native_flash"
        assert gen.compile_model is False
        assert gen.pipe is None

    def test_device_selection_cuda(self, mock_config):
        """Test device selection with CUDA available."""
        with patch("torch.cuda.is_available", return_value=True):
            gen = ZImageGenerator(mock_config)
            assert gen.device == "cuda"

    def test_device_selection_cpu_only(self, mock_config):
        """Test device selection with CPU only mode."""
        mock_config.system.cpu_only = True
        gen = ZImageGenerator(mock_config)
        assert gen.device == "cpu"

    def test_load_model(self, mock_config, mock_pipe):
        """Test model loading."""
        # Create a mock ZImagePipeline class
        mock_pipeline_class = MagicMock()
        mock_pipeline_class.from_pretrained.return_value = mock_pipe

        with patch("torch.cuda.is_available", return_value=False):
            # Mock the import of ZImagePipeline
            with patch.dict(
                "sys.modules", {"diffusers": MagicMock(ZImagePipeline=mock_pipeline_class)}
            ):
                gen = ZImageGenerator(mock_config)
                gen.load_model()

                # Verify from_pretrained was called correctly
                mock_pipeline_class.from_pretrained.assert_called_once_with(
                    "Tongyi-MAI/Z-Image-Turbo",
                    torch_dtype=torch.bfloat16,
                    low_cpu_mem_usage=True,
                    use_safetensors=True,
                )

                assert gen.pipe is not None

    @pytest.mark.asyncio
    async def test_generate(self, mock_config, mock_pipe, tmp_path):
        """Test image generation."""
        # Setup
        mock_config.system.output_dir = tmp_path

        # Create a mock PIL Image that actually writes a file when save() is called
        def mock_save(path):
            """Actually create the file when save is called."""
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).touch()

        mock_image = MagicMock()
        mock_image.save = mock_save
        mock_pipe.return_value.images = [mock_image]

        # Create a mock ZImagePipeline class
        mock_pipeline_class = MagicMock()
        mock_pipeline_class.from_pretrained.return_value = mock_pipe

        with patch("torch.cuda.is_available", return_value=False):
            # Mock the import of ZImagePipeline
            with patch.dict(
                "sys.modules", {"diffusers": MagicMock(ZImagePipeline=mock_pipeline_class)}
            ):
                gen = ZImageGenerator(mock_config)
                gen.load_model()

                result = await gen.generate(prompt="Test prompt", height=1024, width=1024, seed=42)

        # Verify result
        assert isinstance(result, GenerationResult)
        assert result.prompt == "Test prompt"
        assert result.model == "zimage"
        assert result.seed == 42
        assert result.steps == 8  # Default for Z-Image Turbo
        assert result.image_path.exists()

    @pytest.mark.asyncio
    async def test_generate_with_negative_prompt_warning(self, mock_config, caplog):
        """Test that negative prompts trigger a warning."""
        with patch("torch.cuda.is_available", return_value=False):
            gen = ZImageGenerator(mock_config)

            # Mock the pipe to avoid actual generation
            gen.pipe = MagicMock()
            mock_image = MagicMock()
            gen.pipe.return_value.images = [mock_image]

            with patch("src.generators.zimage_generator.logger") as mock_logger:
                await gen.generate(prompt="Test", negative_prompt="Don't want this")

                # Verify warning was logged
                mock_logger.warning.assert_called_once()
                assert "doesn't use negative prompts" in str(mock_logger.warning.call_args)

    def test_cleanup(self, mock_config):
        """Test cleanup method."""
        with patch("torch.cuda.is_available", return_value=True):
            gen = ZImageGenerator(mock_config)
            gen.pipe = MagicMock()  # Set a mock pipe

            with patch("torch.cuda.empty_cache") as mock_empty_cache:
                gen.cleanup()

                # Verify cleanup was called
                assert gen.pipe is None
                mock_empty_cache.assert_called()

    def test_get_model_info(self, mock_config):
        """Test getting model information."""
        with patch("torch.cuda.is_available", return_value=True):
            gen = ZImageGenerator(mock_config)
            info = gen.get_model_info()

        assert info["model_name"] == "Z-Image-Turbo"
        assert info["model_id"] == "Tongyi-MAI/Z-Image-Turbo"
        assert info["parameters"] == "6B"
        assert info["architecture"] == "Single-Stream DiT (S3-DiT)"
        assert info["device"] == "cuda"
        # Check features list contains a bilingual text rendering entry
        features_str = " ".join(info["features"])
        assert "Bilingual text rendering" in features_str or "bilingual" in features_str.lower()


class TestZImageGeneratorIntegration:
    """Integration tests for Z-Image generator."""

    @pytest.mark.skipif(not torch.cuda.is_available(), reason="Requires CUDA for integration test")
    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_full_generation_pipeline(self, mock_config, tmp_path):
        """
        Full integration test with real model.

        This test is skipped by default (marked as 'slow').
        Run with: pytest -m slow
        """
        pytest.importorskip("diffusers.ZImagePipeline")

        mock_config.system.output_dir = tmp_path
        gen = ZImageGenerator(mock_config)

        try:
            gen.load_model()
            result = await gen.generate(prompt="A cute cat", seed=42)

            assert result.image_path.exists()
            assert result.image_path.suffix == ".png"
            assert (result.image_path.with_suffix(".txt")).exists()
        finally:
            gen.cleanup()
