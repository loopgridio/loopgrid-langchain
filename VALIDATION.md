# Validation record — LoopGrid LangChain 0.1.0

**Maintainer validation date:** October 13, 2026. The native LangChain and real-Core E2E checks were run on hardened RC2. Its behavioral modules (`bridge.py`, `core.py`, `leases.py`, `middleware.py`) remain byte-for-byte unchanged in the GitHub-ready source. The maintainer separately reran the GitHub-ready package's unit/security suite, release-source audit, distribution build, metadata/archive checks, and fresh Windows wheel-consumer installation. No hosted CI or public PyPI installation is inferred from these local results.

| Layer | Result | Evidence and limitations |
|---|---|---|
| Windows local unit/security tests | **PASS — 114/114** | Python 3.12.6; 94.81% statement coverage; `python -m pytest -q --cov=loopgrid_langchain --cov-fail-under=90` |
| Native installed SDK | **PASS** | LangChain **1.4.5**; actual `create_agent` synchronous/asynchronous tool handler; one sync + one async synthetic call; replay refused |
| Real LoopGrid Core E2E | **PASS** | Core `0.8.1-design-partner`; signed workspace verify success; no failures, `evidence_complete`, **100% applicable coverage**; two synthetic action callbacks |
| Real LangChain + real Core combined | **PASS** | Installed LangChain `create_agent`, Core `0.8.1-design-partner`, decision `dec_eda5d829d53640be842bb383`, workspace `ws_7a4ae59217aa4d1d`; signed verification true, failures `[]`, `evidence_complete`, 100% applicable coverage, one synthetic handler execution |
| Compile/build | **PASS** | Python compilation and standard `python -m build` wheel + source archive |
| Metadata check | **PASS** | `python -m twine check dist\*` reported PASSED for wheel and sdist |
| Archive verification | **PASS** | `python scripts/check_dist.py` contents verified |
| Dependency integrity | **PASS** | `python -m pip check`: no broken requirements |
| GitHub-ready release-source audit | **PASS** | `python scripts/check_release_source.py`: documentation, local links, package identity, exclusions, CI workflow files verified |
| Fresh Windows wheel consumer | **PASS** | Separate `.consumer-venv` on Python 3.12.6; installed built `loopgrid_langchain-0.1.0-py3-none-any.whl` with dependencies; imported `CoreClient`, `LangChainBridge`, `create_loopgrid_middleware` plus LangChain; `pip check` found no broken requirements |
| Linux offline local tests | **PASS** | Prior engineering run, Python 3.13.5; 114/114 tests, 94.81% coverage |

**Scope limits:** Tests used synthetic model responses and synthetic external actions. **No funds were moved**, no live model-provider invocation was demonstrated, and a Core service-side signed workspace verification is **not** a detached, independently pinned-key offline bundle verification. The separately created Windows wheel-consumer environment verified a built local wheel, **not** installation from the public PyPI registry. A fresh public-registry install remains a post-publication gate.

## Release evidence is separate

GitHub-hosted CI, GitHub Release, PyPI Trusted Publishing, public registry installation, website deployment, and external ecosystem listing are independent steps. Their current status should be read from the relevant **live external service**, not inferred from this dated Windows validation record. The source ships CI and OIDC workflow definitions; a workflow file is not proof that hosted CI or OIDC publication executed.

## Reproduce locally

See [Local validation](docs/LOCAL-VALIDATION.md). The native installed LangChain smoke (`native_agent_e2e.py`) tests a synthetic Core; the real-Core E2E (`real_core_e2e.py`) does not use the native agent. Run **both**, plus `native_core_agent_e2e.py`, to test all three boundaries.
