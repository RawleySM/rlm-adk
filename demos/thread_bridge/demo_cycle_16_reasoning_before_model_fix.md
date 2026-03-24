# Demo: [Cycle 16] CRITICAL -- `reasoning_before_model` No Longer Destroys SkillToolset L1 XML

## TDD Cycle Reference
- Cycle: 16
- Tests: `test_skill_toolset_integration.py::TestReasoningBeforeModelSkillPreservation::test_toolset_l1_xml_survives_before_model_callback`, `test_dynamic_instruction_appended_not_overwritten`
- Assertion: When `SkillToolset.process_llm_request()` has appended `<available_skills>` XML to `system_instruction`, and then `reasoning_before_model` fires, the final `system_instruction` contains BOTH the RLM dynamic instruction AND the skills XML.

## What This Proves
This is the silent killer bug. ADK's execution order is:
1. `_process_agent_tools()` -> `SkillToolset.process_llm_request()` -> appends `<available_skills>` XML to `system_instruction`
2. `_handle_before_model_callback()` -> `reasoning_before_model` -> used to OVERWRITE `system_instruction` entirely

Before the fix, step 2 destroyed everything step 1 appended. Skills would appear wired (no errors) but NEVER appear in the model's prompt. The model would never see available skills.

## Reward-Hacking Risk
This is the highest reward-hacking risk in the entire plan because:
- A test could check that `reasoning_before_model` "processes" the request without verifying the XML survives
- A test could set up the mock request WITHOUT pre-existing toolset content (so there is nothing to destroy)
- A test could check `system_instruction` length increased without checking the XML is specifically present
- The bug is SILENT: no error, no warning, just missing content in the prompt

The demo guards against this by:
1. Simulating the exact ADK execution order (toolset appends first, then callback fires)
2. Checking for the SPECIFIC `<available_skills>` XML marker in the final system instruction
3. Showing what happens WITHOUT the fix (the XML is destroyed)

## Prerequisites
- `reasoning_before_model` updated to use `append_instructions` instead of overwriting
- `SkillToolset` wired (Cycle 15)
- `.venv` activated

## Demo Steps

### Step 1: Simulate the UNFIXED behavior (control case)
```bash
.venv/bin/python3 -c "
# Simulate what USED TO HAPPEN before the fix

# Step 1: ADK sets static instruction
system_instruction = 'You are a reasoning agent. Use execute_code to run Python.'

# Step 2: SkillToolset.process_llm_request() appends L1 XML
toolset_xml = '''

<available_skills>
  <skill>
    <name>recursive-ping</name>
    <description>Dispatch recursive llm_query() calls across depth layers.</description>
  </skill>
</available_skills>'''
system_instruction += toolset_xml

print('BEFORE reasoning_before_model:')
print(f'  Contains <available_skills>: {\"<available_skills>\" in system_instruction}')
print(f'  Length: {len(system_instruction)}')

# Step 3: OLD reasoning_before_model OVERWRITES system_instruction
dynamic_instruction = 'Current iteration: 1. Tokens used: 500.'
system_instruction = dynamic_instruction  # <-- THE BUG

print()
print('AFTER OLD reasoning_before_model (OVERWRITE):')
print(f'  Contains <available_skills>: {\"<available_skills>\" in system_instruction}')
print(f'  Content: {system_instruction[:80]}...')
print(f'  DESTROYED: Skills XML is gone. Model will never see available skills.')
"
```
**Expected output**:
```
BEFORE reasoning_before_model:
  Contains <available_skills>: True
  Length: XXX

AFTER OLD reasoning_before_model (OVERWRITE):
  Contains <available_skills>: False
  Content: Current iteration: 1. Tokens used: 500....
  DESTROYED: Skills XML is gone. Model will never see available skills.
```

### Step 2: Simulate the FIXED behavior
```bash
.venv/bin/python3 -c "
# Simulate what happens AFTER the fix

# Step 1: ADK sets static instruction
system_instruction = 'You are a reasoning agent. Use execute_code to run Python.'

# Step 2: SkillToolset.process_llm_request() appends L1 XML
toolset_xml = '''

<available_skills>
  <skill>
    <name>recursive-ping</name>
    <description>Dispatch recursive llm_query() calls across depth layers.</description>
  </skill>
</available_skills>'''
system_instruction += toolset_xml

print('BEFORE reasoning_before_model:')
print(f'  Contains <available_skills>: {\"<available_skills>\" in system_instruction}')

# Step 3: FIXED reasoning_before_model APPENDS instead of overwriting
dynamic_instruction = 'Current iteration: 1. Tokens used: 500.'
system_instruction += '\n\n' + dynamic_instruction  # <-- THE FIX (append)

print()
print('AFTER FIXED reasoning_before_model (APPEND):')
print(f'  Contains <available_skills>: {\"<available_skills>\" in system_instruction}')
print(f'  Contains dynamic instruction: {\"Current iteration\" in system_instruction}')
print(f'  PRESERVED: Both skills XML and dynamic instruction coexist.')
"
```
**Expected output**:
```
BEFORE reasoning_before_model:
  Contains <available_skills>: True

AFTER FIXED reasoning_before_model (APPEND):
  Contains <available_skills>: True
  Contains dynamic instruction: True
  PRESERVED: Both skills XML and dynamic instruction coexist.
```

### Step 3: Verify the actual callback source uses append, not overwrite
```bash
.venv/bin/python3 -c "
import inspect
from rlm_adk.callbacks.reasoning import reasoning_before_model

source = inspect.getsource(reasoning_before_model)

# Check for the overwrite pattern (the bug)
has_overwrite = 'system_instruction = ' in source and 'system_instruction +=' not in source
# Check for append_instructions (the fix)
has_append = 'append_instructions' in source

print(f'Source has direct overwrite (BUG): {has_overwrite}')
print(f'Source uses append_instructions (FIX): {has_append}')

if has_append and not has_overwrite:
    print('PROOF: reasoning_before_model uses append, not overwrite')
elif has_overwrite:
    print('WARNING: reasoning_before_model still overwrites system_instruction')
"
```
**Expected output**:
```
Source has direct overwrite (BUG): False
Source uses append_instructions (FIX): True
PROOF: reasoning_before_model uses append, not overwrite
```

### Step 4: Run the automated tests
```bash
.venv/bin/python -m pytest tests_rlm_adk/test_skill_toolset_integration.py::TestReasoningBeforeModelSkillPreservation -x -v 2>&1 | tail -8
```
**Expected output**: All tests PASSED

## Verification Checklist
- [ ] Control case: overwrite behavior destroys `<available_skills>` XML
- [ ] Fixed behavior: append preserves both skills XML and dynamic instruction
- [ ] Source code inspection confirms `append_instructions` pattern (not direct assignment)
- [ ] Automated tests pass for all three scenarios (with toolset, without toolset, dynamic instruction)
- [ ] This could NOT pass if the callback still used `system_instruction = ...` assignment because the `<available_skills>` XML would be destroyed on every model call
