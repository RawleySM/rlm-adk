"""RLM ADK Plugins - Before/after agent callbacks for cross-cutting concerns."""

from rlm_adk.plugins.cache import CachePlugin
from rlm_adk.plugins.langfuse_tracing import LangfuseTracingPlugin
from rlm_adk.plugins.observability import ObservabilityPlugin
from rlm_adk.plugins.policy import PolicyPlugin

# SqliteTracingPlugin is conditionally imported -- Track B creates the module.
try:
    from rlm_adk.plugins.sqlite_tracing import SqliteTracingPlugin
except ImportError:
    SqliteTracingPlugin = None  # type: ignore[assignment,misc]

try:
    from rlm_adk.plugins.migration import MigrationPlugin
except ImportError:
    MigrationPlugin = None  # type: ignore[assignment,misc]

__all__ = [
    "CachePlugin",
    "LangfuseTracingPlugin",
    "MigrationPlugin",
    "ObservabilityPlugin",
    "PolicyPlugin",
    "SqliteTracingPlugin",
]
