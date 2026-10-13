# GitHub and PyPI release process

The `loopgrid-langchain` source is a standalone Python distribution (`0.1.0` for the first release) and does not modify LoopGrid Core, the MCP package or `loopgrid-langgraph`.

## Before the first push

1. Review the exact source ZIP and stage only audited source; do not stage `.venv`, `dist`, `.coverage`, SQLite files, keys or intermediate builds.
2. Check that `README.md`, `pyproject.toml`, `CHANGELOG.md`, `VALIDATION.md`, tests and workflows describe the same adapter and version. Technical test evidence stays a **dated historical record**; no `README` publication or official approval claims.
3. Verify that the PyPI name is available and the `loopgridio/loopgrid-langchain` repository identity is correct. Live registry/account confirmation must be done by the maintainer.
4. Run `python scripts/check_release_source.py` and the [local validation](LOCAL-VALIDATION.md) including the isolated wheel-consumer step.

## Create the repository and validate hosted CI

Create an empty public repository at `github.com/loopgridio/loopgrid-langchain`, with **no GitHub-generated README, license or .gitignore**. From the audited folder:

```powershell
git init
git branch -M main
git add -A
git diff --cached --check
git diff --cached --name-only
git status --short
# Inspect the staged list and .env.example before continuing.
git commit -m "Initial release of LoopGrid LangChain integration v0.1.0"
git remote add origin https://github.com/loopgridio/loopgrid-langchain.git
git push -u origin main
```

Check **all** jobs in `.github/workflows/tests.yml` (3 OS × 3 Python versions and the fresh-wheel consumer job). The Windows Core test from the maintainer is separate from hosted jobs because hosted CI has no local Core signing service.

## First PyPI publication through GitHub OIDC

1. After hosted CI is green, configure the GitHub environment **`pypi`** and create a PyPI **pending Trusted Publisher** for owner `loopgridio`, repository `loopgrid-langchain`, workflow `release.yml`, environment `pypi`. Match the current official PyPI Trusted Publishing guidance.
2. Set repository Actions variable `LOOPGRID_PYPI_PUBLISH_ENABLED` to the literal string `true` **before publishing the GitHub Release**. The included `.github/workflows/release.yml` deliberately skips publishing while this variable is unset. Merely uploading the source or creating the environment does not activate the PyPI publisher.
3. From the exact tested commit, tag `v0.1.0` and push it, then create the GitHub Release `v0.1.0` (non-prerelease) for that tag. The release-published event triggers the OIDC workflow. Check the actual publish job and PyPI registry response.
4. From a brand-new consumer environment, install `loopgrid-langchain==0.1.0` **from public PyPI** and run import/version/quickstart smoke. Never infer public registry success from a local wheel.
5. Only afterward update the newest canonical website full-site baseline and request ecosystem listing as that ecosystem permits. Vendor approval is not assumed from an issue/PR.

If PyPI/GitHub rejects or skips an action, diagnose the external settings and failed job first. Avoid changing the README or bumping an immutable version to compensate for a configuration issue.
