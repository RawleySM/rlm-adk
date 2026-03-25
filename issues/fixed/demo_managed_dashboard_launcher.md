# Managed Dashboard Launcher

*2026-03-15T14:20:18Z by Showboat 0.6.0*
<!-- showboat-id: 4d7b0126-27a6-43ab-b46a-03ea77874b1c -->

This demo captures the managed dashboard launcher changes: dashboard fingerprinting, launch-plan decisions, and the guardrail checks used to verify the launcher path.

```bash
grep -n 'DashboardInstanceRecord\|DashboardLaunchPlan\|compute_dashboard_fingerprint\|resolve_dashboard_launch_plan' rlm_adk/plugins/dashboard_auto_launch.py
```

```output
51:def compute_dashboard_fingerprint(
71:class DashboardInstanceRecord:
80:    def from_path(cls, path: Path) -> DashboardInstanceRecord | None:
105:class DashboardLaunchPlan:
171:def resolve_dashboard_launch_plan(
176:    instance_record: DashboardInstanceRecord | None,
180:) -> DashboardLaunchPlan:
188:            return DashboardLaunchPlan(
193:        return DashboardLaunchPlan(
201:            return DashboardLaunchPlan(
206:        return DashboardLaunchPlan(
212:    return DashboardLaunchPlan(
289:    "DashboardInstanceRecord",
290:    "DashboardLaunchPlan",
291:    "compute_dashboard_fingerprint",
300:    "resolve_dashboard_launch_plan",
```

```bash
grep -n 'dashboard_instance.json\|replace_unmanaged_dashboard\|reuse_managed\|RLM_ADK_DASHBOARD_FINGERPRINT' scripts/launch_dashboard_chrome.sh
```

```output
119:    reuse_managed)
128:    restart_managed|replace_unmanaged_dashboard)
144:    RLM_ADK_DASHBOARD_FINGERPRINT="${fingerprint}" \
```

```bash
.venv/bin/python - <<'PY'
from rlm_adk.plugins.dashboard_auto_launch import compute_dashboard_fingerprint, dashboard_instance_file_path
print(f"instance_file={dashboard_instance_file_path()}")
print(f"fingerprint_prefix={compute_dashboard_fingerprint()[:12]}")
PY

```

```output
/home/rawley-stanhope/dev/rlm-adk/.venv/lib/python3.12/site-packages/requests/__init__.py:113: RequestsDependencyWarning: urllib3 (2.6.2) or chardet (6.0.0.post1)/charset_normalizer (3.4.4) doesn't match a supported version!
  warnings.warn(
instance_file=/home/rawley-stanhope/dev/rlm-adk/rlm_adk/.adk/dashboard_instance.json
fingerprint_prefix=63bebf4ce2b0
```

```bash
.venv/bin/ruff check rlm_adk/agent.py rlm_adk/dashboard/app.py rlm_adk/plugins/dashboard_auto_launch.py tests_rlm_adk/test_dashboard_auto_launch.py >/tmp/dashboard_launcher_ruff.txt && echo ruff_status=passed && cat /tmp/dashboard_launcher_ruff.txt
```

```output
ruff_status=passed
All checks passed!
```

```bash
.venv/bin/python -m pytest -m "" tests_rlm_adk/test_dashboard_auto_launch.py tests_rlm_adk/test_service_registry.py tests_rlm_adk/test_adk_plugins_langfuse_optional.py >/tmp/dashboard_launcher_pytest.txt && echo pytest_status=passed && tail -1 /tmp/dashboard_launcher_pytest.txt | sed 's/ in .*//'
```

```output
/home/rawley-stanhope/dev/rlm-adk/.venv/lib/python3.12/site-packages/requests/__init__.py:113: RequestsDependencyWarning: urllib3 (2.6.2) or chardet (6.0.0.post1)/charset_normalizer (3.4.4) doesn't match a supported version!
  warnings.warn(
pytest_status=passed
============================== 30 passed
```
