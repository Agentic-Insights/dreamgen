# CHANGELOG

<!-- version list -->

## v1.1.6 (2026-04-26)

### Bug Fixes

- Make PyPI install resolve
  ([`bee31e0`](https://github.com/Agentic-Insights/dreamgen/commit/bee31e01493925494da6f3df7c4b23a448a8667c))


## v1.1.5 (2026-04-22)

### Bug Fixes

- Stop homepage gallery polling loop ([#16](https://github.com/Agentic-Insights/dreamgen/pull/16),
  [`b8c6c46`](https://github.com/Agentic-Insights/dreamgen/commit/b8c6c4666253aebb76d75fb476bc73370bf613b7))


## v1.1.4 (2026-04-22)

### Bug Fixes

- Invalidate stale empty gallery cache ([#15](https://github.com/Agentic-Insights/dreamgen/pull/15),
  [`22c77f1`](https://github.com/Agentic-Insights/dreamgen/commit/22c77f11b4002d33c942c791876487e5ea1c36b0))


## v1.1.3 (2026-04-22)

### Bug Fixes

- Lazy-load optional image backends ([#14](https://github.com/Agentic-Insights/dreamgen/pull/14),
  [`230dd18`](https://github.com/Agentic-Insights/dreamgen/commit/230dd18e872daaae36b14ceba85dcca395e1f9e4))


## v1.1.2 (2026-04-22)

### Bug Fixes

- Harden gallery against placeholder test artifacts
  ([#13](https://github.com/Agentic-Insights/dreamgen/pull/13),
  [`ba20176`](https://github.com/Agentic-Insights/dreamgen/commit/ba20176843709ca9b661cd3c91126b9ad866531d))


## v1.1.1 (2026-03-25)

### Bug Fixes

- **ci**: Guard zimage cuda cleanup
  ([`36ad93e`](https://github.com/Agentic-Insights/dreamgen/commit/36ad93eb08de7c5c95841ccf26b89b0dda2f6ced))


## v1.1.0 (2026-03-25)

### Bug Fixes

- Add CORS for Docker dev port and use configurable API base URL
  ([`d56ae32`](https://github.com/Agentic-Insights/dreamgen/commit/d56ae3246d761aae6b1b226430ff9f8b8202b2a3))

- Docker setup with unique ports and proper config
  ([`d61529b`](https://github.com/Agentic-Insights/dreamgen/commit/d61529b2d93ca61d96c178f83df58af718d1e019))

- Exclude tsconfig.json from JSON syntax check (JSONC with comments)
  ([#9](https://github.com/Agentic-Insights/dreamgen/pull/9),
  [`c497312`](https://github.com/Agentic-Insights/dreamgen/commit/c4973120d53cbb3efd5c0c64e61f7970dfc7f282))

- Make API server respect USE_MOCK_GENERATOR environment variable
  ([`65fcd90`](https://github.com/Agentic-Insights/dreamgen/commit/65fcd90e24c7d7834d4b0498904699eddc9811fa))

- Make plugin configuration optional in Config class
  ([`a648628`](https://github.com/Agentic-Insights/dreamgen/commit/a64862804ff9b16d91c92b9c712ed11d956354f9))

- Pin transformers and diffusers versions to resolve Flux model loading
  ([`e6c1d5a`](https://github.com/Agentic-Insights/dreamgen/commit/e6c1d5a43c5c6bd5a466773a5a8392d0b3553343))

- Update frontend API base URL for Docker networking
  ([`63dbb9b`](https://github.com/Agentic-Insights/dreamgen/commit/63dbb9bb316b007738dd68de6ec3b72a2ed07d8e))

- **ci**: Repair release workflow and docs
  ([`1cd8a1a`](https://github.com/Agentic-Insights/dreamgen/commit/1cd8a1a00569da55379d6cd665a60b1773112c73))

- **gallery**: Move caption overlay to top
  ([`a65b74e`](https://github.com/Agentic-Insights/dreamgen/commit/a65b74e5c0993ecfef4f9d7f383f0289109f0864))

- **ui**: Add mobile generate button and enhance cloudflare gallery
  ([#11](https://github.com/Agentic-Insights/dreamgen/pull/11),
  [`9d8bfeb`](https://github.com/Agentic-Insights/dreamgen/commit/9d8bfebce80b8a1fa50ad6a8ada8b427182cefb6))

### Chores

- Clean up unused files and improve gitignore
  ([`c73cdf1`](https://github.com/Agentic-Insights/dreamgen/commit/c73cdf1c53d05032006ba3d3e4081d2c153f3b19))

- Cleanup and add plugin CLI commands
  ([`06ed797`](https://github.com/Agentic-Insights/dreamgen/commit/06ed797ab8cfbebf01016de25356aed3bfcacc95))

- Cleanup unused code and consolidate docs
  ([#9](https://github.com/Agentic-Insights/dreamgen/pull/9),
  [`c497312`](https://github.com/Agentic-Insights/dreamgen/commit/c4973120d53cbb3efd5c0c64e61f7970dfc7f282))

- Remove unused CSO module specification
  ([`d600fe5`](https://github.com/Agentic-Insights/dreamgen/commit/d600fe5ae97ade8211b47e6287b551b7f6160d4a))

- Transfer repo to Agentic-Insights org
  ([#11](https://github.com/Agentic-Insights/dreamgen/pull/11),
  [`9d8bfeb`](https://github.com/Agentic-Insights/dreamgen/commit/9d8bfebce80b8a1fa50ad6a8ada8b427182cefb6))

### Documentation

- Add dev mode setup for local backend + Docker frontend
  ([#11](https://github.com/Agentic-Insights/dreamgen/pull/11),
  [`9d8bfeb`](https://github.com/Agentic-Insights/dreamgen/commit/9d8bfebce80b8a1fa50ad6a8ada8b427182cefb6))

- Add Docker development documentation and helper scripts
  ([`b89ea8f`](https://github.com/Agentic-Insights/dreamgen/commit/b89ea8f699d2de56ea0a6f65c3ac230faa5194c1))

### Features

- Add Cloudflare Pages gallery for free image hosting
  ([`5d3f29a`](https://github.com/Agentic-Insights/dreamgen/commit/5d3f29a66a59b6606ab60430c9a10ccffcb38019))

- Add comprehensive code quality infrastructure
  ([`6451fd4`](https://github.com/Agentic-Insights/dreamgen/commit/6451fd4893314484285ed6f3971a89909089d639))

- Configure Docker for shared AI cache and environment-based settings
  ([`f2d2052`](https://github.com/Agentic-Insights/dreamgen/commit/f2d205228e53cbb8e6d883a27e4c015885cfc885))

- Configure Docker with custom ports and shared AI cache support
  ([`2f9634b`](https://github.com/Agentic-Insights/dreamgen/commit/2f9634b67043ea14f3ce57991e7003fe2d6a5ed9))

- **gallery**: Add caption overlay and metadata display
  ([#11](https://github.com/Agentic-Insights/dreamgen/pull/11),
  [`9d8bfeb`](https://github.com/Agentic-Insights/dreamgen/commit/9d8bfebce80b8a1fa50ad6a8ada8b427182cefb6))

- **z-image**: Phase 1 - Core Z-Image integration (WIP)
  ([#9](https://github.com/Agentic-Insights/dreamgen/pull/9),
  [`c497312`](https://github.com/Agentic-Insights/dreamgen/commit/c4973120d53cbb3efd5c0c64e61f7970dfc7f282))

- **zimage**: Complete Phase 1 - Z-Image model integration
  ([#9](https://github.com/Agentic-Insights/dreamgen/pull/9),
  [`c497312`](https://github.com/Agentic-Insights/dreamgen/commit/c4973120d53cbb3efd5c0c64e61f7970dfc7f282))

- **zimage**: Working Z-Image integration with native API
  ([#9](https://github.com/Agentic-Insights/dreamgen/pull/9),
  [`c497312`](https://github.com/Agentic-Insights/dreamgen/commit/c4973120d53cbb3efd5c0c64e61f7970dfc7f282))

- **zimage**: Z-Image model integration (Phase 1)
  ([#9](https://github.com/Agentic-Insights/dreamgen/pull/9),
  [`c497312`](https://github.com/Agentic-Insights/dreamgen/commit/c4973120d53cbb3efd5c0c64e61f7970dfc7f282))

### Testing

- Add comprehensive API test suite
  ([`a61d762`](https://github.com/Agentic-Insights/dreamgen/commit/a61d7620aaed9f9dbcb18804f085b38f1840b071))


## v1.0.1 (2025-09-01)

### Bug Fixes

- Update PyPI project URL in release workflow
  ([`44fcfd2`](https://github.com/Agentic-Insights/dreamgen/commit/44fcfd243d12d7ee84e8bd602e067a0a4541f63b))

### Chores

- **release**: 1.0.1 [skip ci]\n\n##
  [1.0.1](https://github.com/killerapp/dreamgen/compare/v1.0.0...v1.0.1) (2025-09-01)
  ([`94fd9ea`](https://github.com/Agentic-Insights/dreamgen/commit/94fd9ea0b91591b7d26d74a972a266e0e3c15dd5))


## v1.0.0 (2025-09-01)

- Initial Release
