# YamanAI

YamanAI is a desktop AI assistant for Windows, built with PyQt6. It looks and feels like the YamanAI web app: chat with GPT-4o or a local model, open apps and programs with plain-English commands, talk to it through your microphone, and have replies read aloud.

## Features

- **Streaming chat.** Replies appear word by word from GPT-4o, GPT-4o mini, or a local model on any OpenAI-compatible server (Ollama, LM Studio). A **Stop** button ends a reply early and keeps what was written so far.
- **Web-style interface.** Chats grouped by Today / Yesterday / Older, full-width message rows with avatars, syntax-highlighted code blocks with **Copy** and **Live preview** (HTML/CSS/JS), a welcome screen with suggested prompts, and a large rounded input box.
- **Dark and light themes** and three text sizes, set in Settings.
- **App launcher.** Built-in commands for common apps, plus a launcher that finds any installed program or `.exe` by name or full path.
- **Voice input.** Click the microphone, speak in English, and your words are sent as a message.
- **Text-to-speech.** Replies and launch notices can be read aloud, or use the speaker button under any single reply.
- **Saved conversations** that survive restarts, with rename, export (Markdown or JSON) and delete.
- **Responsive window.** Frameless and resizable; the sidebar hides itself on narrow windows; F11 for full screen.
- **Never freezes.** AI requests, app searches, listening and speaking each run on their own `QThread`.

## Requirements

- Windows 10 or 11 (the chat also runs on macOS/Linux, but launching apps is Windows-only)
- **Python 3.9 – 3.13.** PyAudio, used for the microphone, has no Windows build for Python 3.14 yet.
- An [OpenAI API key](https://platform.openai.com/api-keys), unless you only use a local model
- A microphone and an internet connection for voice input

## Installation

```bat
cd C:\YamanAIapp
py -3.13 -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

The voice libraries are optional. If `SpeechRecognition`, `PyAudio` or `pyttsx3` is missing, the app still runs; only that feature is disabled, and the app tells you what to install when you try to use it.

## Usage

```bat
venv\Scripts\python ai_assistant.py
```

1. Click **Settings** (bottom left or the gear icon at the top), paste your OpenAI API key and click **Connect**. The key is verified and remembered.
2. Choose a model in Settings, or click the status pill at the top (`GPT-4o ● Online`).
3. Type a question or a command and press **Enter**. **Shift+Enter** adds a new line.
4. Click the **microphone** in the input box to speak instead of typing.
5. Click the **speaker** icon at the top to have every reply read aloud.

**Launch an app** in the sidebar, and the monitor icon at the top, open built-in apps or any file with one click. **Help** lists everything YamanAI can do; clicking an example puts it in the input box. Right-click a chat to rename, export or delete it.

### Keyboard shortcuts

| Key         | Action                                  |
|-------------|-----------------------------------------|
| Enter       | Send message                            |
| Shift+Enter | New line                                |
| Ctrl+N      | New chat                                |
| Ctrl+B      | Show / hide the sidebar                 |
| F11         | Toggle full screen                      |
| Esc         | Close a dialog, or exit full screen     |

## Commands

### Built-in commands

These open instantly, without contacting the AI.

| Say or type                           | Opens                              |
|---------------------------------------|------------------------------------|
| `calculator`, `calc`                  | Calculator                         |
| `notepad`, `text editor`              | Notepad                            |
| `browser`, `chrome`                   | Chrome (or your default browser)   |
| `task manager`                        | Task Manager                       |
| `command prompt`, `terminal`, `cmd`   | Command Prompt                     |
| `open discord`                        | Discord                            |
| `open whatsapp`                       | WhatsApp                           |
| `open spotify`                        | Spotify                            |
| `open steam`                          | Steam                              |
| `open youtube`                        | YouTube in your browser            |

Natural phrasing works too, for example "can you open spotify for me?" or "please launch steam". For Discord, WhatsApp, Spotify and Steam the desktop app is tried first, then the Microsoft Store version, and the web version opens if neither is installed.

### Any program or file

| Example                                   | What happens                                  |
|-------------------------------------------|-----------------------------------------------|
| `open sample.exe`                         | Searches the system for `sample.exe`          |
| `open obs`                                | Finds the program by name (e.g. OBS Studio)   |
| `C:/Games/game.exe`                       | Runs the file at that path                    |
| `open "C:/Program Files/App/app.exe"`     | Use quotes when the path contains spaces      |

A name is searched for in this order: the `PATH` variable, the registry's *App Paths*, Start Menu shortcuts, then `Program Files`, `Program Files (x86)` and `%LOCALAPPDATA%\Programs` (up to 3 folders deep). If nothing is found you'll see "File or application not found." In that case, give the full path.

### What goes to the AI

Anything that isn't a launch command goes to the AI. Messages that start like a question are always treated as questions, so "how do I open a file in Python?" or "what is Discord?" are answered rather than executed.

## Settings

| Setting             | Notes                                                                 |
|---------------------|-----------------------------------------------------------------------|
| Theme               | Dark or Light                                                         |
| Text size           | Small, Normal or Large                                                |
| AI model            | GPT-4o, GPT-4o mini or Local model                                    |
| Local model server  | Server URL (default `http://localhost:11434/v1`) and model name (default `llama3.1`) |
| OpenAI API key      | Verified when you click Connect                                       |
| System prompt       | Optional extra instructions added to every chat                       |
| Voice               | Read replies aloud on or off                                          |
| Danger zone         | Export all chats as JSON, or delete them all (click twice to confirm) |

Developer settings are constants near the top of `ai_assistant.py`, for example `MODELS`, `MAX_HISTORY`, `SPEECH_LANGUAGE`, `SUGGESTED_PROMPTS` and `USE_CUSTOM_TITLEBAR` (`False` restores the normal Windows title bar). To add a built-in command, add an entry to the `commands` list in `WindowsCommandHandler.__init__`.

## Building the .exe (Nuitka)

`build.bat` builds a standalone Windows program. Put it next to `ai_assistant.py` and `requirements.txt`, set the icon path at the top (default `C:\YamanAIapp\ico\icon.ico`) and run it.

The script:

1. Creates a Python 3.13 venv in `venv\` if there isn't one (installing Python 3.13 through `py install 3.13` if needed), and replaces a 3.14+ venv automatically.
2. Installs the dependencies and Nuitka.
3. Prepares the Windows speech module that pyttsx3 needs inside the .exe.
4. Compiles the app. The first build can take 10–30 minutes.

The result is `build\ai_assistant.dist\YamanAI.exe`. **Share or zip the whole `ai_assistant.dist` folder**, not just the .exe.

You need a C compiler. Visual Studio Build Tools with the "Desktop development with C++" workload is the most reliable choice.

For a single-file .exe, change `--mode=standalone` to `--mode=onefile` in `build.bat`. It starts more slowly, and antivirus programs flag it more often.

## Project structure

Everything lives in `ai_assistant.py`:

| Component                          | Responsibility                                           |
|------------------------------------|----------------------------------------------------------|
| `WindowsCommandHandler`            | Parses commands, searches for and launches programs      |
| `AIWorker`                         | Streams replies from OpenAI or a local server (QThread)  |
| `KeyValidationWorker`              | Verifies the API key (QThread)                           |
| `LaunchWorker`                     | Searches for and launches apps (QThread)                 |
| `STTWorker`                        | Records and transcribes microphone input (QThread)       |
| `TTSWorker`                        | Speaks queued text on one long-lived thread              |
| `ChatThread`, `ThreadStore`        | Conversations and saving them to disk                    |
| `Sidebar`, `Header`                | Navigation, chat list, status pill, window controls      |
| `ChatStream`, `MessageRow`, `CodeBlock` | Messages and highlighted code blocks                |
| `WelcomeScreen`, `Composer`        | Empty-chat screen and the input box                      |
| `SettingsModal`, `HelpModal`       | In-window dialogs                                        |
| `MainWindow`                       | Layout and wiring between all the pieces                 |

## Troubleshooting

**"Python was not found; run without arguments to install from the Microsoft Store"** — That is the Store shortcut, not your Python. Turn off `python.exe` and `python3.exe` under *Settings → Apps → Advanced app settings → App execution aliases*, or set `PYTHON_EXE` at the top of `build.bat`.

**PyAudio fails to install (`portaudio.h: No such file or directory`)** — You are on Python 3.14. Use Python 3.13; `build.bat` sets this up for you.

**"No module named 'openai.resources...'" in the .exe** — The build was made with an older `build.bat`. Use the current one, which bundles `openai`, `httpx2`, `httpcore2`, `anyio` and `pydantic` fully, then delete the `build` folder and rebuild.

**Seeing errors from the .exe** — Change `--windows-console-mode=disable` to `force` in `build.bat` and rebuild; error messages then appear in a console window.

**"PyAudio was not found" / "No microphone found"** — Install PyAudio as above, connect a microphone, and allow desktop apps to use it under *Settings → Privacy & security → Microphone*.

**"Could not reach the Google speech service"** — Voice input needs an internet connection.

**Replies are read in the wrong voice** — The first US English voice found is used (e.g. Microsoft Zira or David). Add voices under *Settings → Time & language → Speech*.

**"Could not reach the local model server"** — Start Ollama or LM Studio and check the server URL and model name in Settings (for Ollama, `ollama pull llama3.1` first).

**"Invalid API Key" or quota errors** — Check your key and billing at [platform.openai.com](https://platform.openai.com).

**Antivirus removes the .exe** — New, unsigned programs are often flagged by mistake. Add the `build` folder to your antivirus exclusions.

## Privacy and security

- Your API key is stored **unencrypted** in the Windows registry under `HKEY_CURRENT_USER\Software\AIAssistant`. Avoid saving it on shared computers.
- Conversations are saved as plain JSON in `%APPDATA%\AIAssistant\YamanAI\threads.json`.
- Messages are sent to OpenAI, or to your local server when Local model is selected. Voice recordings are sent to Google's speech recognition service.
- Launch commands run programs with your user's permissions; programs that need administrator rights show the normal Windows UAC prompt.
- Live preview writes the code to a temporary HTML file and opens it in your browser, so only preview code you trust.
