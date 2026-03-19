# AGENTS.md

## Workspace

- Repository: `D:\project\Axiom-AI-Aimbot`
- Primary entrypoint: `src/main.py`
- Current branch at initialization: `codex/sup-tensorRT`
- Shell environment: PowerShell on Windows

## Current State

- The worktree is dirty and already contains in-progress TensorRT integration changes.
- Do not revert unrelated local modifications unless the user explicitly asks.
- TensorRT runtime support is centered around `src/core/tensorrt_runtime.py`.
- Detection pipeline logic is centered around `src/core/ai_loop.py`.
- Config loading and persistence are centered around `src/core/config.py`.
- Model selection and constraints are handled in `src/core/model_registry.py`.

## Project Conventions

- Prefer `rg` / `rg --files` for codebase search.
- Use `apply_patch` for manual file edits.
- Keep edits ASCII unless the target file already requires Unicode.
- Treat this as a Windows-first Python application.
- The app currently expects TensorRT `.engine` models in `Model/`.
- `config.json` is ignored and represents local runtime configuration.

## Validation

- Tests live under `tests/`.
- Existing TensorRT-focused coverage includes `tests/test_tensorrt_runtime.py`.
- Be careful with commands that may require GPU, CUDA, TensorRT, or Windows-specific runtime dependencies.

## Notes

- PowerShell may emit a blocked profile warning for `C:\Users\11601\Documents\WindowsPowerShell\profile.ps1`; this is noisy but not a blocker for normal commands.
