# Project Context

## Workspace Summary

- Current directory is a research/planning workspace, not a runnable product repo yet.
- There is no business implementation code at the workspace root.
- Root content is mainly:
  - `docs/plan.md`: original product/agent architecture draft in Chinese
  - `docs/multi-agent-framework-design.md`: refined framework design, agent boundaries, and schema recommendations
  - `reference/paper/`: papers used as background material
  - `reference/code/AutoBencher/`: benchmark generation reference implementation
  - `reference/code/yourbench/`: document-to-benchmark generation reference implementation
  - `reference/code/EvalTree/`: capability tree / weakness profiling reference implementation
  - `.vscode/launch.json`: generic Python single-file debug config

## Saved BenchForge Artifacts

- [docs/benchforge-technical-design.md](/Users/zhaoziqing/Desktop/Agent/agent/docs/benchforge-technical-design.md): technical design for the BenchForge architecture, data contracts, agent boundaries, and workflow.
- [docs/superpowers/plans/2026-05-13-benchforge-full-implementation-plan.md](/Users/zhaoziqing/Desktop/Agent/agent/docs/superpowers/plans/2026-05-13-benchforge-full-implementation-plan.md): authoritative task-by-task Claude Code implementation plan for the full external-retrieval-first BenchForge.
- [docs/superpowers/plans/2026-05-13-benchforge-implementation-plan.md](/Users/zhaoziqing/Desktop/Agent/agent/docs/superpowers/plans/2026-05-13-benchforge-implementation-plan.md): earlier local-first MVP plan, now secondary to the full implementation plan above.
- [docs/benchforge-work-summary.md](/Users/zhaoziqing/Desktop/Agent/agent/docs/benchforge-work-summary.md): summary of completed exploration and saved planning results.

## Repository Status

- This directory is currently inside a larger Git repository and appears as an untracked subdirectory from the parent repo.
- Do not assume the workspace root has its own independent Git history.
- There are unrelated modified/deleted files in the parent repository outside this directory; do not touch them unless explicitly asked.

## Technology Stack

## Workspace Level

- Documentation and planning workspace
- Python-oriented references
- PDF papers and local reference code snapshots

## Reference: `reference/code/yourbench`

- Language: Python 3.12
- Packaging: `pyproject.toml` with `setuptools`
- CLI: `typer`
- Config: YAML
- Validation/schema: `pydantic`
- Logging: `loguru`
- Lint/format: `ruff`
- Test framework: `pytest`
- Dependency workflow: `uv` is the recommended installer/runner

## Reference: `reference/code/AutoBencher`

- Language: Python
- Dependency management: `requirements.txt`
- LLM-related dependencies include `openai`, `anthropic`, `pyautogen`, `transformers`, `torch`
- Style/test tooling is not defined in the snapshot

## Reference: `reference/code/EvalTree`

- Language: Python
- Dependency management: `requirements.txt`
- Experiment orchestration: shell scripts plus `python -m ...`
- Focus: capability annotation, embedding, recursive clustering, weakness profiling
- Style/test tooling is not declared in the inspected files

## Directory Structure

```text
.
├── AGENTS.md
├── .vscode/
│   └── launch.json
├── docs/
│   ├── multi-agent-framework-design.md
│   └── plan.md
└── reference/
    ├── paper/
    │   ├── BenchAgents.pdf
    │   ├── autobencher.pdf
    │   ├── evaltree.pdf
    │   └── yourbench.pdf
    └── code/
        ├── AutoBencher/
        ├── EvalTree/
        └── yourbench/
```

## Core Entrypoints

## Workspace Root

- There is no application entrypoint at the root.
- The project definition currently lives in `docs/plan.md`.
- The refined architecture proposal currently lives in `docs/multi-agent-framework-design.md`.
- The target multi-agent evaluation framework is still not implemented in this workspace.

## `reference/code/yourbench`

- Main CLI module: `yourbench.main:main`
- Module entry: `reference/code/yourbench/yourbench/__main__.py`
- Primary command:
  - `yourbench run <config.yaml>`
- Config loading:
  - `reference/code/yourbench/yourbench/conf/loader.py`
- Pipeline orchestration:
  - `reference/code/yourbench/yourbench/pipeline/handler.py`

## `reference/code/AutoBencher`

- Primary launcher script: `reference/code/AutoBencher/run_scripts.py`
- Main modes:
  - `wiki`
  - `multilingual`
  - `math`
- Underlying task scripts:
  - `wiki_autobencher.py`
  - `multilingual_autobencher.py`
  - `math_autobencher.py`

## `reference/code/EvalTree`

- No single top-level CLI found.
- The repo is driven by staged shell scripts and `python -m` invocations.
- Main stage families:
  - `EvalTree/stage1-CapabilityAnnotation`
  - `EvalTree/stage2-CapabilityEmbedding`
  - `EvalTree/stage3-RecursiveClustering`
  - `EvalTree/stage4-CapabilityDescription`
  - `EvalTree/WeaknessProfile`
  - `Assessments/LowPerformance`
  - `Assessments/Synthetic`
  - `Assessments/Extrinsic`

## Run Commands

## Workspace Root

- No root run command exists yet.
- Treat the root as planning/reference-only unless implementation is added later.

## `reference/code/yourbench`

- Recommended direct run:
  - `cd reference/code/yourbench`
  - `uvx --from yourbench yourbench run example/default_example/config.yaml --debug`
- From installed/local source:
  - `uv pip install yourbench`
  - `yourbench run example/default_example/config.yaml`
- From source editable install:
  - `pip install -e .`
  - `yourbench run example/default_example/config.yaml`

## `reference/code/AutoBencher`

- Install:
  - `cd reference/code/AutoBencher`
  - `pip install -r requirements.txt`
- Run predefined experiments:
  - `python run_scripts.py wiki`
  - `python run_scripts.py multilingual`
  - `python run_scripts.py math`
- Note: the checked-in launcher hardcodes cache paths, model names, and output prefixes for the original environment.

## `reference/code/EvalTree`

- Install:
  - `cd reference/code/EvalTree`
  - `pip install -r requirements.txt`
- Typical staged runs from README:
  - `bash EvalTree/stage1-CapabilityAnnotation/annotate.sh`
  - `bash EvalTree/stage2-CapabilityEmbedding/embedding.sh`
  - `bash EvalTree/stage3-RecursiveClustering/build.sh`
  - `bash EvalTree/stage4-CapabilityDescription/describe.sh`
  - `bash Assessments/LowPerformance/run.sh`
  - `bash Assessments/Synthetic/run.sh`

## Test Commands

## Workspace Root

- No root test suite exists.

## `reference/code/yourbench`

- Unit/integration tests exist under `tests/unit` and `tests/integration`.
- Likely commands:
  - `cd reference/code/yourbench`
  - `pytest`
  - `pytest tests/unit`
  - `pytest tests/integration`

## `reference/code/AutoBencher`

- No formal tests were found in the inspected snapshot.

## `reference/code/EvalTree`

- No formal tests were found in the inspected snapshot.
- Validation is experiment/script-driven rather than test-suite-driven.

## Code Style And Conventions

## `reference/code/yourbench`

- Formatting/linting is defined in `pyproject.toml` and `Makefile`.
- Ruff line length: `119`
- Formatting style:
  - double quotes
  - space indentation
- Make targets:
  - `make style file=<path>`
  - `make check file=<path>`
  - `make all`
  - `make quality`
- Important config behavior:
  - pipeline stages are enabled by presence in YAML, even without `run: true`
  - model roles are auto-assigned if omitted

## `reference/code/AutoBencher`

- No explicit formatter/linter config found.
- Existing scripts are experimental and rely on direct script execution.

## `reference/code/EvalTree`

- No explicit formatter/linter/test config found in the inspected files.
- Existing workflow is paper-reproduction oriented and script-heavy.

## Environment And Secrets

- `yourbench` expects environment variables such as:
  - `OPENAI_API_KEY`
  - optionally `OPENAI_BASE_URL`
  - `HF_TOKEN`
  - optionally `HF_ORGANIZATION`
- `EvalTree` README also expects:
  - `OPENAI_API_KEY`
  - `HF_TOKEN`
- `AutoBencher` is LLM/API dependent as well, but the snapshot does not provide a normalized `.env` contract.

## Important Notes And Risks

- There is no root application code yet; any future implementation work should start by creating a real source layout rather than modifying the reference repos directly.
- The current planning state already includes a refined architecture document; new implementation should follow `docs/multi-agent-framework-design.md` instead of relying only on the earlier high-level draft in `docs/plan.md`.
- The three reference projects are snapshots of external work and should be treated as reference material unless explicitly vendored/adapted.
- `AutoBencher` contains environment-specific hardcoded paths and model settings from its original authors' environment.
- `EvalTree` contains large precomputed datasets/results and a nested `.git` directory inside `reference/code/EvalTree/`.
- Because this workspace currently has no root package, no root dependency manifest, and no root tests, new implementation work should first define:
  - source directory layout
  - dependency manager
  - runnable entrypoints
  - test strategy

## Recommended Working Approach

- Use `docs/plan.md` as the original intent and problem statement.
- Use `docs/multi-agent-framework-design.md` as the current source of truth for architecture, agent responsibilities, and the `Blueprint` / `TaskSpec` / `TaskResult` schema direction.
- Use `yourbench` as the main reference for document ingestion, chunking, question generation, and dataset packaging.
- Use `AutoBencher` as a reference for iterative topic expansion and evaluation-loop ideas, not as drop-in production code.
- Use `EvalTree` as the main reference for capability labeling, capability trees, and weakness-profile analysis.
- Avoid editing files under `reference/` unless the task is specifically to study or adapt those snapshots.
