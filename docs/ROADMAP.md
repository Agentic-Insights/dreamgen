# ROADMAP.md

## Vision
Transform continuous-image-gen from a standalone CLI tool into a modular image generation service for the orchestr8 platform ecosystem.

## Current State ✅
- Standalone Python CLI application with Ollama + Flux integration
- Plugin system for dynamic prompt / entropy enhancement
- Local-only execution with GPU support (CUDA/MPS)
- **Modern Next.js Web UI with IDE-style interface** (completed - replaced Gradio)
- **FastAPI backend with REST and WebSocket support** (completed)
- Cloudflare Workers integration for image hosting

## Phase 1: Modularization (Next 2 weeks)
### 1.1 Package Restructuring
- [ ] Extract core image generation into `imagegen` package
- [ ] Create clean API interfaces for external consumption
- [ ] Separate CLI from core functionality
- [ ] Add `__init__.py` exports for public API

### 1.2 Service Interface
- [ ] Create `ImageGenService` class with async methods
- [ ] Add configuration injection support
- [ ] Implement proper error boundaries and exceptions
- [ ] Add service health checks and status endpoints

### 1.3 Plugin System Enhancement
- [ ] Make plugin system configurable per-instance
- [ ] Add plugin discovery mechanism
- [ ] Create plugin interface specification
- [ ] Support remote plugin loading

## Phase 2: Integration Preparation (Week 3-4)
### 2.1 API Development
- [x] REST API wrapper using FastAPI - **COMPLETED**
- [x] WebSocket support for real-time generation updates - **COMPLETED**
- [x] Modern Next.js Web UI with IDE-style interface - **COMPLETED**
- [x] Real-time gallery with IndexedDB caching - **COMPLETED**
- [ ] Queue management for batch operations
- [ ] Rate limiting and resource management

### 2.2 Configuration Management
- [ ] Environment-based configuration profiles
- [ ] Multi-tenant configuration support
- [ ] Runtime configuration updates
- [ ] Secrets management integration

### 2.3 Observability
- [ ] OpenTelemetry instrumentation
- [ ] Structured logging with correlation IDs
- [ ] Metrics collection (generation time, success rate)
- [ ] Health and readiness endpoints

## Phase 3: CloudStack Integration (Week 5-6)
### 3.1 Service Deployment
- [x] Dockerfile for containerized deployment - **COMPLETED**
- [ ] Kubernetes manifests (Deployment, Service, ConfigMap)
- [ ] Helm chart for configurable deployment
- [ ] Resource limits and autoscaling configuration
- [ ] Multi-environment support (dev/staging/production)
- [ ] ArgoCD GitOps deployment configuration

### 3.2 Platform Integration
- [ ] Service mesh integration (Istio/Linkerd)
- [ ] Authentication/authorization hooks
- [ ] Event bus integration for async operations
- [ ] Shared storage backend for images

### 3.3 Multi-Service Orchestration
- [ ] Integration with other cloudstack services
- [ ] Workflow engine support (Argo/Temporal)
- [ ] Message queue integration (RabbitMQ/Kafka)
- [ ] Distributed tracing setup

## Phase 4: Production Readiness (Week 7-8)
### 4.1 Performance Optimization
- [ ] Model caching and warm starts
- [ ] GPU resource pooling
- [ ] Batch processing optimization
- [ ] Memory management improvements

### 4.2 Reliability
- [ ] Circuit breaker patterns
- [ ] Retry logic with backoff
- [ ] Graceful degradation
- [ ] Disaster recovery procedures

### 4.3 Documentation
- [ ] API documentation (OpenAPI/Swagger)
- [ ] Integration guide for cloudstack
- [ ] Operations runbook
- [ ] Architecture decision records (ADRs)

## Quick Wins (Start immediately)
1. ~~**Create setup.py/pyproject.toml** for pip installation~~ - **COMPLETED**
2. **Add GitHub Actions** for CI/CD pipeline
3. ~~**Create Docker image** for easy deployment~~ - **COMPLETED**
4. **Write integration tests** for service interfaces
5. **Document API contracts** in OpenAPI format

## Success Metrics
- Module can be imported and used by external Python projects
- Service handles 100+ concurrent generation requests
- 99.9% uptime in production environment
- Sub-5 second generation time for standard requests
- Seamless integration with 3+ cloudstack services

## Technical Debt to Address
- [ ] Add comprehensive test coverage (target 80%)
- [ ] Implement proper async context managers
- [ ] Standardize error handling across modules
- [ ] Add type hints throughout codebase
- [ ] Create abstraction layer for model backends

## Dependencies
- FastAPI for API layer
- Pydantic for data validation
- OpenTelemetry for observability
- Redis for caching/queuing
- PostgreSQL for metadata storage
