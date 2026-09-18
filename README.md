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
LOGFIRE_TOKEN=<your-logfire-write-token>
```

Use the gateway **root**. The route name is appended by the code, so including it here doubles it.

`LOGFIRE_TOKEN` is a separate thing from the gateway key: it is a project **write token**, created
under **Logfire → project settings → Write tokens**, and it is what `logfire.configure()` in
`script.py` uses to send the trace. Without it the script stops mid-run and asks you to
authenticate interactively. `uv run logfire auth` followed by `uv run logfire projects use <project>`
works too — it writes the same credentials to `.logfire/` instead of `.env`.

Then set the model in `script.py` to the same repo ID you deployed in step 3:

```python
model = OpenAIChatModel('<MODEL>', provider=provider)
```

```bash
uv run --env-file .env script.py
```

`script.py` ships with an email-drafting prompt, so the first run prints an email. This is your
**before** baseline, with no optimization installed yet:

```
Logfire project URL: https://logfire-eu.pydantic.dev/<org>/<project>
Subject: Declining Sprint Planning Invitation - Design Team

Hi [Name],

Thank you for the invitation to the sprint planning session with the design team...

Best regards,
[Your Name]
```

The Logfire URL printed at startup shows the trace.

## 7. Gateway Optimizations

Optimizations live in the gateway rather than in your code. They inject directives into outbound
requests, so they shape how the model behaves on every call through a route without you touching
`script.py`.

The feature is behind a flag. Add this to the end of your Logfire project URL:

```
#enableFlags=gateway_optimizations
```

So `https://logfire-eu.pydantic.dev/<org>/<project>` becomes:

```
https://logfire-eu.pydantic.dev/<org>/<project>#enableFlags=gateway_optimizations
```

That turns on the **Optimizations** tab under **Gateway**.

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

## 🏆 Hackathon prize: change your agent's behavior from the gateway

Your agent code does not change today. `script.py` stays exactly as it is. Everything you do
happens in the gateway — an optimization rule that changes how the model behaves.

**The challenge:** make a visible, defensible change to your agent's behavior using an
optimization on your `modal` route, and show the before and after.

### First, prove the lever works — Caveman mode

Before doing anything clever, install a built-in rule so you can see the gateway really reaching
the model. Go to **Gateway → Optimizations**, find **Caveman mode (terse)** in the recommended
catalog, and install it.

It is a `Style` rule with action `Transform`. Its injected instruction is fixed — built-in rules
cannot be edited, only targeted, enabled, disabled or deleted:

```
STYLE: Output is terse. Drop articles, filler, and hedging. Preserve technical precision.
Short sentences. No restating the question.
```

Under **Targeting**, add a binding to route `modal` (whole route). The rule page shows a **Usage**
chart of requests it ran on and requests it changed — that is your confirmation it fired.

Now set the prompt in `script.py` to something that normally gets a long answer:

```python
result = agent.run_sync('Explain how HTTPS certificate validation works.')
```

Run it with the rule disabled, then enabled. Same code, same model, same prompt:

**Disabled** — 596 words, opening with an intro, four `###` sections, and a summary table:

```
To understand HTTPS certificate validation, you first have to understand the goal: **Trust.**

When your browser connects to `https://google.com`, it needs to know that it is actually
talking to Google's servers and not a hacker sitting in the middle...

### 1. The Foundation: The Trust Store
...
```

**Enabled** — 162 words, straight into a numbered list, no preamble:

```
1. **TCP Handshake**: Client establishes connection to server.
2. **Server Hello**: Server sends SSL/TLS certificate containing its public key.
3. **Chain Verification**: Client checks certificate issuer. It follows a chain of trust from
   the server certificate to intermediate certificates, ending at a pre-installed **Root
   Certificate Authority (CA)** in the browser/OS trust store.
...
```

**73% fewer words, and no technical content lost** — the chain of trust, hostname matching,
expiry, CRL/OCSP revocation and key exchange all survive. That is the rule doing exactly what it
says: drop articles, filler and hedging, preserve technical precision.

Note what it is *not*. The name is a joke about dropped articles, not a request for caveman
diction — the model keeps its technical register because the instruction explicitly tells it to.
Read the injected instruction, not the rule name, when predicting what a rule will do.

Five minutes, and you now know the wiring is correct before investing in a real rule.

### Then make it useful

Swap the caveman rule for something you would actually ship — from the 36 built-in rules, the
recommended sets, or your own. Good directions:

- Cut output tokens without losing the answer
- Force a strict output shape your app can parse
- Change tool-calling or reasoning behavior
- Something specific to your domain that no off-the-shelf rule covers

### What to submit

Show your work with evidence, not description:

1. **The rule** — a screenshot or the text of its injected instruction
2. **Before and after outputs** — same prompts, run with and without, pasted side by side
3. **Logfire trace links** — one baseline, one optimized
4. **Numbers, if your change is the kind that has numbers** — median output tokens, latency or
   cost from Logfire

### How entries are judged

1. **Is the behavior change real and visible?** Before and after must differ in a way a judge can
   see without taking your word for it.
2. **Is it worth doing?** A rule that solves a real problem beats one that only shows off.
3. **Is it yours?** A custom rule written for your own use case beats installing something
   off-the-shelf unchanged.

The caveman rule is the warm-up, not an entry. It proves the mechanism; the prize goes to what you
do with it.

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
| Trace shows `[Scrubbed due to 'session']` instead of the output | Logfire's default scrubbing redacts values containing words like *session*, *token* or *secret*, and a model reply about a *sprint planning session* trips it. The output is still in the `chat` span; pass a `scrubbing` callback to `logfire.configure()` if you need it verbatim in your own log. |

### Scale to zero

The endpoint releases its container after roughly 15 minutes idle, and the next request returns
503 while it restarts. This is normal and not a misconfiguration. Retry, or keep a warm container
if you are demoing live.
