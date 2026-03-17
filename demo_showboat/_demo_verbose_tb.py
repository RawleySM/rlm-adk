"""Demo: Verbose traceback shows local variable values."""
import os
import re

os.environ["RLM_REPL_XMODE"] = "Verbose"
from rlm_adk.repl.ipython_executor import IPythonDebugExecutor, REPLDebugConfig  # noqa: E402

cfg = REPLDebugConfig.from_env()
executor = IPythonDebugExecutor(config=cfg)
ns = {"__builtins__": __builtins__}
code = """\
def analyze_data(data_list):
    total = sum(data_list)
    avg = total / len(data_list)
    threshold = 100
    filtered = [x for x in data_list if x > threshold]
    return filtered[10]  # IndexError

analyze_data([150, 200, 50, 75, 300])
"""
stdout, stderr, success = executor.execute_sync(code, ns)
clean = re.sub(r"\x1b\[[0-9;]*m", "", stderr)
print(clean)
