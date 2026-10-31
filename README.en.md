# Customer-service agent · Empório da Música

*English version of [README.md](README.md). The code, the comments and the example conversations are in Portuguese, the language of the challenge material and of the store's customers.*

Prototype of a text-based customer-service agent for Empório da Música, a fictional musical-instrument store in Campo Grande (MS, Brazil). Technical case for the AI Engineer position at Artefact.

The agent takes on the store's persona, answers from the policy manual, reaches operational data (catalog, stock, promotions, orders) through function calling, and politely declines what falls outside the store's scope.

```
Customer: do you have nylon-string guitars under a thousand reais?
Agent:    Yes! I checked the catalog and picked the nylon options under R$ 1,000 that are in stock: ...
```

Full example conversations, recorded from real runs, are in [`exemplos/`](exemplos/):

| Conversation | What it shows |
|---|---|
| [01 · Catalog: guitars up to R$ 1,000](exemplos/01-catalogo-violoes-ate-1000.md) | search with price filter; PIX price and installments for one item |
| [02 · Price: Takamine GD20 and a promoted product](exemplos/02-preco-takamine-e-promocao.md) | promotional price shown with the original and the percentage; promotion does not stack with PIX |
| [03 · Order with identity confirmation](exemplos/03-pedido-com-confirmacao-de-identidade.md) | asks for a contact before querying; pending order explained |
| [04 · Return by regret](exemplos/04-devolucao-por-arrependimento.md) | **non-trivial case**: crosses the 7-day policy with the real order date and explains what still applies |
| [05 · Out of scope and out of stock](exemplos/05-fora-de-escopo-e-produto-indisponivel.md) | declines accessories and an unrelated topic; out-of-stock product with alternatives |

Each file records the tools called in every turn and the conversation's token usage. To re-record: `python scripts/gravar_exemplos.py`.

## How to run

Requirements: Python 3.11 or later and an Anthropic API key.

```bash
git clone https://github.com/thiagogardev/agente-emporio-musica.git
cd agente-emporio-musica
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate      # Linux and macOS
pip install -e ".[dev]"
copy .env.example .env           # cp on Linux and macOS
```

Edit `.env` and fill in `ANTHROPIC_API_KEY`. The other variables have defaults.

```bash
python -m emporio                                  # interactive chat
python -m emporio -m "Quanto custa o Takamine GD20?"   # single question
python -m emporio --debug                          # shows tools called and tokens
python -m emporio --salvar conversas/minha.md      # saves the transcript on exit
pytest                                             # tool tests (no API calls)
```

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | required | API authentication |
| `EMPORIO_MODELO` | `claude-sonnet-5-5` | model; `claude-haiku-5-5` for cheap tests |
| `EMPORIO_ESFORCO` | `medium` | reasoning effort (`low`, `medium`, `high`) |

## How it works

```
customer ──text──▶ Agente.responder()
                      │  system = persona + policy manual (cached) + date/time
                      │  tools  = 5 tools over the CSV files
                      ▼
                 Claude (messages.create)
                      │ stop_reason == "tool_use"?
                      ├── yes: run the tools locally, return tool_result, repeat
                      └── no: final text for the customer
```

**Two sources of knowledge, two mechanisms.**

- **Policies** (hours, payment, returns, shipping, warranty, data protection) go whole into the system prompt. The manual has 8 pages, about 3k tokens: it fits comfortably and makes a RAG pipeline unnecessary, since retrieval would add a step (and a failure point) without benefit. The block is marked with `cache_control`, so it is billed in full only on the first call of each session.
- **Data** (products, stock, promotions, orders, customers) stays out of the prompt and is queried on demand through tools. Operational data changes; the model must not memorize it. The manual is explicit: "never give prices, stock or deadlines without checking the system".

**The tools** ([`emporio/ferramentas.py`](emporio/ferramentas.py)):

| Tool | When the model calls it | What it does beyond the obvious |
|---|---|---|
| `buscar_produtos` | "what do you have in X", price range | filters by term, category and maximum price with the active promotion already applied; hides unavailable items by default but lists what it hid |
| `detalhar_produto` | a specific product | specs, stock, status; if unavailable or discontinued, returns 3 alternatives from the same category with a close price |
| `listar_promocoes_ativas` | offers, discounts | only promotions with `is_active = 1`; the 21 inactive ones never show up |
| `consultar_pedido` | status, tracking, delivery estimate | requires the order number **and** the owner's phone or e-mail; if they do not match, it refuses and reveals nothing (LGPD, the Brazilian data-protection law) |
| `situacao_atendimento` | hours, open now, address | computes in the Campo Grande time zone whether the store is open and when it reopens |

The manual's pricing rules live in code, not in the prompt: 5% PIX discount on the list price, promotions not cumulative with PIX, interest-free installments with the minimum amount per range (up to 3x, 4 to 6x, 7 to 12x). The model decides *when* to query; the arithmetic is deterministic and tested.

**Edge cases in the data**, handled on purpose because the manual says what to do in each one:

- active product with zero stock (Giannini GF-3D): "temporarily unavailable" plus alternatives;
- discontinued products (Shelby SN-7C, Ibanez Bass 2X): "no longer in the catalog" plus equivalents;
- `coming_soon` product (Kala baritone): "coming soon", not for sale yet;
- 21 of 25 promotions inactive: never promised;
- cancelled orders carry the recorded reason; pending and confirmed orders have no tracking code yet.

## Technical decisions

**Approach: function calling with a manual loop, no framework.** The problem has five tools and a small dataset. LangChain, LlamaIndex or a SQL agent would add layers that hide exactly what the evaluator wants to see: when the model decides to query, what it receives and how it answers. The loop in [`emporio/agente.py`](emporio/agente.py) is about 30 lines and every step is visible and testable. The Anthropic SDK offers a *tool runner* that drives this loop by itself; I did not use it, to avoid depending on a beta API and to control the stop conditions (`refusal`, `max_tokens`, round limit).

**Model: Claude Sonnet 5.5 through the Anthropic API.** The core of the agent is deciding correctly between answering, calling one tool or calling several. That is where smaller models fail most (wrong tool, invented argument, price from memory). Sonnet 5.5 has reliable function calling, natural Portuguese for the persona, and negligible cost at this volume (cents for dozens of conversations). Adaptive reasoning stays on with `medium` effort; `low` is faster and cheaper, `high` helps in ambiguous cases. `claude-haiku-5-5` is documented as the cheap alternative.

**Retrieval: full context, not RAG.** Explained above. If the manual grew to dozens of pages, or there were several documents, the path would be chunking by section with hybrid search (BM25 + embeddings) and citing the section in the answer.

**Prompt.** A short persona, nine numbered rules that are the manual's rules in imperative form, a guide to which tool to use when, and the whole manual in markdown as the "source of truth". The original manual was a PDF; the version in [`data/politicas_da_loja.md`](data/politicas_da_loja.md) was extracted and revised by hand to keep headings and lists, because well-structured text improves how the model uses it. The current date and time go in a separate block, after the cached block, so the cache is not invalidated every minute.

**Interface: CLI.** The brief says the focus is a working agent. The CLI has an interactive mode, a single-message mode (useful for scripts and for generating the examples) and transcript saving in markdown.

**Conversation history: in memory, per session.** The full history (including tool calls and results) is kept during the conversation and resent every turn, which is how the API works. It does not persist between sessions: in a real channel (WhatsApp) the history would come from the channel itself or from a database keyed by phone number, and that is a product decision, not a prototype one. The `--salvar` option saves the visible conversation as markdown.

**Data handling.** CSVs are read with the standard library into typed dataclasses; `specs` (JSON in a string) is deserialized; search normalizes accents and punctuation; phone numbers are compared by digits only; e-mail ignores case. No data was altered.

**Identity before personal data.** The order tool refuses if the contact does not belong to the order's owner, and the prompt instructs the model to ask for the contact naturally. The tool is the barrier; the prompt is only the conversation. Customer data never enters the system prompt.

## Tests

`pytest` runs 34 tests over the data layer and the tools, without calling the API: installment and PIX rules, search with and without promotion, unavailable, discontinued and coming-soon products, identity confirmation on orders, opening-hours computation at four moments of the week. They protect exactly the rules the manual calls non-negotiable.

The model's behavior (choosing which tool to call, tone, out-of-scope refusal) was validated with the conversations in [`exemplos/`](exemplos/), recorded from real runs by the script [`scripts/gravar_exemplos.py`](scripts/gravar_exemplos.py), which runs fixed scenarios and saves the transcript without editing. In the five conversations the model chose the right tool in every turn and called none when the answer was in the manual or out of scope. Total cost of the five recordings: about 20k input tokens (most served from cache) and 5k output tokens.

## Known limitations and what I would do with more time

- **No automatic evaluation of the agent.** Tests cover the tools; the model's behavior was checked by hand. The next step is a set of 30 to 50 questions with expected answers (right tool called, right data quoted, out-of-scope refusal) run in CI, plus an automatic judge for tone and policy adherence.
- **Single provider.** A pluggable provider layer would allow comparing Sonnet with an open model via Groq or Ollama, measuring tool accuracy, latency and cost.
- **No real channel.** WhatsApp integration (official API) would bring customer identification by phone number, persistent history and hand-off to a human agent.
- **Static data.** In production the tools would query the store's system (ERP or database) instead of CSV files; the tool interface already isolates that.
- **Lexical search.** Product search is by normalized words. Open questions ("I want something to start playing") depend on the model choosing good terms; embeddings over name and description would do better.
- **No streaming and no graphical interface.** In a chat UI the answer should stream.

## Use of AI coding assistants

I used **Claude Code** (Anthropic) as a pair programmer throughout, in a terminal session. Workflow:

1. I read the brief, the manual and the CSVs and defined the approach (full context for policies, tools for data, manual loop) before writing code. The decisions in this README are mine; the assistant helped weigh pros and cons.
2. I asked the assistant for the project structure and a first version of each module, reviewing file by file. I corrected business rules that came out wrong in the first version (the installment minimums per range, for example, were fixed with tests that failed on purpose).
3. Tests were written together with the tools and run on every change. Several edge cases in the data (zero stock, discontinued, coming soon, inactive promotions) were found by exploring the CSVs with the assistant before coding.
4. The example conversations were generated by running the real agent through a script; none was edited by hand. Reading the first recording, I saw the search cut the list at 10 items when there were 14; I raised the limit and re-recorded.
5. Incremental commits throughout the work, with messages written by me.

The assistant sped up the mechanical part (scaffolding, parsing, repetitive tests) and acted as a reviewer; the architecture, the decisions and the final verification were mine.

## Delivery

The case brief asks for the repository link in the reply to the process e-mail; the opening e-mail asks for a PDF through Google Forms. Since both instructions coexist, the link goes through both channels: in the e-mail reply and in a PDF sent through the form, generated from this README with the example conversations attached. Assumptions and ambiguities in the brief are documented above, as requested.

## Structure

```
emporio/
  config.py        paths, model, fixed store data, opening hours
  dados.py         CSV reading into dataclasses; normalized search
  ferramentas.py   the 5 tools, pricing rules, tool definitions for the model
  agente.py        persona, system prompt, tool loop
  cli.py           command-line interface
data/              CSVs, original PDF and the manual in markdown
exemplos/          conversations recorded from real runs
scripts/           gravar_exemplos.py runs the scenarios and saves the transcripts
tests/             34 tool tests
```

MIT license.
