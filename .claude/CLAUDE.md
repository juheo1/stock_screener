## Docs-first repository workflow

Before inspecting source files broadly, read repository documentation first.

Recommended reading order:
1. `docs/README.md`
2. `docs/00_getting_started/repository-summary.md`
3. `docs/01_architecture/architecture-overview.md`
4. `docs/01_architecture/data-flow-and-control-flow.md`
5. `docs/02_modules/module-responsibility-map.md`
6. `docs/04_maintenance/change-routing-guide.md`

For edit tasks, start with `docs/04_maintenance/change-routing-guide.md` to identify the smallest likely set of files to inspect.

Only after reading the relevant docs should you open source files, and then only inspect the minimum set of files needed for the task.

Update documentation when code changes materially affect:
- architecture or module boundaries
- public APIs or interfaces
- configuration structure or defaults
- workflow or control flow
- dependency relationships
- future change-routing guidance

Do not rewrite or expand docs for trivial local fixes unless the existing docs would become inaccurate.