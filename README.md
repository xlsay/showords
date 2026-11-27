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

Every command below runs from the project root on Ubuntu 24.04. Steps marked
**(first time only)** set up a machine once; steps marked **(every time)** are
the daily routine. The server and client can share one machine or run on
different ones, and each folder under `codes/` runs on its own.

### Server

Hardware: 8 GB RAM for the default `medium` model on CPU. An NVIDIA GPU is used
automatically when present. Translation needs an API key for any
OpenAI-compatible chat API; without one the server still transcribes.

**Step 1. Install system packages (first time only)**

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip
```

**Step 2. Create the Python environment (first time only)**

```bash
python3 -m venv codes/server/.venv
```

**Step 3. Install CPU-only PyTorch (first time only, CPU servers only)**

Skip this on a GPU server. It keeps silero-vad from pulling the 2.5 GB CUDA build.

```bash
codes/server/.venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu
```

**Step 4. Install Python packages (first time only)**

```bash
codes/server/.venv/bin/pip install -r codes/server/requirements.txt
```

**Step 5. Install CUDA libraries (first time only, GPU servers only)**

Requires an NVIDIA driver (`sudo ubuntu-drivers install`, then reboot).

```bash
codes/server/.venv/bin/pip install nvidia-cublas-cu12 "nvidia-cudnn-cu12==9.*"
```

**Step 6. Edit `codes/server/config.yaml` (first time only)**

- `server.host` — `0.0.0.0` accepts clients from the network; `127.0.0.1` accepts only this machine.
- `server.port` — the port clients connect to (default 8765).
- `server.token` — a shared secret clients must send. Empty means no check; set one
  whenever the port is reachable by people you do not trust.
- `llm.api_key`, `llm.base_url`, `llm.model` — the translation API.
- `whisper.model_size` — `auto` picks `medium` on CPU and `large-v3-turbo` on CUDA.
- `whisper.device` — `auto`, `cpu`, or `cuda`.
- `vad.trailing_silence_seconds` — how much silence ends a sentence.
- `whisper.min_confidence` — raise it if noise produces junk lines.

**Step 7. Open the port in the firewall (first time only, if ufw is enabled)**

```bash
sudo ufw allow 8765/tcp
```

**Step 8. Load the CUDA libraries (every time, GPU servers only)**

```bash
export LD_LIBRARY_PATH=$(codes/server/.venv/bin/python -c 'import os, nvidia.cublas.lib, nvidia.cudnn.lib; print(os.path.dirname(nvidia.cublas.lib.__file__) + ":" + os.path.dirname(nvidia.cudnn.lib.__file__))')
```

**Step 9. Start the server (every time)**

```bash
codes/server/.venv/bin/python codes/server/main.py
```

Expect `MeetingAssist server starting on 0.0.0.0:8765 ...`, then `speech model ready`.
On the very first start, faster-whisper downloads the model named by
`whisper.model_size` into `codes/server/weights/whisper/` (about 1.5 GB for
`medium`) and silero-vad fetches its detector; this takes a few minutes once. The
server serves one client session at a time.

**Step 10. Check the server from the client machine (first time only)**

```bash
curl http://<server-ip>:8765/health
```

The reply should contain `"ready": true`.

### Client

Hardware: a microphone, or system audio to capture. The client needs no model
weights.

**Step 1. Install system packages (first time only)**

`libportaudio2` is needed for microphone capture, `pulseaudio-utils` for system
audio (its `parec` also works on PipeWire, Ubuntu's default).

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip libportaudio2 pulseaudio-utils curl
```

**Step 2. Install Node.js 22 (first time only)**

```bash
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt install -y nodejs
```

**Step 3. Create the Python environment (first time only)**

The desktop app looks for this exact path.

```bash
python3 -m venv codes/client/.venv
```

**Step 4. Install Python packages (first time only)**

```bash
codes/client/.venv/bin/pip install -r codes/client/requirements.txt
```

**Step 5. Install the desktop app packages (first time only)**

```bash
npm --prefix codes/client/frontend install
```

**Step 6. Allow the Electron sandbox (first time only, and after any reinstall in step 5)**

Ubuntu 24.04 blocks Electron's default sandbox; without this the window does not open.

```bash
sudo chown root:root codes/client/frontend/node_modules/electron/dist/chrome-sandbox
sudo chmod 4755 codes/client/frontend/node_modules/electron/dist/chrome-sandbox
```

**Step 7. Point the client at the server (first time only)**

Set the server in the app under **Settings** (address, port, token), or in
`codes/client/config.yaml`. Settings saved in the app override the file.

- `server.host` — the server's IP address or hostname.
- `server.port` — must equal the server's `server.port`.
- `server.token` — must equal the server's `server.token`.
- `audio.source` — `microphone` for in-person meetings, `system` for online meetings.
- `audio.microphone_device` — leave empty for the system default.
- `bridge.port` — local port between the UI and the capture service (default 8766);
  change it only if something else uses that port.

**Step 8. Start the client (every time)**

```bash
npm --prefix codes/client/frontend run dev
```

The desktop window opens and starts its local capture service. The footer shows
the server address and model once the server is reachable and ready. Pick a
source, press **Start**, and speak. The sentence you spoke appears on the first
line and its translation on the second, replaced each time a sentence ends.
**Stop** finishes the last sentence before ending. **Export txt** saves every
sentence so far in the same two-line layout.
