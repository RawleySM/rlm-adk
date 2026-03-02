# Resolving FM-15 Gap: SHOULD_STOP Missing Assertion

*2026-03-02T16:53:19Z by Showboat 0.6.0*
<!-- showboat-id: 120ca8af-774a-4cfe-88b7-db0fba51128b -->

I found an open medium priority gap in fmea_gaps_compiled_2.json for empty_reasoning_output.json. The gap was: No assertion for SHOULD_STOP == True in final state.

I added the test_should_stop_is_true assertion to the TestEmptyReasoningOutput class in tests_rlm_adk/test_fmea_e2e.py.

```bash
sed -n '596,602p' tests_rlm_adk/test_fmea_e2e.py
```

```output
    async def test_should_stop_is_true(self, tmp_path: Path):
        """Verify that SHOULD_STOP is set to True to signal session termination."""
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        assert result.final_state.get(SHOULD_STOP) is True, (
            "Expected SHOULD_STOP to be True in final state"
        )
```

Running the test shows it passes, proving the orchestrator correctly sets SHOULD_STOP to True when the reasoning output is empty.

```bash
uv run pytest tests_rlm_adk/test_fmea_e2e.py::TestEmptyReasoningOutput::test_should_stop_is_true -v
```

```output
============================= test session starts ==============================
platform linux -- Python 3.12.3, pytest-9.0.2, pluggy-1.6.0 -- /home/rawley-stanhope/dev/rlm-adk/.venv/bin/python
cachedir: .pytest_cache
rootdir: /home/rawley-stanhope/dev/rlm-adk
configfile: pyproject.toml
plugins: asyncio-1.3.0, anyio-4.12.0
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 1 item

tests_rlm_adk/test_fmea_e2e.py::TestEmptyReasoningOutput::test_should_stop_is_true PASSED [100%]

=============================== warnings summary ===============================
.venv/lib/python3.12/site-packages/requests/__init__.py:113
  /home/rawley-stanhope/dev/rlm-adk/.venv/lib/python3.12/site-packages/requests/__init__.py:113: RequestsDependencyWarning: urllib3 (2.6.2) or chardet (6.0.0.post1)/charset_normalizer (3.4.4) doesn't match a supported version!
    warnings.warn(

tests_rlm_adk/test_fmea_e2e.py::TestEmptyReasoningOutput::test_should_stop_is_true
tests_rlm_adk/test_fmea_e2e.py::TestEmptyReasoningOutput::test_should_stop_is_true
  /home/rawley-stanhope/dev/rlm-adk/.venv/lib/python3.12/site-packages/google/genai/_api_client.py:744: DeprecationWarning: Inheritance class AiohttpClientSession from ClientSession is discouraged
    class AiohttpClientSession(aiohttp.ClientSession):  # type: ignore[misc]

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
======================== 1 passed, 3 warnings in 0.41s =========================
```
