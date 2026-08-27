# B.O.B. — Architecture

**B.O.B. — Beyond Orbit Buddy**
A local-first Greek-speaking desktop AI companion for Windows 11.

This document records the design and, more importantly, *why* it is this design.
Read it before changing anything structural.

---

## 1. What the requirements actually demand

Stripping the feature list down to the constraints that shape the code:

| # | Requirement | Architectural consequence |
|---|---|---|
| 1 | Voice in, voice out, with **interruption** | Streaming everywhere. TTS must be a cancellable stream of chunks, and the microphone must stay open *while B.O.B. speaks*. This cannot be retrofitted. |
| 2 | Must never block the UI | The core must be able to run with no UI at all. UI is an observer, not the host. |
| 3 | Everything swappable | Capabilities behind Protocols + a registry keyed by config. No concrete class is imported by the core. |
| 4 | Controls a real PC | A hard permission boundary with an audit trail, and no path from model output to a shell. |
| 5 | Greek first | Model, STT and TTS choices are driven by Greek quality, not English benchmarks. This eliminates several otherwise-obvious options. |
| 6 | Local and free | Ollama + faster-whisper + Piper class of stack; cloud is an optional adapter, never a dependency. |
| 7 | Long-term project | Explicit state, typed interfaces, tests on the safety boundary, personality as data. |

Requirements 1 and 2 are the ones that decide the concurrency model, and they are
the reason for most of what follows.

---

## 2. Layered architecture

```
┌──────────────────────────────────────────────────────────────┐
│  PRESENTATION            (Phase 1)                           │
│  Qt/PySide6 shell · animated core · panels · design system   │
│  Runs on the GUI thread. Observes. Never computes.           │
└───────────────▲──────────────────────────┬───────────────────┘
      events    │                          │  commands
   (queued Qt   │                          │  (run_coroutine_
    signals)    │                          │   threadsafe)
┌───────────────┴──────────────────────────▼───────────────────┐
│  KERNEL — headless core, asyncio, no Qt import anywhere      │
│                                                              │
│   EventBus ──── StateMachine ──── Orchestrator (Phase 2+)    │
│       │                                    │                 │
│       │                    ┌───────────────┴──────────────┐  │
│       │                    ▼                              ▼  │
│       │              ToolRegistry                    Providers│
│       │         (validate→permit→audit→run)      (Protocols) │
└───────┼──────────────────────┬──────────────────────┬────────┘
        │                      │                      │
┌───────▼──────┐   ┌───────────▼──────────┐  ┌────────▼───────┐
│ Audio I/O    │   │ Skills / PC control  │  │ LLM STT TTS    │
│ (callback    │   │ (thread pool /       │  │ VAD Wake       │
│  threads)    │   │  subprocess)         │  │ Memory Vision  │
└──────────────┘   └──────────────────────┘  └────────────────┘
```

The single most important rule: **the kernel does not know the UI exists.**
Everything in `src/bob/` today runs, and is tested, with no Qt installed.

---

## 3. Concurrency model

Three technology candidates were considered:

| Option | Verdict |
|---|---|
| Qt threads only, no asyncio | Rejected. Streaming LLM tokens, chunked TTS and cancellable playback are natural as async iterators and painful as thread + queue + signal soup. |
| `qasync` — one merged Qt/asyncio loop | Rejected. It couples the two lifetimes, a slow repaint can stall async callbacks, and the kernel would then require Qt to run *at all* — killing headless testability, which is the property most worth protecting in a long project. |
| **Separate loops, one bridge** | **Chosen.** |

### The chosen model

- **GUI thread** runs the Qt event loop. Nothing else.
- **Kernel thread** runs an asyncio loop owning the bus, state machine,
  orchestrator, providers and tools.
- **One bridge in each direction**, and only one:
  - kernel → UI: a bridge object subscribes to the bus and re-emits Qt signals.
    Qt queued connections across threads are safe by design.
  - UI → kernel: `asyncio.run_coroutine_threadsafe(coro, kernel_loop)`.
  - foreign thread → bus: `EventBus.publish_threadsafe(loop, event)` — already
    implemented and tested in Phase 0.

### Where heavy work goes

asyncio is for *orchestration*, never for computation. CPU-bound work would stall
the loop and, through it, everything else.

| Work | Where it runs | Why |
|---|---|---|
| LLM inference | **Separate process** — Ollama's HTTP server | Already isolated; a model crash or hang cannot take B.O.B. down. Reached with async HTTP. |
| Transcription | Thread pool | `faster-whisper`/CTranslate2 releases the GIL, so a thread genuinely parallelises. |
| Wake word / VAD | Audio callback thread | Per-frame, must be microseconds. These Protocols are deliberately **synchronous** to make that contract explicit. |
| TTS synthesis | Thread pool or subprocess | Depends on the engine chosen in Phase 4. |
| Audio playback | Dedicated consumer task reading a chunk queue | Cancellable — this is what makes barge-in possible. |

---

## 4. Communication: two channels, never mixed

This is the decision that keeps an event-driven system from turning into
untraceable spaghetti, so it is stated as a rule:

### Channel A — events (pub/sub, fire and forget)

Events are **facts about what already happened**. They flow one way, to any number
of subscribers who do not know about each other: the UI, the log, the audit trail,
future metrics.

```python
await bus.publish(TranscriptReady(source="stt", text="άνοιξε το spotify"))
```

Events are **never** used to request something and wait for an answer.

### Channel B — direct calls through Protocols (request/response)

When the orchestrator needs a *result*, it calls the interface and awaits it. The
call stack stays readable, errors propagate normally, and types are checked.

```python
transcript = await self.stt.transcribe(audio)  # B: I need this value
await bus.publish(TranscriptReady(text=transcript.text))  # A: this happened
```

**Why both?** Pure event-driven control flow ("publish `TranscribeRequest`, wait for
`TranscribeResponse`") loses the call stack, loses type checking, and turns every
bug into an archaeology exercise. Pure direct calls, on the other hand, would force
the kernel to know about the UI. Splitting by *purpose* — notification vs. result —
gets the decoupling without the debugging cost.

### Worked example: "Μπομπ, άνοιξε Spotify"

```
wake word (audio thread, sync)   → publish WakeWordDetected      [A]
orchestrator                     → state IDLE → WAKE_DETECTED → LISTENING
VAD (audio thread, sync)         → publish SpeechStarted/Ended   [A]
orchestrator: await stt.transcribe(...)                          [B]
                                 → publish TranscriptReady       [A]
orchestrator: async for chunk in llm.generate(msgs, tools=...)   [B]
                                 → publish ResponseChunk per token [A]
model returns tool_call{name:"app.open", args:{"name":"Spotify"}}
orchestrator: await tools.execute("app.open", args)               [B]
      ToolRegistry: validate → PermissionBroker → audit → run
                                 → publish ToolExecution*        [A]
orchestrator: async for audio in tts.synthesize(text)            [B]
                                 → publish SpeechOutputStarted   [A]
```

The UI renders the whole interaction purely from column [A]. It is never in the
path of column [B], so it can never slow it down or break it.

---

## 5. Technology choices

### Decided now (Phase 0)

| Choice | Why | Alternative rejected |
|---|---|---|
| **Python 3.12+** | Ecosystem for local AI is Python-first. 3.12 gives us `StrEnum`, PEP 695 generics, and a `tomllib` in the stdlib. | 3.11 — worth the newer syntax. **Note: `audioop` was removed in 3.13**, so audio maths is written on `array`/`numpy` from the start. |
| **Protocols over ABCs** | Structural typing: a provider satisfies an interface without importing us. Mocks are trivial, third-party adapters are trivial, the plugin surface stays loose. | ABCs — force inheritance and an import dependency on the core. |
| **Pydantic v2** | One library covers settings validation *and* tool-argument validation *and* generates the JSON schema we hand the LLM. Rust core, so it is fast. | dataclasses + hand-written validation — three times the code, and no free JSON schema. |
| **TOML config, layered** | Human-editable, comment-friendly, `tomllib` is stdlib. `default.toml` (committed) / `user.toml` (gitignored) means project updates never clobber user settings, and user settings never leak into Git. | YAML (whitespace traps, needs a dependency), JSON (no comments). |
| **stdlib `logging`** | Four channels, rotating JSON-lines files. Zero dependencies. | `structlog`/`loguru` — a dependency for something the stdlib does adequately. |

### Recommended, to confirm at the phase that needs them

| Layer | Recommendation | Reasoning and the honest caveat |
|---|---|---|
| **LLM** | Ollama, `qwen2.5:14b-instruct` (fall back to `:7b` on ≤8 GB VRAM) | Qwen2.5 has the strongest Greek of the open models that also do reliable function calling — the combination matters more than either alone. Ollama gives us process isolation and an OpenAI-compatible tool API for free. Llama 3.1 8B is weaker in Greek; Mistral models are weaker at tool calls. |
| **STT** | faster-whisper, `large-v3` | 4× faster than reference Whisper at equal accuracy. **Greek WER is materially worse than English**, so smaller models are not viable — `large-v3` with `int8_float16` is the realistic floor. Budget ~1.5 GB VRAM. |
| **TTS** | Piper, **to be validated in Phase 4** | Piper is fast, local and free, but **its Greek voices are the weakest link in this whole stack** — see risk R2. The `TTSProvider` interface exists precisely so this decision can be reversed without touching anything else. |
| **VAD** | Silero VAD | ~1 MB, far more robust than WebRTC VAD on noisy desktop audio, and it is what makes end-of-utterance detection feel instant. |
| **Wake word** | openWakeWord + a **custom-trained** "Μπομπ" model | No off-the-shelf Greek model exists; see risk R3. |
| **UI** | PySide6 (Qt 6) | LGPL, so no licensing trap. `QGraphicsView` + `QPropertyAnimation` gives a genuinely 60 fps animated core; QML is an option for the core widget if the painter path proves too slow. Electron was rejected outright — a browser engine to draw one orb is not a trade worth making. |
| **Memory** | SQLite + `sqlite-vec` | One file, no server, no Docker. Chroma/LanceDB add a daemon and a large dependency tree for a store that will hold a few hundred records. |
| **Vision** | Qwen2.5-VL 7B via Ollama | Reuses the LLM runtime we already run. Screenshot capture is explicit-only. |

---

## 6. Directory structure

```
B.O.B./
├── config/
│   ├── default.toml           # committed baseline
│   ├── user.toml              # gitignored personal overrides
│   └── personas/bob.md        # ← B.O.B.'s personality lives HERE, not in code
├── src/bob/
│   ├── app.py                 # composition root / entry point
│   ├── core/
│   │   ├── events.py          # event definitions (frozen dataclasses)
│   │   ├── bus.py             # async pub/sub + threadsafe bridge
│   │   ├── states.py          # BobState + transition table (data)
│   │   ├── state_machine.py   # guarded transitions, announced on the bus
│   │   ├── kernel.py          # wires everything from config
│   │   └── errors.py          # exception hierarchy
│   ├── config/                # settings schema + layered loader
│   ├── providers/
│   │   ├── base.py            # the seven Protocols
│   │   ├── registry.py        # name → factory
│   │   ├── mock/              # Phase 0 implementations
│   │   ├── ollama/            # Phase 3
│   │   ├── whisper/           # Phase 2
│   │   └── piper/             # Phase 4
│   ├── tools/
│   │   ├── base.py            # ToolSpec, RiskLevel, @tool decorator
│   │   ├── registry.py        # the single execution funnel
│   │   ├── permissions.py     # PermissionBroker
│   │   ├── audit.py           # append-only JSONL
│   │   └── builtin/           # Phase 0 diagnostics; Phase 6 PC control
│   ├── brain/                 # Phase 3: orchestrator, prompts, context
│   ├── audio/                 # Phase 2: capture, playback, barge-in
│   ├── memory/                # Phase 7
│   ├── vision/                # Phase 8
│   ├── ui/                    # Phase 1: shell, design system, core widget
│   │   ├── bridge.py          #   ← the ONLY file allowed to import both
│   │   └── theme/
│   ├── skills/                # Phase 9: Spotify, Steam, Weather...
│   └── utils/                 # logging, paths
├── tests/
├── ARCHITECTURE.md
└── ROADMAP.md
```

**One deliberate deviation from the structure in the brief:** a `src/` layout,
rather than a top-level `bob/`. It guarantees tests run against the *installed*
package rather than accidentally importing the source directory, which is the
difference between catching a packaging bug in Phase 0 and discovering it while
building the installer in Phase 10.

---

## 7. Safety model

Every action B.O.B. takes passes through exactly one funnel — `ToolRegistry.execute`
— and there is deliberately no way around it:

```
raw args from the model
   │
   ├─ 1. validate  → Pydantic model for THIS tool. Extra keys rejected.
   ├─ 2. authorise → PermissionBroker: config policy by risk level
   ├─ 3. audit     → append-only JSONL, including refusals
   ├─ 4. execute   → with a timeout; exceptions contained
   └─ 5. audit + publish events
```

Four properties are enforced by tests, not by convention:

1. **The model never emits anything executable.** It emits a tool *name* that must
   already exist and a JSON *object* that must satisfy that tool's schema. There is
   no code path from model output to a shell.
2. **HIGH risk can never be auto-approved.** The config schema rejects
   `high = "allow"`, and the broker overrides it again at runtime. Defence in depth,
   because this is the boundary that protects the user's machine.
3. **No confirmation handler means no approval.** If no UI is attached, risky
   actions are refused — never silently allowed. An unanswered prompt times out
   into a refusal.
4. **Refusals are audited too.** They are the entries actually worth reviewing.

Risk is a property of the tool, declared in code. The model does not get to assert
its own risk level.

---

## 8. Major technical risks

Ordered by how much damage they can do to the project.

### R1 — Acoustic echo cancellation for barge-in · **High**
Interruption requires the microphone to stay open while B.O.B. speaks, which means
he hears himself and interrupts himself. Proper AEC is genuinely hard and Windows'
built-in AEC is inconsistent across drivers.
**Mitigation:** the pipeline is designed for it from Phase 0 (chunked, cancellable
TTS). Phase 2 ships headphone-based barge-in, which works reliably today. Speaker
mode adds WebRTC APM / `speexdsp` with a loopback reference in a later pass.
*Fallback:* push-to-talk interruption, which always works.

### R2 — Greek TTS quality · **High**
This is the risk most likely to make B.O.B. unpleasant to use daily. Piper's Greek
voices are limited, and a bad voice is noticed on every single interaction.
**Mitigation:** `TTSProvider` is a two-method interface, so the engine is
replaceable in an afternoon. Phase 4 begins with a listening comparison (Piper vs.
XTTS-v2 vs. Windows SAPI Greek voices) before committing.
*Honest position:* excellent free local Greek TTS may not exist yet. If it does not,
the choice is a heavier local model or an optional cloud voice — the user's call,
and the adapter makes it a config change either way.

### R3 — Wake word reliability · **Medium-High**
"Bob" is short and phonetically sparse — precisely the profile that produces false
activations. No Greek openWakeWord model exists.
**Mitigation:** train a custom model on synthetic Greek "Μπομπ" samples;
confidence threshold and cooldown are already configurable. Requiring a second
confirmation signal (speech within N ms of the trigger) cheaply removes most false
positives.
*Fallback:* a hotkey, which is what most users end up preferring anyway.

### R4 — Function-calling reliability on local models · **Medium**
A 7B model asked to emit strict JSON will sometimes emit prose, or invent a tool.
**Mitigation:** validation already rejects malformed calls rather than executing
them. Phase 3 adds a bounded repair loop (re-prompt with the validation error, twice
at most) plus a deterministic fast-path matcher for the dozen phrasings that
actually get used daily — "άνοιξε X" should never require an LLM round trip.

### R5 — Greek transcription accuracy · **Medium**
Whisper's Greek WER is meaningfully higher than English, and it degrades further on
code-switched speech ("άνοιξε το browser") — exactly how the user talks.
**Mitigation:** `large-v3` only; supply an `initial_prompt` seeded with the app and
technical vocabulary B.O.B. is expected to hear, which measurably improves proper
nouns. Show the transcript in the UI so a misfire is visible before it is acted on.

### R6 — Latency budget · **Medium**
Wake → STT → LLM → TTS can easily total 4–6 seconds, which feels broken.
**Mitigation:** the streaming interfaces exist for exactly this. Speak the first
sentence while the rest is still generating; that alone typically takes perceived
latency under 1.5 s. Budget per stage and measure from Phase 2 rather than at the end.

### R7 — VRAM contention · **Medium**
Whisper large-v3 (~1.5 GB) + a 14B LLM (~9 GB) + a vision model (~6 GB) will not
coexist on an 8 GB card.
**Mitigation:** Ollama unloads idle models; vision loads on demand only. Document a
tested profile per VRAM tier and let `user.toml` select it.

### R8 — UI thread starvation · **Low, but expensive if ignored**
A 60 fps animated core leaves ~16 ms per frame. One synchronous call on the GUI
thread is a visible stutter.
**Mitigation:** the kernel/UI split makes this structurally hard to get wrong. It is
enforceable in review: `src/bob/ui/` may import the kernel, and nothing in the
kernel may import Qt.

---

## 9. Rules for contributors

1. Nothing outside `src/bob/ui/` may import Qt.
2. Nothing in `core/` may import a concrete provider.
3. Events are facts, not requests. If you need a value back, call the interface.
4. Every new tool declares a `RiskLevel` and validates its arguments with Pydantic.
5. No new `is_*` state boolean. Add a state or a reason to the state machine.
6. Personality changes go in `config/personas/`, never in Python.
7. New settings go in `config/schema.py` with a default and a description.
