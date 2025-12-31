# Z-Image Integration Plan for DreamGen

## Executive Summary

Integrating Z-Image-Turbo as an alternative model option for DreamGen, alongside existing FLUX support. Z-Image offers competitive performance (#1 open-source model on Artificial Analysis leaderboard) with efficient 8-step inference and bilingual text rendering.

## Z-Image Overview

### Key Characteristics

- **Model Size**: 6B parameters (comparable to FLUX)
- **Architecture**: Scalable Single-Stream DiT (S3-DiT)
- **Inference Speed**: Sub-second on H800, fits in 16GB VRAM
- **Inference Steps**: 8 NFEs (Number of Function Evaluations)
- **Guidance Scale**: 0.0 (for Turbo variant)
- **Strengths**:
  - Photorealistic generation
  - Bilingual text rendering (English + Chinese)
  - Strong instruction following
  - Efficient single-stream architecture

### Variants

1. **Z-Image-Turbo** ✅ (Available, priority for integration)
2. **Z-Image-Base** (To be released)
3. **Z-Image-Edit** (To be released, image-to-image)

## Integration Approaches

### Option 1: Diffusers-Based Integration (RECOMMENDED)

**Pros:**
- ✅ Consistent with existing FLUX implementation
- ✅ Uses familiar `diffusers` API
- ✅ Minimal code changes needed
- ✅ Easier maintenance and upgrades

**Cons:**
- ⚠️ Requires diffusers from source (ZImagePipeline not in stable)
- ⚠️ Dependency on upstream changes

**Implementation:**
```python
from diffusers import ZImagePipeline

pipe = ZImagePipeline.from_pretrained(
    "Tongyi-MAI/Z-Image-Turbo",
    torch_dtype=torch.bfloat16
)
```

### Option 2: Native PyTorch Implementation

**Pros:**
- ✅ Maximum control over pipeline
- ✅ No dependency on diffusers source
- ✅ Can optimize for specific use cases
- ✅ Access to latest features directly from Z-Image repo

**Cons:**
- ❌ Significant code duplication
- ❌ More maintenance burden
- ❌ Have to track Z-Image updates manually
- ❌ Inconsistent with existing generator pattern

**Implementation:**
- Copy Z-Image source code into DreamGen
- Vendor the implementation
- Maintain custom pipeline

### Option 3: Hybrid Approach

**Pros:**
- ✅ Flexibility to choose based on availability
- ✅ Fallback mechanism
- ✅ Can use native for advanced features

**Cons:**
- ❌ Complex codebase
- ❌ Two implementations to maintain
- ❌ Configuration complexity

## Recommended Approach: Option 1 (Diffusers-Based)

**Rationale:**
1. Maintains consistency with existing FLUX implementation
2. Leverages established `diffusers` ecosystem
3. Minimal code changes to existing generator pattern
4. Clear upgrade path when ZImagePipeline hits stable

**Dependencies Required:**
```bash
# Install diffusers from source for ZImagePipeline
pip install git+https://github.com/huggingface/diffusers

# OR specify in pyproject.toml
diffusers @ git+https://github.com/huggingface/diffusers.git
```

## Architecture Changes

### Current DreamGen Structure

```
src/generators/
├── image_generator.py      # FLUX generator
├── prompt_generator.py     # Ollama-based prompt enhancement
└── mock_image_generator.py # Mock for testing
```

### Proposed Structure

```
src/generators/
├── image_generator.py      # Base class + FLUX
├── zimage_generator.py     # NEW: Z-Image generator
├── prompt_generator.py     # Ollama-based (shared)
└── mock_image_generator.py # Mock (shared)
```

### Configuration Changes

**Current `.env`:**
```bash
FLUX_MODEL=black-forest-labs/FLUX.1-schnell
```

**Proposed Addition:**
```bash
# Model selection
IMAGE_MODEL=flux  # Options: flux, zimage
FLUX_MODEL=black-forest-labs/FLUX.1-schnell
ZIMAGE_MODEL=Tongyi-MAI/Z-Image-Turbo

# Z-Image specific settings
ZIMAGE_ATTENTION=_native_flash  # Options: _native_flash, _flash_3, _sdpa
ZIMAGE_COMPILE=false  # True for sub-second on H100/H800
```

## Implementation Plan

### Phase 1: Core Integration (Week 1)

**Tasks:**
1. ✅ Create `src/generators/zimage_generator.py`
2. ✅ Add `IMAGE_MODEL` configuration to `config.py`
3. ✅ Update `pyproject.toml` with diffusers source dependency
4. ✅ Create factory pattern in `src/main.py` for model selection
5. ✅ Add Z-Image tests to test suite

**Deliverables:**
- Working Z-Image generator
- CLI flag: `dreamgen generate --model zimage`
- Configuration system update

### Phase 2: Optimization & Features (Week 2)

**Tasks:**
1. Add compilation support (for H100/H800)
2. Implement attention backend selection
3. Add memory optimization (CPU offloading)
4. Create performance benchmarks (FLUX vs Z-Image)
5. Update documentation

**Deliverables:**
- Optimized generator with multiple backends
- Performance comparison guide
- Updated CLAUDE.md

### Phase 3: Plugin System Integration (Week 3)

**Tasks:**
1. Test all plugins with Z-Image
2. Verify prompt enhancement compatibility
3. Test LoRA support (if applicable)
4. Validate art styles plugin
5. End-to-end integration testing

**Deliverables:**
- Full plugin compatibility
- Integration tests
- User guide

### Phase 4: Production Readiness (Week 4)

**Tasks:**
1. Add model auto-detection and fallback
2. Create migration guide for existing users
3. Update API server for model selection
4. Add web UI model switcher
5. Documentation and examples

**Deliverables:**
- Production-ready Z-Image support
- Web UI integration
- Complete documentation

## Technical Considerations

### Memory Management

**Z-Image Requirements:**
- **Minimum**: 16GB VRAM (Turbo on consumer GPUs)
- **Optimal**: H100/H800 for sub-second inference
- **bfloat16**: Recommended dtype (vs float16 in FLUX)

**Strategy:**
- Use same GPU memory management as FLUX
- Clear cache between generations
- Support CPU offloading for <16GB systems

### Performance Expectations

**Z-Image-Turbo (8 steps):**
- **H800**: Sub-second (<1s)
- **RTX 4090**: ~3-5 seconds (estimated)
- **16GB VRAM**: Supported

**FLUX.1-schnell (4 steps):**
- **RTX 4090**: ~2-3 seconds

### Compatibility Matrix

| Feature | FLUX | Z-Image | Notes |
|---------|------|---------|-------|
| Text-to-Image | ✅ | ✅ | Both supported |
| Image-to-Image | ✅ | 🔜 | Z-Image-Edit (unreleased) |
| LoRA Support | ✅ | ❓ | Need to investigate |
| Prompt Enhancement | ✅ | ✅ | Ollama-based (shared) |
| Bilingual Text | ⚠️ | ✅ | Z-Image excels |
| Commercial Use | ⚠️ | ✅ | Check licenses |

## Code Structure

### Generator Abstract Base

```python
# src/generators/base_generator.py
from abc import ABC, abstractmethod

class ImageGenerator(ABC):
    @abstractmethod
    async def generate(self, prompt: str, **kwargs):
        pass

    @abstractmethod
    def cleanup(self):
        pass
```

### Z-Image Generator

```python
# src/generators/zimage_generator.py
import torch
from diffusers import ZImagePipeline
from .base_generator import ImageGenerator

class ZImageGenerator(ImageGenerator):
    def __init__(self, config):
        self.config = config
        self.pipe = None

    def load_model(self):
        self.pipe = ZImagePipeline.from_pretrained(
            self.config.model.zimage_model,
            torch_dtype=torch.bfloat16,
            low_cpu_mem_usage=True
        )
        self.pipe.to("cuda")

    async def generate(self, prompt: str, **kwargs):
        images = self.pipe(
            prompt=prompt,
            height=kwargs.get("height", 1024),
            width=kwargs.get("width", 1024),
            num_inference_steps=kwargs.get("steps", 8),
            guidance_scale=0.0,  # Fixed for Turbo
            generator=torch.Generator("cuda").manual_seed(kwargs.get("seed", 42))
        ).images
        return images[0]
```

### Factory Pattern

```python
# src/main.py
def get_generator(config):
    if config.model.image_model == "zimage":
        from generators.zimage_generator import ZImageGenerator
        return ZImageGenerator(config)
    else:
        from generators.image_generator import FluxImageGenerator
        return FluxImageGenerator(config)
```

## Testing Strategy

### Unit Tests

```python
# tests/test_zimage_generator.py
@pytest.mark.asyncio
async def test_zimage_generation():
    generator = ZImageGenerator(mock_config)
    result = await generator.generate("test prompt")
    assert result is not None

@pytest.mark.asyncio
async def test_zimage_chinese_text():
    generator = ZImageGenerator(mock_config)
    result = await generator.generate("测试提示")
    assert result is not None
```

### Integration Tests

- End-to-end generation with plugins
- Plugin compatibility validation
- Memory leak detection
- Performance benchmarks

### Benchmark Suite

```bash
# Compare FLUX vs Z-Image
just benchmark-models

# Output:
# FLUX.1-schnell: 2.3s (4 steps)
# Z-Image-Turbo: 3.8s (8 steps)
# Winner: FLUX (speed)
# Z-Image advantage: Bilingual text
```

## Migration Path

### For Existing Users

1. **Update dependencies**: `uv sync`
2. **Add to .env**: `IMAGE_MODEL=flux` (default, no change)
3. **Try Z-Image**: `IMAGE_MODEL=zimage` or `dreamgen generate --model zimage`
4. **Choose default**: Set `IMAGE_MODEL` in `.env`

### Backward Compatibility

- ✅ Default to FLUX if `IMAGE_MODEL` not set
- ✅ Existing configs continue to work
- ✅ No breaking changes

## Risks & Mitigation

| Risk | Impact | Mitigation |
|------|--------|------------|
| Diffusers source dependency unstable | High | Pin to working commit, vendor if needed |
| ZImagePipeline API changes | Medium | Version lock, add tests |
| Performance worse than FLUX | Low | Make optional, document tradeoffs |
| VRAM requirements too high | Medium | Add CPU offloading, clear docs |
| LoRA incompatibility | Low | Document, add to future roadmap |

## Success Criteria

1. ✅ Z-Image generates images with same quality as demo
2. ✅ All existing plugins work with Z-Image
3. ✅ Performance within 2x of FLUX
4. ✅ Memory usage ≤ 16GB VRAM
5. ✅ Documentation complete and accurate
6. ✅ Tests passing at >80% coverage
7. ✅ Users can switch models seamlessly

## Timeline

- **Week 1**: Core integration + CLI
- **Week 2**: Optimization + benchmarks
- **Week 3**: Plugin validation + testing
- **Week 4**: Web UI + documentation
- **Total**: 4 weeks to production

## Open Questions

1. **LoRA Support**: Does Z-Image support LoRA? Need to investigate.
2. **License**: Confirm commercial use is allowed (appears open-source).
3. **Future Models**: When Z-Image-Base and Z-Image-Edit are released, integration strategy?
4. **Prompt Enhancer**: Z-Image has built-in prompt enhancer - integrate or use Ollama?
5. **Performance**: Actual RTX 4090 benchmarks needed.

## Next Steps

1. ✅ Create this design doc
2. ⏭️ Implement Phase 1 (core integration)
3. ⏭️ Test on RTX 4090 for performance baseline
4. ⏭️ Create PR with initial implementation
5. ⏭️ Gather user feedback

## Resources

- [Z-Image GitHub](https://github.com/Tongyi-MAI/Z-Image)
- [Z-Image HuggingFace](https://huggingface.co/Tongyi-MAI/Z-Image-Turbo)
- [Artificial Analysis Leaderboard](https://artificialanalysis.ai/image/leaderboard/text-to-image)
- [Z-Image Paper](https://arxiv.org/abs/2511.22699)

---

**Status**: 📋 Planning Phase
**Branch**: `feat/z-image-integration`
**Lead**: AI Assistant
**Last Updated**: 2025-12-22
