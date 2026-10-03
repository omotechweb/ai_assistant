# -*- coding: utf-8 -*-
"""
=====================================================================
  Windows AI Assistant
=====================================================================

  INSTALLATION (run in a command prompt):
      pip install PyQt6 openai speechrecognition pyttsx3 pyaudio

  RUN:
      python ai_assistant.py

  FEATURES:
      - Responsive dark theme (F11 = full screen, Esc = exit full screen)
      - OpenAI chat in a background QThread (UI never freezes)
      - Built-in commands: calculator, notepad, task manager, cmd,
        discord, whatsapp, spotify, steam, youtube, chrome/browser
      - Dynamic launcher: "open sample.exe", "C:/path/file.exe",
        "open obs" (searches PATH, App Paths, Start Menu, Program Files)
      - Voice commands via microphone (speech_recognition, Google, en-US)
      - Text-to-speech replies (pyttsx3, English voice) with an On/Off switch

  NOTES:
      - Voice commands require an internet connection (Google Speech API).
      - If "pip install pyaudio" fails:  pip install pipwin && pipwin install pyaudio
        (or install a prebuilt .whl matching your Python version)
=====================================================================
"""

import os
import re
import sys
import queue
import shutil
import subprocess
import webbrowser
from datetime import datetime

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSettings, QTimer, QEvent, QSize, QRectF
from PyQt6.QtGui import QFont, QKeySequence, QShortcut, QPainter, QColor, QPen
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLineEdit,
    QPushButton,
    QLabel,
    QFrame,
    QScrollArea,
    QSizePolicy,
    QCheckBox,
)

# The app still starts if openai is missing; the user is told what to install
try:
    import openai
    from openai import OpenAI

    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

# winreg only exists on Windows (used to detect installed apps)
try:
    import winreg
except ImportError:
    winreg = None

# Voice libraries are optional: if missing, only that feature is disabled
try:
    import speech_recognition as sr

    STT_AVAILABLE = True
except ImportError:
    sr = None
    STT_AVAILABLE = False

try:
    import pyttsx3

    TTS_AVAILABLE = True
except ImportError:
    pyttsx3 = None
    TTS_AVAILABLE = False


# =====================================================================
#  GENERAL SETTINGS
# =====================================================================
APP_NAME = "Windows AI Assistant"
ORG_NAME = "AIAssistant"
# Settings location used by the previous (Turkish) version; migrated once
LEGACY_SETTINGS = ("AIAsistan", "Windows AI Asistanı")

MODEL_NAME = "gpt-4o-mini"          # You can switch to "gpt-3.5-turbo"
MAX_HISTORY = 20                    # Max previous messages sent to the model
SPEECH_LANGUAGE = "en-US"           # Speech recognition language
SYSTEM_PROMPT = (
    "You are a helpful assistant for Windows users. Always respond in clear, "
    "concise, natural English, even if the user writes in another language, "
    "unless they explicitly ask for a different language."
)

# Dark color palette
C = {
    "base": "#1E1E2E",        # Main background
    "mantle": "#181825",      # Cards / chat background
    "crust": "#11111B",
    "surface0": "#313244",    # AI bubbles, input fields
    "surface1": "#45475A",    # Borders
    "surface2": "#585B70",
    "text": "#CDD6F4",
    "subtext": "#A6ADC8",
    "blue": "#89B4FA",        # User bubbles, main accent
    "lavender": "#B4BEFE",
    "green": "#A6E3A1",
    "yellow": "#F9E2AF",
    "red": "#F38BA8",
}


def hex_to_rgba(hex_color: str, alpha: int) -> str:
    """Converts '#RRGGBB' to a QSS 'rgba(r, g, b, a)' string (a: 0-255)."""
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r}, {g}, {b}, {alpha})"


# =====================================================================
#  DARK THEME (QSS)
# =====================================================================
DARK_STYLESHEET = f"""
/* ---------- General ---------- */
QMainWindow, QWidget#central {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {C['base']}, stop:1 {C['mantle']});
}}
QWidget {{
    color: {C['text']};
    font-family: "Segoe UI Variable Text", "Segoe UI", Arial, sans-serif;
    font-size: 10.5pt;
}}
QLabel {{
    background: transparent;
}}

/* ---------- Header ---------- */
QFrame#headerCard {{
    background-color: {C['mantle']};
    border: 1px solid {C['surface0']};
    border-radius: 12px;
}}
QLabel#titleLabel {{
    font-size: 16pt;
    font-weight: 600;
    color: {C['text']};
}}
QLabel#subtitleLabel {{
    color: {C['subtext']};
    font-size: 9pt;
}}

/* ---------- Input boxes (border glows on focus) ---------- */
QFrame#keyBox, QFrame#inputBar {{
    background-color: {C['surface0']};
    border: 1px solid {C['surface1']};
    border-radius: 10px;
}}
QFrame#keyBox:hover, QFrame#inputBar:hover {{
    border: 1px solid {C['surface2']};
}}
QFrame#keyBox[focused="true"], QFrame#inputBar[focused="true"] {{
    border: 1px solid {C['blue']};
}}
QLabel#keyPrefix {{
    color: {C['blue']};
    font-size: 9pt;
    font-weight: 600;
    padding-left: 6px;
}}
QLineEdit#keyInput, QLineEdit#messageInput {{
    background: transparent;
    border: none;
    padding: 9px 4px;
    color: {C['text']};
    selection-background-color: {C['blue']};
    selection-color: {C['crust']};
}}
QLineEdit:disabled {{
    color: {C['surface2']};
}}

/* ---------- Buttons ---------- */
QPushButton#primaryButton {{
    background-color: {C['blue']};
    color: {C['crust']};
    border: 1px solid transparent;
    border-radius: 10px;
    padding: 9px 22px;
    font-weight: 600;
}}
QPushButton#primaryButton:hover {{
    background-color: {C['lavender']};
}}
QPushButton#primaryButton:pressed {{
    background-color: #6F9FEF;
}}
QPushButton#primaryButton:focus {{
    border: 1px solid {C['text']};
}}
QPushButton#primaryButton:disabled {{
    background-color: {C['surface1']};
    color: {C['subtext']};
}}
QPushButton#ghostButton {{
    background: transparent;
    color: {C['subtext']};
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 6px 12px;
}}
QPushButton#ghostButton:hover {{
    background-color: {hex_to_rgba(C['blue'], 32)};
    color: {C['blue']};
}}
QPushButton#ghostButton:pressed {{
    background-color: {hex_to_rgba(C['blue'], 60)};
}}
QPushButton#ghostButton:focus {{
    border: 1px solid {C['blue']};
}}

/* ---------- Chat area ---------- */
QFrame#chatCard {{
    background-color: {C['mantle']};
    border: 1px solid {C['surface0']};
    border-radius: 12px;
}}
QScrollArea#chatArea {{
    background: transparent;
    border: none;
}}
QWidget#qt_scrollarea_viewport, QWidget#chatContainer {{
    background: transparent;
}}

/* ---------- Message bubbles ---------- */
QFrame#userBubble {{
    background-color: {C['blue']};
    border-radius: 10px;
    border-bottom-right-radius: 3px;
}}
QFrame#aiBubble {{
    background-color: {C['surface0']};
    border: 1px solid {C['surface1']};
    border-radius: 10px;
    border-bottom-left-radius: 3px;
}}
QFrame#systemBubble {{
    background-color: {hex_to_rgba(C['yellow'], 20)};
    border: 1px solid {hex_to_rgba(C['yellow'], 75)};
    border-radius: 10px;
}}
QFrame#successBubble {{
    background-color: {hex_to_rgba(C['green'], 22)};
    border: 1px solid {hex_to_rgba(C['green'], 85)};
    border-radius: 10px;
}}
QFrame#errorBubble {{
    background-color: {hex_to_rgba(C['red'], 28)};
    border: 1px solid {hex_to_rgba(C['red'], 110)};
    border-radius: 10px;
}}
QLabel#bubbleMeta {{
    font-size: 8.5pt;
    font-weight: 600;
    color: {C['subtext']};
}}
QFrame#userBubble QLabel#bubbleMeta {{
    color: {hex_to_rgba(C['crust'], 170)};
}}
QFrame#aiBubble QLabel#bubbleMeta {{
    color: {C['blue']};
}}
QLabel#bubbleText {{
    color: {C['text']};
}}
QFrame#userBubble QLabel#bubbleText {{
    color: {C['crust']};
}}
QFrame#systemBubble QLabel#bubbleText {{
    color: {C['yellow']};
    font-size: 9.5pt;
}}
QFrame#successBubble QLabel#bubbleText {{
    color: {C['green']};
    font-size: 9.5pt;
}}
QFrame#errorBubble QLabel#bubbleText {{
    color: {C['red']};
    font-size: 9.5pt;
}}

/* ---------- Microphone button (color changes with state) ---------- */
QPushButton#micButton {{
    background-color: {C['surface1']};
    color: {C['text']};
    border: 1px solid transparent;
    border-radius: 10px;
    padding: 9px 14px;
    font-weight: 600;
}}
QPushButton#micButton:hover {{
    background-color: {C['surface2']};
}}
QPushButton#micButton:focus {{
    border: 1px solid {C['blue']};
}}
QPushButton#micButton:disabled {{
    background-color: {C['surface0']};
    color: {C['surface2']};
}}
QPushButton#micButton[state="preparing"] {{
    background-color: {hex_to_rgba(C['yellow'], 45)};
    color: {C['yellow']};
}}
QPushButton#micButton[state="listening"] {{
    background-color: {C['red']};
    color: {C['crust']};
}}
QPushButton#micButton[state="processing"] {{
    background-color: {C['yellow']};
    color: {C['crust']};
}}

/* ---------- Scrollbar ---------- */
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 6px 3px 6px 0;
}}
QScrollBar::handle:vertical {{
    background: {C['surface1']};
    border-radius: 3px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: {C['surface2']};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: none;
    height: 0;
}}
"""


# =====================================================================
#  WINDOWS COMMAND & APPLICATION HANDLER
# =====================================================================
class WindowsCommandHandler:
    """
    Extracts the app/file to open from the user's message and launches it.

    parse() order:
      1) Full file path   ("open C:/folder/file.exe")      -> run directly
      2) .exe name        ("open sample.exe")              -> built-in commands
                                                               first, then search
      3) Built-in command ("can you open discord")
      4) Free app name    ("open obs", "launch vlc")       -> system search
      5) Otherwise        -> None (message goes to the AI)

    Questions like "how do I open a file in Python?" are always sent to the AI.
    run() is called inside a QThread because searching the disk can be slow.
    """

    SHORT_COMMAND_WORDS = 2
    MAX_APP_NAME_WORDS = 4
    PROGRAM_FILES_DEPTH = 3

    # Launch intent: "open", "launch", "start", "run", "execute", "fire up", "boot up"
    ACTION_PATTERN = re.compile(r"\b(?:open|launch|start|run|execute|fire up|boot up)\b")
    ACTION_TOKEN = re.compile(r"(?:open|launch|start|run|execute|fire|boot)")
    # Messages that begin like a question are sent to the AI, not executed.
    # ("can you open ..." / "could you open ..." are requests, so they are allowed.)
    QUESTION_START = re.compile(
        r"^(?:how|what|why|when|where|which|who|whose|is|are|was|were|does|did|do|"
        r"should|shall|can i|could i|may i|explain|tell me|describe|define)\b"
    )

    # Path and exe patterns (applied to the original text)
    QUOTED_PATTERN = re.compile(r'["“”]([^"“”]+)["“”]')
    PATH_WITH_EXT_PATTERN = re.compile(
        r"([a-zA-Z]:[\\/][^\"<>|?*\n]*?\.(?:exe|bat|cmd|msc|lnk|url|msi))(?=$|[\s'’.,!?])",
        re.IGNORECASE,
    )
    PATH_PLAIN_PATTERN = re.compile(r"([a-zA-Z]:[\\/][^\s\"<>|?*'’]*)")
    EXE_PATTERN = re.compile(r"(?<![\\/\w])([\w\-.+]+\.(?:exe|bat|cmd|msc))(?!\w)", re.IGNORECASE)

    # Words removed when extracting an app name ("please open the obs app for me" -> "obs")
    FILLER_WORDS = {
        "please", "pls", "can", "could", "would", "will", "you", "u", "me", "up",
        "the", "a", "an", "my", "this", "that", "it", "app", "application", "program",
        "file", "called", "named", "now", "quickly", "just", "go", "ahead", "kindly",
        "hey", "assistant", "i", "want", "to", "need", "like", "let's", "lets",
    }
    # Words that end the app name ("open vlc and play music" -> "vlc")
    STOP_WORDS = {"and", "then", "with", "in", "on", "for", "from", "using", "via", "into", "so"}
    # Large or irrelevant folders skipped while scanning Program Files
    SKIP_DIRS = {"windowsapps", "windows defender", "common files", "microsoft.net",
                 "windows nt", "internet explorer", "reference assemblies", "windowspowershell"}

    def __init__(self):
        # Order matters: specific apps first, generic browser last
        # (so "open youtube in chrome" opens YouTube).
        self.commands = [
            {"name": "Task Manager",
             "patterns": [r"\btask ?manager\b", r"\btaskmgr\b"],
             "action": self._open_task_manager},
            {"name": "Command Prompt",
             "patterns": [r"\bcmd\b", r"\bcommand prompt\b", r"\bcommand line\b", r"\bterminal\b"],
             "action": self._open_cmd},
            {"name": "Calculator",
             "patterns": [r"\bcalculator\b", r"\bcalc\b"],
             "action": self._open_calculator},
            {"name": "Notepad",
             "patterns": [r"\bnotepad(?![+\w])", r"\btext editor\b"],
             "action": self._open_notepad},
            {"name": "Discord",
             "patterns": [r"\bdiscord\b"],
             "action": self._open_discord},
            {"name": "WhatsApp",
             "patterns": [r"\bwhats ?app\b"],
             "action": self._open_whatsapp},
            {"name": "Spotify",
             "patterns": [r"\bspotify\b"],
             "action": self._open_spotify},
            {"name": "Steam",
             "patterns": [r"\bsteam\b"],
             "action": self._open_steam},
            {"name": "YouTube",
             "patterns": [r"\byou ?tube\b"],
             "action": self._open_youtube},
            {"name": "Chrome",
             "patterns": [r"\b(?:google )?chrome\b", r"\b(?:web )?browser\b"],
             "action": self._open_chrome},
        ]

    # =================================================================
    #  TEXT ANALYSIS
    # =================================================================
    @staticmethod
    def normalize(text: str) -> str:
        """Lowercases text and unifies apostrophes/quotes."""
        text = text.replace("’", "'").replace("‘", "'")
        return text.lower().strip()

    def _is_question(self, normalized: str) -> bool:
        return bool(self.QUESTION_START.match(normalized))

    def _looks_like_command(self, normalized: str, max_words: int) -> bool:
        """A message counts as a command if it has a launch verb, or is short and not a question."""
        if self._is_question(normalized):
            return False
        if self.ACTION_PATTERN.search(normalized):
            return True
        if "?" in normalized:
            return False
        return len(normalized.split()) <= max_words

    def _find_known(self, normalized: str):
        """Looks for a built-in command pattern in the normalized text."""
        for command in self.commands:
            for pattern in command["patterns"]:
                if re.search(pattern, normalized):
                    return command
        return None

    def parse(self, text: str):
        """
        Parses the message and returns a request dict, or None if it is not a command.
        Request kinds: "known", "path", "search"
        """
        normalized = self.normalize(text)

        # 1) Full file path
        path = self._extract_path(text)
        if path and self._looks_like_command(normalized, max_words=3):
            return {"kind": "path", "path": path, "label": os.path.basename(path) or path}

        # 2) .exe / .bat name
        exe_match = self.EXE_PATTERN.search(text)
        if exe_match and self._looks_like_command(normalized, max_words=3):
            exe_name = exe_match.group(1)
            stem = self.normalize(os.path.splitext(exe_name)[0])
            known = self._find_known(stem)
            if known:
                return {"kind": "known", "command": known, "label": known["name"]}
            return {"kind": "search", "targets": [exe_name], "label": exe_name}

        # 3) Built-in command
        if self._looks_like_command(normalized, max_words=self.SHORT_COMMAND_WORDS):
            known = self._find_known(normalized)
            if known:
                return {"kind": "known", "command": known, "label": known["name"]}

        # 4) Free app name after a launch verb
        if not self._is_question(normalized) and self.ACTION_PATTERN.search(normalized):
            name = self._extract_app_name(normalized)
            if name:
                return {"kind": "search", "targets": [name], "label": name}

        return None

    def _extract_path(self, text: str):
        """Extracts a file/folder path (quoted, with extension, or without spaces)."""
        quoted = self.QUOTED_PATTERN.search(text)
        if quoted:
            candidate = quoted.group(1).strip()
            # Only accept quoted text that really looks like a path
            if re.match(r"^(?:[a-zA-Z]:[\\/]|%\w+%|\\\\)", candidate):
                return os.path.normpath(os.path.expandvars(candidate))

        for pattern in (self.PATH_WITH_EXT_PATTERN, self.PATH_PLAIN_PATTERN):
            match = pattern.search(text)
            if match:
                candidate = match.group(1).strip().rstrip(".,!?")
                return os.path.normpath(os.path.expandvars(candidate))
        return None

    def _extract_app_name(self, normalized: str):
        """
        "could you please open obs studio for me" -> "obs studio"
        "launch vlc and play music"               -> "vlc"
        """
        tokens = [t.strip(".,!?;:\"") for t in normalized.split()]
        tokens = [t for t in tokens if t]

        action_index = next(
            (i for i, token in enumerate(tokens) if self.ACTION_TOKEN.fullmatch(token)), None
        )
        if action_index is None:
            return None

        # In English the app name usually follows the verb
        name_words = []
        for word in tokens[action_index + 1:]:
            word = word.split("'")[0]  # "discord's" -> "discord"
            if word in self.STOP_WORDS:
                if name_words:
                    break
                continue
            if word and word not in self.FILLER_WORDS and not self.ACTION_TOKEN.fullmatch(word):
                name_words.append(word)

        # Fallback: words before the verb ("obs, open it")
        if not name_words:
            name_words = [w for w in (t.split("'")[0] for t in tokens[:action_index])
                          if w and w not in self.FILLER_WORDS and w not in self.STOP_WORDS]

        if not name_words or len(name_words) > self.MAX_APP_NAME_WORDS:
            return None
        return " ".join(name_words)

    # =================================================================
    #  EXECUTION (called from a QThread)
    # =================================================================
    def run(self, request: dict):
        """Executes the request. Returns (success, message_for_user)."""
        kind = request["kind"]

        if kind == "known":
            return self.execute(request["command"])

        if not self._is_windows():
            return False, "Launching files and applications is only supported on Windows."

        if kind == "path":
            path = request["path"]
            if not os.path.exists(path):
                return False, "File or application not found."
            self._launch_file(path)
            return True, f"{request['label']} launched."

        if kind == "search":
            for target in request["targets"]:
                found = self.find_application(target)
                if found:
                    self._launch_file(found)
                    return True, f"{target} launched."
            return False, "File or application not found."

        return False, "Unknown command type."

    def execute(self, command: dict):
        """Runs a built-in command."""
        try:
            return True, command["action"]()
        except FileNotFoundError:
            return False, (f"Could not open {command['name']}. The application was not found "
                           f"or this command only works on Windows.")
        except Exception as exc:
            return False, f"Could not open {command['name']}: {exc}"

    @staticmethod
    def _launch_file(path: str):
        """
        Starts .exe files with Popen inside their own folder (some programs need
        their working directory). If admin rights are required (WinError 740), or
        the target is a .lnk/.bat/folder, os.startfile is used instead.
        """
        if path.lower().endswith(".exe"):
            try:
                subprocess.Popen([path], cwd=os.path.dirname(path) or None)
                return
            except OSError as exc:
                if getattr(exc, "winerror", None) != 740:
                    raise
        os.startfile(path)

    # =================================================================
    #  APPLICATION SEARCH
    # =================================================================
    def find_application(self, target: str):
        """
        Searches for the application in this order:
          1) PATH environment variable
          2) Registry "App Paths" (chrome, excel, etc. are registered here)
          3) Start Menu shortcuts
          4) Program Files folders (limited depth)
        """
        has_extension = bool(os.path.splitext(target)[1])
        if has_extension:
            exe_names = [target]
        else:
            exe_names = list(dict.fromkeys([f"{target}.exe", f"{target.replace(' ', '')}.exe"]))

        # 1) PATH
        for exe in exe_names + ([] if has_extension else [target]):
            found = shutil.which(exe)
            if found:
                return found

        # 2) App Paths
        for exe in exe_names:
            found = self._find_in_app_paths(exe)
            if found:
                return found

        # 3) Start Menu
        stem = os.path.splitext(target)[0] if has_extension else target
        found = self._find_in_start_menu(stem)
        if found:
            return found

        # 4) Program Files
        return self._find_in_program_files(exe_names)

    def _find_in_app_paths(self, exe_name: str):
        if winreg is None:
            return None
        key_path = rf"Software\Microsoft\Windows\CurrentVersion\App Paths\{exe_name}"
        for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            value = self._read_registry(root, key_path, "")
            if value:
                value = os.path.expandvars(value.strip('"'))
                if os.path.isfile(value):
                    return value
        return None

    def _find_in_start_menu(self, name: str):
        """Finds the best matching .lnk/.url shortcut in the Start Menu."""
        key = self.normalize(name)
        roots = [
            os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs"),
            os.path.expandvars(r"%ProgramData%\Microsoft\Windows\Start Menu\Programs"),
        ]
        best_path, best_score = None, 0
        for root in roots:
            if not os.path.isdir(root):
                continue
            for dirpath, _dirs, files in os.walk(root):
                for file in files:
                    stem, ext = os.path.splitext(file)
                    if ext.lower() not in (".lnk", ".url"):
                        continue
                    stem_n = self.normalize(stem)
                    if "uninstall" in stem_n:
                        continue
                    if stem_n == key:
                        score = 3                      # Exact match
                    elif stem_n.startswith(key):
                        score = 2                      # "obs" -> "OBS Studio"
                    elif key in stem_n.split():
                        score = 1                      # Appears as a whole word
                    else:
                        continue
                    if score > best_score:
                        best_path, best_score = os.path.join(dirpath, file), score
                        if score == 3:
                            return best_path
        return best_path

    def _find_in_program_files(self, exe_names):
        """Searches Program Files folders for an .exe, with limited depth."""
        wanted = {name.lower() for name in exe_names}
        roots = [
            os.environ.get("ProgramFiles"),
            os.environ.get("ProgramFiles(x86)"),
            os.path.expandvars(r"%LOCALAPPDATA%\Programs"),
        ]
        for root in dict.fromkeys(r for r in roots if r and os.path.isdir(r)):
            base_depth = root.rstrip("\\/").count(os.sep)
            for dirpath, dirnames, filenames in os.walk(root):
                # Limit depth and skip irrelevant folders
                if dirpath.count(os.sep) - base_depth >= self.PROGRAM_FILES_DEPTH:
                    dirnames[:] = []
                dirnames[:] = [d for d in dirnames if d.lower() not in self.SKIP_DIRS]
                for file in filenames:
                    if file.lower() in wanted:
                        return os.path.join(dirpath, file)
        return None

    # =================================================================
    #  HELPERS
    # =================================================================
    @staticmethod
    def _is_windows() -> bool:
        return sys.platform == "win32"

    def _ensure_windows(self):
        if not self._is_windows():
            raise FileNotFoundError("Not running on Windows")

    @staticmethod
    def _protocol_registered(protocol: str) -> bool:
        """Is a URL protocol such as 'discord:' or 'spotify:' registered on this system?"""
        if winreg is None:
            return False
        try:
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, protocol):
                return True
        except OSError:
            return False

    @staticmethod
    def _read_registry(root, path: str, name: str):
        """Reads a registry value; returns None if it does not exist."""
        if winreg is None:
            return None
        try:
            with winreg.OpenKey(root, path) as key:
                value, _ = winreg.QueryValueEx(key, name)
                return value
        except OSError:
            return None

    def _launch(self, name, exe_candidates=(), protocol=None, protocol_uri=None, web_url=None):
        """For built-in apps: try the .exe, then the URL protocol, then the web version."""
        if self._is_windows():
            for path, args in exe_candidates:
                if not path:
                    continue
                full_path = os.path.expandvars(path)
                if os.path.isfile(full_path):
                    subprocess.Popen([full_path, *args])
                    return f"Opening {name}..."

            # Microsoft Store versions are usually opened through their protocol
            if protocol and self._protocol_registered(protocol):
                try:
                    os.startfile(protocol_uri or f"{protocol}:")
                    return f"Opening {name}..."
                except OSError:
                    pass

        if web_url:
            webbrowser.open(web_url)
            return f"{name} app not found, opening the web version in your browser..."

        raise FileNotFoundError(name)

    # =================================================================
    #  BUILT-IN COMMANDS
    # =================================================================
    def _open_calculator(self):
        self._ensure_windows()
        subprocess.Popen(["calc.exe"])
        return "Opening Calculator..."

    def _open_notepad(self):
        self._ensure_windows()
        subprocess.Popen(["notepad.exe"])
        return "Opening Notepad..."

    def _open_task_manager(self):
        self._ensure_windows()
        os.startfile("taskmgr.exe")  # Handles the UAC prompt correctly if needed
        return "Opening Task Manager..."

    def _open_cmd(self):
        self._ensure_windows()
        subprocess.Popen(
            ["cmd.exe"],
            creationflags=subprocess.CREATE_NEW_CONSOLE,
            cwd=os.path.expanduser("~"),
        )
        return "Opening Command Prompt..."

    def _open_discord(self):
        return self._launch(
            "Discord",
            exe_candidates=[(r"%LOCALAPPDATA%\Discord\Update.exe", ["--processStart", "Discord.exe"])],
            protocol="discord", protocol_uri="discord://",
            web_url="https://discord.com/app",
        )

    def _open_whatsapp(self):
        return self._launch(
            "WhatsApp",
            exe_candidates=[(r"%LOCALAPPDATA%\WhatsApp\WhatsApp.exe", [])],
            protocol="whatsapp", protocol_uri="whatsapp:",
            web_url="https://web.whatsapp.com",
        )

    def _open_spotify(self):
        return self._launch(
            "Spotify",
            exe_candidates=[(r"%APPDATA%\Spotify\Spotify.exe", [])],
            protocol="spotify", protocol_uri="spotify:",
            web_url="https://open.spotify.com",
        )

    def _open_steam(self):
        steam_exe = None
        if winreg is not None:
            steam_exe = self._read_registry(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamExe")
        return self._launch(
            "Steam",
            exe_candidates=[
                (steam_exe, []),
                (r"%ProgramFiles(x86)%\Steam\steam.exe", []),
                (r"%ProgramFiles%\Steam\steam.exe", []),
            ],
            protocol="steam", protocol_uri="steam://open/main",
            web_url="https://store.steampowered.com",
        )

    def _open_chrome(self):
        if self._is_windows():
            found = self._find_in_app_paths("chrome.exe")
            if not found:
                for path in (r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
                             r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
                             r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"):
                    full_path = os.path.expandvars(path)
                    if os.path.isfile(full_path):
                        found = full_path
                        break
            if found:
                subprocess.Popen([found])
                return "Opening Chrome..."
        webbrowser.open("https://www.google.com")
        return "Chrome not found, opening your default browser..."

    @staticmethod
    def _open_youtube():
        webbrowser.open("https://www.youtube.com")
        return "Opening YouTube in your browser..."


# =====================================================================
#  BACKGROUND WORKERS (QThread)
# =====================================================================
class AIWorker(QThread):
    """Sends the OpenAI chat request in the background so the UI never freezes."""

    response_ready = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, api_key: str, messages: list, model: str = MODEL_NAME, parent=None):
        super().__init__(parent)
        self.api_key = api_key
        self.messages = list(messages)
        self.model = model

    def run(self):
        try:
            client = OpenAI(api_key=self.api_key, timeout=60.0)
            completion = client.chat.completions.create(
                model=self.model,
                messages=self.messages,
                temperature=0.7,
            )
            answer = (completion.choices[0].message.content or "").strip()
            self.response_ready.emit(answer or "(The response was empty.)")

        except openai.AuthenticationError:
            self.error_occurred.emit("Invalid API Key. Check your key and save it again.")
        except openai.RateLimitError:
            self.error_occurred.emit("Rate limit or quota exceeded. Check your account balance or wait a moment.")
        except openai.APITimeoutError:
            self.error_occurred.emit("The request timed out. Please try again.")
        except openai.APIConnectionError:
            self.error_occurred.emit("Could not reach the OpenAI servers. Check your internet connection.")
        except openai.APIStatusError as exc:
            self.error_occurred.emit(f"API error ({exc.status_code}): {exc.message}")
        except Exception as exc:
            self.error_occurred.emit(f"Unexpected error: {exc}")


class KeyValidationWorker(QThread):
    """Checks in the background whether the saved API Key works."""

    validated = pyqtSignal(bool, str, bool)  # (is_valid, message, is_auth_error)

    def __init__(self, api_key: str, parent=None):
        super().__init__(parent)
        self.api_key = api_key

    def run(self):
        try:
            client = OpenAI(api_key=self.api_key, timeout=20.0)
            client.models.list()
            self.validated.emit(True, "Connected", False)
        except openai.AuthenticationError:
            self.validated.emit(False, "Invalid API Key", True)
        except openai.APIConnectionError:
            self.validated.emit(False, "No connection", False)
        except Exception as exc:
            self.validated.emit(False, f"Could not verify: {exc}", False)


class LaunchWorker(QThread):
    """Searches for and launches applications in the background (disk scans can be slow)."""

    launched = pyqtSignal(bool, str)  # (success, message)

    def __init__(self, handler: WindowsCommandHandler, request: dict, parent=None):
        super().__init__(parent)
        self.handler = handler
        self.request = request

    def run(self):
        try:
            ok, message = self.handler.run(self.request)
        except FileNotFoundError:
            ok, message = False, "File or application not found."
        except PermissionError:
            ok, message = False, "You don't have permission to run this file."
        except Exception as exc:
            ok, message = False, f"Could not launch: {exc}"
        self.launched.emit(ok, message)


def clean_for_speech(text: str, max_chars: int = 1500) -> str:
    """Strips Markdown symbols, code blocks and links so the text reads naturally aloud."""
    text = re.sub(r"```.*?```", " Code example shown on screen. ", text, flags=re.DOTALL)
    text = re.sub(r"https?://\S+", " link ", text)
    text = re.sub(r"[`*_#>|~]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_chars:
        text = text[:max_chars].rsplit(" ", 1)[0] + ". The rest is shown on screen."
    return text


class TTSWorker(QThread):
    """
    Text-to-speech thread (pyttsx3).

    A single long-lived thread is used: the pyttsx3 engine (SAPI5/COM on Windows)
    is bound to the thread that created it, and creating a new thread per
    sentence can make the second utterance hang. Texts are queued and spoken in order.
    """

    error_occurred = pyqtSignal(str)
    info = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._queue = queue.Queue()
        self._stop_requested = False
        self._engine = None

    # ----- Called from the main thread -----
    def speak(self, text: str):
        if text:
            self._queue.put(text)

    def stop_current(self):
        """Interrupts the current sentence and drops anything still queued."""
        self._stop_requested = True
        with self._queue.mutex:
            self._queue.queue.clear()

    def shutdown(self):
        self.stop_current()
        self._queue.put(None)  # Sentinel that ends the loop

    # ----- Background -----
    def run(self):
        com_initialized = False
        if sys.platform == "win32":
            try:
                import pythoncom  # Part of pywin32, installed with pyttsx3

                pythoncom.CoInitialize()  # Each thread must initialize COM itself
                com_initialized = True
            except ImportError:
                pass

        try:
            engine = pyttsx3.init()
        except Exception as exc:
            self.error_occurred.emit(f"Could not start the text-to-speech engine: {exc}")
            return

        self._engine = engine
        engine.setProperty("rate", 175)
        if not self._select_english_voice(engine):
            self.info.emit("No English voice was found; the system default voice will be used.")

        # Check for stop requests at each word (engine.stop must run on this thread)
        engine.connect("started-word", self._on_word)

        try:
            while True:
                text = self._queue.get()
                if text is None:
                    break
                self._stop_requested = False
                try:
                    engine.say(text)
                    engine.runAndWait()
                except Exception as exc:
                    self.error_occurred.emit(f"Text-to-speech error: {exc}")
        finally:
            try:
                engine.stop()
            except Exception:
                pass
            if com_initialized:
                pythoncom.CoUninitialize()

    def _on_word(self, name, location, length):
        # This callback runs on the engine's own thread, so stop() is safe here
        if self._stop_requested and self._engine is not None:
            try:
                self._engine.stop()
            except Exception:
                pass

    @staticmethod
    def _select_english_voice(engine) -> bool:
        """Selects an English voice, preferring US English (e.g. Microsoft Zira / David)."""
        try:
            voices = engine.getProperty("voices") or []
        except Exception:
            return False

        def describe(voice):
            name = (getattr(voice, "name", "") or "").lower()
            voice_id = (getattr(voice, "id", "") or "").lower()
            languages = " ".join(str(lang) for lang in (getattr(voice, "languages", None) or [])).lower()
            return f"{name} {voice_id} {languages}"

        us_markers = ("en-us", "en_us", "english (united states)", "zira", "david", "mark")
        any_english = ("english", "en-gb", "en_gb", "en-au", "en_au", "en-", "en_")

        for markers in (us_markers, any_english):
            for voice in voices:
                if any(marker in describe(voice) for marker in markers):
                    engine.setProperty("voice", voice.id)
                    return True
        return False


class STTWorker(QThread):
    """Listens to the microphone and converts speech to English text via Google Speech Recognition."""

    listening_started = pyqtSignal()
    processing_started = pyqtSignal()
    recognized = pyqtSignal(str)
    failed = pyqtSignal(str, bool)  # (message, is_real_error)

    LISTEN_TIMEOUT = 6        # Seconds to wait for the user to start speaking
    PHRASE_TIME_LIMIT = 12    # Maximum length of a single phrase (seconds)

    def run(self):
        recognizer = sr.Recognizer()
        recognizer.dynamic_energy_threshold = True
        recognizer.pause_threshold = 0.8

        try:
            with sr.Microphone() as source:
                # Adapt sensitivity to background noise
                recognizer.adjust_for_ambient_noise(source, duration=0.6)
                self.listening_started.emit()
                audio = recognizer.listen(
                    source, timeout=self.LISTEN_TIMEOUT, phrase_time_limit=self.PHRASE_TIME_LIMIT
                )

            self.processing_started.emit()
            text = recognizer.recognize_google(audio, language=SPEECH_LANGUAGE)
            text = (text or "").strip()
            if text:
                self.recognized.emit(text)
            else:
                self.failed.emit("Sorry, I couldn't understand that. Please try again.", False)

        except sr.WaitTimeoutError:
            self.failed.emit("No speech detected. Start speaking right after clicking Listen.", False)
        except sr.UnknownValueError:
            self.failed.emit("Sorry, I couldn't understand that. Try speaking more clearly and closer to the mic.", False)
        except sr.RequestError:
            self.failed.emit("Could not reach the Google speech service. Check your internet connection.", True)
        except AttributeError:
            # speech_recognition raises AttributeError when PyAudio is missing
            self.failed.emit("PyAudio was not found. Run: pip install pyaudio", True)
        except OSError:
            self.failed.emit("No microphone found or it is unavailable. Check the connection and the "
                             "microphone permission in Windows privacy settings.", True)
        except Exception as exc:
            self.failed.emit(f"Speech recognition error: {exc}", True)


# =====================================================================
#  CUSTOM UI COMPONENTS
# =====================================================================
class FocusFrame(QFrame):
    """Frame whose border is highlighted while the input inside it has focus."""

    def watch(self, widget: QWidget):
        widget.installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
            self.setProperty("focused", event.type() == QEvent.Type.FocusIn)
            # Dynamic properties need a re-polish for QSS to update
            self.style().unpolish(self)
            self.style().polish(self)
        return super().eventFilter(obj, event)


class ToggleSwitch(QCheckBox):
    """QCheckBox drawn as a sliding switch with a round knob."""

    TRACK_W, TRACK_H = 34, 18

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def sizeHint(self) -> QSize:
        fm = self.fontMetrics()
        return QSize(self.TRACK_W + 10 + fm.horizontalAdvance(self.text()) + 4,
                     max(self.TRACK_H, fm.height()) + 6)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def hitButton(self, pos) -> bool:
        return self.rect().contains(pos)  # Clicking the label also toggles

    def setText(self, text: str):
        super().setText(text)
        self.updateGeometry()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        on = self.isChecked()

        y = (self.height() - self.TRACK_H) / 2
        track = QRectF(1, y, self.TRACK_W, self.TRACK_H)
        radius = self.TRACK_H / 2

        # Track
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(C["blue"] if on else C["surface1"]))
        painter.drawRoundedRect(track, radius, radius)

        # Knob
        knob = self.TRACK_H - 6
        knob_x = track.right() - knob - 3 if on else track.left() + 3
        painter.setBrush(QColor(C["crust"] if on else C["subtext"]))
        painter.drawEllipse(QRectF(knob_x, y + 3, knob, knob))

        # Keyboard focus ring
        if self.hasFocus():
            painter.setPen(QPen(QColor(C["lavender"]), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(track.adjusted(-1, -1, 1, 1), radius + 1, radius + 1)

        # Label
        painter.setPen(QColor(C["text"] if on else C["subtext"]))
        text_rect = QRectF(self.TRACK_W + 10, 0, self.width() - self.TRACK_W - 10, self.height())
        painter.drawText(text_rect, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), self.text())
        painter.end()


class MessageBubble(QFrame):
    """A single chat message bubble."""

    ROLE_STYLES = {
        "user": ("userBubble", "You"),
        "assistant": ("aiBubble", "Assistant"),
        "typing": ("aiBubble", "Assistant"),
        "system": ("systemBubble", "System"),
        "success": ("successBubble", "System"),
        "error": ("errorBubble", "Error"),
    }
    COMPACT_ROLES = ("system", "success", "error")
    TYPING_TEXT = "Typing"

    def __init__(self, role: str, text: str, parent=None):
        super().__init__(parent)
        self.role = role
        object_name, sender = self.ROLE_STYLES.get(role, self.ROLE_STYLES["system"])
        self.setObjectName(object_name)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Minimum)

        compact = role in self.COMPACT_ROLES
        layout = QVBoxLayout(self)
        if compact:
            layout.setContentsMargins(12, 7, 12, 7)
        else:
            layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(3)

        self.meta = None
        if not compact:
            self.meta = QLabel(f"{sender}   {datetime.now():%H:%M}")
            self.meta.setObjectName("bubbleMeta")
            if role == "user":
                self.meta.setAlignment(Qt.AlignmentFlag.AlignRight)
            layout.addWidget(self.meta)

        # Plain text (no HTML injection), selectable, word-wrapped
        self.body = QLabel(text)
        self.body.setObjectName("bubbleText")
        self.body.setTextFormat(Qt.TextFormat.PlainText)
        self.body.setWordWrap(True)
        self.body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.body)

        self._max_width = 480

    def set_text(self, text: str):
        self.body.setText(text)
        self.fit_to_width(self._max_width)

    def fit_to_width(self, max_width: int):
        """
        Sizes the bubble to its text: short messages stay narrow, long ones grow
        up to max_width. Called again on every resize, so full screen stays tidy.
        """
        self._max_width = max_width
        margins = self.layout().contentsMargins()
        available = max_width - margins.left() - margins.right()

        self.body.ensurePolished()
        metrics = self.body.fontMetrics()
        # Measure the longest typing state so the bubble does not jitter
        text = self.TYPING_TEXT + "..." if self.role == "typing" else self.body.text()
        natural = max(metrics.horizontalAdvance(line) for line in (text.split("\n") or [""]))
        if self.meta is not None:
            self.meta.ensurePolished()
            natural = max(natural, self.meta.fontMetrics().horizontalAdvance(self.meta.text()))

        self.body.setFixedWidth(max(20, min(natural + 4, available)))


class ChatView(QScrollArea):
    """Resize-aware scroll area that stacks message bubbles."""

    BUBBLE_WIDTH_RATIO = 0.70   # Bubbles use at most 70% of the width
    BUBBLE_MAX_PX = 860         # Keeps lines readable in full screen
    BUBBLE_MIN_PX = 220

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("chatArea")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.container = QWidget()
        self.container.setObjectName("chatContainer")
        self.messages_layout = QVBoxLayout(self.container)
        self.messages_layout.setContentsMargins(18, 18, 18, 18)
        self.messages_layout.setSpacing(10)
        self.messages_layout.addStretch(1)  # Keeps messages at the top
        self.setWidget(self.container)

        self._bubbles = []
        self._typing_row = None
        self._typing_bubble = None
        self._typing_step = 0
        self._typing_timer = QTimer(self)
        self._typing_timer.setInterval(400)
        self._typing_timer.timeout.connect(self._animate_typing)

        # Auto-scroll to the bottom as content grows
        self.verticalScrollBar().rangeChanged.connect(
            lambda _min, maximum: self.verticalScrollBar().setValue(maximum)
        )

    def add_message(self, role: str, text: str):
        """User on the right, assistant on the left, system notices centered."""
        bubble = MessageBubble(role, text)
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)

        if role == "user":
            row_layout.addStretch(1)
            row_layout.addWidget(bubble)
        elif role in MessageBubble.COMPACT_ROLES:
            row_layout.addStretch(1)
            row_layout.addWidget(bubble)
            row_layout.addStretch(1)
        else:
            row_layout.addWidget(bubble)
            row_layout.addStretch(1)

        # Insert right before the trailing stretch
        self.messages_layout.insertWidget(self.messages_layout.count() - 1, row)
        self._bubbles.append(bubble)
        self._apply_width(bubble)
        return row, bubble

    # ----- "Typing..." indicator -----
    def show_typing(self):
        if self._typing_row is not None:
            return
        self._typing_step = 0
        self._typing_row, self._typing_bubble = self.add_message("typing", MessageBubble.TYPING_TEXT)
        self._typing_timer.start()

    def hide_typing(self):
        if self._typing_row is None:
            return
        self._typing_timer.stop()
        self._remove_row(self._typing_row, self._typing_bubble)
        self._typing_row = None
        self._typing_bubble = None

    def _animate_typing(self):
        if self._typing_bubble is not None:
            self._typing_step = (self._typing_step + 1) % 4
            self._typing_bubble.set_text(MessageBubble.TYPING_TEXT + "." * self._typing_step)

    # ----- Clearing and sizing -----
    def _remove_row(self, row: QWidget, bubble: MessageBubble):
        self.messages_layout.removeWidget(row)
        row.deleteLater()
        if bubble in self._bubbles:
            self._bubbles.remove(bubble)

    def clear_messages(self):
        self.hide_typing()
        while self.messages_layout.count() > 1:  # Keep the trailing stretch
            item = self.messages_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._bubbles.clear()

    def _bubble_width(self) -> int:
        usable = self.viewport().width() - 36  # Inner margins
        return max(self.BUBBLE_MIN_PX, min(int(usable * self.BUBBLE_WIDTH_RATIO), self.BUBBLE_MAX_PX))

    def _apply_width(self, bubble: MessageBubble):
        bubble.fit_to_width(self._bubble_width())

    def resizeEvent(self, event):
        """Rescales every bubble whenever the window grows or shrinks (incl. full screen)."""
        super().resizeEvent(event)
        width = self._bubble_width()
        for bubble in self._bubbles:
            bubble.fit_to_width(width)


# =====================================================================
#  MAIN WINDOW
# =====================================================================
class MainWindow(QMainWindow):
    """The assistant's main window."""

    # Microphone button texts per state: (normal, narrow window)
    MIC_TEXTS = {
        "idle": ("🎤  Listen", "🎤"),
        "preparing": ("Preparing...", "…"),
        "listening": ("●  Listening...", "●"),
        "processing": ("Processing...", "…"),
    }

    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(960, 740)
        self.setMinimumSize(480, 460)  # Lower bound only; no upper bound

        # State
        self.api_key = ""
        self.history = []
        self.ai_worker = None
        self.key_worker = None
        self.launch_worker = None
        self.stt_worker = None
        self.tts_worker = None
        self._busy = False
        self._compact = False
        self._mic_state = "idle"
        self.command_handler = WindowsCommandHandler()
        self.settings = QSettings(ORG_NAME, APP_NAME)

        self._build_ui()
        self._setup_shortcuts()
        self._load_saved_key()
        self._show_welcome()
        self._load_voice_settings()

    # -----------------------------------------------------------------
    #  UI SETUP (layout-based only, no fixed sizes)
    # -----------------------------------------------------------------
    def _build_ui(self):
        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)

        self.root_layout = QVBoxLayout(central)
        self.root_layout.setContentsMargins(18, 18, 18, 18)
        self.root_layout.setSpacing(14)

        self.root_layout.addWidget(self._build_header())
        self.root_layout.addWidget(self._build_chat_card(), stretch=1)  # Chat takes all free space
        self.root_layout.addWidget(self._build_input_bar())

    def _build_header(self) -> QFrame:
        """Title, TTS switch, status pill and API Key field (QGridLayout)."""
        card = QFrame()
        card.setObjectName("headerCard")
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

        grid = QGridLayout(card)
        grid.setContentsMargins(18, 16, 18, 16)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(12)
        grid.setColumnStretch(0, 1)  # Left column expands

        # Row 0: title + subtitle | TTS switch | status
        title_col = QVBoxLayout()
        title_col.setSpacing(0)
        title = QLabel(APP_NAME)
        title.setObjectName("titleLabel")
        self.subtitle_label = QLabel(f"Model: {MODEL_NAME}   |   Press F11 for full screen")
        self.subtitle_label.setObjectName("subtitleLabel")
        title_col.addWidget(title)
        title_col.addWidget(self.subtitle_label)

        self.status_label = QLabel()
        self.status_label.setObjectName("statusLabel")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.tts_toggle = ToggleSwitch("Text-to-Speech: Off")
        self.tts_toggle.setToolTip("Reads assistant replies and app notifications aloud")
        self.tts_toggle.toggled.connect(self.on_tts_toggled)

        top_row = QHBoxLayout()
        top_row.setSpacing(14)
        top_row.addLayout(title_col, stretch=1)
        top_row.addWidget(self.tts_toggle, alignment=Qt.AlignmentFlag.AlignTop)
        top_row.addWidget(self.status_label, alignment=Qt.AlignmentFlag.AlignTop)
        grid.addLayout(top_row, 0, 0, 1, 2)  # Spans both columns

        # Row 1: API Key box | Save button
        self.key_box = FocusFrame()
        self.key_box.setObjectName("keyBox")
        key_box_layout = QHBoxLayout(self.key_box)
        key_box_layout.setContentsMargins(8, 2, 4, 2)
        key_box_layout.setSpacing(6)

        self.key_prefix = QLabel("API Key")
        self.key_prefix.setObjectName("keyPrefix")

        self.api_key_input = QLineEdit()
        self.api_key_input.setObjectName("keyInput")
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)  # Masked input
        self.api_key_input.setPlaceholderText("Paste your OpenAI API key (starts with sk-...)")
        self.api_key_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.api_key_input.returnPressed.connect(self.save_api_key)
        self.key_box.watch(self.api_key_input)

        self.toggle_key_btn = QPushButton("Show")
        self.toggle_key_btn.setObjectName("ghostButton")
        self.toggle_key_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_key_btn.clicked.connect(self.toggle_key_visibility)

        key_box_layout.addWidget(self.key_prefix)
        key_box_layout.addWidget(self.api_key_input, stretch=1)
        key_box_layout.addWidget(self.toggle_key_btn)

        self.save_key_btn = QPushButton("Save / Connect")
        self.save_key_btn.setObjectName("primaryButton")
        self.save_key_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_key_btn.clicked.connect(self.save_api_key)

        grid.addWidget(self.key_box, 1, 0)
        grid.addWidget(self.save_key_btn, 1, 1)

        self._set_status("Not connected", C["subtext"])
        return card

    def _build_chat_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("chatCard")
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(2, 2, 2, 2)

        self.chat_view = ChatView()
        layout.addWidget(self.chat_view)
        return card

    def _build_input_bar(self) -> QFrame:
        self.input_bar = FocusFrame()
        self.input_bar.setObjectName("inputBar")
        self.input_bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        layout = QHBoxLayout(self.input_bar)
        layout.setContentsMargins(10, 6, 6, 6)
        layout.setSpacing(6)

        self.input_field = QLineEdit()
        self.input_field.setObjectName("messageInput")
        self.input_field.setPlaceholderText("Type your message or command (e.g. \"open discord\", \"open sample.exe\")")
        self.input_field.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.input_field.returnPressed.connect(self.send_message)  # Enter sends
        self.input_bar.watch(self.input_field)

        self.mic_btn = QPushButton()
        self.mic_btn.setObjectName("micButton")
        self.mic_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mic_btn.setToolTip("Click and speak in English; your words are sent as a message")
        self.mic_btn.clicked.connect(self.start_listening)

        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setObjectName("ghostButton")
        self.clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_btn.clicked.connect(self.clear_chat)

        self.send_btn = QPushButton("Send")
        self.send_btn.setObjectName("primaryButton")
        self.send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.send_btn.clicked.connect(self.send_message)

        layout.addWidget(self.input_field, stretch=1)
        layout.addWidget(self.mic_btn)
        layout.addWidget(self.clear_btn)
        layout.addWidget(self.send_btn)

        self._set_mic_state("idle")
        self.input_field.setFocus()
        return self.input_bar

    def _setup_shortcuts(self):
        QShortcut(QKeySequence("F11"), self, activated=self.toggle_fullscreen)
        QShortcut(QKeySequence("Escape"), self, activated=self.exit_fullscreen)

    # -----------------------------------------------------------------
    #  RESPONSIVE LAYOUT
    # -----------------------------------------------------------------
    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def exit_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()

    def resizeEvent(self, event):
        """Adjusts margins and secondary elements to the window size."""
        super().resizeEvent(event)
        width = self.width()
        if width < 700:
            margin = 10
        elif width < 1400:
            margin = 18
        else:
            margin = 28
        self.root_layout.setContentsMargins(margin, margin, margin, margin)

        # Hide secondary labels in narrow windows to free up space
        self.subtitle_label.setVisible(width >= 620)
        self.key_prefix.setVisible(width >= 560)

        # Shorten the voice control labels in narrow windows
        compact = width < 640
        if compact != self._compact:
            self._compact = compact
            self._set_mic_state(self._mic_state)
            self._update_tts_text()

    # -----------------------------------------------------------------
    #  API KEY
    # -----------------------------------------------------------------
    def _load_saved_key(self):
        saved_key = self.settings.value("api_key", "", type=str)
        if not saved_key:
            # One-time migration from the previous version's settings location
            legacy = QSettings(*LEGACY_SETTINGS)
            saved_key = legacy.value("api_key", "", type=str)
            if saved_key:
                self.settings.setValue("api_key", saved_key)
                self.settings.setValue("tts_enabled", legacy.value("tts_enabled", False, type=bool))

        if saved_key:
            self.api_key = saved_key
            self.api_key_input.setText(saved_key)
            self._set_status("Saved key loaded", C["green"])

    def toggle_key_visibility(self):
        if self.api_key_input.echoMode() == QLineEdit.EchoMode.Password:
            self.api_key_input.setEchoMode(QLineEdit.EchoMode.Normal)
            self.toggle_key_btn.setText("Hide")
        else:
            self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
            self.toggle_key_btn.setText("Show")

    def save_api_key(self):
        key = self.api_key_input.text().strip()

        if not key:
            self.chat_view.add_message("system", "Please enter your API Key first!")
            self.api_key_input.setFocus()
            return

        if not OPENAI_AVAILABLE:
            self.chat_view.add_message("error", "The openai library is not installed. Run: pip install openai")
            return

        if not key.startswith("sk-"):
            self.chat_view.add_message("system", "Note: OpenAI keys usually start with \"sk-\". Trying anyway.")

        self.api_key = key
        self.settings.setValue("api_key", key)  # Remembered on next launch

        self.save_key_btn.setEnabled(False)
        self._set_status("Verifying...", C["yellow"])

        self.key_worker = KeyValidationWorker(key, self)
        self.key_worker.validated.connect(self.on_key_validated)
        self.key_worker.finished.connect(self.key_worker.deleteLater)
        self.key_worker.start()

    def on_key_validated(self, ok: bool, message: str, is_auth_error: bool):
        self.save_key_btn.setEnabled(True)
        self.key_worker = None

        if ok:
            self._set_status("Connected", C["green"])
            self.chat_view.add_message("success", "API Key saved and connection verified.")
        elif is_auth_error:
            self.api_key = ""
            self.settings.remove("api_key")
            self._set_status(message, C["red"])
            self.chat_view.add_message("error", "Invalid API Key. Enter a valid key and save it again.")
        else:
            # Network issue etc.: keep the key so it can be retried later
            self._set_status(message, C["yellow"])
            self.chat_view.add_message("system", f"Key saved but could not be verified ({message}).")

    # -----------------------------------------------------------------
    #  SENDING MESSAGES
    # -----------------------------------------------------------------
    def send_message(self):
        """Checks for an app/file launch request first; otherwise sends the message to the AI."""
        if self.ai_worker is not None or self.launch_worker is not None:
            return

        text = self.input_field.text().strip()
        if not text:
            return

        self.input_field.clear()
        self.chat_view.add_message("user", text)

        # 1) App / file launch request -> LaunchWorker (background)
        request = self.command_handler.parse(text)
        if request:
            self._start_launch(request)
            return

        # 2) API Key check
        if not self.api_key:
            self.chat_view.add_message("system", "Please enter your API Key first!")
            self.api_key_input.setFocus()
            return

        if not OPENAI_AVAILABLE:
            self.chat_view.add_message("error", "The openai library is not installed. Run: pip install openai")
            return

        # 3) OpenAI request -> AIWorker (background)
        self.history.append({"role": "user", "content": text})
        messages = [{"role": "system", "content": SYSTEM_PROMPT}] + self.history[-MAX_HISTORY:]

        self.set_busy(True, mode="ai")
        self.ai_worker = AIWorker(self.api_key, messages, parent=self)
        self.ai_worker.response_ready.connect(self.handle_ai_response)
        self.ai_worker.error_occurred.connect(self.handle_ai_error)
        self.ai_worker.finished.connect(self.on_ai_worker_finished)
        self.ai_worker.start()

    # ----- Launching applications -----
    def _start_launch(self, request: dict):
        if request["kind"] == "search":
            self.chat_view.add_message("system", f"Searching for {request['label']}...")

        self.set_busy(True, mode="launch")
        self.launch_worker = LaunchWorker(self.command_handler, request, self)
        self.launch_worker.launched.connect(self.handle_launch_result)
        self.launch_worker.finished.connect(self.on_launch_worker_finished)
        self.launch_worker.start()

    def handle_launch_result(self, ok: bool, message: str):
        self.chat_view.add_message("success" if ok else "error", message)
        self.speak(message)

    def on_launch_worker_finished(self):
        if self.launch_worker is not None:
            self.launch_worker.deleteLater()
            self.launch_worker = None
        self.set_busy(False)

    # ----- AI responses -----
    def handle_ai_response(self, answer: str):
        self.chat_view.hide_typing()
        self.history.append({"role": "assistant", "content": answer})
        self.chat_view.add_message("assistant", answer)
        self.speak(answer)

    def handle_ai_error(self, error_message: str):
        self.chat_view.hide_typing()
        if self.history and self.history[-1]["role"] == "user":
            self.history.pop()  # Remove the failed message from the context
        self.chat_view.add_message("error", error_message)

    def on_ai_worker_finished(self):
        if self.ai_worker is not None:
            self.ai_worker.deleteLater()
            self.ai_worker = None
        self.set_busy(False)

    def clear_chat(self):
        self.chat_view.clear_messages()
        self.history.clear()
        self._show_welcome()

    # -----------------------------------------------------------------
    #  TEXT-TO-SPEECH (TTS)
    # -----------------------------------------------------------------
    def _load_voice_settings(self):
        if self.settings.value("tts_enabled", False, type=bool):
            self.tts_toggle.setChecked(True)  # Triggers on_tts_toggled

    def _update_tts_text(self):
        state = "On" if self.tts_toggle.isChecked() else "Off"
        prefix = "TTS" if self._compact else "Text-to-Speech"
        self.tts_toggle.setText(f"{prefix}: {state}")

    def on_tts_toggled(self, checked: bool):
        if checked and not TTS_AVAILABLE:
            self.chat_view.add_message("error", "pyttsx3 is not installed. Run: pip install pyttsx3")
            self.tts_toggle.blockSignals(True)
            self.tts_toggle.setChecked(False)
            self.tts_toggle.blockSignals(False)
            checked = False
        elif checked:
            self._ensure_tts_worker()
        elif self.tts_worker is not None:
            self.tts_worker.stop_current()  # Stop speaking immediately when switched off

        self._update_tts_text()
        self.settings.setValue("tts_enabled", checked)

    def _ensure_tts_worker(self):
        if self.tts_worker is not None:
            return
        self.tts_worker = TTSWorker(self)
        self.tts_worker.error_occurred.connect(self.on_tts_error)
        self.tts_worker.info.connect(lambda msg: self.chat_view.add_message("system", msg))
        self.tts_worker.finished.connect(self.on_tts_worker_finished)
        self.tts_worker.start()

    def speak(self, text: str):
        """Queues text for speaking if TTS is on (the UI does not wait)."""
        if self.tts_toggle.isChecked() and self.tts_worker is not None:
            self.tts_worker.speak(clean_for_speech(text))

    def on_tts_error(self, message: str):
        self.chat_view.add_message("error", message)
        if "Could not start" in message:
            self.tts_toggle.setChecked(False)

    def on_tts_worker_finished(self):
        if self.tts_worker is not None:
            self.tts_worker.deleteLater()
            self.tts_worker = None

    # -----------------------------------------------------------------
    #  SPEECH-TO-TEXT (STT)
    # -----------------------------------------------------------------
    def _set_mic_state(self, state: str):
        """Updates the mic button text and color (via the QSS 'state' property)."""
        self._mic_state = state
        normal, short = self.MIC_TEXTS[state]
        self.mic_btn.setText(short if self._compact else normal)
        self.mic_btn.setProperty("state", state)
        self.mic_btn.style().unpolish(self.mic_btn)
        self.mic_btn.style().polish(self.mic_btn)

    def start_listening(self):
        if self.stt_worker is not None or self._busy:
            return  # Already listening or another task is running
        if not STT_AVAILABLE:
            self.chat_view.add_message(
                "error", "speechrecognition is not installed. Run: pip install speechrecognition pyaudio")
            return

        # Don't let the assistant's own voice get recorded
        if self.tts_worker is not None:
            self.tts_worker.stop_current()

        self._set_mic_state("preparing")
        self._set_status("Preparing microphone", C["yellow"])

        self.stt_worker = STTWorker(self)
        self.stt_worker.listening_started.connect(self.on_listening_started)
        self.stt_worker.processing_started.connect(self.on_processing_started)
        self.stt_worker.recognized.connect(self.on_speech_recognized)
        self.stt_worker.failed.connect(self.on_speech_failed)
        self.stt_worker.finished.connect(self.on_stt_worker_finished)
        self.stt_worker.start()

    def on_listening_started(self):
        self._set_mic_state("listening")
        self._set_status("Listening, speak now", C["red"])

    def on_processing_started(self):
        self._set_mic_state("processing")
        self._set_status("Converting speech to text", C["yellow"])

    def on_speech_recognized(self, text: str):
        """Writes the recognized text into the input box and sends it."""
        self._set_mic_state("idle")
        self._refresh_status()
        self.input_field.setText(text)
        self.send_message()

    def on_speech_failed(self, message: str, is_error: bool):
        self._set_mic_state("idle")
        self._refresh_status()
        self.chat_view.add_message("error" if is_error else "system", message)

    def on_stt_worker_finished(self):
        if self.stt_worker is not None:
            self.stt_worker.deleteLater()
            self.stt_worker = None
        if self._mic_state != "idle":
            self._set_mic_state("idle")
        self.mic_btn.setEnabled(not self._busy)

    # -----------------------------------------------------------------
    #  HELPERS
    # -----------------------------------------------------------------
    def _refresh_status(self):
        if self._busy:
            return  # set_busy manages the status while busy
        if self.api_key:
            self._set_status("Connected", C["green"])
        else:
            self._set_status("Not connected", C["subtext"])

    def set_busy(self, busy: bool, mode: str = "ai"):
        """Locks the input while a request is running and shows the state."""
        self._busy = busy
        self.mic_btn.setEnabled(not busy)
        self.send_btn.setEnabled(not busy)
        self.input_field.setEnabled(not busy)
        if busy:
            self.send_btn.setText("Waiting")
            if mode == "ai":
                self.chat_view.show_typing()
                self._set_status("Waiting for response", C["blue"])
            else:
                self._set_status("Launching application", C["yellow"])
        else:
            self.chat_view.hide_typing()
            self.send_btn.setText("Send")
            self._refresh_status()
            self.input_field.setFocus()

    def _set_status(self, text: str, color: str):
        """Updates the pill-shaped status indicator in the top right."""
        self.status_label.setText(f"●  {text}")
        self.status_label.setStyleSheet(
            f"color: {color};"
            f"background-color: {hex_to_rgba(color, 30)};"
            f"border: 1px solid {hex_to_rgba(color, 85)};"
            "border-radius: 11px;"
            "padding: 4px 12px;"
            "font-size: 9pt;"
        )

    def _show_welcome(self):
        self.chat_view.add_message(
            "assistant",
            "Hi! I can answer your questions or open programs on your computer.\n\n"
            "Built-in commands: calculator, notepad, task manager, cmd, terminal, "
            "discord, whatsapp, spotify, steam, youtube, chrome, browser\n\n"
            "Any program: \"open sample.exe\", \"open obs\", \"open C:/Games/game.exe\"\n"
            "Use quotes for paths with spaces: open \"C:/Program Files/App/app.exe\"\n\n"
            "Voice: click Listen and speak in English. Turn on the Text-to-Speech "
            "switch in the top right to hear the replies.",
        )

    # -----------------------------------------------------------------
    #  SHUTDOWN
    # -----------------------------------------------------------------
    def closeEvent(self, event):
        for worker in (self.ai_worker, self.key_worker, self.launch_worker):
            if worker is not None and worker.isRunning():
                worker.wait(3000)

        # TTS: clear the queue and end its loop
        if self.tts_worker is not None:
            self.tts_worker.shutdown()
            self.tts_worker.wait(3000)

        # STT: the microphone timeout is only a few seconds
        if self.stt_worker is not None and self.stt_worker.isRunning():
            if not self.stt_worker.wait(2000):
                self.stt_worker.terminate()  # Last resort so closing never hangs
                self.stt_worker.wait(500)
        event.accept()


# =====================================================================
#  ENTRY POINT
# =====================================================================
def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORG_NAME)
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(DARK_STYLESHEET)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
