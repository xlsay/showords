# MeetingAssist

## Overview

MeetingAssist is a client/server meeting captioner. The client captures microphone
or system audio and streams it over WebSocket to the server by IP and port. The
server splits speech into sentences, transcribes them with Whisper, and translates
Chinese to English or English to Chinese through an OpenAI-compatible API. The
client shows each sentence with its translation and exports the conversation as txt.

## Project Structure

```
codes/
├── server/                # runs on the ASR machine
│   ├── config.yaml        # listen address, token, VAD, Whisper, translation, LLM
│   ├── requirements.txt   # server Python dependencies
│   ├── weights/           # Whisper model cache
│   ├── common/            # config loader, event schemas, hardware detection
│   ├── audio/             # network audio input and VAD segmentation
│   ├── asr/               # faster-whisper transcription with language detection
│   ├── translation/       # Chinese/English translation
│   ├── llm/               # OpenAI-compatible chat client
│   ├── session/           # audio to transcript to translation loop
│   └── main.py            # server entry point
└── client/                # runs on each user's machine
    ├── config.yaml        # server address, token, audio source and devices
    ├── requirements.txt   # client Python dependencies
    ├── common/            # config loader
    ├── audio/             # microphone and system-audio capture
    ├── link/              # WebSocket link to the server
    ├── frontend/          # Electron + React desktop UI
    └── main.py            # local bridge between capture, server and UI
```

## How to Run

The server and client can run on different machines or on the same one. Each folder
under `codes/` runs on its own; copy only `codes/server/` to the server machine and
only `codes/client/` to a client machine if you prefer.

### 1. Server machine

Requirements:

- Python 3.12 or newer
- 8 GB RAM for the default `medium` model on CPU; an NVIDIA GPU with CUDA is used automatically
- An API key for any OpenAI-compatible chat API (translation is off without one)
- The chosen port (default 8765) open in the firewall for inbound TCP

Install from the project root:

```powershell
.\scripts\install.ps1 -Role server
```

```bash
./scripts/install.sh server
```

Or by hand, inside `codes/server/`:

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt    # Linux/macOS: .venv/bin/python
```

Weights: nothing to download by hand. On first start, faster-whisper downloads the
model named by `whisper.model_size` into `codes/server/weights/whisper/` (about
1.5 GB for `medium`), and silero-vad fetches its detector. Clients see "loading the
speech model" until this finishes.

Edit `codes/server/config.yaml`:

- `server.host` — `0.0.0.0` accepts clients from the network; `127.0.0.1` accepts only this machine.
- `server.port` — the port clients connect to.
- `server.token` — a shared secret clients must send. Empty means no check; set one
  whenever the port is reachable by people you do not trust.
- `llm.api_key`, `llm.base_url`, `llm.model` — the translation API.
- `whisper.model_size` — `auto` picks `medium` on CPU and `large-v3-turbo` on CUDA.
  Use `small` or `tiny` on a slow machine.
- `whisper.device` — `auto`, `cpu`, or `cuda`.
- `vad.trailing_silence_seconds` — how much silence ends a sentence.
- `whisper.min_confidence` — raise it if noise produces junk lines.

Start the server:

```powershell
.\scripts\start.ps1 -Role server
```

```bash
./scripts/start.sh server
```

Expect `MeetingAssist server starting on 0.0.0.0:8765 ...`, then `speech model ready`.
From the client machine, `http://<server-ip>:8765/health` should return
`"ready": true`. The server serves one client session at a time.

### 2. Client machine

Requirements:

- Python 3.12 or newer
- Node.js 20 or newer
- A microphone, or system audio to capture (WASAPI loopback on Windows,
  PulseAudio/PipeWire monitor on Linux, a virtual input device such as BlackHole on macOS)
- On Linux, PortAudio: `sudo apt install portaudio19-dev libportaudio2`

Install from the project root:

```powershell
.\scripts\install.ps1 -Role client
```

```bash
./scripts/install.sh client
```

The client needs no model weights.

Point the client at the server, either in the app under **Settings** (address, port,
token) or in `codes/client/config.yaml`:

- `server.host` — the server's IP address or hostname.
- `server.port` — must equal the server's `server.port`.
- `server.token` — must equal the server's `server.token`.
- `audio.source` — `microphone` for in-person meetings, `system` for online meetings.
- `audio.microphone_device`, `audio.loopback_device` — leave empty for the system default.
- `bridge.port` — local port between the UI and the capture service (default 8766);
  change it only if something else uses that port.

Settings saved in the app override `config.yaml`.

Start the client:

```powershell
.\scripts\start.ps1 -Role client
```

```bash
./scripts/start.sh client
```

The desktop window opens and starts its local capture service. The footer shows the
server address and model once the server is reachable and ready. Pick a source,
press **Start**, and speak. The sentence you spoke appears on the first line and its
translation on the second, replaced each time a sentence ends. **Stop** finishes the
last sentence before ending. **Export txt** saves every sentence so far in the same
two-line layout.
