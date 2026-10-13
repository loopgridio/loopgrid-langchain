# Local validation and consumer-install checks

Use a fresh Python 3.12 environment in the repository root containing `pyproject.toml`. The real-Core smoke scripts intentionally create disposable test workspaces and policies; **never run against a production Core instance**.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
python -m pytest -q --cov=loopgrid_langchain --cov-fail-under=90
python .\scripts\native_agent_e2e.py

# Historical maintainer Core container name only; use your own test Core:
# docker start loopgrid-dify-test
Invoke-RestMethod http://127.0.0.1:8000/ready
$env:LOOPGRID_BASE_URL = "http://127.0.0.1:8000"
python .\scripts\real_core_e2e.py
python .\scripts\native_core_agent_e2e.py

python -m compileall -q src tests scripts
python -m build
python -m twine check dist\*
python .\scripts\check_dist.py
python -m pip check
```

**Independent local consumer venv:** the editable install above does not count as a wheel-consumer verification. After building, run:

```powershell
py -3.12 -m venv .consumer-venv
.\.consumer-venv\Scripts\python.exe -m pip install (Get-ChildItem .\dist\*.whl | Select-Object -First 1).FullName
.\.consumer-venv\Scripts\python.exe -c "from loopgrid_langchain import LangChainBridge, CoreClient, create_loopgrid_middleware, LocalAsyncSqliteDispatchLease; import langchain; print('PASS clean wheel import')"
.\.consumer-venv\Scripts\python.exe -m pip check
```

Review the complete stdout of each job before marking a release gate passed. Keep signed/Core verification distinct from detached trusted-key verification. All external effects in shipped tests are synthetic; no real funds are moved.
