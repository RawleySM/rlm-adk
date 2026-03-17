# Google Cloud Project: Gemini API — Workspace API Configuration

## Project Details

| Field | Value |
|---|---|
| **Project Name** | Gemini API |
| **Project ID** | `gen-lang-client-0730373468` |
| **Project Number** | `1030663661375` |
| **Created** | 2025-05-13 |
| **Lifecycle** | ACTIVE |
| **Billing** | Enabled (`billingAccounts/01CC21-A8C1AA-6BB0C3`) |
| **Owner** | `rawley.stanhope@gmail.com` |
| **Token Location** | `/home/rawley-stanhope/dev/rlm-adk/token.json` |
| **Client Secret Location** | `/home/rawley-stanhope/dev/rlm-adk/client_secret.json` |

## API Keys

| Display Name | UID | Restrictions | Created |
|---|---|---|---|
| Generative Language API Key | `5f2b8a36-c0ce-4a21-aec0-6dc4a78970c0` | Locked to `generativelanguage.googleapis.com` | 2025-05-13 |
| Gemini | `4cd9e204-3150-448b-84d2-721c375e6253` | Locked to `generativelanguage.googleapis.com` | 2025-10-01 |
| API key 3 | `7cdf0ab5-157c-4fc3-8425-0fc4facdc5f7` | **Unrestricted** | 2026-02-20 |

> **Note:** API key 3 is unrestricted — it can call any enabled API including Google Drive. Consider restricting it if not needed for Workspace access.

## Service Accounts

| Email | Display Name | Role |
|---|---|---|
| `1030663661375-compute@developer.gserviceaccount.com` | Default compute service account | `roles/editor`, `roles/aiplatform.admin`, `roles/iam.devOps`, `roles/gsuiteaddons.developer` |
| `rlm-agent-sa@gen-lang-client-0730373468.iam.gserviceaccount.com` | RLM Agent Service Account | `roles/logging.logWriter`, `roles/cloudtrace.agent`, `roles/monitoring.metricWriter`, `roles/storage.objectAdmin` |

## IAM Bindings (User)

| Role | Member |
|---|---|
| `roles/owner` | `rawley.stanhope@gmail.com` |
| `roles/apphub.admin` | `rawley.stanhope@gmail.com` |
| `roles/cloudhub.operator` | `rawley.stanhope@gmail.com` |
| `roles/designcenter.admin` | `rawley.stanhope@gmail.com` |

## Enabled APIs (64 total)

### Google Workspace APIs (All Enabled)

| API | Status | Programmatic Access |
|---|---|---|
| `drive.googleapis.com` (Google Drive API) | **ENABLED** | Read/write files, list folders, search, export Google Docs/Sheets as PDF/text |
| `gmail.googleapis.com` (Gmail API) | **ENABLED** | Read/send emails, search messages, access attachments, manage labels |
| `docs.googleapis.com` (Google Docs API) | **ENABLED** | Read/write Google Docs content programmatically (structured JSON) |
| `sheets.googleapis.com` (Google Sheets API) | **ENABLED** | Read/write spreadsheet data, cell-level access |
| `calendar-json.googleapis.com` (Google Calendar API) | **ENABLED** | Read/create events, manage calendars |
| `tasks.googleapis.com` (Google Tasks API) | **ENABLED** | Read/write tasks, manage task lists |
| `people.googleapis.com` (People API) | **ENABLED** | Access contacts and profile information |

### AI & ML APIs

| API | Purpose |
|---|---|
| `generativelanguage.googleapis.com` | Gemini API (primary LLM endpoint) |
| `aiplatform.googleapis.com` | Vertex AI (model training, endpoints, Reasoning Engine) |
| `cloudaicompanion.googleapis.com` | Gemini for Google Cloud |
| `geminicloudassist.googleapis.com` | Gemini Cloud Assist |

### Data & Analytics APIs

| API | Purpose |
|---|---|
| `bigquery.googleapis.com` | BigQuery core |
| `bigquerystorage.googleapis.com` | BigQuery Storage (fast reads) |
| `bigqueryconnection.googleapis.com` | External connections |
| `bigquerydatapolicy.googleapis.com` | Data policy management |
| `bigquerydatatransfer.googleapis.com` | Scheduled transfers |
| `bigquerymigration.googleapis.com` | Migration tools |
| `bigqueryreservation.googleapis.com` | Slot reservations |
| `analyticshub.googleapis.com` | Data exchange |
| `dataplex.googleapis.com` | Data governance |
| `dataform.googleapis.com` | SQL workflow |

### Infrastructure & Compute

| API | Purpose |
|---|---|
| `compute.googleapis.com` | Compute Engine VMs |
| `container.googleapis.com` | GKE (Kubernetes) |
| `run.googleapis.com` | Cloud Run |
| `cloudbuild.googleapis.com` | Cloud Build CI/CD |
| `artifactregistry.googleapis.com` | Container/package registry |
| `storage.googleapis.com` | Cloud Storage |
| `dns.googleapis.com` | Cloud DNS |
| `pubsub.googleapis.com` | Pub/Sub messaging |

### Observability & Operations

| API | Purpose |
|---|---|
| `logging.googleapis.com` | Cloud Logging (Log ingest) |
| `monitoring.googleapis.com` | Cloud Monitoring (Telemetry/Metrics) |
| `cloudtrace.googleapis.com` | Cloud Trace (Distributed tracing) |
| `observability.googleapis.com` | Observability core |
| `telemetry.googleapis.com` | OpenTelemetry ingest |

### IAM & Security

| API | Purpose |
|---|---|
| `iam.googleapis.com` | IAM management |
| `iamcredentials.googleapis.com` | SA credential generation |
| `iap.googleapis.com` | Identity-Aware Proxy (used for programmatic OAuth) |
| `orgpolicy.googleapis.com` | Org policies |
| `cloudasset.googleapis.com` | Asset inventory |
| `oslogin.googleapis.com` | OS Login |

### Other Enabled Services

`apphub`, `appoptimize`, `apptopology`, `autoscaling`, `capacityplanner`, `cloudquotas`, `config`, `containerfilesystem`, `containerregistry`, `designcenter`, `gkebackup`, `gkeconnect`, `gkehub`, `krmapihosting`, `maintenance`, `multiclustermetering`, `networkconnectivity`, `recommender`, `servicehealth`, `serviceusage`

---

## OAuth 2.0 Configuration (Completed)

### OAuth Consent Screen (Google Auth Platform)

| Setting | Value |
|---|---|
| **App name** | rlm-agent |
| **User support email** | `rawley.stanhope@gmail.com` |
| **Developer contact** | `rawley.stanhope@gmail.com` |
| **User type** | External |
| **Publishing status** | Testing |
| **Test users** | `rawley.stanhope@gmail.com` |
| **OAuth user cap** | 1/100 used |

### OAuth 2.0 Client ID

| Field | Value |
|---|---|
| **Name** | MCP GDrive Server |
| **Type** | Desktop |
| **Client ID** | `1030663661375-52f16902mb74i5ejmded471s5h75pcgk.apps.googleusercontent.com` |
| **Client secret** | `****zkJ6` (verified and in root as `client_secret.json`) |

### Authentication Path & Scripts

For programmatic access from the RLM-ADK codebase:

1. **Auth Script:** `scripts/setup_rlm_agent_auth.py`
   - Configures the authorization flow using the local `client_secret.json`.
   - Produces the persistent `token.json`.
2. **Verification Scripts:**
   - `scripts/test_gmail_pull.py`: Fetches and summarizes latest 10 emails.
   - `scripts/send_love_poem.py`: Tests the `send` scope.

---

## Using Workspace APIs for Understand Benchmark

### What's Available Now

All Workspace APIs are enabled and scoped. Programmatic access includes:

1. **Google Drive** — list/search files, export Docs as text/plain, Sheets as CSV, read metadata
2. **Gmail** — search messages, read email bodies, access attachments, manage labels
3. **Google Docs** — read/write document content as structured JSON
4. **Google Sheets** — read/write spreadsheet data, cell-level access
5. **Google Calendar** — read/create events, manage calendars
6. **People API** — access contacts and profile information

### Python Client Snippet (Sending Email)
```python
import base64
from email.message import EmailMessage
from googleapiclient.discovery import build

# After loading credentials from token.json
service = build('gmail', 'v1', credentials=creds)

message = EmailMessage()
message.set_content("Hello from rlm-agent!")
message['To'] = "recipient@example.com"
message['Subject'] = "Automated Message"

encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
service.users().messages().send(userId='me', body={'raw': encoded_message}).execute()
```

### Key Dependency Packages

```
google-api-python-client
google-auth-httplib2
google-auth-oauthlib
```

---

*Last Updated: 2026-03-15 via Gemini CLI*
