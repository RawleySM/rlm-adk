Run the overnight dashboard UI validation pipeline.

This script reads `scripts/ui_validate/manifest.json` (125 items covering all state keys, UI controls, flow blocks, routes, event handlers, connectors, data models, and visual styling) and validates unchecked items using an Agent SDK team pipeline.

## Steps

1. **Launch the dashboard** so agents and the user can see the latest code running:
   Run `/dashboard_launch` (kills stale server, starts fresh, opens in Chrome).

2. Check current manifest progress:
```bash
python3 -c "import json; m=json.load(open('scripts/ui_validate/manifest.json')); checked=sum(1 for i in m['items'] if i['checked']); print(f'{checked}/{m[\"summary\"][\"total_items\"]} validated ({m[\"summary\"][\"total_items\"]-checked} remaining)')"
```

3. Run the validation script for up to 5 items:
```bash
.venv/bin/python scripts/ui_validate/validate_dashboard.py --max-items 5
```

4. Report results:
```bash
cat scripts/ui_validate/run_report.md
```

For overnight automation, use: `/loop 20m /validate_dashboard`
