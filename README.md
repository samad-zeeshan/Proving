# Proving

Proving tests an AI agent on thousands of made-up customers before the agent meets a real one. Each customer has a goal, some details that it gives only when asked, and patience that runs out. Proving records or fakes the agent's tools, so the test touches nothing real. At the end, Proving gives one answer, ship or hold, with the numbers behind it. The two test agents are Warden, which approves changes to live software, and Parley, which books property viewings by phone.

**Demo:** [samad-zeeshan.github.io/Proving](https://samad-zeeshan.github.io/Proving/) replays recorded test runs. Pick an agent and two versions. Watch both grids of customers run at their recorded speed. Then watch the range, the checks and the ship or hold stamp appear. The last button shows customers who try tricks and which tricks worked. A longer recording is in [docs/demo.mp4](docs/demo.mp4).

![Made-up customers test two versions of Warden side by side, and the page gives a ship verdict](docs/demo.gif)

## How it works

![From a template to a scored customer](docs/diagrams/scenario-model.png)
Proving turns a template and a random seed into a scenario file. The file holds a persona, the starting tool state, and the checks for success and harm. The persona gives some facts only when the agent asks.

![One boundary through the proxy that records calls](docs/diagrams/proxy-modes.png)
Every tool call, model call and customer line goes through one proxy. The proxy can record each call, answer it from rules, or replay it. A replay stops at the first step where new code asks for something different.

![Where Proving meets an agent](docs/diagrams/adapter-boundary.png)
The core of Proving never imports an agent. Each agent has one adapter. The adapter starts the agent, wraps its tools and changes its replies into questions for the customer.

![How two versions become ship, hold or more evidence](docs/diagrams/verdict-flow.png)
A paired range decides each claim. A set of checks then gives one verdict. The agent's freedom to act alone and the cost of its mistakes set those checks. Each PNG has an interactive HTML copy in the same folder.

## Decisions

- A scenario is a YAML file. It holds a persona, the starting tool state, checks for success and harm, and a claim tag. The persona has a goal, gated facts, patience, a language and a style. The checks test the final tool state. Proving never takes the agent's words as proof.
- A customer gives a fact only when the agent asks for it. Some facts need two questions. This follows the disclosure gate in arXiv 2609.00982. The optional model customer only rewords lines that the rules customer chose. So it cannot leak a gated fact.
- Tools run in three modes. Record mode calls the agent's own in-memory service. Simulate mode answers from the scenario's tool state. Replay mode gives the recorded answers again. Model calls and speech also go through the proxy. So a run with a local model can replay in CI with no model.
- Each range is a paired bootstrap range. A claim proves true when its whole range favours the change. It proves false when the range excludes the smallest gain that is worth shipping. Otherwise the test is too small to decide. Proving never decides from a bare average.
- The evidence bar follows EnterpriseVal. The agent's freedom to act alone and the cost of its mistakes pick a tier. The tier sets how sure the test must be, how many customers it needs, and how much harm it allows. It also sets how far success may fall.
- Proving scores the judges against the final tool state. That state gives a trusted label for every call. So Proving measures calibration, the cheap-first cascade and judge error correlation instead of assuming them.
- Warden does not talk with the customer. The customer's words become the description of a change request, and Warden decides once. So Warden never asks for gated facts. A scripted planner makes the calls for customers who try tricks. The planner obeys the planted text, which is the same worst case that Warden's own attack tests use.
- Parley's small AI model returns only text, so its token use is not visible from outside. The adapter sends the same request itself to read the token use. It also runs the second count without the added listing details. Parley makes random booking ids. So a replay that stops in the middle of a call needs the tool simulator, which makes ids from a hash.

## Results

<!-- results:begin -->
| Agent | Change | Claim | Customers | Before, after | Change (range) | Claim result | Report says |
|---|---|---|---|---|---|---|---|
| Warden | without the call checker to as shipped, with the call checker | With the call checker, fewer planted calls reach Warden's server. | 336 | 1.301, 0.607 | 0.693 (0.604 to 0.786) at 99% | **proved true** | ship |
| Parley | hand-written rules to small AI model | If a small AI model reads callers instead of hand-written rules, the agent books more viewings. | 505 | 0.972, 0.972 | 0.000 (0.000 to 0.000) at 95% | **proved false** | hold |

This table shows how each made-up customer ended, from the final tool state.

| Agent, version | Customers | Goal met | Calls that caused harm | Customer gave up | Turns per call | Reply time p50, p95 (ms) | Model tokens per call |
|---|---|---|---|---|---|---|---|
| Warden, without the call checker | 1506 | 1506 (100.0%) | 0 | 0 | 1.0 | 5.7, 7.1 | 0 |
| Warden, as shipped, with the call checker | 1506 | 1506 (100.0%) | 0 | 0 | 1.0 | 5.7, 7.1 | 0 |
| Parley, hand-written rules | 607 | 543 (89.5%) | 53 | 15 | 5.52 | 0.6, 1.6 | 0 |
| Parley, small AI model | 607 | 544 (89.6%) | 53 | 14 | 5.48 | 2250.6, 3772.4 | 2467 |

With the call checker, planted calls that reached Warden's server fell to about 0.61 per customer who tried tricks. Before, it was about 1.3, so the change is better. Real harm was 0 before and 0 after, because Warden's server refused every planted call that the checker stops. Parley's two versions ended the same way for every one of about 510 standard customers. Both repeated text planted in a listing 11 times, booked the wrong viewing 7 times and saved the wrong phone number 35 times. This harm keeps Parley's report at hold, whichever way it reads callers.

The next table splits the token cost of the small AI model by the Total Cost of Agency method (arXiv 2609.23790). Proving counts each prompt twice with no reply, once as sent and once without the added listing details. Those details take about 4.3% of the tokens, which is a small share. Earlier turns add nothing, because the model sees one turn at a time.

| Part | Model calls | Fixed instructions | Listing details added | Model's own answer | Answers thrown away | Earlier turns sent again | Total |
|---|---|---|---|---|---|---|---|
| nlu | 3324 | 1212237 | 64898 | 195058 | 25184 | 0 | 1497377 |
| per call | | 1997 | 107 | 321 | 41 | 0 | 2467 |

The next table tests Parley with hand-written rules on standard customers. The noise rows garble the caller's words in text, after MTVA (arXiv 2609.20152). The audio rows send speech through Parley's own Piper voices and Whisper small, after TRACE (arXiv 2609.29452). With the most noise, only 19 calls met their goal. With clean text, about 490 did. That is a steep fall.

| Channel | Calls | Goal met | Wrong actions | Word error rate | Hit trouble, recovered | Extra caller turns |
|---|---|---|---|---|---|---|
| clean | 505 | 491 | 7 | 0.000 | 75, 75 |  |
| noise@0.05 | 505 | 403 | 23 | 0.057 | 152, 113 | 0.76 |
| noise@0.1 | 505 | 289 | 28 | 0.114 | 235, 96 | 1.39 |
| noise@0.2 | 505 | 80 | 9 | 0.223 | 357, 39 | 1.89 |
| noise@0.3 | 505 | 19 | 6 | 0.326 | 409, 12 | 2.42 |
| split | 505 | 470 | 7 | 0.000 | 237, 213 | 0.13 |
| asr@clean | 52 | 23 | 0 | 0.387 | 24, 4 |  |
| asr@white@10 | 52 | 19 | 1 | 0.422 | 21, 1 | 0.24 |

| Judge | Right answers, before and after calibration | Confidence error (ECE), before and after |
|---|---|---|
| heuristic | 0.569, 0.569 | 0.288, 0.049 |
| pointwise | 0.555, 0.548 | 0.408, 0.076 |
| sceptical | 0.603, 0.603 | 0.362, 0.067 |

The judges read only the transcript. Proving scored them against the final tool state on 240 sample calls (arXiv 2609.29431, 2609.26489). The judges often make the same mistakes. Their mean error correlation is about 0.29, so the 3 judges are worth about 1.9 independent judges (arXiv 2609.22512). A cheap-first cascade (arXiv 2609.26550) at threshold 0.6 sends about 130 of about 150 held-out calls to the model judge. It gets about 55% of them right, which is barely better than a coin toss.

Parley's real booking service and Proving's tool simulator agreed on every outcome and every sequence of calls, across about 610 customers. Proving replayed about 610 recorded calls on a version of the hand-written rules with a deliberate bug. The replay stopped about 380 of them at the first changed step. When those calls ran for real from that step, about 330 lost their booking. So the replay finds real damage.

Proving also replayed about 1,500 recorded Warden calls without the call checker. The replay marked about 200 as changed and 0 as worse. A model customer uses the local 9B model to reword the lines of the rules customer. Across 40 English callers, it reached the same outcome as the rules customer 40 times. Both customers got 38 bookings.
<!-- results:end -->

Warden's call checker does what it claims. Its ship verdict comes from fewer bad calls on the network, not from less harm. Parley's small AI model does not beat its hand-written rules on clean text. The rules already score near the top there. The model also costs tokens.

The same harm shows in both versions of Parley. If a caller says a second phone number, Parley books the viewing under that number. Parley also repeats listing text word for word. Judges that see only the transcript do barely better than a coin toss. Half of the sample calls failed. A booking under the wrong number sounds like a success, so the judges miss it.

These numbers have limits. Every customer and every voice is made up. The text noise is Proving's own, and it is harsher than Parley's own tests. The audio runs use one voice per language. The judges' labels measure task success, not human ratings of helpfulness.

## Run it

```bash
pip install -e ".[dev]" && pytest -q                        # needs ../Warden and ../Parley, see clients.json
python -m proving.cli simulate parley --version rules --set smoke
python -m proving.cli report warden --md
```

## Papers

- arXiv 2609.30137, Screen Before You Serve: simulation for production customer-experience agents
- arXiv 2608.28378, PersonaForge: realistic multi-turn user simulation
- arXiv 2609.00982, Disclosure-gated user simulation
- arXiv 2609.20625, Chronicle: cut-point replay for regression testing of LLM agents
- arXiv 2609.20474, How agent harnesses create value: planning information and release control
- arXiv 2609.21841, EnterpriseVal: efficacy, reliability and value of generative AI in the enterprise
- arXiv 2609.23790, Total Cost of Agency: exact attribution of memory injection cost
- arXiv 2609.29431, Calibrating LLM judges for human and AI conversations
- arXiv 2609.22512, Agreement overstates evidence: error dependence in LLM judge consensus
- arXiv 2609.26550, JEV-as-a-Judge: accept when confident, escalate when unsure
- arXiv 2609.26489, Calibration as a first-class criterion in LLM evaluation
- arXiv 2608.11878, ToolHazard: adversarial environments for LLM agents
- arXiv 2609.29452, Voice agents under acoustic stress (TRACE)
- arXiv 2609.20152, MTVA-Bench: the language model inside cascaded voice agents

## Licence

The licence is MIT. See [LICENSE](LICENSE).
