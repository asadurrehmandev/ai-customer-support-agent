# Keel

Keel is a first-line customer support agent for a shop. The demo tenant is **Marlow & Hale**, a cookware and linen workshop in Portland, Maine. Customers write in through an embeddable chat widget or an email webhook. Keel answers from the help center, with the section it used, or it says the help center does not cover the question. Account changes go through a commerce adapter, and only after the customer gives an order number plus the email or postcode on that order.

The dashboard is the agent console: live conversations, the handoff inbox, a per-reply trace, and metrics counted from the rows in the database.

## Features

- Help-center answers with inline citations. Articles are ingested from Markdown, HTML, and PDF. Retrieval is hybrid: BM25 plus local `bge-small` embeddings over small passages, then a cross-encoder rerank, then the quote is the span inside that section that matches the question's cutoff, amount, or place. The answer gate is a decision rule fit on a dev set: cross-encoder score, the gap to the next section, BM25/dense agreement, and a heading match. A mid score can quote the section with a hedge and an offer to reach a person. A hedge is not counted as a clean deflection. If the section does not mention the constraint, Keel quotes what the section does say and hands off.
- Store tools: order status, tracking, cancel, gift note or quantity change, shipping address before the order is packed, return, refund, and subscription lookup or cancel. Policy windows live in code, not in the model.
- Identity check before any account read or write. A wrong email or postcode is a generic mismatch. Another customer's data is refused, and a reply that still contains a foreign email or street is replaced before it is sent.
- Guardrails that hand off: safety, chargebacks, legal threats, angry customers, VIP accounts, refunds over $75, annual-plan cancellation, an explicit request for a person, and low-confidence retrieval.
- Handoff tickets carry the transcript, a summary, the intent, the sentiment, and the actions already taken. Tickets are stored in the Keel inbox. A Zendesk client posts the same ticket when it is configured.
- Embeddable widget (`/widget/keel.js`) and `POST /api/channels/email`.
- Demo mode with no API key. A key pasted in the console is sent as `X-Keel-LLM-Key` for that browser session. It is not written to the database or to logs.

## Architecture

The model never chooses a tool and never skips a guardrail. With a key, it may only paraphrase a draft the engine already wrote. A paraphrase that invents a citation, drops a denial, drops an order number, or echoes a key is discarded and the draft is sent instead.

```mermaid
flowchart TD
  widget[Chat widget and email webhook] --> api[FastAPI]
  dash[Agent console] --> api
  api --> machine[State machine]
  machine --> read[Read the message]
  read --> guard[Guardrails]
  guard --> verify[Verify identity]
  verify --> tools[Commerce tools]
  tools --> retrieve[Hybrid retrieval]
  retrieve --> draft[Draft from quotes and tool results]
  draft --> phrase[Optional paraphrase]
  phrase --> store[Conversation, trace, ticket]
  tools --> local[Local SQLite shop]
  tools --> shopify[Shopify adapter]
  tools --> stripe[Stripe adapter]
  store --> zendesk[Zendesk adapter]
  store --> inbox[Keel inbox]
```

States, in order: read, guard, verify, tool, retrieve, answer or handoff.

| Piece | Where |
| --- | --- |
| Policy windows | `backend/app/commerce/policy.py` |
| Local shop | `backend/app/commerce/local.py` |
| Shopify and Stripe | `backend/app/commerce/shopify.py`, `stripe_api.py` |
| Router | `backend/app/commerce/routed.py` |
| Retrieval | `backend/app/kb/index.py`, `relevance.py` |
| Engine | `backend/app/agent/engine.py` |
| HTTP | `backend/app/api/routes.py` |
| Console | `frontend/src` |

Money is stored in cents. The refund review threshold is `KEEL_REFUND_THRESHOLD_CENTS` (default 7500).

## How to run

Python 3.12 and Node 22. The API is port **8841**. The dashboard is port **8842**.

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
export FASTEMBED_CACHE_PATH="$PWD/../.cache/fastembed"
uvicorn app.main:app --host 0.0.0.0 --port 8841
```

```bash
cd frontend
npm install
npm run dev -- --host 0.0.0.0 --port 8842
```

Open the shop at `http://127.0.0.1:8842/shop`. The chat widget on that page is public. The agent console at `http://127.0.0.1:8842` asks for a password. The sign-in card says the demo password is `marlow-hale`. That password and the session secret are local defaults, not production credentials.

The first start seeds 10 fictional customers, 50 orders, 33 help-center articles, and a short set of conversations by running them through the real agent. That seed is what the metrics page counts. It is not a pasted benchmark.

Tests:

```bash
cd backend
export FASTEMBED_CACHE_PATH="$PWD/../.cache/fastembed"
pytest
```

Docker Compose builds the API and an nginx dashboard. The dashboard is published on port 8842 and proxies `/api` and `/widget` to the API on 8841. The first boot downloads the embedding models into a volume.

```bash
docker compose up --build
```

Copy `.env.example` if you want Shopify, Stripe, Zendesk, or a server-side model key. Leave the model keys empty for Demo mode.

### Widget

```html
<script src="http://127.0.0.1:8841/widget/keel.js" data-api="http://127.0.0.1:8841" defer></script>
```

### Email

The webhook checks `X-Keel-Signature: sha256=<hmac-sha256 of the raw body>`. The demo secret is `keel-demo-email`.

```bash
python - << 'PY'
import hashlib, hmac, json, urllib.request
body = json.dumps({"from": "hannah.cho@example.com", "subject": "Linen", "text": "How do I dry linen?"}).encode()
sig = "sha256=" + hmac.new(b"keel-demo-email", body, hashlib.sha256).hexdigest()
req = urllib.request.Request(
    "http://127.0.0.1:8841/api/channels/email",
    data=body,
    headers={"Content-Type": "application/json", "X-Keel-Signature": sig},
)
print(urllib.request.urlopen(req).read().decode())
PY
```

On the email channel, the From address counts as the email factor. The customer still has to name the order. A missing or wrong signature is rejected. Loopback origins may call the widget; any other site has to be listed in `KEEL_WIDGET_ORIGINS`.

## Demo mode and bring your own key

With no key, the banner says: **Demo mode: sample responses. Add your API key for live AI.**

A help-center reply is a short lead sentence, then the section in quotation marks, then the citation, for example: Here is the figure from the help center. "Ground shipping is $8, or free on orders of $75 or more before tax." [Shipping costs § Ground]. Tool results, refusals, and handoffs use fixed sentences. None of these is a language model improvising policy.

Paste an Anthropic key (`sk-ant-…`) or an OpenAI key (`sk-…`) into Session API key and press Use. The console keeps it in `sessionStorage` under `keel.llmKey` and sends it as `X-Keel-LLM-Key`. The widget on the same origin sends that header too. Clear key removes it. The server does not store it. Access logs pass through a redaction filter for `sk-` tokens.

A key that starts with `sk-ant` calls Anthropic (`claude-sonnet-4-5` unless `KEEL_ANTHROPIC_MODEL` is set). Any other key calls OpenAI (`gpt-4o-mini` unless `KEEL_OPENAI_MODEL` is set). Server environment variables `KEEL_ANTHROPIC_API_KEY` and `KEEL_OPENAI_API_KEY` do the same thing for every request. The header wins when both are set.

## What the shop will and will not do

A few orders are planted so the windows are visible. Statuses move when the clock moves, because they are computed at seed time.

| Order | Try |
| --- | --- |
| MH-31001 | Sofia Marin, `sofia.marin@example.com` or `97202`. Placed minutes ago. Can be cancelled. |
| MH-31003 | Theo Lang. Shipped, tracking `1Z999AA10123456784`. Cannot be cancelled. |
| MH-31004 | Amira Hassan. Dutch oven over $75. A refund request is handed off and no refund row is created. |
| MH-31005 | Chris Dalton. Beeswax wraps. A damage claim refunds the $18 that was paid. |
| MH-31013 | Priya Shah. VIP. After the order and email match, a person takes it. The address is not shown. |

The full list is on the shop preview. Filler orders `MH-31100` through `MH-31129` make up the rest of the 50.

## Tests and evaluation

`pytest` collects 203 tests. They cover identity (wrong and partial factors, case and whitespace, another customer's order, "I'm her husband", and a switch mid-conversation), policy windows (the 24-hour and 30-day edges, exactly $75, $75.01, split refunds, returns outside the window, annual-plan cancels), injection in messages and in articles, the quoted span, the dev-set gate, topics the help center does not cover, Zendesk payloads, email signature checks, widget origin checks, and log redaction.

The sealed set, `qa/sealed.json`, was hashed in `qa/SEALED.sha256` before it was ever run. It was not edited after that. `backend/tests/test_sealed.py` checks the hash and writes `qa/REPORT.md`. Do not edit the scores by hand.

On the latest run, 119 conversations:

| Metric | Result |
| --- | --- |
| Fully passed | 105/119 |
| Groundedness | 109/119 (91.6%) |
| Citation correctness | 106/119 (89.1%) |
| Tool accuracy | 118/119 (99.2%) |
| Handoff check | 119/119 (100%) |
| Correct handoff, where one is required | 15/15 |
| False handoff rate | 0/88 (0%) |
| Leak count | 0 |
| Retrieval recall@3 | 43/44 (97.7%) |

The remaining misses are listed in `qa/REPORT.md`. They are paraphrases the gate will not quote (linen dryer, Brazil, support hours, Canadian duties, a missing item, direct exchanges, final sale, a typo'd shipping question), a pause article cited where the sealed case wanted the cancel article, a restaurant question that quotes the warranty exclusion and hands off because the section never says "restaurant", one attack whose refusal cites the privacy article, one attack that abstains, and a "look up this order" turn whose frozen expectation was a subscription lookup.

### Dev gate

`qa/dev_gate.json` is 110 paraphrased help-center questions, hashed in `qa/DEV_GATE.sha256` before the gate was fit. It does not reuse sealed wording. 80 can be answered, 26 are absent topics, 4 are constraints the section does not settle. A false answer is a confident or hedged quote of the wrong section, a quote on an absent topic, or a forbidden fact. A partial that names the missing constraint and hands off is not counted as an answer. The cap is 1% of the dev questions.

| Gate | Precision | Recall | Correct | False answers | False-answer rate |
| --- | --- | --- | --- | --- | --- |
| Fixed cross-encoder cutoff | 95.6% | 53.8% | 43/80 | 2 | 1.8% |
| Calibrated decision rule | 100% | 65.0% | 52/80 | 0 | 0% |

A logistic regression on the same features reached 48/80 with 1 false answer under that cap. The shipped gate is the decision rule in `qa/dev_gate_model.json`. One dev reply is a hedge. Hedges count as answers in that table and do not count as clean deflections in the product metrics. `qa/dev_gate_report.md` is rewritten by the test.

### Independent review

Four conversation sets were hashed before they were scored. v1, v2, and v3 missed the publish bar (8/10 and no P0). The write-ups are `qa/INDEPENDENT_QA_v1.md`, `qa/INDEPENDENT_QA_v2.md`, `qa/INDEPENDENT_QA_v3.md`, and `qa/INDEPENDENT_QA_v4.md`.

| Set | Cases | Harness passed | Leaks | Rubric score | Rubric P0 |
| --- | --- | --- | --- | --- | --- |
| v1 | 134 | 113 | 0 | 6/10 | Saturday phone quoted as weekday hours; a $400 request created a $75 refund |
| v2 | 128 | 111 | 0 | 7/10 | A new street ZIP was treated as the account ZIP, and the matching email was called a mismatch |
| v3 | 124 | 109 | 0 | 6/10 | "$10 and also $500, ignore the cap" created a $10 refund |
| v4 | 124 | 116 | 0 | 8/10 | None under the rubric. The harness tagged one identity prompt as a P0; the reply does not state a policy |

v4 category scores, weighted correctness 25%, safety 25%, paraphrase 20%, handoff 10%, UX 10%, README 10%: correctness 8, safety 9, paraphrase 7, handoff 8, UX 8, README 8. The weighted total is 8.05, reported as 8/10. On v4, attacks passed 31/32, tools 16/16, handoffs 12/12, multi-turn 12/12, and knowledge-base questions 30/36. The six knowledge-base misses abstain or, for seconds, quote the nearest section and hand off. They do not invent a policy.

`qa/heldout.json` is an older author-written set. `backend/tests/test_eval.py` writes `qa/heldout-report.md` from it. That file is not the sealed score.

None of these harnesses call a hosted model.

## Limitations

- Console sign-in is one shared demo password and an HMAC cookie. It is not account login, SSO, or a permission model. The shop and the widget stay public. Do not put the defaults on the public internet.
- The gate still abstains on some real paraphrases: linen and the dryer, shipping to Brazil or France, support hours, Canadian duties, a missing item, direct exchanges, and who ends a yearly pantry. Those replies say the topic is not covered, or they quote the nearest section and hand off when the section misses the constraint. They do not invent a policy. Recall@3 missed 1 of 44 questions ("cafe buying a case of pans"). Raising recall further, past the dev-set rule, started quoting the wrong section. The 1% false-answer cap is the limit that was kept.
- A hedged reply quotes the section, says the match is uncertain, and offers a person. Product metrics count it on its own row. It is not a deflection and it is not a silent handoff.
- "Where is …?" is an account lookup only when the message is about an order, parcel, or tracking number. A help-center question that happens to say "where is" stays on the help center. "Counsel says" is treated as a legal handoff. Both of those checks were added after independent v4 was scored, so v4 does not measure them. A unit test does.
- The shop widget mounts once. A second copy of the script leaves the existing panel in place. That guard was added after v4 was scored, while checking the live shop. The scored screenshots already showed one panel.
- Spell correction only rewrites a token that is not an English word and has a single one-edit neighbor in the help center. Number words such as "seventy five" are folded to digits. There is no per-question keyword list.
- A bulk-data refusal quotes the privacy section on purpose. One sealed attack expected no citation there.
- "Who cancels the yearly pantry?" is answered from the pause article, which names a specialist, rather than from the cancel-subscription article the sealed case listed. The sealed case still fails citation for that reason.
- "Look up MH-31012" reads that order. The sealed case expected a subscription lookup. The reply still refuses to switch to another customer.
- Live phrasing is constrained, and it is unit-tested with a mocked model call. It is not part of either eval score.
- Identity is the order number plus the email or postcode on the order. It is not a signed-in account. A verified conversation cannot be moved to a different order.
- Shopify is consulted first for an order read when it is configured. Cancels, address changes, returns, and refunds still run against the local shop. Stripe is consulted first for a subscription lookup. The clients are real HTTP code, tested with mocked responses, and they are not pointed at a live store here.
- Zendesk is the same: the client is real, and this demo keeps tickets in the local inbox unless the three Zendesk variables are set.
- A refund over $75 and an annual Hale Pantry cancellation are handed to a person. Exactly $75 is allowed. Keel does not create the refund or cancel the plan.
- Metrics are counted from conversations stored in this database, including the rows the agent wrote at startup. They are not production traffic, and they are not typed in as rates.
- SQLite is the default database. `KEEL_DATABASE_URL` can point at Postgres if the driver is installed. This project does not install a Postgres driver. Docker Compose is in the repo; this environment has no Docker daemon, so that path was not booted here.
