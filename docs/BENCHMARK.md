# Choosing your Whisper model

B.O.B. ships with `stt.model = "large-v3-turbo"` as a **provisional** default. It
is not a considered choice for your machine — nobody can make that choice from a
blog post, because Greek accuracy, your CPU, your GPU's VRAM and your microphone
all matter. This is how to decide properly.

## 1. Record a few samples

Six to ten short clips, 2–6 seconds each, recorded **on the microphone you will
actually use, in the room you will actually use it**. That last part matters more
than the model choice: a laptop array microphone in a room with a fan is a
different problem from a headset.

Cover the cases B.O.B. has to survive:

| Sample | Why it is in the set |
|---|---|
| `Άνοιξε το Spotify` | plain command, English product name |
| `Τι πρόγραμμα τρώει όλη τη RAM;` | technical English inside Greek |
| `Άνοιξε το Visual Studio Code` | multi-word product name |
| `Θέλω να κάνουμε update το project` | Greek grammar around English verbs |
| `Πήγαινε στον φάκελο Downloads` | a path-like word |
| a longer, casual sentence | natural pace, not dictation |

Save each as **16-bit mono WAV**. Any recorder will do; Audacity exports this
directly. Put a `.txt` beside each with the correct transcript — without those the
harness can measure speed but not accuracy, which is half the point.

```
samples/
    spotify.wav
    spotify.txt        ← "Άνοιξε το Spotify"
    ram.wav
    ram.txt
    ...
```

## 2. Run the benchmark

```bash
python -m bob benchmark-stt --samples ./samples
```

Restrict the candidates while iterating:

```bash
python -m bob benchmark-stt --samples ./samples --models small,medium,large-v3-turbo
python -m bob benchmark-stt --samples ./samples --device cpu --compute-type int8
```

Each model is downloaded on first use — several gigabytes for `large-v3`.

## 3. Read the results

```
model                device compute         load     RTF     WER     CER   peak MB
------------------------------------------------------------------------------
large-v3-turbo       cuda   float16          4.2s    0.16    6.1%    2.4%      2100
```

- **RTF** (real-time factor) — transcribe time ÷ audio duration. Below 1.00 is
  faster than real time. For a voice assistant you want **well** below: at RTF
  0.3 a four-second command costs 1.2 seconds before B.O.B. can even start
  thinking.
- **WER / CER** — word and character error rate against your references, scored
  case- and accent-insensitively with punctuation removed. Accents are stripped
  *for scoring only*; B.O.B. keeps them in real transcripts. Scoring a model down
  for writing `ανοιξε` instead of `άνοιξε` would hide the errors that actually
  break command recognition.
- **peak MB** — process peak RSS. On CUDA this does not include VRAM; watch
  `nvidia-smi` for that.

Read the transcripts too, not just the numbers. A model that scores 8% WER but
renders `Spotify` as `Σποτιφάι` every time is worse for B.O.B. than one at 12%
that gets product names right — because product names are what tools key on.

## 4. Apply your choice

Put it in `config/user.toml` (gitignored, so project updates never clobber it):

```toml
[stt]
model = "large-v3-turbo"
device = "cuda"
compute_type = "float16"
```

## The candidates, and one that is missing

| Model | Notes |
|---|---|
| `tiny`, `base` | Latency floor for reference. Greek quality is not usable. |
| `small` | Worth testing on CPU-only machines. |
| `medium` | Often the practical middle for Greek. |
| `large-v3` | Quality ceiling. Slowest, ~3 GB. |
| `large-v3-turbo` | 809M params, much faster decoding. **Whether its Greek matches `large-v3` is exactly what you are measuring.** |

**`distil-whisper` is deliberately absent.** It is English-only, so it is not a
candidate for a Greek assistant, whatever its speed numbers say.

## VRAM guidance

| VRAM | Suggested starting point |
|---|---|
| CPU only | `small` or `medium`, `int8` |
| 4 GB | `medium`, `int8_float16` |
| 6–8 GB | `large-v3-turbo`, `float16` |
| 12 GB+ | `large-v3`, `float16` |

Phase 3 adds an LLM that also wants VRAM, so leave headroom.

## If CUDA fails on Windows

The usual cause is CTranslate2 not finding matching cuDNN/cuBLAS DLLs. The error
message B.O.B. prints says so. Either install the cuDNN 9 runtime and put it on
`PATH`, or set `device = "cpu"` and use a smaller model.
