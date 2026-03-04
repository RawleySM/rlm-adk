# Gemini API Contract Summary for Fake Provider

Research conducted against:
- **google-genai** SDK v1.56.0
- **google-adk** SDK v1.25.0
- Codebase at `/home/rawley-stanhope/dev/rlm-adk/`

---

## 1. SDK and API Version Identification

### Installed Versions
- `google-genai==1.56.0` (the unified Python SDK for Gemini)
- `google-adk==1.25.0` (Agent Development Kit)
- Python 3.11

### API Flavor: Gemini Developer API (NOT Vertex AI)
This codebase uses the **Gemini Developer API** (non-Vertex):
- Auth: `GEMINI_API_KEY` env var (set in `.env`)
- No `vertexai=True`, no `project`/`location` in the client init
- ADK's `Gemini` class in `google_llm.py` creates the client via:
  ```python
  Client(http_options=types.HttpOptions(
      headers=tracking_headers,
      retry_options=self.retry_options,
      base_url=self.base_url,   # None by default
  ))
  ```
- The `Client.__init__` picks up `GEMINI_API_KEY` from env (or `GOOGLE_API_KEY`)

### API Version and Base URL
For the Gemini Developer API (non-Vertex), the SDK sets:
- **Base URL**: `https://generativelanguage.googleapis.com/`
- **API version**: `v1beta`
- Full URL pattern: `https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent`

For our fake, we override via:
- `HttpOptions(base_url="http://localhost:PORT/")` on the `Client`, OR
- Env var `GOOGLE_GEMINI_BASE_URL` (checked by `_base_url.get_base_url()`)

### Model Name Transform
For non-Vertex (Gemini API), the `t_model()` transform in `_transformers.py` does:
```python
# Input: "gemini-3-pro-preview"
# Output: "models/gemini-3-pro-preview"
if model.startswith('models/'):
    return model
elif model.startswith('tunedModels/'):
    return model
else:
    return f'models/{model}'
```

So the URL path becomes: `models/gemini-3-pro-preview:generateContent`

### Full Request URL Construction
From `_build_request()` in `_api_client.py`:
```
url = join_url_path(base_url, f"{api_version}/{path}")
```
Concrete example:
```
POST https://generativelanguage.googleapis.com/v1beta/models/gemini-3-pro-preview:generateContent
```

For streaming:
```
POST https://generativelanguage.googleapis.com/v1beta/models/gemini-3-pro-preview:streamGenerateContent?alt=sse
```

---

## 2. Client Configuration Options (Base URL Override)

### Option A: HttpOptions.base_url (Recommended for Fake)
```python
from google.genai import Client
from google.genai.types import HttpOptions

client = Client(
    api_key="fake-key",
    http_options=HttpOptions(base_url="http://localhost:8090/")
)
```

### Option B: Environment Variable
```bash
export GOOGLE_GEMINI_BASE_URL="http://localhost:8090/"
export GEMINI_API_KEY="fake-key"
```
The SDK checks `GOOGLE_GEMINI_BASE_URL` in `_base_url.py:get_base_url()` before falling back to the default.

### Option C: Global Override (Monkeypatch)
```python
from google.genai._base_url import set_default_base_urls
set_default_base_urls(gemini_url="http://localhost:8090/", vertex_url=None)
```

### How It Flows Through ADK
ADK's `Gemini` class (in `google_llm.py`) creates the client with:
```python
Client(http_options=types.HttpOptions(
    headers=tracking_headers,
    retry_options=self.retry_options,
    base_url=self.base_url,   # Gemini.base_url field
))
```
The `Gemini.base_url` field defaults to `None`. So the cleanest approach for the fake is:
1. Set `GOOGLE_GEMINI_BASE_URL=http://localhost:PORT/` env var, OR
2. Use `model=Gemini(base_url="http://localhost:PORT/")` when creating the LlmAgent

In both cases, the SDK will send requests to the fake server with the same path structure.

---

## 3. Request Schema

### Endpoint
```
POST {base_url}{api_version}/models/{model_name}:generateContent
```

### Wire Format (JSON body after SDK serialization)
The SDK takes the Python-side `GenerateContentConfig` and serializes it with camelCase field names. The `_GenerateContentParameters_to_mldev` transformer produces:

```json
{
  "contents": [
    {
      "role": "user",
      "parts": [
        {"text": "Hello, what is 2+2?"}
      ]
    },
    {
      "role": "model",
      "parts": [
        {"text": "2+2 equals 4."}
      ]
    }
  ],
  "systemInstruction": {
    "role": "user",
    "parts": [
      {"text": "You are a helpful assistant..."}
    ]
  },
  "generationConfig": {
    "temperature": 0.0,
    "topP": 0.95,
    "topK": 40,
    "maxOutputTokens": 8192,
    "candidateCount": 1,
    "thinkingConfig": {
      "includeThoughts": true,
      "thinkingBudget": 1024
    }
  },
  "safetySettings": [],
  "tools": [],
  "toolConfig": {}
}
```

### Field Mapping (Python SDK -> Wire JSON)

| SDK Field (snake_case) | Wire Field (camelCase) | Location in JSON |
|---|---|---|
| `contents` | `contents` | top-level |
| `config.system_instruction` | `systemInstruction` | **top-level** (parent_object) |
| `config.temperature` | `temperature` | `generationConfig` |
| `config.top_p` | `topP` | `generationConfig` |
| `config.top_k` | `topK` | `generationConfig` |
| `config.max_output_tokens` | `maxOutputTokens` | `generationConfig` |
| `config.candidate_count` | `candidateCount` | `generationConfig` |
| `config.stop_sequences` | `stopSequences` | `generationConfig` |
| `config.response_mime_type` | `responseMimeType` | `generationConfig` |
| `config.response_schema` | `responseSchema` | `generationConfig` |
| `config.thinking_config` | `thinkingConfig` | `generationConfig` |
| `config.safety_settings` | `safetySettings` | **top-level** (parent_object) |
| `config.tools` | `tools` | **top-level** (parent_object) |
| `config.tool_config` | `toolConfig` | **top-level** (parent_object) |
| `config.cached_content` | `cachedContent` | **top-level** (parent_object) |

**IMPORTANT**: `systemInstruction`, `safetySettings`, `tools`, `toolConfig`, and `cachedContent` are written to the **parent** (top-level) object, NOT inside `generationConfig`. The SDK pops `config` from the request dict before sending.

### Contents Structure
Each content entry:
```json
{
  "role": "user" | "model",
  "parts": [
    {"text": "string"},
    {"thought": true, "text": "thinking text"},
    {"functionCall": {"name": "fn", "args": {...}}},
    {"functionResponse": {"name": "fn", "response": {...}}},
    {"inlineData": {"mimeType": "image/png", "data": "base64..."}},
    {"fileData": {"mimeUri": "gs://...", "mimeType": "..."}},
    {"executableCode": {"code": "...", "language": "PYTHON"}},
    {"codeExecutionResult": {"outcome": "OK", "output": "..."}}
  ]
}
```

### What This Codebase Actually Sends
Based on `reasoning_before_model` and `worker_before_model`, the requests contain:
1. **Reasoning agent**: system_instruction (long) + contents (user/model message history) + thinkingConfig
2. **Worker agents**: contents (single user message with text) + temperature=0.0

Minimal worker request:
```json
{
  "contents": [
    {
      "role": "user",
      "parts": [{"text": "Answer this question..."}]
    }
  ],
  "generationConfig": {
    "temperature": 0.0
  }
}
```

Minimal reasoning request:
```json
{
  "contents": [
    {"role": "user", "parts": [{"text": "iteration prompt"}]},
    {"role": "model", "parts": [{"text": "previous response"}]},
    {"role": "user", "parts": [{"text": "REPL output + next prompt"}]}
  ],
  "systemInstruction": {
    "parts": [{"text": "system prompt + dynamic context"}]
  },
  "generationConfig": {
    "thinkingConfig": {
      "includeThoughts": true,
      "thinkingBudget": 1024
    }
  }
}
```

---

## 4. Response Schema

### Wire Format (JSON returned by API)
```json
{
  "candidates": [
    {
      "content": {
        "role": "model",
        "parts": [
          {"thought": true, "text": "Let me think about this..."},
          {"text": "The answer is 4."}
        ]
      },
      "finishReason": "STOP",
      "avgLogprobs": -0.123,
      "tokenCount": 42,
      "safetyRatings": [
        {
          "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
          "probability": "NEGLIGIBLE"
        }
      ],
      "citationMetadata": null,
      "groundingMetadata": null,
      "index": 0
    }
  ],
  "usageMetadata": {
    "promptTokenCount": 150,
    "candidatesTokenCount": 42,
    "totalTokenCount": 192,
    "thoughtsTokenCount": 100
  },
  "modelVersion": "gemini-3-pro-preview-001",
  "responseId": "resp_abc123"
}
```

### SDK Deserialization (`_GenerateContentResponse_from_mldev`)
The SDK maps camelCase wire JSON to snake_case Python:

| Wire (camelCase) | Python (snake_case) |
|---|---|
| `candidates` | `candidates` (list of Candidate) |
| `candidates[0].content` | `candidate.content` (Content) |
| `candidates[0].finishReason` | `candidate.finish_reason` |
| `candidates[0].tokenCount` | `candidate.token_count` |
| `candidates[0].avgLogprobs` | `candidate.avg_logprobs` |
| `candidates[0].safetyRatings` | `candidate.safety_ratings` |
| `candidates[0].groundingMetadata` | `candidate.grounding_metadata` |
| `candidates[0].citationMetadata` | `candidate.citation_metadata` |
| `usageMetadata` | `usage_metadata` |
| `modelVersion` | `model_version` |
| `promptFeedback` | `prompt_feedback` |
| `responseId` | `response_id` |

### ADK's `LlmResponse.create()` extracts:
```python
LlmResponse(
    content=candidate.content,           # Content object
    grounding_metadata=candidate.grounding_metadata,
    usage_metadata=usage_metadata,       # From top-level
    finish_reason=candidate.finish_reason,
    citation_metadata=candidate.citation_metadata,
    avg_logprobs=candidate.avg_logprobs,
    logprobs_result=candidate.logprobs_result,
    model_version=response.model_version,
)
```

### What This Codebase Reads from Responses
From `reasoning_after_model` and `worker_after_model`:

1. **Text extraction** (both reasoning + worker):
   ```python
   response_text = "".join(
       part.text for part in llm_response.content.parts
       if part.text and not part.thought   # Skip thought parts!
   )
   ```

2. **Usage metadata** (both):
   ```python
   usage = llm_response.usage_metadata
   input_tokens = getattr(usage, "prompt_token_count", 0) or 0
   output_tokens = getattr(usage, "candidates_token_count", 0) or 0
   ```

3. **Finish reason**: Used in `LlmResponse.create()` to detect `STOP` vs error

### Minimum Viable Response for Fake
```json
{
  "candidates": [
    {
      "content": {
        "role": "model",
        "parts": [
          {"text": "Response text here"}
        ]
      },
      "finishReason": "STOP",
      "index": 0
    }
  ],
  "usageMetadata": {
    "promptTokenCount": 100,
    "candidatesTokenCount": 50,
    "totalTokenCount": 150
  },
  "modelVersion": "gemini-3-pro-preview"
}
```

### Response with Thinking (thought parts)
```json
{
  "candidates": [
    {
      "content": {
        "role": "model",
        "parts": [
          {"thought": true, "text": "Internal reasoning..."},
          {"text": "Visible response text"}
        ]
      },
      "finishReason": "STOP",
      "index": 0
    }
  ],
  "usageMetadata": {
    "promptTokenCount": 100,
    "candidatesTokenCount": 50,
    "totalTokenCount": 150,
    "thoughtsTokenCount": 30
  },
  "modelVersion": "gemini-3-pro-preview"
}
```

---

## 5. Tool/Function Call Schema

### This Codebase Does NOT Use Function Calling
Confirmed: `grep -ri "function_call\|function_response\|tool_use\|tool_result" rlm_adk/` returns zero matches. The codebase uses only text-based content (user/model messages with text parts).

### For Completeness: Function Call Wire Format
If needed in the future, the wire format would be:

**Request (declaring tools):**
```json
{
  "tools": [
    {
      "functionDeclarations": [
        {
          "name": "get_weather",
          "description": "Get weather for a location",
          "parameters": {
            "type": "OBJECT",
            "properties": {
              "location": {"type": "STRING"}
            },
            "required": ["location"]
          }
        }
      ]
    }
  ]
}
```

**Response (model calls a function):**
```json
{
  "candidates": [{
    "content": {
      "role": "model",
      "parts": [{
        "functionCall": {
          "name": "get_weather",
          "args": {"location": "San Francisco"}
        }
      }]
    },
    "finishReason": "STOP"
  }]
}
```

**Follow-up (sending function result back):**
```json
{
  "contents": [
    ...,
    {
      "role": "model",
      "parts": [{"functionCall": {"name": "get_weather", "args": {"location": "SF"}}}]
    },
    {
      "role": "user",
      "parts": [{"functionResponse": {"name": "get_weather", "response": {"temperature": 72}}}]
    }
  ]
}
```

**NOT needed for MVP fake** -- the codebase only uses text parts.

---

## 6. Streaming Protocol

### Does This Codebase Use Streaming?
**No.** Grep confirms no `stream=True` or streaming generator patterns in `rlm_adk/`. The ADK `Gemini.generate_content_async()` has both paths, but the `LlmAgent` default flow uses the non-streaming path:
```python
response = await self.api_client.aio.models.generate_content(
    model=llm_request.model,
    contents=llm_request.contents,
    config=llm_request.config,
)
```

### For Completeness: Streaming Wire Format
Streaming endpoint: `POST .../models/{model}:streamGenerateContent?alt=sse`

SSE format (server-sent events):
```
data: {"candidates":[{"content":{"role":"model","parts":[{"text":"Hello"}]},"index":0}]}

data: {"candidates":[{"content":{"role":"model","parts":[{"text":" world"}]},"index":0}]}

data: {"candidates":[{"content":{"role":"model","parts":[{"text":"!"}]},"finishReason":"STOP","index":0}],"usageMetadata":{"promptTokenCount":5,"candidatesTokenCount":3,"totalTokenCount":8}}

```

**NOT needed for MVP fake.**

---

## 7. Error Response Patterns

### Error Response Wire Format
The SDK checks `response.status_code` first, then parses:
```json
{
  "error": {
    "code": 429,
    "message": "Resource exhausted. Please retry after 60 seconds.",
    "status": "RESOURCE_EXHAUSTED"
  }
}
```

### SDK Error Classification
From `errors.py`:
- **4xx** -> `ClientError(APIError)` (includes 400, 401, 403, 404, 429)
- **5xx** -> `ServerError(APIError)` (includes 500, 502, 503, 504)
- Other -> `APIError`

All error classes have:
- `error.code` (int): HTTP status code
- `error.message` (str): Error message
- `error.status` (str): Status string (e.g., "RESOURCE_EXHAUSTED")
- `error.details` (dict): Full response JSON
- `error.response` (httpx.Response): Raw response object

### Retryable Status Codes
Default SDK retry codes (`_RETRY_HTTP_STATUS_CODES`):
```python
(408, 429, 500, 502, 503, 504)
```

This codebase's orchestrator (`_TRANSIENT_STATUS_CODES`):
```python
frozenset({408, 429, 500, 502, 503, 504})
```

Orchestrator retry uses `is_transient_error()`:
```python
def is_transient_error(exc: Exception) -> bool:
    if isinstance(exc, (ServerError, ClientError)):
        return getattr(exc, "code", None) in _TRANSIENT_STATUS_CODES
    return False
```

### Fake Error Responses
For rate limiting:
```json
HTTP 429
{
  "error": {
    "code": 429,
    "message": "Resource has been exhausted (e.g. check quota).",
    "status": "RESOURCE_EXHAUSTED"
  }
}
```

For server error:
```json
HTTP 500
{
  "error": {
    "code": 500,
    "message": "An internal error has occurred.",
    "status": "INTERNAL"
  }
}
```

For bad request:
```json
HTTP 400
{
  "error": {
    "code": 400,
    "message": "Invalid value at 'contents'...",
    "status": "INVALID_ARGUMENT"
  }
}
```

---

## 8. Auth Mechanism

### API Key Authentication
For the Gemini Developer API (non-Vertex):
- The SDK reads `GEMINI_API_KEY` or `GOOGLE_API_KEY` from environment
- The key is sent as an HTTP header: `x-goog-api-key: <api_key>`

From `_api_client.py`:
```python
self._http_options.headers = {'Content-Type': 'application/json'}
if self.api_key:
    self._http_options.headers['x-goog-api-key'] = self.api_key
```

### Headers Sent
```
Content-Type: application/json
x-goog-api-key: AIzaSy...
user-agent: google-genai-sdk/1.56.0 gl-python/3.11.x
x-goog-api-client: google-genai-sdk/1.56.0 gl-python/3.11.x
```

ADK adds tracking headers:
```
x-goog-api-client: adk-py/1.25.0 ...
```

A server-side timeout header is also populated:
```python
populate_server_timeout_header(headers, timeout_in_seconds)
```

### Fake API Key Strategy
The fake server should:
1. Accept ANY value in the `x-goog-api-key` header
2. Not validate the key at all
3. The test setup uses `GEMINI_API_KEY=fake-key-for-testing`

---

## 9. Assumptions and Open Questions

### Assumptions for Fake Server
1. **Single endpoint needed**: `POST /v1beta/models/{model}:generateContent` (non-streaming)
2. **No streaming endpoint** needed (codebase uses non-streaming only)
3. **No function calling** needed (codebase uses text-only parts)
4. **Thinking parts optional**: The fake can include `thought` parts in the response if testing thinking config, but the codebase filters them out via `not part.thought`
5. **Usage metadata** is read and stored but not critical for correctness -- the fake can return approximate values
6. **Model name in URL** will be `models/gemini-3-pro-preview` or `models/gemini-3.1-pro-preview`

### Open Questions
1. **Does the codebase ever call `generate_content_stream`?** No -- confirmed via grep. But the ADK `LlmAgent` might in theory switch to streaming for bidi connections.
2. **Does ADK strip `_url` keys before sending?** Yes -- `_build_request()` deletes all keys starting with `_`.
3. **Does the SDK send the `model` in the body or only in the URL?** Only in the URL. The body does NOT contain a `model` field -- it's extracted to `_url.model` by the transformer and used to construct the path, then stripped.
4. **What timeout does the SDK use?** Default is from `HttpOptions.timeout` (milliseconds). The SDK sends a `X-Server-Timeout` header. The fake should not impose its own timeout.
5. **Does ADK auto-create the genai.Client or re-use one?** ADK's `Gemini` class uses `@cached_property` for `api_client`, so it creates one `Client` instance per `Gemini` model object and reuses it.

---

## 10. Route Table for Fake Server

### Required Route
| Method | Path Pattern | Purpose |
|--------|-------------|---------|
| `POST` | `/v1beta/models/{model}:generateContent` | Main text generation |

### Optional Future Routes
| Method | Path Pattern | Purpose |
|--------|-------------|---------|
| `POST` | `/v1beta/models/{model}:streamGenerateContent?alt=sse` | SSE streaming |
| `POST` | `/v1beta/models/{model}:countTokens` | Token counting |
| `GET`  | `/v1beta/models/{model}` | Model info |
| `GET`  | `/v1beta/models` | List models |

### Request/Response Contract Summary

**Request**:
```
POST /v1beta/models/gemini-3-pro-preview:generateContent HTTP/1.1
Host: localhost:8090
Content-Type: application/json
x-goog-api-key: fake-key

{
  "contents": [
    {"role": "user", "parts": [{"text": "..."}]},
    {"role": "model", "parts": [{"text": "..."}]}
  ],
  "systemInstruction": {
    "parts": [{"text": "system prompt..."}]
  },
  "generationConfig": {
    "temperature": 0.0,
    "thinkingConfig": {"includeThoughts": true, "thinkingBudget": 1024}
  }
}
```

**Response**:
```
HTTP/1.1 200 OK
Content-Type: application/json

{
  "candidates": [{
    "content": {
      "role": "model",
      "parts": [{"text": "response text"}]
    },
    "finishReason": "STOP",
    "index": 0
  }],
  "usageMetadata": {
    "promptTokenCount": 100,
    "candidatesTokenCount": 50,
    "totalTokenCount": 150
  },
  "modelVersion": "gemini-3-pro-preview"
}
```

**Error Response (429)**:
```
HTTP/1.1 429 Too Many Requests
Content-Type: application/json

{
  "error": {
    "code": 429,
    "message": "Resource exhausted.",
    "status": "RESOURCE_EXHAUSTED"
  }
}
```

---

## 11. Env Var Quick Reference for Fake

```bash
# Point SDK to fake server
export GOOGLE_GEMINI_BASE_URL="http://localhost:8090/"

# Provide a fake API key (SDK requires one for non-Vertex)
export GEMINI_API_KEY="fake-key-for-testing"

# Unset any real keys to avoid confusion
unset GOOGLE_API_KEY
```

---

## 12. Source File References

### SDK Source (in .venv)
- Client init: `.venv/.../google/genai/client.py` (line 345)
- Base URL resolution: `.venv/.../google/genai/_base_url.py`
- API client (request building): `.venv/.../google/genai/_api_client.py` (line 1052 `_build_request`, line 541 `__init__`)
- Model transforms: `.venv/.../google/genai/models.py` (line 1285 `_GenerateContentParameters_to_mldev`, line 950 `_GenerateContentConfig_to_mldev`, line 1352 `_GenerateContentResponse_from_mldev`)
- Error classes: `.venv/.../google/genai/errors.py`
- Retry logic: `.venv/.../google/genai/_api_client.py` (line 449 `_RETRY_HTTP_STATUS_CODES`, line 464 `retry_args`)
- ADK Gemini LLM: `.venv/.../google/adk/models/google_llm.py` (line 83 `Gemini`, line 298 `api_client`)

### Repo Source
- Agent factory: `rlm_adk/agent.py` (line 140 `create_reasoning_agent`, line 200 `create_rlm_orchestrator`)
- Worker pool: `rlm_adk/dispatch.py` (line 50 `WorkerPool`, line 201 `create_dispatch_closures`)
- Orchestrator loop: `rlm_adk/orchestrator.py` (line 66 `RLMOrchestratorAgent`, line 53 `is_transient_error`)
- Reasoning callbacks: `rlm_adk/callbacks/reasoning.py` (response text extraction, usage metadata)
- Worker callbacks: `rlm_adk/callbacks/worker.py` (prompt injection, response extraction)
