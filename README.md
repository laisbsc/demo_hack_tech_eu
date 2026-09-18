# Inference on Modal, piped through the Pydantic AI Gateway

This demo runs any open-weight model on your own Modal GPU, routes the request through the
Pydantic AI Gateway, and traces it in Logfire. Billing goes to your Modal account, so Modal
credits pay for it.

```
script.py  ──>  Pydantic AI Gateway  ──>  Modal endpoint (vLLM)  ──>  your model
                        │
                        └──>  Logfire trace
```

`<MODEL>` below stands for the Hugging Face repo ID of whichever model you pick, for example
`google/gemma-4-31B-it` or `deepseek-ai/DeepSeek-V4.1-Flash`. The same string is used throughout.

## What you need

- A Modal account with credits
- A Logfire account with a Pydantic AI Gateway
- `uv`

You will add Modal to that gateway as a BYOK (bring your own key) provider in step 5 — the
gateway holds your Modal credentials and calls Modal on your behalf, so your code never talks to
Modal directly.

## 1. Install and authenticate the Modal CLI

```bash
uv tool install modal
modal setup
```

`modal setup` opens a browser to log in.

## 2. Create a proxy token

The gateway authenticates to Modal with this token.

```bash
modal workspace proxy-tokens create
```

It prints a token ID (`wk-…`) and a secret (`ws-…`). **The secret is shown once.** Copy both.

If the token is environment-scoped, allow it into the environment you deploy to:

```bash
modal workspace proxy-tokens allow <token-id> main
```

Skipping this makes step 3 fail with "Create a proxy token to require authentication for this
Endpoint", even though the token exists.

## 3. Create the endpoint

Pick any model from the [Modal Library](https://modal.com/library) — or bring your own weights
from a private Hugging Face repo or a Modal Volume. `--model` takes the Hugging Face repo ID,
which each model's library page shows:

```bash
modal endpoint create --name gateway --model <MODEL>
```

Write that repo ID down. The **same string** goes into the code in step 6.

Size is the one thing worth thinking about. A dense single-GPU model such as
`google/gemma-4-31B-it` schedules quickly; large mixture-of-experts models need several GPUs at
once and can sit unscheduled if capacity is tight. Start small, then scale up once the pipeline
works.

Provisioning takes several minutes. Check with `modal endpoint list`.

## 4. Copy the endpoint URL

Open the endpoint's dashboard page — the URL is printed by step 3, or find it at
[modal.com/endpoints](https://modal.com/endpoints). It looks like:

```
https://<workspace>--ep-<name>-server.<region>.modal.direct
```

This URL is **only** on the dashboard. It is not in `modal endpoint list`, not in its `--json`
output, and not derivable from the workspace and endpoint names.

## 5. Add Modal as a BYOK provider in the gateway

In Logfire, open your Pydantic AI Gateway and add Modal as a provider. Fill in the four fields:

| Field | Value |
| --- | --- |
| Provider name | `modal` |
| Base URL | `<endpoint-url>/v1` (from step 4) |
| Proxy token ID | `wk-…` (from step 2) |
| Proxy token secret | `ws-…` (from step 2) |

Name it `modal` to match this demo. The name you choose is what goes in `route=` in the code, so
if you call it something else, change `route=` to match — a mismatch returns a 404 that lists the
valid names.

<!-- TODO: screenshot of the provider form, filled in -->

The base URL field is prefilled with `https://api.modal.com/v1`. **Replace it.** That host is
Modal's gRPC control plane, not an inference API — leaving it produces an empty response body
that surfaces as a confusing parse error.

This is what BYOK means here: the credentials live in the gateway, not in your app. That is what
lets the gateway meter usage, apply limits, and trace every call while Modal bills your account.

## 6. Configure and run

`.env`:

```bash
PYDANTIC_AI_GATEWAY_BASE_URL=https://gateway-eu.pydantic.dev/proxy
PYDANTIC_AI_GATEWAY_API_KEY=<your-logfire-key>
```

Use the gateway **root**. The route name is appended by the code, so including it here doubles it.

Then set the model in `script.py` to the same repo ID you deployed in step 3:

```python
model = OpenAIChatModel('<MODEL>', provider=provider)
```

```bash
uv run --env-file .env script.py
```

Expected:

```
Here is the output: result.output='Parallel lines have so much in common. It's a shame they'll never meet.'
```

The Logfire URL printed at startup shows the trace.

## 7. Gateway Optimizations and Guardrails

Both features live in the gateway rather than in your code, so they apply to every call through a
route without you touching `script.py`.

- **Optimizations** inject directives into outbound requests — they shape how the model behaves.
- **Guardrails** detect secrets and personal data in requests and let you observe, flag, redact or
  block — they control what data crosses the boundary.

Both are behind a feature flag. Add this to the end of your Logfire project URL:

```
#enableFlags=gateway_optimizations,gateway_guardrails_beta
```

So `https://logfire-eu.pydantic.dev/<org>/<project>` becomes:

```
https://logfire-eu.pydantic.dev/<org>/<project>#enableFlags=gateway_optimizations,gateway_guardrails_beta
```

That turns on the **Optimizations** and **Guardrails** tabs under **Gateway**.

### Installing an optimization

Go to **Gateway → Optimizations → New optimization**. Write a custom rule, or pick from the 36
existing ones and the recommended sets.

<!-- TODO: screenshot of the Optimizations tab -->

Installing is two steps. Step 1 is the rule; **step 2 is "Choose endpoints"**, where you tick which
endpoints it installs on. Tick `modal` — the name you gave the provider in step 5. You must select
at least one.

<!-- TODO: screenshot of the Choose endpoints step -->

All 36 rules can be installed on a Modal endpoint. The provider tags on some cards (`anthropic`,
`openai`, `google-vertex`) say which model a rule was tuned for, not where you can install it. A
rule grounded in one vendor's quirks may not transfer, though — "Let reasoning models plan
internally" is about the o-series, "Use extended thinking" is about Claude's thinking blocks.
Whether they help an open-weight model is an empirical question.

### Adding a guardrail

Go to **Gateway → Guardrails**. Guardrails detect and anonymize information before it reaches a
model. The tab has two views: **Protections** (the rules) and **Connections** (external engines).

Eleven prebuilt protections ship enabled, covering common credentials:

| | |
| --- | --- |
| Anthropic API keys | OpenAI API keys |
| AWS access key IDs | Prefect Cloud API keys |
| GitHub personal access tokens | Slack tokens |
| GitLab personal access tokens | SSH / PEM private keys |
| Google API keys | Stripe live keys |
| JSON Web Tokens | |

**They all default to `Observe` on all requests** — they detect and record, but change nothing.
That matters for the prize: an untouched protection produces a trace entry, not a redaction.

**New protection** starts from one of three:

- **Prebuilt protection** — curated templates for secrets, personal data, financial data, network
  identifiers
- **Custom pattern** — your own regex; each protection matches one pattern
- **Presidio protection** — your own Presidio service for detecting and redacting personal data

A custom pattern takes a name, an optional description, and the regex, with live syntax
validation. **Pattern tests** let you run sample messages against the pattern before saving, and
the samples are stored with the protection — worth using, since a regex that misses is
indistinguishable from a guardrail that never fired.

<!-- TODO: screenshot of the New protection form -->

Then choose where it applies and what it does:

- **Apply to:** all endpoints, or specific endpoints with a per-endpoint action. Pick your `modal`
  endpoint if you only want it on this route.
- **Action:** `Off`, `Observe`, `Flag response`, `Redact`, or `Block`.

## 🏆 Hackathon prize: best gateway config

Install one optimization and one guardrail on your `modal` route and measure both. The entry is
**six numbers and four trace links**.

### Set up a baseline

Write 10 fixed prompts representative of what your agent does. Run them with no optimization
installed. This is your baseline, and you reuse the same 10 prompts for every measurement.

### Optimization: report the delta

Install one optimization on the `modal` endpoint, rerun the same 10 prompts, and report from
Logfire:

| Metric | Before | After |
| --- | --- | --- |
| Median output tokens | | |
| Median latency (ms) | | |
| Total cost for the 10 runs | | |

Link the baseline trace and the after trace.

**Qualifies if** one of the three metrics improves by at least 20% and the outputs still answer
the prompts. A rule that halves token count by making the model useless does not count — paste two
sample outputs so a judge can see they still work.

### Guardrail: report catch rate

Create a protection, set its action to **Redact** or **Block** (`Observe` does not count), and
scope it to your `modal` endpoint. Then build a 20-line test set:

- 10 inputs containing the data you are protecting
- 10 that look similar but should not match

Report:

| Metric | Value |
| --- | --- |
| Caught (of 10) | |
| False positives (of 10) | |
| Action used | Redact / Block |

Link a trace showing a redaction and a trace showing a clean request passing through.

**Qualifies if** you catch at least 9 of 10 with 0 false positives.

### Scoring

Among qualifying entries:

1. **Largest verified improvement** on your chosen optimization metric
2. **Tiebreak:** a custom regex or custom rule beats an off-the-shelf one
3. **Tiebreak:** a guardrail catching something specific to your domain beats a prebuilt
   credential detector

Both halves must qualify. An entry with a great optimization and an `Observe`-only guardrail
scores nothing.

## How the code picks its client

```python
provider = gateway_provider('openai-chat', route='modal')
model = OpenAIChatModel('<MODEL>', provider=provider)
```

`OpenAIChatModel` names the **wire protocol**, not the model vendor. Modal serves every model
through vLLM, which implements OpenAI's `/chat/completions` format, so this is the right client
whoever trained the weights — Google, DeepSeek, Qwen, Moonshot or your own fine-tune.

This is why the guide works for any model: swapping models means changing the repo ID in two
places (the `modal endpoint create` command and this line) and nothing else.

`'openai-chat'` rather than the default: Modal implements `/chat/completions` but not
`/responses`, which the plain `openai` flavor would use.

`route='modal'` is the name of the provider in your gateway. A wrong route returns a 404 listing
the valid names.

## The `metadata` workaround

`script.py` widens one field before making any request:

```python
for _model in (ChatCompletion, _ChatCompletion):
    _model.model_fields['metadata'].annotation = dict[str, Any] | None
    _model.model_rebuild(force=True)
```

Modal returns `metadata.weight_versions` as a list; the OpenAI schema types `metadata` as
`dict[str, str]`. Without this, the request succeeds and the response is then discarded with
`UnexpectedModelBehavior: 1 validation error`.

Both classes need widening because the payload passes through both — the SDK's model serializes
it (producing a warning) and pydantic-ai's validates it (producing the error).

## Troubleshooting

| Symptom | Cause |
| --- | --- |
| `503 modal_no_live_containers` | Endpoint scaled to zero. Retry; cold start is ~2 min. |
| `'str' object has no attribute 'output'` or `expected JSON data` | Gateway base URL still points at `api.modal.com`. |
| `404 unknown inference model` | Wrong host — that is the *shared* endpoint host. Dedicated endpoints have their own URL (step 4). |
| `UnexpectedModelBehavior: 1 validation error` | The `metadata` widening is missing. |
| `UserError: Unknown upstream provider` | First argument to `gateway_provider` must be an API flavor, not a provider name. |
| `Route not found` | The `route=` name does not exist in your gateway. The error lists the valid ones. |

### Scale to zero

The endpoint releases its container after roughly 15 minutes idle, and the next request returns
503 while it restarts. This is normal and not a misconfiguration. Retry, or keep a warm container
if you are demoing live.
