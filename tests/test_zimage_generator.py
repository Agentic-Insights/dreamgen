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
    config.model.zimage_model_path = Path("/tmp/fake_zimage_model")
    config.model.zimage_attention = "_sdpa"
    config.model.zimage_compile = False
    config.image.height = 1024
    config.image.width = 1024
    config.system.output_dir = Path("/tmp/test_output")
    config.system.cpu_only = False
    return config


class TestZImageGenerator:
    """Tests for ZImageGenerator class."""

    def test_initialization(self, mock_config):
        """Test generator initialization."""
        gen = ZImageGenerator(mock_config)
        assert gen.model_path == Path("/tmp/fake_zimage_model")
        assert gen.attention_backend == "_sdpa"
        assert gen.compile_model is False
        assert gen.components is None

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

    def test_zimage_src_path_not_found(self, mock_config):
        """Test error when Z-Image source not found."""
        gen = ZImageGenerator(mock_config)
        # Mock the path check to simulate missing Z-Image repo
        with patch.object(Path, "exists", return_value=False):
            with pytest.raises(ImportError) as exc_info:
                gen._get_zimage_src_path()
            assert "Z-Image source not found" in str(exc_info.value)

    def test_cleanup(self, mock_config):
        """Test cleanup method."""
        with patch("torch.cuda.is_available", return_value=True):
            gen = ZImageGenerator(mock_config)
            # Set mock components
            gen.components = {
                "transformer": MagicMock(),
                "vae": MagicMock(),
                "text_encoder": MagicMock(),
                "tokenizer": MagicMock(),
                "scheduler": MagicMock(),
            }

            with patch("torch.cuda.empty_cache") as mock_empty_cache:
                gen.cleanup()

                # Verify cleanup was called
                assert gen.components is None
                mock_empty_cache.assert_called()

    def test_get_model_info(self, mock_config):
        """Test getting model information."""
        with patch("torch.cuda.is_available", return_value=True):
            gen = ZImageGenerator(mock_config)
            info = gen.get_model_info()

        assert info["model_name"] == "Z-Image-Turbo"
        assert info["model_path"] == "/tmp/fake_zimage_model"
        assert info["parameters"] == "6B"
        assert info["architecture"] == "Single-Stream DiT (S3-DiT)"
        assert info["device"] == "cuda"
        # Check features list contains a bilingual text rendering entry
        features_str = " ".join(info["features"])
        assert "Bilingual text rendering" in features_str or "bilingual" in features_str.lower()


class TestZImageGeneratorWithMockZImage:
    """Tests that mock the Z-Image native API."""

    @pytest.fixture
    def mock_zimage_components(self):
        """Create mock Z-Image components."""
        return {
            "transformer": MagicMock(),
            "vae": MagicMock(),
            "text_encoder": MagicMock(),
            "tokenizer": MagicMock(),
            "scheduler": MagicMock(),
        }

    @pytest.mark.asyncio
    async def test_generate_with_mocked_api(self, mock_config, mock_zimage_components, tmp_path):
        """Test generation with mocked Z-Image API."""
        mock_config.system.output_dir = tmp_path

        # Create a mock image
        mock_image = MagicMock()

        def mock_save(path):
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).touch()

        mock_image.save = mock_save

        # Mock zimage.generate to return our mock image
        mock_generate = MagicMock(return_value=[mock_image])

        with patch("torch.cuda.is_available", return_value=False):
            gen = ZImageGenerator(mock_config)
            # Pre-set components to skip load_model
            gen.components = mock_zimage_components

            # Mock the Z-Image imports
            with patch.object(gen, "_get_zimage_src_path", return_value=Path("/fake/zimage/src")):
                with patch.dict(
                    "sys.modules",
                    {
                        "zimage": MagicMock(generate=mock_generate),
                    },
                ):
                    result = await gen.generate(
                        prompt="Test prompt", height=1024, width=1024, seed=42
                    )

        assert isinstance(result, GenerationResult)
        assert result.prompt == "Test prompt"
        assert result.model == "zimage"
        assert result.seed == 42
        assert result.steps == 8


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

        Requires:
        - Z-Image repo cloned to ref-repos/Z-Image
        - Z-Image model downloaded to ckpts/Z-Image-Turbo
        """
        # Check if Z-Image is available
        project_root = Path(__file__).parent.parent
        zimage_src = project_root / "ref-repos" / "Z-Image" / "src"
        if not zimage_src.exists():
            pytest.skip("Z-Image repo not cloned to ref-repos/Z-Image")

        model_path = project_root / "ckpts" / "Z-Image-Turbo"
        if not model_path.exists():
            pytest.skip("Z-Image model not downloaded to ckpts/Z-Image-Turbo")

        mock_config.model.zimage_model_path = model_path
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
