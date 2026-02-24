# Verifying Gemini API Token Usage via gcloud CLI

Cross-references token counts from the RLM observability plugin (`rlm_observability.yaml`) against the actual usage registered on the Google Cloud project via Cloud Monitoring APIs.

## Prerequisites

- `gcloud` CLI installed and authenticated
- Project `geminilogs` with the following APIs enabled:
  - `generativelanguage.googleapis.com` (Generative Language API)
  - `monitoring.googleapis.com` (Cloud Monitoring API)
- A `GOOGLE_API_KEY` configured in `.env` (used by the RLM agent at runtime)

## Step 1: Identify the API Key and Project

The API key is stored in `.env` as `GOOGLE_API_KEY`. The key itself is associated with the GCP project `geminilogs`. We do **not** need to pass the API key to any gcloud command -- gcloud authenticates via OAuth, and the Cloud Monitoring data is associated with the project, not the individual key.

## Step 2: Confirm gcloud Authentication and Project

```bash
# Check active account and project
gcloud config list
```

Output confirms:
- `account = rawley.stanhope@gmail.com`
- `project = geminilogs`

```bash
# Verify authenticated identity
gcloud auth list
```

Output confirms `rawley.stanhope@gmail.com` is the active credentialed account.

## Step 3: Verify Enabled APIs

```bash
gcloud services list --enabled --project=geminilogs
```

Output:
```
NAME                               TITLE
aiplatform.googleapis.com          Vertex AI API
cloudaicompanion.googleapis.com    Gemini for Google Cloud API
cloudtrace.googleapis.com          Cloud Trace API
generativelanguage.googleapis.com  Generative Language API
logging.googleapis.com             Cloud Logging API
monitoring.googleapis.com          Cloud Monitoring API
```

Key APIs: `generativelanguage.googleapis.com` (where Gemini API calls are tracked) and `monitoring.googleapis.com` (how we query usage).

## Step 4: Discover Available Metric Types

The `gcloud monitoring` CLI has limited subcommands, so we use the Monitoring REST API directly with an OAuth bearer token.

```bash
# Get an OAuth access token
TOKEN=$(gcloud auth print-access-token)

# List all metric descriptors for the generativelanguage API
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://monitoring.googleapis.com/v3/projects/geminilogs/metricDescriptors?filter=metric.type%20%3D%20starts_with(%22generativelanguage%22)&pageSize=100" \
  -o /tmp/gl_metrics.json
```

Then filter for token-related and request-related metrics:

```bash
python3 -c "
import json
with open('/tmp/gl_metrics.json') as f:
    data = json.load(f)
for d in data.get('metricDescriptors',[]):
    t = d['type']
    if 'token' in t.lower() or 'generate_content' in t.lower() or 'request' in t.lower():
        print(t)
        print(f'  -> {d.get(\"description\",\"\")}')
        print()
"
```

### Key Metrics Discovered

| Metric Type | Description |
|-------------|-------------|
| `generativelanguage.googleapis.com/quota/generate_content_paid_tier_input_token_count/usage` | Input token count per model per minute (paid tier) |
| `generativelanguage.googleapis.com/quota/generate_requests_per_model/usage` | Request count per model per minute |
| `generativelanguage.googleapis.com/quota/generate_content_free_tier_input_token_count/usage` | Input token count (free tier -- empty if on paid tier) |

**Note:** Google Cloud Monitoring tracks **input tokens** and **request counts** for quota/rate-limiting purposes. **Output tokens are not tracked** in these quota metrics.

## Step 5: Query Daily Aggregate -- Request Counts per Model

```bash
TOKEN=$(gcloud auth print-access-token)

curl -s -H "Authorization: Bearer $TOKEN" \
  "https://monitoring.googleapis.com/v3/projects/geminilogs/timeSeries?filter=metric.type%3D%22generativelanguage.googleapis.com%2Fquota%2Fgenerate_requests_per_model%2Fusage%22&interval.startTime=2026-02-09T00:00:00Z&interval.endTime=2026-02-10T00:00:00Z&aggregation.alignmentPeriod=86400s&aggregation.perSeriesAligner=ALIGN_SUM"
```

Result:
| Model | Requests (Feb 9) |
|-------|-------------------|
| `gemini-2.5-flash` | 105 |
| `gemini-3-pro` | 27 |

## Step 6: Query Daily Aggregate -- Input Token Counts per Model

```bash
TOKEN=$(gcloud auth print-access-token)

curl -s -H "Authorization: Bearer $TOKEN" \
  "https://monitoring.googleapis.com/v3/projects/geminilogs/timeSeries?filter=metric.type%3D%22generativelanguage.googleapis.com%2Fquota%2Fgenerate_content_paid_tier_input_token_count%2Fusage%22&interval.startTime=2026-02-09T00:00:00Z&interval.endTime=2026-02-10T00:00:00Z&aggregation.alignmentPeriod=86400s&aggregation.perSeriesAligner=ALIGN_SUM"
```

Result (deduplicated by model -- each model appears twice, once per limit_name):
| Model | Limit Name | Input Tokens (Feb 9) |
|-------|-----------|----------------------|
| `gemini-2.5-flash` | `GenerateContentPaidTierInputTokensPerModelPerMinute` | 63,559 |
| `gemini-3-pro` | `GenerateContentPaidTierInputTokensPerModelPerMinute` | **679,205** |

The `gemini-3-pro` total of **679,205** matches the observability log's `llm_prompt_tokens: 679,205` exactly.

## Step 7: Query Per-Minute Breakdown (Raw Time Series)

To see the per-minute distribution, query **without** aggregation parameters:

```bash
TOKEN=$(gcloud auth print-access-token)

curl -s -H "Authorization: Bearer $TOKEN" \
  "https://monitoring.googleapis.com/v3/projects/geminilogs/timeSeries?filter=metric.type%3D%22generativelanguage.googleapis.com%2Fquota%2Fgenerate_content_paid_tier_input_token_count%2Fusage%22%20AND%20metric.labels.model%3D%22gemini-3-pro%22&interval.startTime=2026-02-09T00:00:00Z&interval.endTime=2026-02-10T00:00:00Z" \
  -o /tmp/gl_tokens_raw.json

python3 -c "
import json
with open('/tmp/gl_tokens_raw.json') as f:
    data = json.load(f)
for ts in data.get('timeSeries',[]):
    limit = ts['metric']['labels']['limit_name']
    print(f'Limit: {limit}')
    for p in ts['points']:
        print(f'  {p[\"interval\"][\"startTime\"]} -> {p[\"interval\"][\"endTime\"]}: {p[\"value\"][\"int64Value\"]} tokens')
    print()
"
```

Result (`GenerateContentPaidTierInputTokensPerModelPerMinute`):

| UTC Window | Input Tokens |
|------------|-------------|
| 16:58:32 - 16:59:32 | 12,272 |
| 16:59:32 - 17:00:32 | 65,164 |
| 17:00:32 - 17:01:32 | 113,589 |
| 17:01:32 - 17:02:32 | 88,290 |
| 17:02:32 - 17:03:32 | 228,308 |
| 17:03:32 - 17:04:32 | 171,582 |
| **Total** | **679,205** |

This corresponds to the local-time run window 11:59:03 - 12:03:43 EST (UTC-5).

## Step 8: Query Per-Minute Request Counts

```bash
TOKEN=$(gcloud auth print-access-token)

curl -s -H "Authorization: Bearer $TOKEN" \
  "https://monitoring.googleapis.com/v3/projects/geminilogs/timeSeries?filter=metric.type%3D%22generativelanguage.googleapis.com%2Fquota%2Fgenerate_requests_per_model%2Fusage%22%20AND%20metric.labels.model%3D%22gemini-3-pro%22&interval.startTime=2026-02-09T00:00:00Z&interval.endTime=2026-02-10T00:00:00Z" \
  -o /tmp/gl_reqs_raw.json

python3 -c "
import json
with open('/tmp/gl_reqs_raw.json') as f:
    data = json.load(f)
for ts in data.get('timeSeries',[]):
    limit = ts['metric']['labels']['limit_name']
    total_reqs = sum(int(p['value']['int64Value']) for p in ts['points'])
    print(f'Limit: {limit}')
    for p in ts['points']:
        print(f'  {p[\"interval\"][\"startTime\"]} -> {p[\"interval\"][\"endTime\"]}: {p[\"value\"][\"int64Value\"]} requests')
    print(f'  TOTAL: {total_reqs}')
    print()
"
```

Result (`GenerateRequestsPerMinutePerProjectPerModel`):

| UTC Window | Requests |
|------------|----------|
| 16:59:11 - 17:00:11 | 4 |
| 17:00:11 - 17:01:11 | 5 |
| 17:01:11 - 17:02:11 | 6 |
| 17:02:11 - 17:03:11 | 6 |
| 17:03:11 - 17:04:11 | 6 |
| **Total** | **27** |

This matches the 27 `llm_request` / `llm_response` entries in the observability YAML.

## Verification Summary

| Metric | Observability Log | Cloud Monitoring | Match |
|--------|-------------------|------------------|-------|
| Input tokens (gemini-3-pro) | 679,205 | 679,205 | Exact |
| LLM request count | 27 | 27 | Exact |
| Output tokens | 3,596 | N/A (not tracked in quota metrics) | -- |
| Cached tokens | 474,641 | N/A (not tracked in quota metrics) | -- |

## Why They Match Exactly

The observability plugin (`rlm_agent/observability_plugin.py`, lines 447-451) reads token counts from `llm_response.usage_metadata`, which is parsed from the Gemini API HTTP response body's `usageMetadata` field. Cloud Monitoring reads from the same server-side counters. Both sources reflect the **same server-computed token counts** -- the plugin is not estimating LLM tokens independently.

```
Gemini API server
  +-- HTTP response body --> usageMetadata --> ADK LlmResponse.usage_metadata
  |     \-- plugin reads & accumulates --> token_ledger in YAML
  |
  \-- server-side metrics pipeline --> Cloud Monitoring quota time series
        \-- what we queried via gcloud + REST API
```

## Notes

- **Timezone**: Log timestamps are local EST (UTC-5). Cloud Monitoring uses UTC.
- **Model name mapping**: Code uses `gemini-3-pro-preview`; Cloud Monitoring normalizes to `gemini-3-pro`.
- **Tier**: The API key is on the **paid tier** (free tier metrics returned empty).
- **Ingest delay**: Cloud Monitoring quota metrics have a ~150s ingest delay. Per-minute data is available after that, but fine-grained queries with narrow windows may return empty if not aligned to the metric's native period.
- **gcloud CLI limitations**: `gcloud monitoring` doesn't expose `metricDescriptors` or `timeSeries` subcommands directly. Use the REST API at `https://monitoring.googleapis.com/v3/` with `gcloud auth print-access-token` for the bearer token.