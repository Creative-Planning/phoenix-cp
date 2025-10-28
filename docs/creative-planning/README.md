# Phoenix Custom Documentation

This directory contains custom documentation for the Arize Phoenix fork maintained for the Creative Planning project. These docs cover our custom evaluations, experiments, and deployment workflows specific to integrating Phoenix with DIFY AI workflows.

## Documentation Overview

### 📊 [Experiments Guide](./experiments-guide.md)
**Audience:** Analysts and workflow owners

Comprehensive guide for running experiments and evaluations on DIFY workflows. Covers:
- Quick start setup and configuration
- Dataset formats (input-only vs. gold answer datasets)
- Running experiments locally and via Docker
- Continuous trace evaluations
- End-to-end workflow with iteration examples
- Troubleshooting and FAQs

**Start here** if you're new to running experiments or need to evaluate your DIFY workflow quality.

---

### 🐳 [Experiments Docker Guide](./experiments-docker.md)
**Audience:** Analysts and developers using Docker Compose

Detailed guide for running experiments using the Docker Compose `experiment-runner` service. Covers:
- Docker architecture and networking
- All usage patterns and commands
- Environment variable configuration
- Network configuration options
- Performance and cost considerations
- Docker-specific troubleshooting

**Use this** when running Phoenix via Docker Compose and need to execute experiments in containers.

---

### 🚀 [Deployment Guide](./deployment.md)
**Audience:** Platform/DevOps engineers

Complete deployment playbook for infrastructure teams. Covers:
- Environment configuration and secrets management
- Eval runner sidecar setup
- Experiment runner configuration
- EC2 deployment workflow with prerequisites
- SSL/HTTPS setup with self-signed certificates
- DIFY trace ingestion configuration
- Post-deployment hardening and operations

**Use this** when deploying Phoenix to EC2 or managing the production infrastructure.

---

### 📖 [DIFY API Reference](./dify-api-reference.md)
**Audience:** Developers integrating with DIFY

API reference documentation for the DIFY Chat App API. Covers:
- Authentication and base URL configuration
- Sending chat messages (blocking and streaming modes)
- Request/response formats
- File upload specifications
- Error codes and handling

**Reference this** when building integrations with DIFY or debugging API calls.

---

## Quick Navigation

### By Task

**I want to...**
- Run my first experiment → [Experiments Guide - Quick Start](./experiments-guide.md#2-quick-start)
- Run experiments in Docker → [Experiments Docker Guide](./experiments-docker.md)
- Deploy Phoenix to EC2 → [Deployment Guide](./deployment.md)
- Understand dataset formats → [Experiments Guide - Dataset Expectations](./experiments-guide.md#3-dataset-expectations)
- Set up continuous evals → [Experiments Guide - Continuous Trace Evals](./experiments-guide.md#5-continuous-trace-evals)
- Debug DIFY API calls → [DIFY API Reference](./dify-api-reference.md)
- Troubleshoot experiments → [Experiments Guide - Troubleshooting](./experiments-guide.md#8-troubleshooting)

### By Role

**Analysts & Workflow Owners:**
1. Start: [Experiments Guide](./experiments-guide.md)
2. Docker setup: [Experiments Docker Guide](./experiments-docker.md)
3. API reference: [DIFY API Reference](./dify-api-reference.md)

**Platform/DevOps Engineers:**
1. Start: [Deployment Guide](./deployment.md)
2. Reference: [Experiments Docker Guide](./experiments-docker.md) for service configuration
3. Reference: [Experiments Guide](./experiments-guide.md) to understand user workflows

---

## Related Documentation

### In This Repository

- `scripts/experiments/README.md` - Detailed script documentation
- `scripts/experiments/QUICKSTART.md` - Quick command reference
- `scripts/experiments/DATASET_FORMATS.md` - Dataset schema examples
- `scripts/experiments/DOCKER_SETUP_SUMMARY.md` - Docker architecture summary

### Upstream Phoenix Documentation

- [Phoenix Docs](https://arize.com/docs/phoenix/)
- [Phoenix Datasets & Experiments](https://arize.com/docs/phoenix/datasets-and-experiments/)
- [Phoenix Evaluations](https://arize.com/docs/phoenix/evaluation/evals)
- [Phoenix GitHub](https://github.com/Arize-ai/phoenix)

### DIFY Documentation

- [DIFY Official Docs](https://docs.dify.ai/)
- [DIFY GitHub](https://github.com/langgenius/dify)

---

## Project Context

This is a fork of [Arize Phoenix](https://github.com/Arize-ai/phoenix) with custom additions for:
- Automated RAG evaluation workflows
- DIFY workflow integration and tracing
- Continuous quality monitoring
- Experiment comparison tooling
- Production deployment scripts

All custom work is maintained on the `gba-poc` branch. See `CLAUDE.md` in the repository root for additional project context and objectives.

---

## Contributing

When adding or updating documentation in this directory:

1. **Maintain audience focus** - Each doc targets specific users (analysts vs. operators)
2. **Update cross-references** - Keep links between docs accurate
3. **Add to this README** - Update the navigation sections when adding new docs
4. **Test examples** - Verify all code examples and commands work
5. **Update dates** - Note significant updates at the top of changed files

---

## Support

For questions or issues:
- Check the troubleshooting sections in the relevant guides
- Review related documentation in `scripts/experiments/`
- Consult upstream Phoenix documentation for core features
- Open issues in the project repository

---

*Last updated: 2025-10-28*
