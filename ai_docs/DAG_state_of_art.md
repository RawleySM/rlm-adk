# State of the Art: Agents Reasoning over Directed Acyclic Graphs (DAGs)

## Overview
Recent advancements in LLM agent architectures have seen a paradigm shift from linear, sequential reasoning models (like basic Chain-of-Thought or standard ReAct loops) towards **Directed Acyclic Graph (DAG)** structures. DAGs offer clear advantages for complex reasoning, multi-agent orchestration, and parallel execution by explicitly modeling tasks as nodes and dependencies as one-way edges.

This document summarizes the current state-of-the-art based on recent arXiv publications and open-source GitHub implementations.

---

## 1. Key Research & Papers (arXiv)

Recent academic work highlights how DAGs improve execution latency, handle multi-subject tasks, and enable dynamic planning.

### Flash-Searcher: Fast and Effective Web Agents via DAG-Based Parallel Execution
*   **arXiv:** `2509.25301`
*   **Core Innovation:** Reimagines web agent execution as a DAG rather than a sequential chain. It decomposes user queries into subtasks with explicit dependencies.
*   **Impact:** By identifying subtasks with no mutual dependencies, the framework executes independent tool calls and reasoning paths in parallel, reducing overall execution steps and latency by up to 35% without sacrificing accuracy.

### S-DAG: A Subject-Based Directed Acyclic Graph for Multi-Agent Heterogeneous Reasoning
*   **arXiv:** `2511.06727`
*   **Core Innovation:** Utilizes a Graph Neural Network (GNN) to identify distinct "subjects" within a complex query and maps them to an S-DAG.
*   **Impact:** Nodes represent specific subjects or domains, while edges dictate the flow of contextual information. This structure successfully coordinates heterogeneous, specialized models for multi-domain reasoning tasks.

### DeMAC: Enhancing Multi-Agent Coordination with Dynamic DAG
*   **Conference:** EMNLP 2025
*   **Core Innovation:** Moves beyond static DAG planning by introducing a dynamically updated DAG. It integrates a Manager-Player feedback loop.
*   **Impact:** Allows agents to adapt their long-term strategies and execution graphs in real-time in response to environmental disruptions (tested extensively in interactive simulation environments).

---

## 2. Prominent Open-Source Implementations (GitHub)

The open-source ecosystem provides both general-purpose orchestration frameworks and specialized internal-reasoning graphs.

### Orchestration & Frameworks
*   **[LangGraph (by LangChain)](https://github.com/langchain-ai/langgraph):** The industry standard for stateful, multi-actor applications. While it supports cyclic graphs, its primary use case is defining robust DAGs for agent pipelines. It emphasizes shared state and granular control over node transitions.
*   **[LangDAG](https://github.com/reedxiao/langdag) / [pwwang/langdag](https://github.com/pwwang/langdag):** A Python framework explicitly tailored for building LLM agent workflows as DAGs, heavily inspired by data engineering tools like Apache Airflow. It focuses on concurrent node processing and stateful execution.
*   **[Dynamiq](https://github.com/dynamiq-ai/dynamiq):** An orchestration framework utilizing a "Graph Orchestrator" for RAG and multi-agent systems, prioritizing complex dependency management and parallel agent execution.
*   **[DAGent](https://github.com/aiagentstore/dagent):** Designed to structure AI agents into DAG workflows specifically to enhance fault tolerance and reliability in multi-step procedures.

### Internal Reasoning Frameworks
*   **[Diagram of Thought (DoT)](https://github.com/diagram-of-thought/diagram-of-thought):** Rather than orchestrating multiple agents, DoT is a reasoning framework where a single LLM builds a "mental DAG." The model generates nodes (propositions/ideas) and edges (critiques/dependencies), allowing it to explore parallel lines of evidence before synthesizing a conclusion.
*   **[Graph-Reasoning-LLM (GraphWiz)](https://github.com/Graph-Reasoner/Graph-Reasoning-LLM):** Focuses on training LLMs to inherently output explicit, structured graph reasoning paths, particularly effective for algorithmic graph problems.

---

## 3. Synthesis: Common Threads and Architectures

Across both academic research and open-source tooling, several common architectural threads have emerged.

### Why DAGs? (The "Common Thread")
1.  **Deterministic Execution & Topological Sorting:** Unlike autonomous agents that can get stuck in infinite loops, DAGs guarantee a finite execution path. Topological sorting ensures tasks are executed in a logically valid order.
2.  **Parallelism:** The explicit definition of edges allows frameworks to identify independent nodes and execute them concurrently (e.g., Flash-Searcher).
3.  **State Management:** Complex workflows require passing context over many steps. A graph architecture centralizes this into a shared "State" object passed between nodes.

### Standard Python Architecture
Most Python implementations share a remarkably similar object-oriented and functional design pattern.

#### Core Python Classes & Functions

**1. The `State` Object**
Usually defined using `typing.TypedDict` or `pydantic.BaseModel`. It represents the memory of the graph.
```python
from typing import TypedDict, Annotated
import operator

class AgentState(TypedDict):
    query: str
    intermediate_steps: Annotated[list[str], operator.add] # Reducer logic
    final_answer: str
```

**2. The `Node` (Functions / Methods)**
Nodes are typically pure functions or class methods. They accept the current `State`, perform an LLM call or tool execution, and return an updated dictionary.
```python
def planner_node(state: AgentState) -> dict:
    # LLM logic to break query into a DAG plan
    return {"intermediate_steps": ["Plan generated"]}

def execution_node(state: AgentState) -> dict:
    # Tool execution logic
    return {"intermediate_steps": ["Tool executed"]}
```

**3. The `GraphBuilder` / Orchestrator**
A class responsible for assembling the DAG, adding nodes, defining edges, and compiling the final executable graph.
```python
class DAGBuilder:
    def add_node(self, name: str, node_func: callable): ...
    
    # Defines static dependencies (Node A must finish before Node B)
    def add_edge(self, source: str, target: str): ...
    
    # Often includes conditional routing based on state
    def add_conditional_edges(self, source: str, router_func: callable, target_map: dict): ...
    
    def compile(self): ... # Performs topological sort and returns executable
```

### Execution Flow
1. **Initialization:** The graph is instantiated with an initial state (e.g., the user query).
2. **Traversal:** The engine executes nodes whose incoming edges are satisfied.
3. **State Mutation:** Each node returns a partial state update, which the engine merges into the global state (often using specific reducer functions for lists or dictionaries).
4. **Completion:** The graph terminates when it reaches a node with no outgoing edges (a sink node).

---

## 4. New Findings (Comprehensive Sweep, March 4, 2026)

### 4.1 ADK-Python DAG Composition: Official Capabilities + Community Signals

For this repository (`google-adk` in Python), DAG behavior can be built as compositional workflow control:

*   **Workflow control primitives are first-class and deterministic:** [`SequentialAgent`, `ParallelAgent`, `LoopAgent`](https://google.github.io/adk-docs/agents/workflow-agents/).
*   **`SequentialAgent`** provides ordered stage-by-stage orchestration ([docs](https://google.github.io/adk-docs/agents/workflow-agents/sequential-agents/)).
*   **`ParallelAgent`** provides fan-out concurrency for independent branches ([docs](https://google.github.io/adk-docs/agents/workflow-agents/parallel-agents/)).
*   **`LoopAgent`** provides bounded iterative execution ([docs](https://google.github.io/adk-docs/agents/workflow-agents/loop-agents/)).
*   **Custom orchestration (custom edges/routing)** is explicitly supported through custom agents (`BaseAgent`, `_run_async_impl`) ([docs](https://google.github.io/adk-docs/agents/custom-agents/)).
*   **Tool-level parallelism** is documented for async function tools ([tool performance docs](https://google.github.io/adk-docs/tools-custom/performance/)).
*   **Composition patterns** (coordinator/dispatcher, fan-out/fan-in, hierarchical, iterative) are documented in ADK multi-agent guidance ([docs](https://google.github.io/adk-docs/agents/multi-agents/)).

Community / forum exploration (requested):

*   [google/adk-python issue #1828](https://github.com/google/adk-python/issues/1828): request for map-style dynamic fan-out workflow behavior.
*   [google/adk-python issue #1376](https://github.com/google/adk-python/issues/1376): loop termination and parent continuation semantics discussion.
*   [google/adk-python issue #3081](https://github.com/google/adk-python/issues/3081): transfer/routing behavior edge case report.
*   [google/adk-python discussion #3348](https://github.com/google/adk-python/discussions/3348): resume behavior and sequential re-execution questions.
*   [Google Developer Forum workflow guide](https://discuss.google.dev/t/a-practical-guide-to-production-ready-agentic-workflows-with-adk-and-agent-engine/265828): production workflow patterns with ADK and Agent Engine.

**Practical inference for `rlm_adk`:** ADK already supports DAG-like orchestration by composing workflow agents and custom agents, but it is not yet a native arbitrary DAG scheduler with runtime graph generation as a core primitive.

### 4.2 Production Workflow Orchestrators (Durability, Retries, Scheduling)

These are strong options when DAG execution must survive process crashes, support scheduling, or provide operational controls:

*   **[Prefect](https://github.com/PrefectHQ/prefect)** ([docs](https://docs.prefect.io/v3/get-started)): Pythonic task/flow orchestration with retries, states, schedules, and async support.
*   **[Dagster](https://github.com/dagster-io/dagster)** ([docs](https://docs.dagster.io/)): typed graph execution, scheduling/sensors, and strong observability.
*   **[Apache Airflow](https://github.com/apache/airflow)** ([DAG docs](https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/dags.html)): mature, scheduler-first DAG orchestration.
*   **[Temporal + Python SDK](https://github.com/temporalio/sdk-python)** ([docs](https://docs.temporal.io/develop/python)): durable, event-sourced workflow runtime for long-running executions.
*   **[Flyte](https://github.com/flyteorg/flyte)** ([docs](https://docs.flyte.org/en/latest/)): typed workflows and scalable orchestration for Python tasks.
*   **[Argo Workflows](https://github.com/argoproj/argo-workflows)** ([docs](https://argo-workflows.readthedocs.io/en/latest/)): Kubernetes-native DAG/workflow execution.
*   **[Metaflow](https://github.com/Netflix/metaflow)** ([docs](https://docs.metaflow.org/)): Python workflow authoring with production backends.
*   **[Hatchet](https://github.com/hatchet-dev/hatchet)** ([site/docs](https://hatchet.run/)): modern task/workflow runtime focused on durable execution patterns.

### 4.3 Embedded Python DAG / Graph Engines (Library-Level Integration)

These are good fits for embedding DAG execution directly into the current codebase without adopting a full external control plane:

*   **[Dask Task Graphs](https://github.com/dask/dask)** ([graphs docs](https://docs.dask.org/en/stable/graphs.html)): dynamic task graphs with local/distributed execution.
*   **[Hamilton](https://github.com/apache/hamilton)** ([docs](https://hamilton.apache.org/)): function-based DAG construction with explicit dependencies.
*   **[Parsl](https://github.com/Parsl/parsl)** ([docs](https://parsl.readthedocs.io/en/stable/)): parallel scripting and dependency-aware workflow execution.
*   **[Celery Canvas](https://github.com/celery/celery)** ([canvas docs](https://docs.celeryq.dev/en/stable/userguide/canvas.html)): DAG-like chains/groups/chords on distributed workers.
*   **[Luigi](https://github.com/spotify/luigi)** ([docs](https://luigi.readthedocs.io/en/stable/)): dependency-driven Python pipelines.
*   **[redun](https://github.com/insitro/redun)** ([docs](https://insitro.github.io/redun/)): workflow execution with caching and provenance.
*   **[NetworkX](https://github.com/networkx/networkx)** ([DAG algorithms](https://networkx.org/documentation/stable/reference/algorithms/dag.html)): low-level DAG modeling/analysis (pair with a custom executor).
*   **Python stdlib [`graphlib.TopologicalSorter`](https://docs.python.org/3/library/graphlib.html)**: lightweight topological execution planning primitive.

### 4.4 Agent-Oriented Graph Frameworks (Beyond Existing Entries)

Additional agent-graph repos that can accelerate DAG-like multi-agent orchestration patterns:

*   **[AutoGen GraphFlow](https://github.com/microsoft/autogen)** ([docs](https://microsoft.github.io/autogen/stable/user-guide/agentchat-user-guide/graph-flow.html)): explicit directed execution graphs for agent teams (sequential/parallel/conditional/looping).
*   **[AG2](https://github.com/ag2ai/ag2)** ([StateFlow docs](https://docs.ag2.ai/latest/docs/use-cases/notebooks/notebooks/agentchat_groupchat_stateflow/)): state-driven multi-agent orchestration patterns.
*   **[CrewAI Flows](https://github.com/crewAIInc/crewAI)** ([docs](https://docs.crewai.com/en/concepts/flows)): event-driven agent flow control with branching and looping.
*   **[LlamaIndex Workflows](https://github.com/run-llama/llama_index)** ([docs](https://developers.llamaindex.ai/python/llamaagents/workflows/)): step/event-based agent workflow composition.
*   **[Haystack Pipelines](https://github.com/deepset-ai/haystack)** ([pipeline docs](https://docs.haystack.deepset.ai/docs/pipelines)): directed multigraph pipelines with async/branching support.
*   **[Pydantic Graph (`pydantic-graph`)](https://github.com/pydantic/pydantic-ai)** ([docs](https://ai.pydantic.dev/graph/)): strongly-typed async graph/FSM library for Python.
*   **[Apache Burr](https://github.com/apache/burr)** ([docs](https://burr.apache.org/)): state-machine-oriented orchestration for agent applications.
*   **[Griptape Workflows](https://github.com/griptape-ai/griptape)** ([docs](https://docs.griptape.ai/stable/griptape-framework/structures/workflows/)): task workflows modeled as a non-sequential DAG.
*   **[Semantic Kernel Process Framework](https://github.com/microsoft/semantic-kernel)** ([docs](https://learn.microsoft.com/en-us/semantic-kernel/frameworks/process/process-framework)): event-driven multi-step process orchestration.
