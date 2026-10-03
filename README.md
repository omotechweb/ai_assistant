# Windows AI Assistant

A desktop assistant for Windows built with PyQt6. Chat with OpenAI models, launch apps and files with plain-English commands, talk to it through your microphone, and have replies read aloud.

## Features

- **AI chat** powered by the OpenAI API (`gpt-4o-mini` by default), with conversation context.
- **App launcher.** Built-in commands for common apps, plus a dynamic launcher that finds any installed program or `.exe` by name or path.
- **Voice commands.** Click *Listen*, speak in English, and your words are sent as a message.
- **Text-to-speech.** Replies and launch notifications can be read aloud with an English voice.
- **Responsive dark UI.** Chat bubbles, a resizable layout and full-screen mode (F11).
- **Never freezes.** OpenAI requests, app searches, listening and speaking each run on their own `QThread`.

## Requirements

- Windows 10 or 11 (the chat UI also runs on macOS/Linux, but launching apps is Windows-only)
- Python 3.9 or newer
- An [OpenAI API key](https://platform.openai.com/api-keys)
- A microphone and an internet connection for voice commands

## Installation

```bash
git clone <your-repo-url>
cd windows-ai-assistant
pip install -r requirements.txt
```

If `PyAudio` fails to install, try one of these:

```bash
pip install pipwin
pipwin install pyaudio
```

Alternatively, download a prebuilt `.whl` matching your Python version and install it with `pip install <file>.whl`.

The voice libraries are optional. If `SpeechRecognition`, `PyAudio` or `pyttsx3` is missing, the app still runs; only the related feature is disabled, and the app tells you what to install when you try to use it.

## Usage

```bash
python ai_assistant.py
```

1. Paste your OpenAI API key into the **API Key** field and click **Save / Connect**. The key is verified and remembered for next time.
2. Type a question or a command and press **Enter** (or click **Send**).
3. Click **🎤 Listen** to speak instead of typing.
4. Turn on the **Text-to-Speech** switch in the top right to hear replies.

### Keyboard shortcuts

| Key   | Action                |
|-------|-----------------------|
| Enter | Send message          |
| F11   | Toggle full screen    |
| Esc   | Exit full screen      |

## Commands

### Built-in commands

These open instantly, without contacting the AI.

| Say or type                                    | Opens                         |
|------------------------------------------------|-------------------------------|
| `calculator`, `calc`                           | Calculator                    |
| `notepad`, `text editor`                       | Notepad                       |
| `browser`, `chrome`                            | Chrome (or the default browser) |
| `task manager`                                 | Task Manager                  |
| `command prompt`, `terminal`, `cmd`            | Command Prompt                |
| `open discord`                                 | Discord                       |
| `open whatsapp`                                | WhatsApp                      |
| `open spotify`                                 | Spotify                       |
| `open steam`                                   | Steam                         |
| `open youtube`                                 | YouTube in your browser       |

Natural phrasing works too, for example "can you open spotify for me?" or "please launch steam".

For Discord, WhatsApp, Spotify and Steam the assistant tries the desktop app first, then the Microsoft Store version, and opens the web version if neither is installed.

### Launching any program or file

| Example                                   | What happens                                   |
|-------------------------------------------|------------------------------------------------|
| `open sample.exe`                         | Searches the system for `sample.exe`           |
| `open obs`                                | Finds the program by name (e.g. *OBS Studio*)  |
| `C:/Games/game.exe`                       | Runs the file at that path directly            |
| `open "C:/Program Files/App/app.exe"`     | Use quotes when the path contains spaces       |

When only a name is given, the assistant searches in this order:

1. The `PATH` environment variable
2. The registry's *App Paths* entries
3. Start Menu shortcuts
4. `Program Files`, `Program Files (x86)` and `%LOCALAPPDATA%\Programs` (up to 3 folders deep)

If nothing is found you'll see **"File or application not found."** In that case, provide the full path.

### What goes to the AI

Anything that isn't a launch command is sent to OpenAI. Messages that start like a question are always treated as questions, even if they mention an app. For example, "how do I open a file in Python?" and "what is Discord?" go to the AI.

## Configuration

Settings are constants near the top of `ai_assistant.py`:

| Constant          | Default         | Purpose                                     |
|-------------------|-----------------|---------------------------------------------|
| `MODEL_NAME`      | `gpt-4o-mini`   | OpenAI model used for chat                  |
| `MAX_HISTORY`     | `20`            | Previous messages sent as context           |
| `SPEECH_LANGUAGE` | `en-US`         | Speech recognition language                 |
| `SYSTEM_PROMPT`   | English-only    | Instructions given to the model             |

To add a new built-in command, add an entry to the `commands` list in `WindowsCommandHandler.__init__` with a name, one or more regex patterns, and the method that opens it.

## Project structure

Everything lives in a single file, `ai_assistant.py`:

| Component               | Responsibility                                         |
|-------------------------|--------------------------------------------------------|
| `WindowsCommandHandler` | Parses commands, searches for and launches programs    |
| `AIWorker`              | Sends chat requests to OpenAI (QThread)                |
| `KeyValidationWorker`   | Verifies the API key (QThread)                         |
| `LaunchWorker`          | Runs app searches and launches (QThread)               |
| `STTWorker`             | Records and transcribes microphone input (QThread)     |
| `TTSWorker`             | Speaks text from a queue on one long-lived thread      |
| `ChatView`, `MessageBubble` | Chat area and message bubbles                      |
| `ToggleSwitch`          | The Text-to-Speech on/off switch                       |
| `MainWindow`            | Window layout and wiring between the pieces            |

## Troubleshooting

**"PyAudio was not found"** — Install PyAudio as described in [Installation](#installation).

**"No microphone found or it is unavailable"** — Check that a microphone is connected and that desktop apps are allowed to use it under *Settings → Privacy & security → Microphone*.

**"Could not reach the Google speech service"** — Voice recognition needs an internet connection.

**Speech is not recognized well** — Speak right after the button turns red, close to the mic, and in a quiet room. Recording stops after a short pause or 12 seconds.

**Replies are read in the wrong voice or accent** — The assistant picks the first US English voice it finds (e.g. Microsoft Zira or David). You can add voices under *Settings → Time & language → Speech*.

**"Invalid API Key" or quota errors** — Check your key and billing at [platform.openai.com](https://platform.openai.com).

**A program isn't found by name** — Use its full path, in quotes if it contains spaces.

## Privacy and security notes

- Your API key is stored **unencrypted** in the Windows registry (via `QSettings`, under `HKEY_CURRENT_USER\Software\AIAssistant`). Avoid saving it on shared computers.
- Messages you send to the AI are sent to OpenAI. Voice recordings are sent to Google's speech recognition service for transcription.
- Launch commands run programs with your user's permissions. Programs that require administrator rights will show the normal Windows UAC prompt.
