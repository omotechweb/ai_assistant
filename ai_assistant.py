# -*- coding: utf-8 -*-
"""
=====================================================================
  YamanAI  -  Windows AI Assistant (desktop)
=====================================================================

  INSTALLATION (run in a command prompt):
      pip install PyQt6 openai speechrecognition pyttsx3 pyaudio qtawesome keyring

      (keyring is optional: it keeps the API key in Windows Credential Manager)

  RUN:
      python ai_assistant.py

  DESIGN:
      Same look as the YamanAI web app: chats grouped by Today /
      Yesterday / Older in the sidebar, full-width message rows with
      avatars, dark code blocks with Copy and Live preview, a welcome
      screen with suggested prompts, a large rounded input box and a
      settings window (theme, font size, model, system prompt, export).

  FEATURES:
      - Streaming replies from OpenAI (GPT-4o / GPT-4o mini) or a local
        OpenAI-compatible model server, with a Stop button (QThread)
      - Built-in commands + dynamic .exe / path launcher (QThread)
      - Voice commands (speech_recognition, Google, en-US) and
        text-to-speech replies (pyttsx3), each in its own QThread
      - Dark and light theme, three font sizes, saved conversations
      - Frameless, resizable, responsive window (F11 = full screen)
      - NEW in 1.1:
          * Edit & resend your last message, Retry after an error
          * Attach text/code files (paperclip button or drag & drop)
          * "Scroll to bottom" button, Up arrow recalls your last message
          * Creativity setting (Precise / Balanced / Creative)
          * Reply info (model + response time) under each answer
          * Open websites ("open github.com"), folders (Downloads,
            Documents, Desktop), File Explorer, Windows Settings, Paint...
          * Import chats from a JSON export, window size/position remembered
          * Taskbar flashes when a reply finishes in the background
      - NEW in 1.2:
          * Turkish interface (Settings > Language), automatic / Turkish / English
            reply language, Turkish voice input (tr-TR) and Turkish TTS voice
          * Turkish launch commands ("discord'u aç", "hesap makinesini aç")
          * Image attachments for vision models (paperclip, drag & drop, Ctrl+V)
          * Custom OpenAI model ID and token usage under each reply
          * Automatic chat titles, pinned chats, Save button on code blocks
          * "lock my computer" / "bilgisayarı kilitle" and the Recycle Bin

  SHORTCUTS:
      Enter = send, Shift+Enter = new line, Ctrl+N = new chat,
      Ctrl+B = toggle sidebar, Ctrl+F = search chats, Ctrl+Shift+R = regenerate / retry,
      Ctrl+L = focus input, Ctrl+Shift+C = copy last reply, Up = recall last message,
      Ctrl+= / Ctrl+- / Ctrl+0 = text size, F11 = full screen,
      Esc = close dialog / stop reply / exit full screen

  NOTES:
      - Voice commands require an internet connection (Google Speech API).
      - PyAudio has prebuilt Windows wheels up to Python 3.13.
=====================================================================
"""

import os
import re
import sys
import html
import base64
import json
import math
import time
import uuid
import queue
import shutil
import weakref
import tempfile
import subprocess
import webbrowser
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import (
    Qt, QThread, pyqtSignal, QSettings, QTimer, QEvent, QSize, QRectF, QPoint, QPointF, QStandardPaths,
    QLocale, QBuffer, QByteArray, QIODevice,
)
from PyQt6.QtGui import (
    QFont, QKeySequence, QShortcut, QPainter, QColor, QPen, QIcon, QAction, QBrush,
    QLinearGradient, QGuiApplication, QPainterPath, QPixmap, QImage,
)
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLineEdit,
    QTextEdit,
    QPlainTextEdit,
    QPushButton,
    QToolButton,
    QLabel,
    QFrame,
    QScrollArea,
    QSizePolicy,
    QCheckBox,
    QSplitter,
    QStackedWidget,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QFileDialog,
    QInputDialog,
    QMessageBox,
    QToolTip,
)

# Icons (optional: the app still works without them, just without icons)
try:
    import qtawesome as qta

    QTA_AVAILABLE = True
except ImportError:
    qta = None
    QTA_AVAILABLE = False

if QTA_AVAILABLE:
    # Qt sometimes asks for a 0x0 icon while a button is being laid out; qtawesome
    # then prints QPainter warnings. Returning an empty pixmap for that case is harmless.
    try:
        from PyQt6.QtGui import QPixmap
        from qtawesome.iconic_font import CharIconEngine

        _qta_pixmap = CharIconEngine.pixmap

        def _safe_pixmap(self, size, mode, state):
            if size.width() <= 0 or size.height() <= 0:
                return QPixmap()
            return _qta_pixmap(self, size, mode, state)

        CharIconEngine.pixmap = _safe_pixmap
    except Exception:
        pass

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

# keyring is optional: when installed the API key goes to Windows Credential Manager
# instead of plain text in the registry (pip install keyring)
try:
    import keyring

    KEYRING_AVAILABLE = True
except ImportError:
    keyring = None
    KEYRING_AVAILABLE = False

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
APP_NAME = "YamanAI"                # Window title, sidebar brand, taskbar name
APP_SHORT_NAME = "YamanAI"
APP_VERSION_LABEL = "Beta 1.2"
ORG_NAME = "AIAssistant"
# Settings are stored under the previous app name so saved keys/preferences are kept
SETTINGS_APP_NAME = "Windows AI Assistant"
LEGACY_SETTINGS = ("AIAsistan", "Windows AI Asistanı")

MAX_HISTORY = 20                    # Max previous messages sent to the model
# Languages: interface, replies and voice input
UI_LANGUAGES = {"tr": "Türkçe", "en": "English"}          # Shown in their own language
REPLY_LANGUAGES = {"auto": "Same as my message", "tr": "Always Turkish", "en": "Always English"}
SPEECH_LANGUAGES = {"tr": ("Turkish (tr-TR)", "tr-TR"), "en": ("English (en-US)", "en-US")}
UI_LANG = "en"                      # Set in main() before any widget is created

SYSTEM_PROMPT_BASE = (
    "You are YamanAI, a helpful assistant for Windows users. Be clear, concise and natural. "
    "Use Markdown code blocks with a language tag when you show code or commands."
)
REPLY_LANGUAGE_RULES = {
    "auto": "Reply in the same language the user writes in (for example Turkish when the user "
            "writes Turkish), unless they explicitly ask for another language.",
    "tr": "Always reply in natural, fluent Turkish, even if the user writes in another language, "
          "unless they explicitly ask for a different language.",
    "en": "Always reply in natural English, even if the user writes in another language, "
          "unless they explicitly ask for a different language.",
}


def build_system_prompt(reply_language: str, extra: str = "") -> str:
    prompt = SYSTEM_PROMPT_BASE + " " + REPLY_LANGUAGE_RULES.get(reply_language, REPLY_LANGUAGE_RULES["auto"])
    if extra:
        prompt += "\n\nAdditional instructions from the user:\n" + extra
    return prompt

# Models offered in Settings and in the header pill
MODELS = [
    {"id": "gpt-4o", "label": "GPT-4o (Powerful)", "short": "GPT-4o", "provider": "openai"},
    {"id": "gpt-4o-mini", "label": "GPT-4o mini (Fast)", "short": "GPT-4o Mini", "provider": "openai"},
    {"id": "custom", "label": "Custom OpenAI model", "short": "Custom", "provider": "openai"},
    {"id": "local", "label": "Local model", "short": "Local", "provider": "local"},
]
DEFAULT_MODEL_ID = "gpt-4o"
DEFAULT_LOCAL_BASE_URL = "http://localhost:11434/v1"   # Ollama; LM Studio uses :1234
DEFAULT_LOCAL_MODEL = "llama3.1"
DEFAULT_CUSTOM_MODEL = ""
TITLE_MODEL = "gpt-4o-mini"         # Writes automatic chat titles (OpenAI models)

FONT_SIZES = {"sm": ("Small", 10.5), "base": ("Normal", 12.0), "lg": ("Large", 13.5)}
DEFAULT_FONT_SIZE = "sm"

# "Creativity" setting -> sampling temperature
TEMPERATURES = {"precise": ("Precise", 0.2), "balanced": ("Balanced", 0.7), "creative": ("Creative", 1.0)}
DEFAULT_TEMPERATURE = "balanced"

# Attachments: text/code files inserted into the prompt as a code block
MAX_ATTACHMENT_BYTES = 100_000
# Images are sent to vision models (GPT-4o, llava...) as JPEG
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
MAX_IMAGE_BYTES = 20_000_000
MAX_IMAGE_SIDE = 1568                # Longer side is scaled down to this before sending
MAX_IMAGES_PER_MESSAGE = 4
IMAGE_HISTORY_MESSAGES = 6           # Older messages are resent without their images
ATTACHMENT_LANGS = {
    ".py": "python", ".js": "javascript", ".ts": "typescript", ".jsx": "jsx", ".tsx": "tsx",
    ".html": "html", ".htm": "html", ".css": "css", ".json": "json", ".md": "markdown",
    ".java": "java", ".c": "c", ".h": "c", ".cpp": "cpp", ".hpp": "cpp", ".cs": "csharp",
    ".go": "go", ".rs": "rust", ".sh": "bash", ".ps1": "powershell", ".bat": "bat", ".cmd": "bat",
    ".sql": "sql", ".xml": "xml", ".yml": "yaml", ".yaml": "yaml", ".ini": "ini", ".toml": "toml",
    ".php": "php", ".rb": "ruby", ".kt": "kotlin", ".swift": "swift", ".lua": "lua", ".r": "r",
    ".txt": "", ".csv": "", ".log": "", ".cfg": "",
}

# Suggested prompts on the welcome screen (clicking fills the input box)
SUGGESTED_PROMPTS = [
    ("Write code", "Can you write a simple web scraper in Python?"),
    ("Explain", "How do quantum computers work?"),
    ("Translate", "Translate this into Turkish: \"Hello world!\""),
    ("Brainstorm", "Suggest 5 creative names for a mobile app."),
]
PREVIEW_LANGS = {"html", "css", "javascript", "js"}

# App icon: "icon.ico" bundled next to the program, or the development path below
APP_ICON_FILE = "icon.ico"
APP_ICON_DEV_PATH = r"C:\YamanAIapp\ico\icon.ico"
APP_USER_MODEL_ID = "YamanAI.Desktop"

USE_CUSTOM_TITLEBAR = True          # False = keep the normal Windows title bar
SIDEBAR_WIDTH = 260
CHAT_COLUMN_MAX = 768               # Readable width of messages (like the web app)
SIDEBAR_AUTO_HIDE_WIDTH = 860       # Sidebar hides itself below this window width


# =====================================================================
#  THEMES (same palette as the web app)
# =====================================================================
THEMES = {
    "dark": {
        "bg": "#212121", "sidebar": "#171717", "input": "#2F2F2F", "card": "#111111",
        "text": "#F3F4F6", "text_strong": "#FFFFFF", "body": "#E5E7EB",
        "muted": "#9CA3AF", "faint": "#6B7280", "dim": "#4B5563",
        "border": "#1F2937", "border_strong": "#374151",
        "hover": "rgba(255, 255, 255, 13)", "active": "rgba(255, 255, 255, 26)",
        "user_row": "rgba(255, 255, 255, 8)", "line": "rgba(255, 255, 255, 26)",
        "field": "rgba(255, 255, 255, 13)", "chip": "rgba(255, 255, 255, 15)",
        "chip_hover": "rgba(255, 255, 255, 31)", "chip_border": "rgba(255, 255, 255, 51)",
        "composer_border": "rgba(255, 255, 255, 26)",
        "accent_text": "#60A5FA", "inline_code_bg": "#363636", "inline_code_fg": "#93C5FD",
        "title_from": "#FFFFFF", "title_to": "#6B7280",
    },
    "light": {
        "bg": "#F5F5F5", "sidebar": "#FFFFFF", "input": "#FFFFFF", "card": "#FFFFFF",
        "text": "#111827", "text_strong": "#000000", "body": "#1F2937",
        "muted": "#6B7280", "faint": "#9CA3AF", "dim": "#9CA3AF",
        "border": "#E5E7EB", "border_strong": "#D1D5DB",
        "hover": "rgba(0, 0, 0, 10)", "active": "rgba(0, 0, 0, 20)",
        "user_row": "rgba(0, 0, 0, 8)", "line": "rgba(0, 0, 0, 25)",
        "field": "rgba(0, 0, 0, 8)", "chip": "rgba(0, 0, 0, 6)",
        "chip_hover": "rgba(0, 0, 0, 12)", "chip_border": "rgba(0, 0, 0, 30)",
        "composer_border": "#D1D5DB",
        "accent_text": "#2563EB", "inline_code_bg": "#E5E7EB", "inline_code_fg": "#1D4ED8",
        "title_from": "#111827", "title_to": "#6B7280",
    },
}
# Colors that are the same in both themes
FIXED_COLORS = {
    "accent": "#2563EB", "accent_hover": "#3B82F6", "accent_soft": "#93C5FD", "cyan": "#06B6D4",
    "green": "#22C55E", "green_text": "#4ADE80", "red": "#F87171", "red_strong": "#DC2626",
    "amber": "#F59E0B", "white": "#FFFFFF",
    "code_header": "#1A1A1A", "code_bg": "#0A0A0A", "code_text": "#D4D4D4", "code_muted": "#6B7280",
    "avatar_user": "#374151", "avatar_user_border": "#4B5563", "avatar_user_icon": "#D1D5DB",
}

P = {}            # The active palette (filled by apply_theme)
CURRENT_THEME = "dark"


def apply_theme(name: str):
    global CURRENT_THEME
    CURRENT_THEME = name if name in THEMES else "dark"
    P.clear()
    P.update(FIXED_COLORS)
    P.update(THEMES[CURRENT_THEME])


apply_theme("dark")


# =====================================================================
#  TRANSLATIONS  (English source text -> Turkish)
# =====================================================================
TR = {
    # ----- Built-in apps and folders -----
    "Lock computer": "Bilgisayarı kilitle", "Task Manager": "Görev Yöneticisi",
    "Command Prompt": "Komut İstemi", "Calculator": "Hesap Makinesi", "Notepad": "Not Defteri",
    "Snipping Tool": "Ekran Alıntısı Aracı", "Recycle Bin": "Geri Dönüşüm Kutusu",
    "File Explorer": "Dosya Gezgini", "Downloads": "İndirilenler", "Documents": "Belgeler",
    "Desktop": "Masaüstü", "Desktop folder": "Masaüstü klasörü", "Windows Settings": "Windows Ayarları",
    "Control Panel": "Denetim Masası",
    "Opening Calculator...": "Hesap Makinesi açılıyor...",
    "Opening Notepad...": "Not Defteri açılıyor...",
    "Opening Paint...": "Paint açılıyor...",
    "Opening File Explorer...": "Dosya Gezgini açılıyor...",
    "Opening Windows Settings...": "Windows Ayarları açılıyor...",
    "Opening Control Panel...": "Denetim Masası açılıyor...",
    "Opening Task Manager...": "Görev Yöneticisi açılıyor...",
    "Opening Command Prompt...": "Komut İstemi açılıyor...",
    "Opening Chrome...": "Chrome açılıyor...",
    "Opening YouTube in your browser...": "YouTube tarayıcınızda açılıyor...",
    "Locking your computer...": "Bilgisayarınız kilitleniyor...",
    "Opening the Recycle Bin...": "Geri Dönüşüm Kutusu açılıyor...",
    "Chrome not found, opening your default browser...": "Chrome bulunamadı, varsayılan tarayıcınız açılıyor...",
    "Opening your {name} folder...": "{name} klasörünüz açılıyor...",
    "Opening {name}...": "{name} açılıyor...",
    "Opening {url} in your browser...": "{url} tarayıcınızda açılıyor...",
    "{name} app not found, opening the web version in your browser...":
        "{name} uygulaması bulunamadı, web sürümü tarayıcınızda açılıyor...",
    "{name} launched.": "{name} başlatıldı.",
    "Searching for {name}...": "{name} aranıyor...",
    "No app named \"{name}\" was found, so YamanAI will answer instead.":
        "\"{name}\" adında bir uygulama bulunamadı, bu yüzden YamanAI cevap verecek.",
    "Unknown command type.": "Bilinmeyen komut türü.",
    "Could not open your web browser.": "Web tarayıcınız açılamadı.",
    "Launching files and applications is only supported on Windows.":
        "Dosya ve uygulama başlatma yalnızca Windows'ta desteklenir.",
    "File or application not found.": "Dosya veya uygulama bulunamadı.",
    "You don't have permission to run this file.": "Bu dosyayı çalıştırma izniniz yok.",
    "Could not launch: {error}": "Başlatılamadı: {error}",
    "Could not open {name}. The application was not found or this command only works on Windows.":
        "{name} açılamadı. Uygulama bulunamadı ya da bu komut yalnızca Windows'ta çalışır.",
    "Could not open {name}: {error}": "{name} açılamadı: {error}",

    # ----- Models, options, groups -----
    "GPT-4o (Powerful)": "GPT-4o (Güçlü)", "GPT-4o mini (Fast)": "GPT-4o mini (Hızlı)",
    "Custom OpenAI model": "Özel OpenAI modeli", "Local model": "Yerel model",
    "Custom": "Özel", "Local": "Yerel",
    "Small": "Küçük", "Normal": "Normal", "Large": "Büyük",
    "Precise": "Kesin", "Balanced": "Dengeli", "Creative": "Yaratıcı",
    "Same as my message": "Mesajımla aynı", "Always Turkish": "Hep Türkçe", "Always English": "Hep İngilizce",
    "Turkish (tr-TR)": "Türkçe (tr-TR)", "English (en-US)": "İngilizce (en-US)",
    "Pinned": "Sabitlenenler", "Today": "Bugün", "Yesterday": "Dün",
    "Previous 7 days": "Önceki 7 gün", "Older": "Daha eski",
    "Dark": "Koyu", "Light": "Açık",

    # ----- Welcome screen and composer -----
    "How can I help you?": "Size nasıl yardımcı olabilirim?",
    "Write code, translate, or just chat with YamanAI. You can also ask it to open apps on your PC.":
        "Kod yazdırın, çeviri yapın ya da YamanAI ile sohbet edin. Bilgisayarınızdaki uygulamaları da açabilir.",
    "Write code": "Kod yaz", "Explain": "Açıkla", "Translate": "Çevir", "Brainstorm": "Fikir üret",
    "Can you write a simple web scraper in Python?": "Python ile basit bir web kazıyıcı yazabilir misin?",
    "How do quantum computers work?": "Kuantum bilgisayarlar nasıl çalışır?",
    "Translate this into Turkish: \"Hello world!\"": "Şunu İngilizceye çevir: \"Merhaba dünya!\"",
    "Suggest 5 creative names for a mobile app.": "Bir mobil uygulama için 5 yaratıcı isim öner.",
    "Ask YamanAI anything, or type \"open discord\"...": "YamanAI'ye bir şey sor ya da \"discord'u aç\" yaz...",
    "Preparing the microphone...": "Mikrofon hazırlanıyor...",
    "Listening... speak now": "Dinliyorum... şimdi konuşun",
    "Converting speech to text...": "Konuşma yazıya çevriliyor...",
    "Attach a file or image (or drag or paste it here)": "Dosya veya görsel ekle (ya da buraya sürükle / yapıştır)",
    "Voice input": "Sesli giriş", "Remove": "Kaldır",
    "Send (Enter)": "Gönder (Enter)", "Stop generating": "Yanıtı durdur",
    "Describe the attached image(s).": "Ekteki görsel(ler)i açıkla.",
    "You can attach up to {count} images per message.": "Bir mesaja en fazla {count} görsel ekleyebilirsiniz.",
    "screenshot": "ekran-goruntusu",

    # ----- Messages -----
    "Copy reply": "Cevabı kopyala", "Read aloud": "Sesli oku", "Regenerate reply": "Cevabı yeniden oluştur",
    "Copy message": "Mesajı kopyala", "Edit and resend": "Düzenle ve yeniden gönder",
    "Retry (Ctrl+Shift+R)": "Yeniden dene (Ctrl+Shift+R)", "Scroll to bottom": "En alta git",
    "Live preview": "Canlı önizleme", "Copy": "Kopyala", "Copied": "Kopyalandı",
    "Save": "Kaydet", "Saved": "Kaydedildi", "Save the code to a file": "Kodu dosyaya kaydet",
    "Save code": "Kodu kaydet", "Save failed": "Kaydedilemedi", "All files": "Tüm dosyalar",
    "Image": "Görsel", "Images": "Görseller", "You": "Siz",
    "*Response interrupted.*": "*Yanıt yarıda kaldı.*", "*Response stopped.*": "*Yanıt durduruldu.*",
    "(The response was empty.)": "(Yanıt boş geldi.)",
    "{count} tokens": "{count} token",
    "Last reply copied": "Son cevap kopyalandı",
    "Code example shown on screen.": "Kod örneği ekranda gösteriliyor.",
    "link": "bağlantı", "The rest is shown on screen.": "Devamı ekranda.",

    # ----- Header, sidebar, menus -----
    "Change model": "Modeli değiştir", "Show sidebar (Ctrl+B)": "Kenar çubuğunu göster (Ctrl+B)",
    "Hide sidebar (Ctrl+B)": "Kenar çubuğunu gizle (Ctrl+B)",
    "Text-to-Speech: Off": "Sesli okuma: Kapalı", "Text-to-Speech: On": "Sesli okuma: Açık",
    "Launch an app": "Uygulama aç", "Help": "Yardım", "Settings": "Ayarlar",
    "Minimize": "Simge durumuna küçült", "Maximize": "Ekranı kapla", "Restore": "Önceki boyut", "Close": "Kapat",
    "New chat": "Yeni sohbet", "Delete chat": "Sohbeti sil", "Search chats (Ctrl+F)": "Sohbetlerde ara (Ctrl+F)",
    "No chats yet": "Henüz sohbet yok", "No matching chats": "Eşleşen sohbet yok",
    "Pin": "Sabitle", "Unpin": "Sabitlemeyi kaldır", "Rename": "Yeniden adlandır",
    "Export as Markdown": "Markdown olarak dışa aktar", "Delete": "Sil",
    "{app} {version} for Windows": "Windows için {app} {version}",
    "{app} {version}  •  Powered by {provider}": "{app} {version}  •  {provider} ile çalışır",
    "a local model": "yerel model", "Online": "Çevrimiçi", "No API key": "API anahtarı yok",
    "Listening": "Dinleniyor",
    "Open file or program…": "Dosya veya program aç…", "Open file or program": "Dosya veya program aç",
    "Programs": "Programlar", "Attach files": "Dosya ekle",
    "Text, code and image files": "Metin, kod ve görsel dosyaları",
    "Rename chat": "Sohbeti yeniden adlandır", "Chat name:": "Sohbet adı:",
    "Export chat": "Sohbeti dışa aktar", "Export chats": "Sohbetleri dışa aktar",
    "Import chats": "Sohbetleri içe aktar", "Export failed": "Dışa aktarılamadı", "Import failed": "İçe aktarılamadı",
    "Could not read this file:\n{error}": "Bu dosya okunamadı:\n{error}",
    "This file doesn't contain YamanAI chats.": "Bu dosyada YamanAI sohbeti yok.",
    "({count} skipped: already present or empty)": "({count} atlandı: zaten var veya boş)",
    "{count} chat(s) imported": "{count} sohbet içe aktarıldı",

    # ----- Settings -----
    "Language": "Dil", "Interface": "Arayüz", "Replies": "Cevaplar",
    "A new interface language is applied after YamanAI restarts.":
        "Yeni arayüz dili YamanAI yeniden başlatıldığında uygulanır.",
    "Theme": "Tema", "Text size": "Yazı boyutu", "AI model": "Yapay zekâ modeli", "Creativity": "Yaratıcılık",
    "Model ID, e.g. gpt-4.1": "Model kimliği, ör. gpt-4.1",
    "Custom model ID (used with \"Custom OpenAI model\"). Pick a model that can see images if you attach pictures.":
        "Özel model kimliği (\"Özel OpenAI modeli\" seçiliyken kullanılır). Görsel ekleyecekseniz görsel "
        "görebilen bir model seçin.",
    "Precise gives focused, repeatable answers (good for code). Creative gives more varied ideas.":
        "Kesin; odaklı ve tutarlı cevaplar verir (kod için iyi). Yaratıcı; daha çeşitli fikirler üretir.",
    "Local model server": "Yerel model sunucusu", "Server URL": "Sunucu adresi", "Model name": "Model adı",
    "Used with \"Local model\". Any OpenAI-compatible server works, e.g. Ollama (port 11434) or LM Studio (port 1234). No API key needed.":
        "\"Yerel model\" seçiliyken kullanılır. OpenAI uyumlu her sunucu çalışır; ör. Ollama (port 11434) "
        "veya LM Studio (port 1234). API anahtarı gerekmez.",
    "OpenAI API key": "OpenAI API anahtarı", "Show": "Göster", "Hide": "Gizle", "Connect": "Bağlan",
    "System prompt (optional)": "Sistem istemi (isteğe bağlı)",
    "For example: \"You are a Python expert.\"": "Örneğin: \"Sen bir Python uzmanısın.\"",
    "Voice": "Ses", "Read replies aloud (Text-to-Speech)": "Cevapları sesli oku (metin okuma)",
    "Voice input uses Google speech recognition and needs an internet connection.":
        "Sesli giriş Google konuşma tanımayı kullanır ve internet bağlantısı gerektirir.",
    "Your chats": "Sohbetleriniz", "Name new chats automatically": "Yeni sohbetleri otomatik adlandır",
    "Danger zone": "Tehlikeli bölge", "Delete all chats": "Tüm sohbetleri sil",
    "Are you sure? Click again": "Emin misiniz? Tekrar tıklayın",
    "Cancel": "İptal", "Click an example to put it in the input box.": "Bir örneğe tıklayınca yazı kutusuna eklenir.",
    "A key is saved.": "Kayıtlı bir anahtar var.", "No key saved yet.": "Henüz anahtar kaydedilmedi.",
    "Please enter your API Key first!": "Lütfen önce API anahtarınızı girin!",
    "Please enter your API Key first! Open Settings to add it.":
        "Lütfen önce API anahtarınızı girin! Eklemek için Ayarlar'ı açın.",
    "Enter a custom model ID in Settings first.": "Önce Ayarlar'dan bir özel model kimliği girin.",
    "(OpenAI keys usually start with \"sk-\")": "(OpenAI anahtarları genellikle \"sk-\" ile başlar)",
    "Verifying...": "Doğrulanıyor...", "Connected": "Bağlandı", "Invalid API Key": "Geçersiz API anahtarı",
    "No connection": "Bağlantı yok", "Could not verify: {error}": "Doğrulanamadı: {error}",
    "Connected. Your API Key is saved in Windows Credential Manager and working.":
        "Bağlandı. API anahtarınız Windows Kimlik Bilgileri Yöneticisi'nde kayıtlı ve çalışıyor.",
    "Connected. Your API Key is saved in the app settings and working.":
        "Bağlandı. API anahtarınız uygulama ayarlarında kayıtlı ve çalışıyor.",
    "Invalid API Key. Enter a valid key and connect again.":
        "Geçersiz API anahtarı. Geçerli bir anahtar girip yeniden bağlanın.",
    "Key saved but could not be verified ({error}).": "Anahtar kaydedildi ama doğrulanamadı ({error}).",

    # ----- AI errors -----
    "The openai library is not installed. Run: pip install openai":
        "openai kütüphanesi yüklü değil. Şunu çalıştırın: pip install openai",
    "Invalid API Key. Check your key in Settings and connect again.":
        "Geçersiz API anahtarı. Ayarlar'dan anahtarınızı kontrol edip yeniden bağlanın.",
    "Rate limit or quota exceeded. Check your account balance or wait a moment.":
        "İstek sınırı veya kota aşıldı. Hesap bakiyenizi kontrol edin ya da biraz bekleyin.",
    "The request timed out. Please try again.": "İstek zaman aşımına uğradı. Lütfen tekrar deneyin.",
    "Could not reach the local model server at {url}. Make sure it is running (for example Ollama or LM Studio).":
        "{url} adresindeki yerel model sunucusuna ulaşılamadı. Çalıştığından emin olun (ör. Ollama veya LM Studio).",
    "Connection error. Check your internet connection and try again.":
        "Bağlantı hatası. İnternet bağlantınızı kontrol edip tekrar deneyin.",
    "The model \"{model}\" was not found on the local server. Download it first (e.g. ollama pull {model}) or change it in Settings.":
        "\"{model}\" modeli yerel sunucuda bulunamadı. Önce indirin (ör. ollama pull {model}) ya da Ayarlar'dan değiştirin.",
    "The model \"{model}\" is not available for your account.": "\"{model}\" modeli hesabınızda kullanılamıyor.",
    "API error ({code}): {message}": "API hatası ({code}): {message}",
    "Unexpected error: {error}": "Beklenmeyen hata: {error}",

    # ----- Attachments -----
    "\"{name}\" is a folder; only files can be attached.": "\"{name}\" bir klasör; yalnızca dosya eklenebilir.",
    "\"{name}\" is too large to attach ({size} KB, limit {limit} KB).":
        "\"{name}\" eklemek için çok büyük ({size} KB, sınır {limit} KB).",
    "Could not read \"{name}\": {error}": "\"{name}\" okunamadı: {error}",
    "\"{name}\" is not a text file, so it can't be attached.": "\"{name}\" bir metin dosyası değil, eklenemiyor.",
    "\"{name}\" could not be opened as an image.": "\"{name}\" görsel olarak açılamadı.",

    # ----- Voice -----
    "pyttsx3 is not installed. Run: pip install pyttsx3": "pyttsx3 yüklü değil. Şunu çalıştırın: pip install pyttsx3",
    "speechrecognition is not installed. Run: pip install speechrecognition pyaudio":
        "speechrecognition yüklü değil. Şunu çalıştırın: pip install speechrecognition pyaudio",
    "Could not start the text-to-speech engine: {error}": "Metin okuma motoru başlatılamadı: {error}",
    "Text-to-speech error: {error}": "Metin okuma hatası: {error}",
    "No Turkish voice was found, so another voice is used. You can add one in Windows Settings > Time & language > Speech.":
        "Türkçe ses bulunamadı, başka bir ses kullanılıyor. Windows Ayarları > Saat ve dil > Konuşma bölümünden "
        "Türkçe ses ekleyebilirsiniz.",
    "No English voice was found; the system default voice will be used.":
        "İngilizce ses bulunamadı; sistemin varsayılan sesi kullanılacak.",
    "Sorry, I couldn't understand that. Please try again.": "Üzgünüm, anlayamadım. Lütfen tekrar deneyin.",
    "No speech detected. Start speaking right after clicking the microphone.":
        "Konuşma algılanmadı. Mikrofona tıkladıktan hemen sonra konuşmaya başlayın.",
    "Sorry, I couldn't understand that. Try speaking more clearly and closer to the mic.":
        "Üzgünüm, anlayamadım. Daha net ve mikrofona daha yakın konuşmayı deneyin.",
    "Could not reach the Google speech service. Check your internet connection.":
        "Google konuşma hizmetine ulaşılamadı. İnternet bağlantınızı kontrol edin.",
    "PyAudio was not found. Run: pip install pyaudio": "PyAudio bulunamadı. Şunu çalıştırın: pip install pyaudio",
    "No microphone found or it is unavailable. Check the connection and the microphone permission in Windows privacy settings.":
        "Mikrofon bulunamadı veya kullanılamıyor. Bağlantıyı ve Windows gizlilik ayarlarındaki mikrofon iznini kontrol edin.",
    "Speech recognition error: {error}": "Konuşma tanıma hatası: {error}",
}


def tr(text: str) -> str:
    """Returns the text in the interface language (English is the source language)."""
    if UI_LANG == "tr":
        return TR.get(text, text)
    return text


def caps(text: str) -> str:
    """Upper case that respects Turkish dotted/dotless i (i -> İ, ı -> I)."""
    if UI_LANG == "tr":
        text = text.replace("i", "İ").replace("ı", "I")
    return text.upper()


def detect_ui_language(settings: QSettings) -> str:
    """Saved choice, otherwise Turkish on a Turkish Windows and English elsewhere."""
    saved = settings.value("ui_language", "", type=str)
    if saved in UI_LANGUAGES:
        return saved
    return "tr" if QLocale.system().name().lower().startswith("tr") else "en"


KEYRING_SERVICE = "YamanAI"
KEYRING_USER = "openai_api_key"


class SecretStore:
    """
    Stores the API key in the OS credential vault when keyring is available,
    otherwise in QSettings (the old behavior). A key found in QSettings is moved
    into the vault automatically.
    """

    def __init__(self, settings: QSettings):
        self.settings = settings

    @property
    def secure(self) -> bool:
        return KEYRING_AVAILABLE

    def load(self) -> str:
        key = ""
        if KEYRING_AVAILABLE:
            try:
                key = keyring.get_password(KEYRING_SERVICE, KEYRING_USER) or ""
            except Exception:
                key = ""
        plain = self.settings.value("api_key", "", type=str)
        if not plain:
            plain = QSettings(*LEGACY_SETTINGS).value("api_key", "", type=str)
        if not key and plain:
            key = plain
            self.save(key)          # Migrates to the vault (or into the new settings)
        elif key and plain:
            self.settings.remove("api_key")
        return key

    def save(self, key: str):
        if KEYRING_AVAILABLE:
            try:
                keyring.set_password(KEYRING_SERVICE, KEYRING_USER, key)
                self.settings.remove("api_key")
                return
            except Exception:
                pass   # No usable vault: fall back to settings
        self.settings.setValue("api_key", key)

    def delete(self):
        self.settings.remove("api_key")
        if KEYRING_AVAILABLE:
            try:
                keyring.delete_password(KEYRING_SERVICE, KEYRING_USER)
            except Exception:
                pass


UI_FONT_CSS = '"Segoe UI Variable Text", "Segoe UI", Arial, sans-serif'
MONO_FONT_CSS = "'Cascadia Code', 'Fira Code', Consolas, 'Courier New', monospace"


def hex_to_rgba(hex_color: str, alpha: int) -> str:
    """Converts '#RRGGBB' to a QSS 'rgba(r, g, b, a)' string (a: 0-255)."""
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r}, {g}, {b}, {alpha})"


def to_qcolor(value: str) -> QColor:
    """Accepts '#RRGGBB' or 'rgba(r, g, b, a)' palette values."""
    match = re.match(r"rgba\((\d+),\s*(\d+),\s*(\d+),\s*(\d+)\)", value or "")
    if match:
        return QColor(*(int(part) for part in match.groups()))
    return QColor(value)


# =====================================================================
#  ICONS
# =====================================================================
# FontAwesome equivalents, used automatically when a Phosphor icon is unavailable
ICON_FALLBACKS = {
    "ph.list": "fa5s.bars", "ph.plus": "fa5s.plus", "ph.x": "fa5s.times",
    "ph.robot": "fa5s.robot", "ph.user": "fa5s.user", "ph.monitor": "fa5s.desktop",
    "ph.chat-centered": "fa5s.comment-alt", "ph.caret-right": "fa5s.chevron-right",
    "ph.question": "fa5s.question-circle", "ph.sun": "fa5s.sun", "ph.moon": "fa5s.moon",
    "ph.download-simple": "fa5s.download", "ph.text-aa": "fa5s.font",
    "ph.paper-plane-right": "fa5s.paper-plane", "ph.stop-circle": "fa5s.stop-circle",
    "ph.sparkle": "fa5s.magic", "ph.trash": "fa5s.trash", "ph.gear-six": "fa5s.cog",
    "ph.play": "fa5s.play", "ph.arrow-square-out": "fa5s.external-link-alt",
    "ph.copy": "fa5s.copy", "ph.check": "fa5s.check", "ph.microphone": "fa5s.microphone",
    "ph.speaker-high": "fa5s.volume-up", "ph.speaker-slash": "fa5s.volume-mute",
    "ph.app-window": "fa5s.window-maximize", "ph.check-circle": "fa5s.check-circle",
    "ph.warning-circle": "fa5s.exclamation-circle", "ph.magnifying-glass": "fa5s.search",
    "ph.info": "fa5s.info-circle", "ph.folder-open": "fa5s.folder-open",
    "ph.pencil-simple": "fa5s.pen", "ph.calculator": "fa5s.calculator",
    "ph.notepad": "fa5s.sticky-note", "ph.globe": "fa5s.globe", "ph.chart-line": "fa5s.chart-line",
    "ph.terminal-window": "fa5s.terminal", "ph.chat-circle-dots": "fa5s.comment-dots",
    "ph.chat-circle": "fa5s.comment", "ph.music-notes": "fa5s.music",
    "ph.game-controller": "fa5s.gamepad", "ph.arrows-clockwise": "fa5s.redo",
    "ph.funnel-simple": "fa5s.filter", "ph.youtube-logo": "fa5b.youtube", "ph.cube": "fa5s.cube",
    "ph.arrow-down": "fa5s.arrow-down", "ph.paperclip": "fa5s.paperclip", "ph.file-text": "fa5s.file-alt",
    "ph.sliders": "fa5s.sliders-h", "ph.paint-brush": "fa5s.paint-brush", "ph.scissors": "fa5s.cut",
    "ph.upload-simple": "fa5s.upload", "ph.folder": "fa5s.folder", "ph.desktop": "fa5s.desktop",
    "ph.push-pin": "fa5s.thumbtack", "ph.image": "fa5s.image", "ph.floppy-disk": "fa5s.save",
    "ph.lock": "fa5s.lock",
}


def resolve_color(key_or_hex: str) -> str:
    return P.get(key_or_hex, key_or_hex)


def icon(names, color=None, active=None, disabled=None) -> QIcon:
    """qtawesome icon with Phosphor -> FontAwesome fallbacks; empty icon if unavailable."""
    if not QTA_AVAILABLE:
        return QIcon()
    if isinstance(names, str):
        names = (names,)
    names = list(names) + [ICON_FALLBACKS[n] for n in names if n in ICON_FALLBACKS]
    color = resolve_color(color or "muted")
    for name in names:
        try:
            return qta.icon(
                name,
                color=color,
                color_active=resolve_color(active) if active else color,
                color_disabled=resolve_color(disabled or "dim"),
            )
        except Exception:
            continue
    return QIcon()


class IconRegistry:
    """
    Remembers which widget uses which icon and palette color, so every icon
    can be redrawn in the new colors when the theme changes.
    """

    _entries = []

    @classmethod
    def bind(cls, widget, names, color="muted", kind="icon", size=16, active=None, disabled=None):
        entry = (weakref.ref(widget), names, color, kind, size, active, disabled)
        cls._apply(entry)
        cls._entries.append(entry)
        if len(cls._entries) > 600:
            cls._prune()
        return widget

    @classmethod
    def _apply(cls, entry) -> bool:
        ref, names, color, kind, size, active, disabled = entry
        widget = ref()
        if widget is None:
            return False
        try:
            image = icon(names, color, active, disabled)
            if kind == "pixmap":
                widget.setPixmap(image.pixmap(QSize(size, size)))
            else:
                widget.setIcon(image)
            return True
        except RuntimeError:  # The C++ widget was already deleted
            return False

    @classmethod
    def _prune(cls):
        cls._entries = [e for e in cls._entries if e[0]() is not None]

    @classmethod
    def refresh(cls):
        cls._entries = [e for e in cls._entries if cls._apply(e)]


# =====================================================================
#  STYLESHEET (rebuilt whenever the theme or font size changes)
# =====================================================================
def build_stylesheet(message_pt: float) -> str:
    return f"""
/* ---------- General ---------- */
QWidget {{
    color: {P['text']};
    font-family: {UI_FONT_CSS};
    font-size: 10pt;
}}
QLabel {{
    background: transparent;
}}
QWidget#windowFrame {{
    background-color: {P['sidebar']};
}}
QFrame#mainPanel {{
    background-color: {P['bg']};
}}
QSplitter::handle {{
    background-color: {P['border']};
}}
QToolTip {{
    background-color: #111111;
    color: #FFFFFF;
    border: 1px solid rgba(255, 255, 255, 26);
    border-radius: 6px;
    padding: 4px 8px;
    font-size: 8.5pt;
}}

/* ---------- Sidebar ---------- */
QFrame#sidebar {{
    background-color: {P['sidebar']};
}}
QLabel#brandLabel {{
    color: {P['text']};
    font-size: 10.5pt;
    font-weight: 600;
}}
QPushButton#newChatButton {{
    background: transparent;
    border: 1px solid {P['border_strong']};
    border-radius: 8px;
    padding: 9px 12px;
    text-align: left;
    color: {P['text']};
}}
QPushButton#newChatButton:hover {{
    background-color: {P['active']};
    border: 1px solid {P['dim']};
}}
QPushButton#launchButton {{
    background-color: rgba(30, 58, 138, 26);
    border: 1px solid rgba(30, 58, 138, 77);
    border-radius: 8px;
    padding: 9px 12px;
    text-align: left;
    color: {P['accent_text']};
}}
QPushButton#launchButton:hover {{
    background-color: rgba(30, 58, 138, 51);
    border: 1px solid rgba(59, 130, 246, 128);
}}
QPushButton#launchButton::menu-indicator {{
    image: none;
    width: 0px;
}}
QPushButton#navRow {{
    background: transparent;
    border: none;
    border-radius: 8px;
    padding: 8px 10px;
    text-align: left;
    color: {P['muted']};
}}
QPushButton#navRow:hover {{
    background-color: {P['hover']};
    color: {P['text']};
}}
QFrame#sidebarFooter {{
    border-top: 1px solid {P['border']};
}}
QLabel#sidebarCaption {{
    color: {P['dim']};
    font-size: 8pt;
}}
QListWidget#threadList {{
    background: transparent;
    border: none;
    outline: 0;
}}
QListWidget#threadList::item {{
    border-radius: 8px;
    margin: 0px;
}}
QListWidget#threadList::item:hover {{
    background-color: {P['hover']};
}}
QListWidget#threadList::item:selected {{
    background-color: {P['active']};
}}
QLabel#groupLabel {{
    color: {P['dim']};
    font-size: 7.5pt;
    font-weight: 600;
    padding-left: 8px;
}}
QLabel#threadTitle {{
    color: {P['muted']};
}}
QLabel#threadTitle[active="true"] {{
    color: {P['text']};
}}
QLineEdit#searchInput {{
    background-color: {P['field']};
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 6px 8px;
    font-size: 9pt;
}}
QLineEdit#searchInput:focus {{
    border: 1px solid rgba(59, 130, 246, 128);
}}
QLabel#emptyThreads {{
    color: {P['dim']};
    font-size: 8.5pt;
}}

/* ---------- Icon buttons ---------- */
QToolButton#iconButton {{
    background: transparent;
    border: none;
    border-radius: 8px;
    padding: 7px;
}}
QToolButton#iconButton:hover {{
    background-color: {P['active']};
}}
QToolButton#iconButton:checked {{
    background-color: rgba(37, 99, 235, 40);
}}
QToolButton#trashButton {{
    background: transparent;
    border: none;
    border-radius: 5px;
    padding: 4px;
}}
QToolButton#trashButton:hover {{
    background-color: rgba(248, 113, 113, 30);
}}
QToolButton::menu-indicator {{
    image: none;
    width: 0px;
}}

/* ---------- Header ---------- */
QFrame#header {{
    background-color: {P['bg']};
}}
QFrame#statusPill {{
    background-color: {P['field']};
    border: 1px solid {P['line']};
    border-radius: 12px;
}}
QFrame#statusPill:hover {{
    border: 1px solid {P['dim']};
}}
QLabel#pillModel {{
    color: {P['muted']};
    font-size: 8.5pt;
    font-weight: 600;
}}
QLabel#pillState {{
    font-size: 8.5pt;
    font-weight: 600;
}}

/* ---------- Messages ---------- */
QScrollArea#stream {{
    background: transparent;
    border: none;
}}
QWidget#qt_scrollarea_viewport, QWidget#streamContent {{
    background: transparent;
}}
QFrame#userRow {{
    background-color: {P['user_row']};
}}
QFrame#aiRow, QFrame#activityRow {{
    background: transparent;
}}
QLabel#messageText {{
    color: {P['body']};
    font-size: {message_pt}pt;
}}
QLabel#activityText {{
    color: {P['muted']};
    font-size: {max(9.0, message_pt - 1)}pt;
}}
QLabel#activityText[status="error"] {{
    color: {P['red']};
}}
QFrame#codeCard {{
    background-color: {P['code_bg']};
    border: 1px solid rgba(255, 255, 255, 26);
    border-radius: 12px;
}}
QFrame#codeHeader {{
    background-color: {P['code_header']};
    border: none;
    border-bottom: 1px solid rgba(255, 255, 255, 13);
    border-top-left-radius: 12px;
    border-top-right-radius: 12px;
}}
QLabel#codeLang {{
    color: {P['code_muted']};
    font-size: 7.5pt;
    font-weight: 700;
}}
QPushButton#codeAction {{
    background: transparent;
    border: none;
    color: {P['code_muted']};
    font-size: 7.5pt;
    font-weight: 700;
    padding: 2px 4px;
}}
QPushButton#codeAction:hover {{
    color: #E5E7EB;
}}
QPushButton#previewAction {{
    background: transparent;
    border: none;
    color: #60A5FA;
    font-size: 7.5pt;
    font-weight: 700;
    padding: 2px 4px;
}}
QPushButton#previewAction:hover {{
    color: #93C5FD;
}}
QScrollArea#codeScroll, QWidget#codeViewport {{
    background-color: {P['code_bg']};
    border: none;
    border-bottom-left-radius: 12px;
    border-bottom-right-radius: 12px;
}}
QLabel#codeBody {{
    color: {P['code_text']};
    font-family: {MONO_FONT_CSS};
    font-size: 9.75pt;
    background-color: {P['code_bg']};
}}
QToolButton#messageAction {{
    background: transparent;
    border: none;
    border-radius: 6px;
    padding: 4px;
}}
QToolButton#messageAction:hover {{
    background-color: {P['hover']};
}}
QLabel#messageMeta {{
    color: {P['faint']};
    font-size: 8pt;
    padding-left: 6px;
}}
QToolButton#scrollDownButton {{
    background-color: {P['input']};
    border: 1px solid {P['border_strong']};
    border-radius: 18px;
}}
QToolButton#scrollDownButton:hover {{
    border: 1px solid rgba(59, 130, 246, 128);
}}

/* ---------- Welcome screen ---------- */
QLabel#welcomeSubtitle {{
    color: {P['faint']};
    font-size: 10pt;
}}
QPushButton#promptChip {{
    background-color: {P['chip']};
    border: 1px solid {P['chip_border']};
    border-radius: 12px;
    padding: 15px 18px;
    text-align: left;
    color: {P['body']};
    font-weight: 600;
}}
QPushButton#promptChip:hover {{
    background-color: {P['chip_hover']};
    border: 1px solid rgba(59, 130, 246, 128);
    color: {P['text_strong']};
}}

/* ---------- Composer (input box) ---------- */
QFrame#composer {{
    background-color: {P['input']};
    border: 2px solid {P['composer_border']};
    border-radius: 24px;
}}
QFrame#composer[focused="true"] {{
    border: 2px solid rgba(59, 130, 246, 153);
}}
QTextEdit#promptInput {{
    background: transparent;
    border: none;
    color: {P['text']};
    font-size: 11pt;
    selection-background-color: {P['accent']};
    selection-color: #FFFFFF;
}}
QToolButton#sendButton {{
    background-color: {P['field']};
    border: 1px solid transparent;
    border-radius: 12px;
}}
QToolButton#sendButton[state="ready"] {{
    background-color: {P['accent']};
}}
QToolButton#sendButton[state="ready"]:hover {{
    background-color: {P['accent_hover']};
}}
QToolButton#sendButton[state="stop"] {{
    background-color: rgba(239, 68, 68, 51);
    border: 1px solid rgba(239, 68, 68, 77);
}}
QToolButton#sendButton[state="stop"]:hover {{
    background-color: rgba(239, 68, 68, 77);
}}
QToolButton#micButton {{
    background: transparent;
    border: none;
    border-radius: 12px;
}}
QToolButton#micButton:hover, QToolButton#attachButton:hover {{
    background-color: {P['hover']};
}}
QToolButton#attachButton {{
    background: transparent;
    border: none;
    border-radius: 12px;
}}
QToolButton#micButton[state="preparing"] {{
    background-color: rgba(245, 158, 11, 51);
}}
QToolButton#micButton[state="listening"] {{
    background-color: #EF4444;
}}
QToolButton#micButton[state="processing"] {{
    background-color: {P['amber']};
}}
QFrame#imageChip {{
    background-color: {P['field']};
    border: 1px solid {P['line']};
    border-radius: 10px;
}}
QLabel#imageChipName {{
    color: {P['muted']};
    font-size: 8.5pt;
}}
QLabel#messageImage {{
    border: 1px solid {P['line']};
    border-radius: 8px;
}}
QLabel#footerNote {{
    color: {P['dim']};
    font-size: 7.5pt;
    font-weight: 700;
}}

/* ---------- Modals (Settings, Help) ---------- */
QFrame#modalCard {{
    background-color: {P['card']};
    border: 1px solid {P['border_strong']};
    border-radius: 16px;
}}
QFrame#modalHeader {{
    border: none;
    border-bottom: 1px solid {P['line']};
}}
QFrame#modalFooter {{
    border: none;
    border-top: 1px solid {P['line']};
}}
QLabel#modalTitle {{
    color: {P['text']};
    font-size: 13pt;
    font-weight: 700;
}}
QLabel#fieldLabel {{
    color: {P['faint']};
    font-size: 8pt;
    font-weight: 700;
}}
QLabel#dangerLabel {{
    color: rgba(239, 68, 68, 204);
    font-size: 8pt;
    font-weight: 700;
}}
QLabel#fieldHint {{
    color: {P['faint']};
    font-size: 8.5pt;
}}
QLabel#helpBody {{
    color: {P['body']};
}}
QScrollArea#modalScroll, QWidget#modalBody {{
    background: transparent;
    border: none;
}}
QPushButton#optionButton {{
    background-color: {P['field']};
    border: 1px solid {P['line']};
    border-radius: 12px;
    padding: 11px 14px;
    color: {P['muted']};
    font-weight: 500;
}}
QPushButton#optionButton:hover {{
    background-color: {P['active']};
}}
QPushButton#optionButton:checked {{
    background-color: rgba(37, 99, 235, 51);
    border: 1px solid rgba(59, 130, 246, 128);
    color: {P['accent_text']};
}}
QPushButton#dangerButton {{
    background-color: rgba(239, 68, 68, 26);
    border: 1px solid rgba(239, 68, 68, 77);
    border-radius: 12px;
    padding: 11px 14px;
    color: {P['red']};
    font-weight: 500;
}}
QPushButton#dangerButton:hover {{
    background-color: rgba(239, 68, 68, 51);
}}
QPushButton#dangerButton[confirm="true"] {{
    background-color: {P['red_strong']};
    border: 1px solid #EF4444;
    color: #FFFFFF;
    font-weight: 700;
}}
QPushButton#primaryButton {{
    background-color: {P['accent']};
    color: #FFFFFF;
    border: 1px solid transparent;
    border-radius: 12px;
    padding: 8px 22px;
    font-weight: 600;
}}
QPushButton#primaryButton:hover {{
    background-color: {P['accent_hover']};
}}
QPushButton#primaryButton:disabled {{
    background-color: {P['border_strong']};
    color: {P['muted']};
}}
QPushButton#textButton {{
    background: transparent;
    border: none;
    color: {P['muted']};
    padding: 8px 14px;
}}
QPushButton#textButton:hover {{
    color: {P['text']};
}}
QLineEdit, QPlainTextEdit#systemPromptInput {{
    background-color: {P['field']};
    border: 1px solid {P['line']};
    border-radius: 12px;
    padding: 8px 12px;
    color: {P['text']};
    selection-background-color: {P['accent']};
    selection-color: #FFFFFF;
}}
QLineEdit:focus, QPlainTextEdit#systemPromptInput:focus {{
    border: 1px solid rgba(59, 130, 246, 128);
}}

/* ---------- Menus ---------- */
QMenu {{
    background-color: {P['card']};
    border: 1px solid {P['border_strong']};
    border-radius: 10px;
    padding: 5px;
}}
QMenu::item {{
    padding: 7px 22px 7px 10px;
    border-radius: 6px;
    color: {P['text']};
}}
QMenu::item:selected {{
    background-color: {P['active']};
}}
QMenu::icon {{
    padding-left: 8px;
}}
QMenu::separator {{
    height: 1px;
    background: {P['line']};
    margin: 4px 6px;
}}

/* ---------- Scrollbars (thin, rounded, transparent track) ---------- */
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 2px 2px 2px 0px;
}}
QScrollBar::handle:vertical {{
    background: {P['line']};
    border-radius: 4px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: {P['dim']};
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 8px;
    margin: 0px 2px 2px 2px;
}}
QScrollBar::handle:horizontal {{
    background: rgba(255, 255, 255, 40);
    border-radius: 4px;
    min-width: 30px;
}}
QScrollBar::add-line, QScrollBar::sub-line,
QScrollBar::add-page, QScrollBar::sub-page {{
    background: none;
    width: 0px;
    height: 0px;
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
    MAX_COMMAND_WORDS = 9          # Longer messages are always sent to the AI
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

    # Turkish: question words anywhere ("discord nasıl açılır") and launch verbs, which
    # normally come last ("discord'u aç", "hesap makinesini açar mısın")
    TR_QUESTION = re.compile(r"\b(?:nasıl|neden|niye|niçin|nedir|ne zaman|nerede|hangi|kaç|kim|ne demek|ne işe)\b")
    TR_ACTION_TOKEN = re.compile(r"(?:aç|açar|açsana|açın|açınız|açıver|açabilir\w*|başlat\w*|çalıştır\w*)")
    TR_TRAILING_WORDS = {"mısın", "misin", "musun", "müsün", "mısınız", "misiniz", "lütfen", "hemen",
                         "şimdi", "benim", "için", "bana", "artık"}

    # Polite openers stripped before checking that the message *starts* with a launch verb
    # ("hey, can you please open obs" -> "open obs").
    LEADING_FILLER = re.compile(
        r"^(?:(?:hey|hi|ok|okay|yo|please|pls|kindly|yamanai|assistant|just|now|"
        r"can you|could you|would you|will you|can u|"
        r"i want to|i wanna|i need to|i'd like to|i would like to|let's|lets|go ahead and)[\s,.!]+)+"
    )

    # Path and exe patterns (applied to the original text)
    QUOTED_PATTERN = re.compile(r'["“”]([^"“”]+)["“”]')
    PATH_WITH_EXT_PATTERN = re.compile(
        r"([a-zA-Z]:[\\/][^\"<>|?*\n]*?\.(?:exe|bat|cmd|msc|lnk|url|msi))(?=$|[\s'’.,!?])",
        re.IGNORECASE,
    )
    PATH_PLAIN_PATTERN = re.compile(r"([a-zA-Z]:[\\/][^\s\"<>|?*'’]*)")
    EXE_PATTERN = re.compile(r"(?<![\\/\w])([\w\-.+]+\.(?:exe|bat|cmd|msc))(?!\w)", re.IGNORECASE)
    # Websites: "open github.com", "go to https://example.org/page"
    URL_PATTERN = re.compile(
        r"(?:https?://)?(?:www\.)?[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9-]+)*"
        r"\.(?:com|net|org|io|dev|app|ai|co|tr|edu|gov|me|tv|gg|uk|de|info|xyz|so|sh)(?:/\S*)?",
        re.IGNORECASE,
    )

    # Words removed when extracting an app name ("please open the obs app for me" -> "obs")
    FILLER_WORDS = {
        "please", "pls", "can", "could", "would", "will", "you", "u", "me", "up",
        "the", "a", "an", "my", "this", "that", "it", "app", "application", "program",
        "file", "called", "named", "now", "quickly", "just", "go", "ahead", "kindly",
        "hey", "assistant", "i", "want", "to", "need", "like", "let's", "lets",
    }
    TR_FILLER_WORDS = {"lütfen", "şu", "şunu", "bu", "bunu", "uygulama", "uygulamasını", "uygulamayı",
                       "programı", "program", "programını", "benim", "için", "bana", "bir", "hemen",
                       "şimdi", "hey", "yamanai", "asistan"}
    # Words that end the app name ("open vlc and play music" -> "vlc")
    STOP_WORDS = {"and", "then", "with", "in", "on", "for", "from", "using", "via", "into", "so"}
    # Large or irrelevant folders skipped while scanning Program Files
    SKIP_DIRS = {"windowsapps", "windows defender", "common files", "microsoft.net",
                 "windows nt", "internet explorer", "reference assemblies", "windowspowershell"}

    def __init__(self):
        # Order matters: specific apps first, generic browser last
        # (so "open youtube in chrome" opens YouTube).
        self.commands = [
            {"name": "Lock computer",
             "patterns": [r"^(?:please )?lock (?:the |my |this )?(?:pc|computer|screen|windows)[.!]?$",
                          r"^(?:lütfen )?(?:bilgisayarı|ekranı|pc'yi) kilitle\w*[.!]?$"],
             "action": self._lock_pc, "standalone": True},
            {"name": "Task Manager",
             "patterns": [r"\btask ?manager\b", r"\btaskmgr\b", r"\bgörev yöneticisi"],
             "action": self._open_task_manager},
            {"name": "Command Prompt",
             "patterns": [r"\bcmd\b", r"\bcommand prompt\b", r"\bcommand line\b", r"\bterminal\b",
                          r"\bkomut (?:istemi|satırı)"],
             "action": self._open_cmd},
            {"name": "Calculator",
             "patterns": [r"\bcalculator\b", r"\bcalc\b", r"\bhesap makinesi"],
             "action": self._open_calculator},
            {"name": "Notepad",
             "patterns": [r"\bnotepad(?![+\w])", r"\btext editor\b", r"\bnot ?defter"],
             "action": self._open_notepad},
            {"name": "Paint",
             "patterns": [r"\bms ?paint\b", r"\bpaint(?![.\w])"],
             "action": self._open_paint},
            {"name": "Snipping Tool",
             "patterns": [r"\bsnipping tool\b", r"\bscreenshot tool\b", r"\bekran alıntısı",
                          r"\bekran görüntüsü aracı"],
             "action": self._open_snipping_tool},
            {"name": "Recycle Bin",
             "patterns": [r"\brecycle bin\b", r"\bgeri dönüşüm kutusu"],
             "action": self._open_recycle_bin},
            {"name": "File Explorer",
             "patterns": [r"\bfile explorer\b", r"\bwindows explorer\b", r"\bexplorer\b",
                          r"\bthis pc\b", r"\bmy computer\b", r"\bdosya gezgini", r"\bbilgisayarım"],
             "action": self._open_explorer},
            {"name": "Downloads",
             "patterns": [r"\bdownloads?(?: folder)?[.!]?$", r"\bindirilenler"],
             "action": lambda: self._open_folder("Downloads", "DownloadLocation")},
            {"name": "Documents",
             "patterns": [r"\bdocuments(?: folder)?[.!]?$", r"\bmy documents\b", r"\bbelgeler"],
             "action": lambda: self._open_folder("Documents", "DocumentsLocation")},
            {"name": "Desktop folder",
             "patterns": [r"\bdesktop folder\b", r"^(?:open|show)(?: my| the)? desktop[.!]?$", r"\bmasaüstü"],
             "action": lambda: self._open_folder("Desktop", "DesktopLocation")},
            {"name": "Windows Settings",
             "patterns": [r"\b(?:windows|pc|system|computer) settings\b",
                          r"\b(?:windows|sistem|bilgisayar|pc) ayarlar"],
             "action": self._open_windows_settings},
            {"name": "Control Panel",
             "patterns": [r"\bcontrol panel\b", r"\bdenetim masası"],
             "action": self._open_control_panel},
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
             "patterns": [r"\b(?:google )?chrome\b", r"\b(?:web )?browser\b", r"\btarayıcı"],
             "action": self._open_chrome},
        ]

    # =================================================================
    #  TEXT ANALYSIS
    # =================================================================
    @staticmethod
    def normalize(text: str) -> str:
        """Lowercases text and unifies apostrophes/quotes."""
        text = text.replace("’", "'").replace("‘", "'").replace("İ", "i")
        return text.lower().replace("̇", "").strip()

    def _is_question(self, normalized: str) -> bool:
        return bool(self.QUESTION_START.match(normalized) or self.TR_QUESTION.search(normalized))

    def _has_launch_intent(self, normalized: str) -> bool:
        """
        True only when the message is a short request that *starts* with a launch verb.
        "can you open discord" -> True
        "write a python script that opens discord" / "start a flask server in python" -> False
        (Previously any message containing "open", "run" or "start" was hijacked.)
        """
        if self._is_question(normalized) or len(normalized.split()) > self.MAX_COMMAND_WORDS:
            return False
        body = self.LEADING_FILLER.sub("", normalized).lstrip(" ,")
        first = body.split()[0].strip(".,!?;:") if body.split() else ""
        if self.ACTION_TOKEN.fullmatch(first) or self.TR_ACTION_TOKEN.fullmatch(first):
            return True
        return self._tr_verb_index(body.split()) is not None   # "discord'u aç"

    def _tr_verb_index(self, tokens):
        """Turkish puts the verb last: index of a final launch verb, ignoring polite words."""
        cleaned = [token.strip(".,!?;:\"") for token in tokens]
        index = len(cleaned) - 1
        while index >= 0 and (not cleaned[index] or cleaned[index] in self.TR_TRAILING_WORDS):
            index -= 1
        if index >= 0 and self.TR_ACTION_TOKEN.fullmatch(cleaned[index]):
            return index
        return None

    def _looks_like_command(self, normalized: str, max_words: int) -> bool:
        """A message counts as a command if it starts with a launch verb, or is very short."""
        if self._is_question(normalized):
            return False
        if self._has_launch_intent(normalized):
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

        # Multi-line messages and messages with code are never commands
        # (previously "run this code: ..." could launch VS Code's code.exe)
        if "\n" in normalized or "`" in normalized:
            return None

        # 0) Website after a launch verb: "open github.com"
        if self._has_launch_intent(normalized):
            url = self._extract_url(normalized)
            if url:
                return {"kind": "url", "url": url, "label": url}

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

        # 3) Built-in command ("lock my computer" also works without a launch verb)
        known = self._find_known(normalized)
        if known and (self._looks_like_command(normalized, max_words=self.SHORT_COMMAND_WORDS)
                      or (known.get("standalone") and not self._is_question(normalized))):
            return {"kind": "known", "command": known, "label": known["name"]}

        # 4) Free app name after a launch verb. If nothing is found on disk the
        #    message is handed to the AI instead ("run a marathon" is not an app).
        if self._has_launch_intent(normalized):
            name = self._extract_app_name(normalized)
            if name:
                return {"kind": "search", "targets": [name], "label": name, "fallback_to_ai": True}

        return None

    def _extract_url(self, normalized: str):
        """Returns the first token that is a web address ("github.com", "https://x.org/a")."""
        for token in normalized.split():
            token = token.strip(".,!?;:\"'()").split("'")[0]   # "github.com'u" -> "github.com"
            if re.match(r"^[a-zA-Z]:[\\/]", token):
                continue
            if self.URL_PATTERN.fullmatch(token):
                return token if token.startswith(("http://", "https://")) else "https://" + token
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

        # Turkish word order: "obs'yi aç", "vlc programını başlat"
        tr_index = self._tr_verb_index(tokens)
        if tr_index is not None and tr_index > 0:
            words = [token.split("'")[0] for token in tokens[:tr_index]]
            name_words = [w for w in words if w and w not in self.FILLER_WORDS
                          and w not in self.TR_FILLER_WORDS and w not in self.STOP_WORDS]
            if not name_words or len(name_words) > self.MAX_APP_NAME_WORDS:
                return None
            return " ".join(name_words)

        action_index = next(
            (i for i, token in enumerate(tokens)
             if self.ACTION_TOKEN.fullmatch(token) or self.TR_ACTION_TOKEN.fullmatch(token)), None
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

        if kind == "url":
            if webbrowser.open(request["url"]):
                return True, tr("Opening {url} in your browser...").format(url=request["url"])
            return False, tr("Could not open your web browser.")

        if not self._is_windows():
            return False, tr("Launching files and applications is only supported on Windows.")

        if kind == "path":
            path = request["path"]
            if not os.path.exists(path):
                return False, tr("File or application not found.")
            self._launch_file(path)
            return True, tr("{name} launched.").format(name=request["label"])

        if kind == "search":
            for target in request["targets"]:
                found = self.find_application(target)
                if found:
                    self._launch_file(found)
                    return True, tr("{name} launched.").format(name=target)
            return False, tr("File or application not found.")

        return False, tr("Unknown command type.")

    def execute(self, command: dict):
        """Runs a built-in command."""
        try:
            return True, command["action"]()
        except FileNotFoundError:
            return False, tr("Could not open {name}. The application was not found or this command "
                             "only works on Windows.").format(name=tr(command["name"]))
        except Exception as exc:
            return False, tr("Could not open {name}: {error}").format(name=tr(command["name"]), error=exc)

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
                    return tr("Opening {name}...").format(name=tr(name))

            # Microsoft Store versions are usually opened through their protocol
            if protocol and self._protocol_registered(protocol):
                try:
                    os.startfile(protocol_uri or f"{protocol}:")
                    return tr("Opening {name}...").format(name=tr(name))
                except OSError:
                    pass

        if web_url:
            webbrowser.open(web_url)
            return tr("{name} app not found, opening the web version in your browser...").format(name=tr(name))

        raise FileNotFoundError(name)

    # =================================================================
    #  BUILT-IN COMMANDS
    # =================================================================
    def _open_calculator(self):
        self._ensure_windows()
        subprocess.Popen(["calc.exe"])
        return tr("Opening Calculator...")

    def _open_notepad(self):
        self._ensure_windows()
        subprocess.Popen(["notepad.exe"])
        return tr("Opening Notepad...")

    def _open_paint(self):
        self._ensure_windows()
        subprocess.Popen(["mspaint.exe"])
        return tr("Opening Paint...")

    def _open_snipping_tool(self):
        return self._launch(
            "Snipping Tool",
            exe_candidates=[(r"%WINDIR%\System32\SnippingTool.exe", [])],
            protocol="ms-screenclip", protocol_uri="ms-screenclip:",
        )

    def _open_explorer(self):
        self._ensure_windows()
        subprocess.Popen(["explorer.exe"])
        return tr("Opening File Explorer...")

    def _open_folder(self, name: str, location: str):
        self._ensure_windows()
        path = QStandardPaths.writableLocation(getattr(QStandardPaths.StandardLocation, location))
        if not path or not os.path.isdir(path):
            path = os.path.join(os.path.expanduser("~"), name)
        if not os.path.isdir(path):
            raise FileNotFoundError(path)
        os.startfile(path)
        return tr("Opening your {name} folder...").format(name=tr(name))

    def _open_windows_settings(self):
        self._ensure_windows()
        os.startfile("ms-settings:")
        return tr("Opening Windows Settings...")

    def _open_control_panel(self):
        self._ensure_windows()
        subprocess.Popen(["control.exe"])
        return tr("Opening Control Panel...")

    def _lock_pc(self):
        self._ensure_windows()
        import ctypes

        if not ctypes.windll.user32.LockWorkStation():
            raise OSError("LockWorkStation failed")
        return tr("Locking your computer...")

    def _open_recycle_bin(self):
        self._ensure_windows()
        subprocess.Popen(["explorer.exe", "shell:RecycleBinFolder"])
        return tr("Opening the Recycle Bin...")

    def _open_task_manager(self):
        self._ensure_windows()
        os.startfile("taskmgr.exe")  # Handles the UAC prompt correctly if needed
        return tr("Opening Task Manager...")

    def _open_cmd(self):
        self._ensure_windows()
        subprocess.Popen(
            ["cmd.exe"],
            creationflags=subprocess.CREATE_NEW_CONSOLE,
            cwd=os.path.expanduser("~"),
        )
        return tr("Opening Command Prompt...")

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
                return tr("Opening Chrome...")
        webbrowser.open("https://www.google.com")
        return tr("Chrome not found, opening your default browser...")

    @staticmethod
    def _open_youtube():
        webbrowser.open("https://www.youtube.com")
        return tr("Opening YouTube in your browser...")


# =====================================================================
#  BACKGROUND WORKERS (QThread)
# =====================================================================
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
            self.validated.emit(True, tr("Connected"), False)
        except openai.AuthenticationError:
            self.validated.emit(False, tr("Invalid API Key"), True)
        except openai.APIConnectionError:
            self.validated.emit(False, tr("No connection"), False)
        except Exception as exc:
            self.validated.emit(False, tr("Could not verify: {error}").format(error=exc), False)


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
            ok, message = False, tr("File or application not found.")
        except PermissionError:
            ok, message = False, tr("You don't have permission to run this file.")
        except Exception as exc:
            ok, message = False, tr("Could not launch: {error}").format(error=exc)
        self.launched.emit(ok, message)


def clean_for_speech(text: str, max_chars: int = 1500) -> str:
    """Strips Markdown symbols, code blocks and links so the text reads naturally aloud."""
    text = re.sub(r"```.*?```", " " + tr("Code example shown on screen.") + " ", text, flags=re.DOTALL)
    text = re.sub(r"https?://\S+", " " + tr("link") + " ", text)
    text = re.sub(r"[`*_#>|~]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_chars:
        text = text[:max_chars].rsplit(" ", 1)[0] + ". " + tr("The rest is shown on screen.")
    return text


TURKISH_HINT_RE = re.compile(
    r"[ğış]|\b(?:ve|bir|bu|için|ile|değil|nasıl|çok|ama|gibi|daha|evet|hayır|merhaba|şey)\b"
)   # No IGNORECASE: it would let "i" match the Turkish dotless "ı"


def guess_language(text: str) -> str:
    """Rough guess ('tr' or 'en') used to pick a voice when the reply language is automatic."""
    sample = text[:2000].replace("İ", "i").replace("I", "ı" if "ı" in text else "i").lower()
    return "tr" if len(TURKISH_HINT_RE.findall(sample)) >= 2 else "en"


class TTSWorker(QThread):
    """
    Text-to-speech thread (pyttsx3).

    A single long-lived thread is used: the pyttsx3 engine (SAPI5/COM on Windows)
    is bound to the thread that created it, and creating a new thread per
    sentence can make the second utterance hang. Texts are queued with their
    language and spoken in order with a matching voice (e.g. Microsoft Tolga for Turkish).
    """

    error_occurred = pyqtSignal(str, bool)   # (message, is_fatal)
    info = pyqtSignal(str)

    VOICE_MARKERS = {
        "tr": [("tr-tr", "tr_tr", "turkish", "türk", "tolga")],
        "en": [("en-us", "en_us", "english (united states)", "zira", "david", "mark"),
               ("english", "en-gb", "en_gb", "en-au", "en_au", "en-", "en_")],
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._queue = queue.Queue()
        self._stop_requested = False
        self._engine = None
        self._voice_lang = None
        self._warned = set()

    # ----- Called from the main thread -----
    def speak(self, text: str, lang: str = "en"):
        if text:
            self._queue.put((text, lang))

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
            self.error_occurred.emit(tr("Could not start the text-to-speech engine: {error}").format(error=exc), True)
            return

        self._engine = engine
        engine.setProperty("rate", 175)
        # Check for stop requests at each word (engine.stop must run on this thread)
        engine.connect("started-word", self._on_word)

        try:
            while True:
                item = self._queue.get()
                if item is None:
                    break
                text, lang = item
                self._stop_requested = False
                try:
                    self._use_voice(engine, lang)
                    engine.say(text)
                    engine.runAndWait()
                except Exception as exc:
                    self.error_occurred.emit(tr("Text-to-speech error: {error}").format(error=exc), False)
        finally:
            try:
                engine.stop()
            except Exception:
                pass
            if com_initialized:
                pythoncom.CoUninitialize()

    def _use_voice(self, engine, lang: str):
        if lang == self._voice_lang:
            return
        self._voice_lang = lang
        if self._select_voice(engine, lang):
            return
        if lang not in self._warned:
            self._warned.add(lang)
            if lang == "tr":
                self.info.emit(tr("No Turkish voice was found, so another voice is used. You can add one in "
                                  "Windows Settings > Time & language > Speech."))
            else:
                self.info.emit(tr("No English voice was found; the system default voice will be used."))
        if lang != "en":
            self._select_voice(engine, "en")

    def _on_word(self, name, location, length):
        # This callback runs on the engine's own thread, so stop() is safe here
        if self._stop_requested and self._engine is not None:
            try:
                self._engine.stop()
            except Exception:
                pass

    @classmethod
    def _select_voice(cls, engine, lang: str) -> bool:
        """Selects an installed voice for the language (Turkish: Tolga; English: Zira / David)."""
        try:
            voices = engine.getProperty("voices") or []
        except Exception:
            return False

        def describe(voice):
            name = (getattr(voice, "name", "") or "").lower()
            voice_id = (getattr(voice, "id", "") or "").lower()
            languages = " ".join(str(lang) for lang in (getattr(voice, "languages", None) or [])).lower()
            return f"{name} {voice_id} {languages}"

        for markers in cls.VOICE_MARKERS.get(lang, []):
            for voice in voices:
                if any(marker in describe(voice) for marker in markers):
                    engine.setProperty("voice", voice.id)
                    return True
        return False


class STTWorker(QThread):
    """Listens to the microphone and converts speech to text via Google Speech Recognition."""

    listening_started = pyqtSignal()
    processing_started = pyqtSignal()
    recognized = pyqtSignal(str)
    failed = pyqtSignal(str, bool)  # (message, is_real_error)

    LISTEN_TIMEOUT = 6        # Seconds to wait for the user to start speaking
    PHRASE_TIME_LIMIT = 12    # Maximum length of a single phrase (seconds)

    def __init__(self, language: str = "en-US", parent=None):
        super().__init__(parent)
        self.language = language   # "tr-TR" or "en-US"

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
            text = recognizer.recognize_google(audio, language=self.language)
            text = (text or "").strip()
            if text:
                self.recognized.emit(text)
            else:
                self.failed.emit(tr("Sorry, I couldn't understand that. Please try again."), False)

        except sr.WaitTimeoutError:
            self.failed.emit(tr("No speech detected. Start speaking right after clicking the microphone."), False)
        except sr.UnknownValueError:
            self.failed.emit(tr("Sorry, I couldn't understand that. Try speaking more clearly and closer "
                                "to the mic."), False)
        except sr.RequestError:
            self.failed.emit(tr("Could not reach the Google speech service. Check your internet connection."), True)
        except AttributeError:
            # speech_recognition raises AttributeError when PyAudio is missing
            self.failed.emit(tr("PyAudio was not found. Run: pip install pyaudio"), True)
        except OSError:
            self.failed.emit(tr("No microphone found or it is unavailable. Check the connection and the "
                                "microphone permission in Windows privacy settings."), True)
        except Exception as exc:
            self.failed.emit(tr("Speech recognition error: {error}").format(error=exc), True)


# =====================================================================
#  AI WORKER (streaming, cancellable)
# =====================================================================
class AIWorker(QThread):
    """
    Streams the reply from OpenAI or a local OpenAI-compatible server in the
    background. 'partial' carries the text so far; cancel() stops the stream.
    'response_ready' also carries token usage when the server reports it.
    """

    partial = pyqtSignal(str)
    response_ready = pyqtSignal(str, object)   # (answer, usage dict or None)
    error_occurred = pyqtSignal(str)

    EMIT_INTERVAL = 0.05  # Seconds between UI updates while streaming

    def __init__(self, api_key: str, messages: list, model: str,
                 base_url: str = None, provider: str = "openai", temperature: float = 0.7, parent=None):
        super().__init__(parent)
        self.api_key = api_key
        self.messages = list(messages)
        self.model = model
        self.base_url = base_url
        self.provider = provider
        self.temperature = temperature
        self._cancelled = False
        self._stream = None

    def cancel(self):
        """Stops the reply. Closing the stream also interrupts a connection that is
        waiting for data, so the thread ends quickly instead of hanging until timeout."""
        self._cancelled = True
        stream = self._stream
        if stream is not None:
            try:
                stream.close()
            except Exception:
                pass

    def _fail(self, message: str):
        if not self._cancelled:
            self.error_occurred.emit(message)

    def _open_stream(self, client):
        params = {"model": self.model, "messages": self.messages, "stream": True,
                  "temperature": self.temperature}
        if self.provider == "openai":
            params["stream_options"] = {"include_usage": True}
        try:
            return client.chat.completions.create(**params)
        except openai.BadRequestError as exc:
            # Some newer (reasoning) models only accept the default temperature
            if "temperature" not in str(exc):
                raise
            params.pop("temperature")
            return client.chat.completions.create(**params)

    def run(self):
        local = self.provider == "local"
        try:
            kwargs = {"api_key": self.api_key, "timeout": 180.0 if local else 60.0}
            if self.base_url:
                kwargs["base_url"] = self.base_url
            client = OpenAI(**kwargs)
            stream = self._open_stream(client)
            self._stream = stream
            if self._cancelled:          # Stop was pressed while connecting
                stream.close()
                return
            parts, last_emit, usage = [], 0.0, None
            try:
                for chunk in stream:
                    if self._cancelled:
                        break
                    chunk_usage = getattr(chunk, "usage", None)
                    if chunk_usage is not None:
                        usage = {"prompt": getattr(chunk_usage, "prompt_tokens", 0) or 0,
                                 "completion": getattr(chunk_usage, "completion_tokens", 0) or 0,
                                 "total": getattr(chunk_usage, "total_tokens", 0) or 0}
                    choices = getattr(chunk, "choices", None) or []
                    if not choices:
                        continue
                    delta = getattr(choices[0], "delta", None)
                    piece = getattr(delta, "content", None) if delta is not None else None
                    if piece:
                        parts.append(piece)
                        now = time.monotonic()
                        if now - last_emit >= self.EMIT_INTERVAL:
                            last_emit = now
                            self.partial.emit("".join(parts))
            finally:
                close = getattr(stream, "close", None)
                if close:
                    try:
                        close()
                    except Exception:
                        pass
            if self._cancelled:
                return
            answer = "".join(parts).strip()
            self.response_ready.emit(answer or tr("(The response was empty.)"), usage)

        except openai.AuthenticationError:
            self._fail(tr("Invalid API Key. Check your key in Settings and connect again."))
        except openai.RateLimitError:
            self._fail(tr("Rate limit or quota exceeded. Check your account balance or wait a moment."))
        except openai.APITimeoutError:
            self._fail(tr("The request timed out. Please try again."))
        except openai.APIConnectionError:
            if local:
                self._fail(tr("Could not reach the local model server at {url}. Make sure it is running "
                              "(for example Ollama or LM Studio).").format(url=self.base_url))
            else:
                self._fail(tr("Connection error. Check your internet connection and try again."))
        except openai.NotFoundError:
            if local:
                self._fail(tr("The model \"{model}\" was not found on the local server. Download it first "
                              "(e.g. ollama pull {model}) or change it in Settings.").format(model=self.model))
            else:
                self._fail(tr("The model \"{model}\" is not available for your account.").format(model=self.model))
        except openai.APIStatusError as exc:
            self._fail(tr("API error ({code}): {message}").format(code=exc.status_code, message=exc.message))
        except Exception as exc:
            self._fail(tr("Unexpected error: {error}").format(error=exc))


class TitleWorker(QThread):
    """Asks the model for a short chat title after the first reply (runs once per chat)."""

    done = pyqtSignal(str, str)   # (thread_id, title)

    PROMPT = ("Write a short title (at most 6 words) for this conversation, in the same language "
              "as the user's message. Reply with the title only: no quotes, no emoji, no final period.")

    def __init__(self, thread_id: str, api_key: str, model: str, base_url, user_text: str,
                 reply_text: str, parent=None):
        super().__init__(parent)
        self.thread_id = thread_id
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.user_text = user_text
        self.reply_text = reply_text

    def run(self):
        try:
            kwargs = {"api_key": self.api_key, "timeout": 15.0}
            if self.base_url:
                kwargs["base_url"] = self.base_url
            result = OpenAI(**kwargs).chat.completions.create(model=self.model, messages=[
                {"role": "system", "content": self.PROMPT},
                {"role": "user", "content": f"User: {self.user_text[:1200]}\n\nAssistant: {self.reply_text[:1200]}"},
            ])
            title = (result.choices[0].message.content or "").strip()
            title = title.splitlines()[0].strip().strip("\"'“”*#").rstrip(".").strip() if title else ""
            if title:
                self.done.emit(self.thread_id, make_title(title))
        except Exception:
            pass   # The chat simply keeps its first-message title


# =====================================================================
#  CONVERSATION DATA (saved between sessions)
# =====================================================================
NEW_THREAD_TITLE = "New chat"


def make_title(text: str) -> str:
    first_line = text.strip().split("\n")[0]
    return first_line if len(first_line) <= 50 else first_line[:49].rstrip() + "…"


def group_by_date(threads):
    """
    Pinned / Today / Yesterday / Previous 7 days / Older, newest first.
    Uses calendar days (previously "Today" meant "the last 24 hours", so a chat
    from 23:00 yesterday was still listed under Today the next morning).
    """
    today = datetime.now().date()
    groups = {"Pinned": [], "Today": [], "Yesterday": [], "Previous 7 days": [], "Older": []}
    for thread in sorted(threads, key=lambda t: t.updated, reverse=True):
        if getattr(thread, "pinned", False):
            groups["Pinned"].append(thread)
            continue
        try:
            age = (today - datetime.fromtimestamp(thread.updated).date()).days
        except (OverflowError, OSError, ValueError):
            age = 999
        if age <= 0:
            groups["Today"].append(thread)
        elif age == 1:
            groups["Yesterday"].append(thread)
        elif age < 7:
            groups["Previous 7 days"].append(thread)
        else:
            groups["Older"].append(thread)
    return list(groups.items())


class ChatThread:
    """One conversation: visible entries plus the message history sent to the model."""

    def __init__(self, title=NEW_THREAD_TITLE, thread_id=None, created=None,
                 updated=None, entries=None, history=None, pinned=False):
        self.id = thread_id or uuid.uuid4().hex
        self.title = title
        self.created = created or time.time()
        self.updated = updated or self.created
        # Entry types: user, assistant, activity (status: running/success/error/info)
        self.entries = entries or []
        self.history = history or []
        self.pinned = bool(pinned)

    def is_empty(self) -> bool:
        return not self.entries

    def to_dict(self) -> dict:
        return {"id": self.id, "title": self.title, "created": self.created,
                "updated": self.updated, "entries": self.entries, "history": self.history,
                "pinned": self.pinned}

    @classmethod
    def from_dict(cls, data: dict):
        title = data.get("title") or NEW_THREAD_TITLE
        if title == "New thread":  # Title used by earlier versions
            title = NEW_THREAD_TITLE
        entries = []
        for entry in data.get("entries") or []:
            if not isinstance(entry, dict):
                continue
            entry = dict(entry)
            # The app was closed (or crashed) while a reply was streaming: without this
            # the row would show typing dots forever after a restart.
            if entry.pop("streaming", False) and not entry.get("text"):
                entry["text"] = tr("*Response interrupted.*")
            if entry.get("type") == "activity" and entry.get("status") == "running":
                entry["status"] = "info"
            entries.append(entry)
        history = [m for m in (data.get("history") or [])
                   if isinstance(m, dict) and m.get("role") in ("user", "assistant") and m.get("content")]
        return cls(title=title, thread_id=data.get("id"), created=data.get("created"),
                   updated=data.get("updated"), entries=entries, history=history,
                   pinned=bool(data.get("pinned", False)))

    def to_markdown(self) -> str:
        lines = [f"# {self.title}", ""]
        for entry in self.entries:
            kind = entry.get("type")
            if kind == "user":
                lines += [f"**{tr('You')}:**", ""]
                lines += [f"*[{tr('Image')}: {image.get('name', '')}]*" for image in entry.get("images") or []]
                lines += [entry.get("text", ""), ""]
            elif kind == "assistant":
                lines += ["**YamanAI:**", "", entry.get("text", ""), ""]
            elif kind == "activity":
                lines += [f"> {entry.get('text', '')}", ""]
        return "\n".join(lines)


class ThreadStore:
    """Saves conversations as JSON in the user's app-data folder."""

    MAX_THREADS = 300

    def __init__(self):
        base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
        base = base or os.path.expanduser("~")
        self.path = os.path.join(base, "threads.json")
        # Folder used before the app was renamed to YamanAI
        self.legacy_path = os.path.join(os.path.dirname(base), SETTINGS_APP_NAME, "threads.json")

    def load(self):
        path = self.path
        if not os.path.exists(path) and os.path.exists(self.legacy_path):
            path = self.legacy_path
        try:
            with open(path, encoding="utf-8") as file:
                data = json.load(file)
            return [ChatThread.from_dict(item) for item in data.get("threads", [])]
        except (OSError, ValueError, TypeError, AttributeError):
            return []

    def save(self, threads):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            temp_path = self.path + ".tmp"
            with open(temp_path, "w", encoding="utf-8") as file:
                json.dump({"version": 1, "threads": [t.to_dict() for t in threads[:self.MAX_THREADS]]},
                          file, ensure_ascii=False, indent=1)
            os.replace(temp_path, self.path)  # Atomic: never leaves a half-written file
        except OSError:
            pass


# ----- Message content (plain text, or text + images for vision models) -----
def content_text(content) -> str:
    """The text of a history message, whether it is a string or a list of parts."""
    if isinstance(content, list):
        return "\n".join(part.get("text", "") for part in content
                         if isinstance(part, dict) and part.get("type") == "text")
    return content or ""


def image_data_url(image: dict) -> str:
    return f"data:{image.get('mime', 'image/jpeg')};base64,{image.get('data', '')}"


def user_content(text: str, images=None):
    if not images:
        return text
    return [{"type": "text", "text": text}] + [
        {"type": "image_url", "image_url": {"url": image_data_url(image)}} for image in images
    ]


def prepare_history(history: list) -> list:
    """Only the latest messages are resent with their images (they are large); older ones get a note."""
    cutoff = len(history) - IMAGE_HISTORY_MESSAGES
    prepared = []
    for index, message in enumerate(history):
        content = message.get("content")
        if index < cutoff and isinstance(content, list):
            count = sum(1 for part in content if isinstance(part, dict) and part.get("type") == "image_url")
            message = {"role": message["role"],
                       "content": content_text(content) + f"\n[{count} image(s) were attached here]"}
        prepared.append(message)
    return prepared


# =====================================================================
#  MARKDOWN & CODE RENDERING (web look: VS Code dark code, blue bullets)
# =====================================================================
FENCE_RE = re.compile(r"```([\w+#.\-]*)[^\n]*\n(.*?)(?:```|\Z)", re.DOTALL)
CODE_TOKEN_TEMPLATE = (
    r"(?P<comment>{comments})"
    r"|(?P<string>\"\"\".*?\"\"\"|'''.*?'''|\"(?:\\.|[^\"\\\n])*\"|'(?:\\.|[^'\\\n])*'|`(?:\\.|[^`\\])*`)"
    r"|(?P<number>\b\d+(?:\.\d+)?\b)"
    r"|(?P<control>\b(?:if|elif|else|for|while|return|import|from|as|try|except|finally|with|break|"
    r"continue|raise|yield|await|switch|case|default|do|throw|catch|export)\b)"
    r"|(?P<keyword>\b(?:def|class|lambda|in|not|and|or|is|None|True|False|pass|async|const|let|var|"
    r"function|new|this|self|public|private|static|void|int|string|bool|true|false|null|undefined)\b)"
    r"|(?P<function>\b[A-Za-z_]\w*(?=\())"
)
# Comment syntax depends on the language: '#' is a color in CSS and '//' is
# floor division in Python, so each family gets its own tokenizer.
HASH_COMMENT_LANGS = {
    "python", "py", "bash", "sh", "shell", "zsh", "powershell", "ps1", "ps", "ruby", "rb",
    "yaml", "yml", "toml", "r", "perl", "pl", "dockerfile", "makefile", "make", "ini", "conf",
    "nim", "elixir", "ex", "julia", "coffee",
}
SLASH_COMMENT_LANGS = {
    "javascript", "js", "jsx", "typescript", "ts", "tsx", "java", "c", "cpp", "c++", "h", "hpp",
    "cs", "c#", "csharp", "go", "rust", "rs", "kotlin", "kt", "swift", "dart", "scala", "json",
    "jsonc", "css", "scss", "sass", "less", "php", "html", "xml", "svg", "vue", "svelte",
}
_COMMENT_PATTERNS = {
    "hash": r"#[^\n]*",
    "slash": r"//[^\n]*|/\*.*?\*/|<!--.*?-->",
    "both": r"#[^\n]*|//[^\n]*|/\*.*?\*/|<!--.*?-->",
}
CODE_TOKEN_RES = {
    family: re.compile(CODE_TOKEN_TEMPLATE.replace("{comments}", pattern), re.DOTALL)
    for family, pattern in _COMMENT_PATTERNS.items()
}


def comment_family(language: str) -> str:
    language = (language or "").lower()
    if language in HASH_COMMENT_LANGS:
        return "hash"
    if language in SLASH_COMMENT_LANGS:
        return "slash"
    return "both"


CODE_COLORS = {  # VS Code Dark+
    "comment": "#6A9955", "string": "#CE9178", "number": "#B5CEA8",
    "control": "#C586C0", "keyword": "#569CD6", "function": "#DCDCAA",
}
TABLE_SEPARATOR_RE = re.compile(r"^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?$")


def split_code_blocks(text: str):
    """Splits a reply into ("text", str) and ("code", language, code) segments."""
    segments, position = [], 0
    for match in FENCE_RE.finditer(text):
        if match.start() > position:
            segments.append(("text", text[position:match.start()]))
        segments.append(("code", match.group(1) or "", match.group(2).rstrip("\n")))
        position = match.end()
    if position < len(text):
        segments.append(("text", text[position:]))
    return segments


def highlight_code(code: str, language: str = "") -> str:
    parts, position = [], 0
    for match in CODE_TOKEN_RES[comment_family(language)].finditer(code):
        parts.append(html.escape(code[position:match.start()]))
        kind = match.lastgroup
        style = f"color:{CODE_COLORS[kind]};"
        if kind == "comment":
            style += "font-style:italic;"
        parts.append(f'<span style="{style}">{html.escape(match.group(0))}</span>')
        position = match.end()
    parts.append(html.escape(code[position:]))
    return (f'<pre style="margin:0; font-family:{MONO_FONT_CSS}; color:{P["code_text"]}; '
            f'line-height:145%;">{"".join(parts)}</pre>')


def md_inline(text: str) -> str:
    """Escapes text and renders `code`, **bold**, *italic*, ~~strike~~ and [links](url)."""
    escaped = html.escape(text, quote=False)
    output = []
    for part in re.split(r"(`[^`\n]+`)", escaped):
        if len(part) >= 2 and part.startswith("`") and part.endswith("`"):
            output.append(
                f'<span style="background-color:{P["inline_code_bg"]}; color:{P["inline_code_fg"]}; '
                f'font-family:{MONO_FONT_CSS};">&nbsp;{part[1:-1]}&nbsp;</span>'
            )
            continue
        # Links are swapped for placeholders first, so the bold/italic rules can no
        # longer break URLs such as https://site.com/_page_ (bug in 1.0)
        links = []

        def stash(url: str, label: str) -> str:
            links.append(f'<a href="{url}" style="color:{P["accent_text"]};">{label}</a>')
            return f"\x00{len(links) - 1}\x00"

        part = MD_LINK_RE.sub(lambda m: stash(m.group(2), m.group(1)), part)
        part = BARE_URL_RE.sub(lambda m: stash(m.group(1), m.group(1)), part)
        part = re.sub(r"\*\*(.+?)\*\*", rf'<b style="color:{P["text"]};">\1</b>', part)
        part = re.sub(r"(?<![\*\w])\*(?!\s)(.+?)(?<!\s)\*(?![\*\w])", r"<i>\1</i>", part)
        part = re.sub(r"(?<!\w)_(?!\s)(.+?)(?<!\s)_(?!\w)", r"<i>\1</i>", part)
        part = re.sub(r"~~(.+?)~~", r"<s>\1</s>", part)
        part = re.sub(r"\x00(\d+)\x00", lambda m: links[int(m.group(1))], part)
        output.append(part)
    return "".join(output)


MD_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^\s)\"]+)\)")
BARE_URL_RE = re.compile(r"(?<![\w/\"'=])(https?://[^\s<>()\"]*[^\s<>()\".,;:!?'])")


def _table_cells(line: str):
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [cell.strip() for cell in line.split("|")]


def markdown_to_html(text: str) -> str:
    """Paragraphs, headings, lists with blue bullets, quotes, tables and rules."""
    lines = text.split("\n")
    blocks, paragraph, items = [], [], []
    state = {"list": None}
    heading_sizes = {1: "18pt", 2: "15pt", 3: "13pt", 4: "11.5pt", 5: "11pt", 6: "11pt"}

    def flush_paragraph():
        if paragraph:
            blocks.append(f'<p style="margin:0 0 12px 0; line-height:170%;">{"<br>".join(paragraph)}</p>')
            paragraph.clear()

    def flush_list():
        if items:
            rows = []
            for number, item in enumerate(items, 1):
                marker = f"{number}." if state["list"] == "ol" else "&#8226;"
                rows.append(f'<tr><td width="22" valign="top" style="color:{P["accent_text"]}; '
                            f'line-height:170%;">{marker}</td><td style="line-height:170%;">{item}</td></tr>')
            blocks.append(f'<table cellspacing="0" cellpadding="1" style="margin:2px 0 12px 0;">{"".join(rows)}</table>')
            items.clear()
        state["list"] = None

    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        # Table: header row followed by a separator row
        if (stripped.startswith("|") and index + 1 < len(lines)
                and TABLE_SEPARATOR_RE.match(lines[index + 1].strip())):
            flush_paragraph()
            flush_list()
            header = _table_cells(stripped)
            body_rows = []
            index += 2
            while index < len(lines) and lines[index].strip().startswith("|"):
                body_rows.append(_table_cells(lines[index]))
                index += 1
            head_html = "".join(f'<th align="left" style="color:{P["text"]}; background-color:{P["inline_code_bg"]};">'
                                f'{md_inline(c)}</th>' for c in header)
            body_html = "".join("<tr>" + "".join(f'<td style="color:{P["muted"]};">{md_inline(c)}</td>' for c in row)
                                + "</tr>" for row in body_rows)
            blocks.append(f'<table border="1" cellspacing="0" cellpadding="8" style="border-collapse:collapse; '
                          f'border-color:{P["border_strong"]}; margin:6px 0 14px 0;"><tr>{head_html}</tr>{body_html}</table>')
            continue

        if not stripped:
            flush_paragraph()
            flush_list()
        elif re.match(r"^(-{3,}|\*{3,}|_{3,})$", stripped):
            flush_paragraph()
            flush_list()
            blocks.append("<hr>")
        elif re.match(r"^(#{1,6})\s+(.*)", stripped):
            flush_paragraph()
            flush_list()
            match = re.match(r"^(#{1,6})\s+(.*)", stripped)
            level = len(match.group(1))
            blocks.append(f'<p style="margin:12px 0 8px 0; font-size:{heading_sizes[level]}; font-weight:700; '
                          f'color:{P["text"]};">{md_inline(match.group(2))}</p>')
        elif stripped.startswith(">"):
            flush_paragraph()
            flush_list()
            quote = md_inline(stripped.lstrip(">").strip())
            blocks.append(f'<table cellspacing="0" cellpadding="0" style="margin:4px 0 12px 0;"><tr>'
                          f'<td width="4" bgcolor="#2B5BB5"></td><td width="14"></td>'
                          f'<td style="color:{P["muted"]}; font-style:italic; line-height:170%;">{quote}</td></tr></table>')
        elif re.match(r"^[-*•+]\s+(.*)", stripped) or re.match(r"^\d+[.)]\s+(.*)", stripped):
            flush_paragraph()
            bullet = re.match(r"^[-*•+]\s+(.*)", stripped)
            tag = "ul" if bullet else "ol"
            if state["list"] not in (None, tag):
                flush_list()
            state["list"] = tag
            content = (bullet or re.match(r"^\d+[.)]\s+(.*)", stripped)).group(1)
            items.append(md_inline(content))
        else:
            flush_list()
            paragraph.append(md_inline(stripped))
        index += 1

    flush_paragraph()
    flush_list()
    return "".join(blocks)


PREVIEW_PREFIX = "yamanai-preview-"


def cleanup_old_previews(max_age_hours: float = 24):
    """Deletes live-preview HTML files left in the temp folder by earlier sessions."""
    folder, limit = tempfile.gettempdir(), time.time() - max_age_hours * 3600
    try:
        names = os.listdir(folder)
    except OSError:
        return
    for name in names:
        if name.startswith(PREVIEW_PREFIX) and name.endswith(".html"):
            path = os.path.join(folder, name)
            try:
                if os.path.getmtime(path) < limit:
                    os.remove(path)
            except OSError:
                pass


def read_attachment(path: str):
    """
    Reads a text/code file for the prompt.
    Returns (True, (language, text)) or (False, error_message).
    """
    name = os.path.basename(path)
    try:
        if os.path.isdir(path):
            return False, tr("\"{name}\" is a folder; only files can be attached.").format(name=name)
        size = os.path.getsize(path)
        if size > MAX_ATTACHMENT_BYTES:
            return False, tr("\"{name}\" is too large to attach ({size} KB, limit {limit} KB).").format(
                name=name, size=size // 1024, limit=MAX_ATTACHMENT_BYTES // 1024)
        with open(path, "rb") as file:
            raw = file.read()
    except OSError as exc:
        return False, tr("Could not read \"{name}\": {error}").format(name=name, error=exc.strerror or exc)
    if b"\x00" in raw[:4096]:
        return False, tr("\"{name}\" is not a text file, so it can't be attached.").format(name=name)
    for encoding in ("utf-8-sig", "cp1254", "latin-1"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    language = ATTACHMENT_LANGS.get(os.path.splitext(name)[1].lower(), "")
    return True, (language, text.replace("\r\n", "\n"))


def encode_image(image: QImage, name: str):
    """Scales an image down, flattens transparency onto white and encodes it as base64 JPEG."""
    if image is None or image.isNull():
        return None
    if max(image.width(), image.height()) > MAX_IMAGE_SIDE:
        image = image.scaled(MAX_IMAGE_SIDE, MAX_IMAGE_SIDE, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
    flat = QImage(image.size(), QImage.Format.Format_RGB32)
    flat.fill(QColor("#FFFFFF"))
    painter = QPainter(flat)
    painter.drawImage(0, 0, image)
    painter.end()
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    flat.save(buffer, "JPG", 88)
    buffer.close()
    return {"name": name, "mime": "image/jpeg", "data": base64.b64encode(data.data()).decode("ascii")}


def read_image_attachment(path: str):
    """Returns (True, image dict) or (False, error_message)."""
    name = os.path.basename(path)
    try:
        size = os.path.getsize(path)
    except OSError as exc:
        return False, tr("Could not read \"{name}\": {error}").format(name=name, error=exc.strerror or exc)
    if size > MAX_IMAGE_BYTES:
        return False, tr("\"{name}\" is too large to attach ({size} KB, limit {limit} KB).").format(
            name=name, size=size // 1024, limit=MAX_IMAGE_BYTES // 1024)
    result = encode_image(QImage(path), name)
    if result is None:
        return False, tr("\"{name}\" could not be opened as an image.").format(name=name)
    return True, result


def pixmap_from_image(image: dict) -> QPixmap:
    pixmap = QPixmap()
    try:
        pixmap.loadFromData(base64.b64decode(image.get("data", "")))
    except (ValueError, TypeError):
        pass
    return pixmap


LANG_EXTENSIONS = {
    "python": ".py", "py": ".py", "javascript": ".js", "js": ".js", "typescript": ".ts", "ts": ".ts",
    "jsx": ".jsx", "tsx": ".tsx", "html": ".html", "css": ".css", "json": ".json", "bash": ".sh",
    "sh": ".sh", "shell": ".sh", "powershell": ".ps1", "ps1": ".ps1", "bat": ".bat", "batch": ".bat",
    "cmd": ".bat", "csharp": ".cs", "cs": ".cs", "c#": ".cs", "cpp": ".cpp", "c++": ".cpp", "c": ".c",
    "java": ".java", "go": ".go", "rust": ".rs", "rs": ".rs", "sql": ".sql", "yaml": ".yml", "yml": ".yml",
    "xml": ".xml", "markdown": ".md", "md": ".md", "php": ".php", "ruby": ".rb", "kotlin": ".kt",
    "swift": ".swift", "lua": ".lua", "toml": ".toml", "ini": ".ini", "csv": ".csv",
}


def extension_for(language: str) -> str:
    return LANG_EXTENSIONS.get((language or "").lower(), ".txt")


def open_live_preview(code: str, language: str):
    """Opens HTML/CSS/JS code in the default browser (like the web app's Live preview)."""
    language = language.lower()
    if language == "css":
        document = (f"<html><head><style>{code}</style></head><body style=\"background:#1a1a1a;padding:2rem\">"
                    f"<p style=\"font-family:sans-serif;color:#888\">CSS preview</p></body></html>")
    elif language in ("javascript", "js"):
        document = (f"<html><body style=\"background:#111;color:#eee;font-family:monospace;padding:1rem\">"
                    f"<script>{code}</script></body></html>")
    else:
        document = code
    path = os.path.join(tempfile.gettempdir(), f"{PREVIEW_PREFIX}{uuid.uuid4().hex[:8]}.html")
    with open(path, "w", encoding="utf-8") as file:
        file.write(document)
    webbrowser.open(Path(path).as_uri())


def set_tracking(widget: QWidget, spacing: float):
    """Letter spacing (QSS has no letter-spacing property)."""
    font = widget.font()
    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    widget.setFont(font)


# =====================================================================
#  SMALL REUSABLE WIDGETS
# =====================================================================
def make_icon_button(icon_names, tooltip: str, object_name="iconButton", size=18, color="muted",
                     active="accent_text") -> QToolButton:
    button = QToolButton()
    button.setObjectName(object_name)
    IconRegistry.bind(button, icon_names, color, active=active)
    button.setIconSize(QSize(size, size))
    button.setToolTip(tooltip)
    button.setAccessibleName(tooltip)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setAutoRaise(True)
    return button


class ElidedLabel(QLabel):
    """Single-line label that shortens long text with '…' instead of stretching."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self._full_text = text
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self._refresh()

    def sizeHint(self) -> QSize:
        return QSize(self.fontMetrics().horizontalAdvance(self._full_text) + 4, super().sizeHint().height())

    def minimumSizeHint(self) -> QSize:
        return QSize(24, super().minimumSizeHint().height())

    def setText(self, text: str):
        self._full_text = text
        self._refresh()
        self.updateGeometry()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh()

    def _refresh(self):
        self.ensurePolished()
        elided = self.fontMetrics().elidedText(self._full_text, Qt.TextElideMode.ElideRight, max(0, self.width()))
        QLabel.setText(self, elided)


class FocusFrame(QFrame):
    """Frame whose border is highlighted while the input inside it has focus."""

    def watch(self, widget: QWidget):
        widget.installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
            self.setProperty("focused", event.type() == QEvent.Type.FocusIn)
            self.style().unpolish(self)
            self.style().polish(self)
        return super().eventFilter(obj, event)


def repolish(widget: QWidget):
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class ToggleSwitch(QCheckBox):
    """QCheckBox drawn as a sliding switch with a round knob."""

    TRACK_W, TRACK_H = 38, 20

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def sizeHint(self) -> QSize:
        fm = self.fontMetrics()
        return QSize(self.TRACK_W + 12 + fm.horizontalAdvance(self.text()) + 4,
                     max(self.TRACK_H, fm.height()) + 6)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def hitButton(self, pos) -> bool:
        return self.rect().contains(pos)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        on = self.isChecked()
        y = (self.height() - self.TRACK_H) / 2
        track = QRectF(1, y, self.TRACK_W, self.TRACK_H)
        radius = self.TRACK_H / 2
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(P["accent"]) if on else to_qcolor(P["active"]))
        painter.drawRoundedRect(track, radius, radius)
        knob = self.TRACK_H - 6
        knob_x = track.right() - knob - 3 if on else track.left() + 3
        painter.setBrush(QColor("#FFFFFF") if on else QColor(P["muted"]))
        painter.drawEllipse(QRectF(knob_x, y + 3, knob, knob))
        if self.hasFocus():
            painter.setPen(QPen(QColor(P["accent_hover"]), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(track.adjusted(-1, -1, 1, 1), radius + 1, radius + 1)
        painter.setPen(QColor(P["text"] if on else P["muted"]))
        text_rect = QRectF(self.TRACK_W + 12, 0, self.width() - self.TRACK_W - 12, self.height())
        painter.drawText(text_rect, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), self.text())
        painter.end()


class DragArea(QFrame):
    """Area that moves the frameless window when dragged; double-click maximizes."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._press_pos = None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        window = self.window()
        if (USE_CUSTOM_TITLEBAR and self._press_pos is not None
                and event.buttons() & Qt.MouseButton.LeftButton
                and (event.position().toPoint() - self._press_pos).manhattanLength() > 3
                and not window.isFullScreen() and window.windowHandle() is not None):
            self._press_pos = None
            window.windowHandle().startSystemMove()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._press_pos = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        window = self.window()
        if USE_CUSTOM_TITLEBAR and event.button() == Qt.MouseButton.LeftButton and not window.isFullScreen():
            window.showNormal() if window.isMaximized() else window.showMaximized()
            return
        super().mouseDoubleClickEvent(event)


class ResizableFrame(QWidget):
    """Central widget; its thin outer margin is the resize border of the frameless window."""

    MARGIN = 5

    def __init__(self, window: QMainWindow):
        super().__init__()
        self.setObjectName("windowFrame")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMouseTracking(True)
        self._window = window

    def _edges(self, pos: QPoint):
        if not USE_CUSTOM_TITLEBAR or self._window.isMaximized() or self._window.isFullScreen():
            return None
        m, rect = self.MARGIN + 1, self.rect()
        edges = []
        if pos.x() <= m:
            edges.append(Qt.Edge.LeftEdge)
        elif pos.x() >= rect.width() - m:
            edges.append(Qt.Edge.RightEdge)
        if pos.y() <= m:
            edges.append(Qt.Edge.TopEdge)
        elif pos.y() >= rect.height() - m:
            edges.append(Qt.Edge.BottomEdge)
        if not edges:
            return None
        combined = edges[0]
        for edge in edges[1:]:
            combined |= edge
        return combined, set(edges)

    def mouseMoveEvent(self, event):
        found = self._edges(event.position().toPoint())
        if found is None:
            self.unsetCursor()
        else:
            edges = found[1]
            if edges in ({Qt.Edge.LeftEdge, Qt.Edge.TopEdge}, {Qt.Edge.RightEdge, Qt.Edge.BottomEdge}):
                self.setCursor(Qt.CursorShape.SizeFDiagCursor)
            elif edges in ({Qt.Edge.RightEdge, Qt.Edge.TopEdge}, {Qt.Edge.LeftEdge, Qt.Edge.BottomEdge}):
                self.setCursor(Qt.CursorShape.SizeBDiagCursor)
            elif edges & {Qt.Edge.LeftEdge, Qt.Edge.RightEdge}:
                self.setCursor(Qt.CursorShape.SizeHorCursor)
            else:
                self.setCursor(Qt.CursorShape.SizeVerCursor)
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        found = self._edges(event.position().toPoint())
        if found and event.button() == Qt.MouseButton.LeftButton and self._window.windowHandle():
            self._window.windowHandle().startSystemResize(found[0])
            return
        super().mousePressEvent(event)

    def leaveEvent(self, event):
        self.unsetCursor()
        super().leaveEvent(event)


class WindowButton(QPushButton):
    """Minimize / maximize-restore / close button drawn with QPainter (no icon font needed)."""

    SIZE = QSize(46, 32)

    def __init__(self, kind: str, tooltip: str):
        super().__init__()
        self.kind = kind
        self._maximized = False
        self.setFixedSize(self.SIZE)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setToolTip(tooltip)
        self.setAccessibleName(tooltip)

    def set_maximized(self, maximized: bool):
        self._maximized = maximized
        self.update()

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        hovered, pressed = self.underMouse(), self.isDown()
        is_close = self.kind == "close"
        if pressed or hovered:
            if is_close:
                painter.fillRect(self.rect(), QColor("#C50F1F" if pressed else "#E81123"))
            else:
                painter.fillRect(self.rect(), to_qcolor(P["active"] if pressed else P["hover"]))
        color = "#FFFFFF" if is_close and (hovered or pressed) else P["muted"]
        painter.setPen(QPen(QColor(color), 1.2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        cx, cy, s = self.width() / 2, self.height() / 2, 5.0
        if self.kind == "minimize":
            painter.drawLine(QPointF(cx - s, cy), QPointF(cx + s, cy))
        elif self.kind == "maximize":
            if self._maximized:
                painter.drawRect(QRectF(cx - s, cy - s + 2, 2 * s - 2, 2 * s - 2))
                painter.drawLine(QPointF(cx - s + 2, cy - s), QPointF(cx + s, cy - s))
                painter.drawLine(QPointF(cx + s, cy - s), QPointF(cx + s, cy + s - 2))
            else:
                painter.drawRect(QRectF(cx - s, cy - s, 2 * s, 2 * s))
        else:
            painter.drawLine(QPointF(cx - s, cy - s), QPointF(cx + s, cy + s))
            painter.drawLine(QPointF(cx + s, cy - s), QPointF(cx - s, cy + s))
        painter.end()


class AvatarTile(QWidget):
    """Rounded avatar: blue-cyan gradient with a robot (AI) or gray with a person (user)."""

    def __init__(self, kind: str = "ai", size: int = 32, radius: float = 8):
        super().__init__()
        self.kind = kind
        self._radius = radius
        self.setFixedSize(size, size)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        path = QPainterPath()
        path.addRoundedRect(rect, self._radius, self._radius)
        if self.kind == "ai":
            gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
            gradient.setColorAt(0, QColor(P["accent"]))
            gradient.setColorAt(1, QColor(P["cyan"]))
            painter.fillPath(path, QBrush(gradient))
            image, fallback = icon("ph.robot", "#FFFFFF"), "Y"
        else:
            painter.fillPath(path, QColor(P["avatar_user"]))
            painter.setPen(QPen(QColor(P["avatar_user_border"]), 1))
            painter.drawPath(path)
            image, fallback = icon("ph.user", P["avatar_user_icon"]), "U"
        side = int(self.width() * 0.5)
        target = QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side).toRect()
        if image.isNull():
            painter.setPen(QColor("#FFFFFF"))
            painter.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter), fallback)
        else:
            image.paint(painter, target)
        painter.end()


class SparkleTile(QWidget):
    """Welcome-screen tile: soft blue gradient, slightly rotated, with a sparkle icon."""

    def __init__(self, size: int = 64):
        super().__init__()
        self.setFixedSize(size + 8, size + 8)
        self._size = size

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(self.width() / 2, self.height() / 2)
        painter.rotate(3)
        half = self._size / 2
        rect = QRectF(-half, -half, self._size, self._size)
        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        gradient.setColorAt(0, QColor(37, 99, 235, 77))
        gradient.setColorAt(1, QColor(6, 182, 212, 51))
        path = QPainterPath()
        path.addRoundedRect(rect, 16, 16)
        painter.fillPath(path, QBrush(gradient))
        painter.setPen(QPen(QColor(59, 130, 246, 77), 1))
        painter.drawPath(path)
        side = 28
        icon("ph.sparkle", P["accent_text"]).paint(painter, QRectF(-side / 2, -side / 2, side, side).toRect())
        painter.end()


class GradientTitle(QWidget):
    """Bold title with a vertical white-to-gray text gradient (like the web heading)."""

    def __init__(self, text: str, point_size: float = 18):
        super().__init__()
        self._text = text
        self._font = QFont()
        self._font.setPointSizeF(point_size)
        self._font.setBold(True)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

    def sizeHint(self) -> QSize:
        from PyQt6.QtGui import QFontMetrics
        metrics = QFontMetrics(self._font)
        return QSize(metrics.horizontalAdvance(self._text) + 8, metrics.height() + 6)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setFont(self._font)
        gradient = QLinearGradient(0, 0, 0, self.height())
        gradient.setColorAt(0, QColor(P["title_from"]))
        gradient.setColorAt(1, QColor(P["title_to"]))
        painter.setPen(QPen(QBrush(gradient), 1))
        painter.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter), self._text)
        painter.end()


class PulseDot(QWidget):
    """Small status dot that softly pulses."""

    def __init__(self, size: int = 6):
        super().__init__()
        self.setFixedSize(size, size)
        self._color = QColor(P["green"])
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(60)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def set_color(self, color: str):
        self._color = QColor(color)
        self.update()

    def _tick(self):
        self._phase = (self._phase + 0.12) % (2 * math.pi)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(self._color)
        color.setAlphaF(0.55 + 0.45 * (0.5 + 0.5 * math.sin(self._phase)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(self.rect())
        painter.end()


class TypingDots(QWidget):
    """Three bouncing dots shown while the reply is being written."""

    def __init__(self):
        super().__init__()
        self.setFixedSize(46, 24)
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._tick)

    def showEvent(self, event):
        self._timer.start()
        super().showEvent(event)

    def hideEvent(self, event):
        self._timer.stop()
        super().hideEvent(event)

    def _tick(self):
        self._phase = (self._phase + 0.21) % (2 * math.pi)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(P["accent_text"])
        color.setAlphaF(0.6)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        for index in range(3):
            lift = max(0.0, math.sin(self._phase - index * 0.9)) * 5
            painter.drawEllipse(QRectF(4 + index * 14, 10 - lift, 8, 8))
        painter.end()


# =====================================================================
#  MESSAGE WIDGETS
# =====================================================================
class CodeBlock(QFrame):
    """Dark code card: language label, Live preview (HTML/CSS/JS), Copy, horizontal scroll."""

    def __init__(self, language: str, code: str):
        super().__init__()
        self.setObjectName("codeCard")
        self._language = (language or "").lower()
        self._code = code
        layout = QVBoxLayout(self)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(0)

        header = QFrame()
        header.setObjectName("codeHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 7, 12, 7)
        header_layout.setSpacing(12)
        self.language_label = QLabel((language or "text").upper())
        self.language_label.setObjectName("codeLang")
        header_layout.addWidget(self.language_label)
        header_layout.addStretch(1)
        if self._language in PREVIEW_LANGS:
            preview = QPushButton(caps(tr("Live preview")))
            preview.setObjectName("previewAction")
            IconRegistry.bind(preview, "ph.play", "#60A5FA")
            preview.setIconSize(QSize(11, 11))
            preview.setCursor(Qt.CursorShape.PointingHandCursor)
            preview.clicked.connect(lambda: open_live_preview(self._code, self._language))
            header_layout.addWidget(preview)
        self.copy_button = QPushButton(caps(tr("Copy")))
        self.copy_button.setObjectName("codeAction")
        IconRegistry.bind(self.copy_button, "ph.copy", "code_muted")
        self.copy_button.setIconSize(QSize(12, 12))
        self.copy_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_button.clicked.connect(self._copy)
        header_layout.addWidget(self.copy_button)
        self.save_button = QPushButton(caps(tr("Save")))
        self.save_button.setObjectName("codeAction")
        self.save_button.setToolTip(tr("Save the code to a file"))
        IconRegistry.bind(self.save_button, "ph.floppy-disk", "code_muted")
        self.save_button.setIconSize(QSize(12, 12))
        self.save_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_button.clicked.connect(self._save)
        header_layout.addWidget(self.save_button)

        self.body = QLabel()
        self.body.setObjectName("codeBody")
        self.body.setTextFormat(Qt.TextFormat.RichText)
        self.body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.body.setContentsMargins(22, 18, 22, 18)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("codeScroll")
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setWidgetResizable(False)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll.setWidget(self.body)

        layout.addWidget(header)
        layout.addWidget(self.scroll)
        for widget in (self.language_label, self.copy_button, self.save_button):
            widget.ensurePolished()
            set_tracking(widget, 1.2)
        self.set_code(code)

    def set_code(self, code: str):
        self._code = code
        self.body.setText(highlight_code(code, self._language))
        self.body.adjustSize()
        self._fit()

    def _fit(self):
        needs_scroll = self.body.width() > self.scroll.viewport().width()
        bar = self.scroll.horizontalScrollBar().sizeHint().height() if needs_scroll else 0
        self.scroll.setFixedHeight(self.body.height() + bar)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()

    def _copy(self):
        QApplication.clipboard().setText(self._code)
        self.copy_button.setText(caps(tr("Copied")))
        IconRegistry.bind(self.copy_button, "ph.check", "green_text")
        QTimer.singleShot(2000, self._reset_copy)

    def _reset_copy(self):
        try:
            self.copy_button.setText(caps(tr("Copy")))
            IconRegistry.bind(self.copy_button, "ph.copy", "code_muted")
        except RuntimeError:
            pass

    def _save(self):
        default = os.path.join(os.path.expanduser("~"), "code" + extension_for(self._language))
        path, _filter = QFileDialog.getSaveFileName(self, tr("Save code"), default, tr("All files") + " (*)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8", newline="\n") as file:
                file.write(self._code.rstrip("\n") + "\n")
        except OSError as exc:
            QMessageBox.warning(self, tr("Save failed"), str(exc))
            return
        self.save_button.setText(caps(tr("Saved")))
        QTimer.singleShot(2000, self._reset_save)

    def _reset_save(self):
        try:
            self.save_button.setText(caps(tr("Save")))
        except RuntimeError:
            pass


class MessageRow(QFrame):
    """Full-width message row with avatar (user rows have a subtle background)."""

    speak_requested = pyqtSignal(str)
    regenerate_requested = pyqtSignal()
    edit_requested = pyqtSignal()

    def __init__(self, role: str, text: str, final: bool = True, meta: str = "", images=None):
        super().__init__()
        self.role = role
        self.setObjectName("userRow" if role == "user" else "aiRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(16, 26, 16, 26)

        self.inner = QWidget()
        inner_layout = QHBoxLayout(self.inner)
        inner_layout.setContentsMargins(0, 0, 0, 0)
        inner_layout.setSpacing(20)
        inner_layout.addWidget(AvatarTile("user" if role == "user" else "ai"), 0, Qt.AlignmentFlag.AlignTop)
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 2, 0, 0)
        self.body_layout.setSpacing(12)
        inner_layout.addWidget(self.body, 1)
        outer.addWidget(self.inner, 0, Qt.AlignmentFlag.AlignHCenter)

        self._text = None
        self._final = None
        self._segments = []   # [(kind, key, widget)]
        self._dots = None
        self._actions = None
        self._regen_button = None
        self._regen_visible = False
        self._edit_button = None
        self._retry_button = None
        self._meta = meta
        self._meta_label = None
        self._images = images or []
        if self._images:
            self.body_layout.addWidget(self._build_image_strip(self._images))
        self.set_text(text, final)

    @staticmethod
    def _build_image_strip(images) -> QWidget:
        """Thumbnails of the images sent with a message."""
        strip = QWidget()
        layout = QHBoxLayout(strip)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        for image in images:
            label = QLabel()
            label.setObjectName("messageImage")
            pixmap = pixmap_from_image(image)
            if pixmap.isNull():
                label.setText(image.get("name", tr("Image")))
            else:
                label.setPixmap(pixmap.scaled(QSize(220, 160), Qt.AspectRatioMode.KeepAspectRatio,
                                              Qt.TransformationMode.SmoothTransformation))
            label.setToolTip(image.get("name", ""))
            layout.addWidget(label)
        layout.addStretch(1)
        return strip

    def set_content_width(self, width: int, side_padding: int):
        self.layout().setContentsMargins(side_padding, 26, side_padding, 26)
        self.inner.setFixedWidth(width)

    # ----- Content -----
    def _clear_segments(self):
        for _kind, _key, widget in self._segments:
            self.body_layout.removeWidget(widget)
            widget.deleteLater()
        self._segments = []

    def _make_text_label(self, rich: str, plain: bool = False) -> QLabel:
        label = QLabel(rich)
        label.setObjectName("messageText")
        label.setTextFormat(Qt.TextFormat.PlainText if plain else Qt.TextFormat.RichText)
        label.setWordWrap(True)
        label.setOpenExternalLinks(True)
        label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        return label

    def set_text(self, text: str, final: bool = True):
        """Updates the message in place (used while a reply is streaming)."""
        if text == self._text and final == self._final:
            return
        self._text, self._final = text, final

        # Typing dots while nothing has arrived yet
        if not text:
            self._clear_segments()
            if self._dots is None:
                self._dots = TypingDots()
                self.body_layout.addWidget(self._dots)
            return
        if self._dots is not None:
            self.body_layout.removeWidget(self._dots)
            self._dots.deleteLater()
            self._dots = None

        if self.role == "user":
            if self._segments:
                self._segments[0][2].setText(text)
            else:
                label = self._make_text_label(text, plain=True)
                self.body_layout.addWidget(label)
                self._segments = [("text", None, label)]
                self._build_user_actions()
            return

        # Assistant: text and code segments; existing widgets are reused while streaming
        wanted = []
        for segment in split_code_blocks(text):
            if segment[0] == "code":
                wanted.append(("code", segment[1].lower(), segment[2]))
            else:
                rich = markdown_to_html(segment[1])
                if rich:
                    wanted.append(("text", None, rich))
        same_prefix = all(
            index < len(wanted) and self._segments[index][:2] == wanted[index][:2]
            for index in range(len(self._segments))
        )
        if not same_prefix:
            self._clear_segments()
        for index, (kind, key, content) in enumerate(wanted):
            if index < len(self._segments):
                widget = self._segments[index][2]
                if kind == "code":
                    widget.set_code(content)
                else:
                    widget.setText(content)
                continue
            widget = CodeBlock(key, content) if kind == "code" else self._make_text_label(content)
            insert_at = self.body_layout.count() - (1 if self._actions is not None else 0)
            self.body_layout.insertWidget(insert_at, widget)
            self._segments.append((kind, key, widget))

        # Copy / read-aloud actions once the reply is complete
        if final and self._actions is None:
            self._actions = QWidget()
            actions = QHBoxLayout(self._actions)
            actions.setContentsMargins(0, 0, 0, 0)
            actions.setSpacing(2)
            copy_button = make_icon_button("ph.copy", tr("Copy reply"), "messageAction", 15, "faint")
            copy_button.clicked.connect(lambda: self._copy(copy_button))
            speak_button = make_icon_button("ph.speaker-high", tr("Read aloud"), "messageAction", 15, "faint")
            speak_button.clicked.connect(lambda: self.speak_requested.emit(self._text or ""))
            self._regen_button = make_icon_button("ph.arrows-clockwise", tr("Regenerate reply"),
                                                  "messageAction", 15, "faint")
            self._regen_button.clicked.connect(self.regenerate_requested)
            self._regen_button.setVisible(self._regen_visible)
            actions.addWidget(copy_button)
            actions.addWidget(speak_button)
            actions.addWidget(self._regen_button)
            self._meta_label = QLabel(self._meta)
            self._meta_label.setObjectName("messageMeta")
            actions.addWidget(self._meta_label)
            actions.addStretch(1)
            self.body_layout.addWidget(self._actions)

    def _build_user_actions(self):
        """Copy / Edit / Retry under your own message (Edit and Retry only on the latest one)."""
        self._actions = QWidget()
        actions = QHBoxLayout(self._actions)
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(2)
        copy_button = make_icon_button("ph.copy", tr("Copy message"), "messageAction", 15, "faint")
        copy_button.clicked.connect(lambda: self._copy(copy_button))
        self._edit_button = make_icon_button("ph.pencil-simple", tr("Edit and resend"),
                                             "messageAction", 15, "faint")
        self._edit_button.clicked.connect(self.edit_requested)
        self._retry_button = make_icon_button("ph.arrows-clockwise", tr("Retry (Ctrl+Shift+R)"),
                                              "messageAction", 15, "faint")
        self._retry_button.clicked.connect(self.regenerate_requested)
        self._edit_button.setVisible(False)
        self._retry_button.setVisible(False)
        actions.addWidget(copy_button)
        actions.addWidget(self._edit_button)
        actions.addWidget(self._retry_button)
        actions.addStretch(1)
        self.body_layout.addWidget(self._actions)

    def set_meta(self, text: str):
        """Small grey note next to the reply buttons, e.g. 'GPT-4o · 3.2 s'."""
        self._meta = text or ""
        if self._meta_label is not None:
            self._meta_label.setText(self._meta)

    def set_regenerate_visible(self, visible: bool):
        """Only the latest reply can be regenerated."""
        self._regen_visible = visible
        if self._regen_button is not None:
            self._regen_button.setVisible(visible)

    def set_user_actions(self, edit: bool, retry: bool):
        if self._edit_button is not None:
            self._edit_button.setVisible(edit)
            self._retry_button.setVisible(retry)

    def _copy(self, button: QToolButton):
        QApplication.clipboard().setText(self._text or "")
        IconRegistry.bind(button, "ph.check", "green_text")
        QTimer.singleShot(1500, lambda: IconRegistry.bind(button, "ph.copy", "faint"))


class ActivityRow(QFrame):
    """Console-style line for launches, voice notices and errors (aligned with the text column)."""

    ICONS = {
        "running": ("ph.magnifying-glass", "muted"),
        "success": ("ph.check-circle", "green_text"),
        "error": ("ph.warning-circle", "red"),
        "info": ("ph.info", "muted"),
    }

    def __init__(self, status: str, text: str):
        super().__init__()
        self.setObjectName("activityRow")
        outer = QHBoxLayout(self)
        outer.setContentsMargins(16, 6, 16, 6)
        self.inner = QWidget()
        layout = QHBoxLayout(self.inner)
        layout.setContentsMargins(52, 0, 0, 0)   # Avatar width + gap, so it lines up with message text
        layout.setSpacing(10)
        icon_name, color = self.ICONS.get(status, self.ICONS["info"])
        icon_label = QLabel()
        IconRegistry.bind(icon_label, icon_name, color, kind="pixmap", size=15)
        icon_label.setFixedWidth(16)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        icon_label.setContentsMargins(0, 3, 0, 0)
        label = QLabel(text)
        label.setObjectName("activityText")
        label.setProperty("status", status)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(icon_label)
        layout.addWidget(label, 1)
        outer.addWidget(self.inner, 0, Qt.AlignmentFlag.AlignHCenter)

    def set_content_width(self, width: int, side_padding: int):
        self.layout().setContentsMargins(side_padding, 6, side_padding, 6)
        self.inner.setFixedWidth(width)


class ChatStream(QScrollArea):
    """Scrollable list of full-width message rows."""

    speak_requested = pyqtSignal(str)
    regenerate_requested = pyqtSignal()
    edit_requested = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setObjectName("stream")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget()
        content.setObjectName("streamContent")
        self.rows_layout = QVBoxLayout(content)
        self.rows_layout.setContentsMargins(0, 0, 0, 24)
        self.rows_layout.setSpacing(0)
        self.rows_layout.addStretch(1)
        self.setWidget(content)

        self._rows = []
        self._by_entry = {}
        self._width, self._padding = 640, 48

        self._locked = False   # True while a reply/launch is running: hides Edit/Retry/Regenerate

        # Round "scroll to bottom" button, shown when you scroll up
        self.down_button = make_icon_button("ph.arrow-down", tr("Scroll to bottom"), "scrollDownButton", 16, "text")
        self.down_button.setParent(self)
        self.down_button.setFixedSize(36, 36)
        self.down_button.clicked.connect(self.scroll_to_bottom)
        self.down_button.hide()

        self._stick_to_bottom = True
        bar = self.verticalScrollBar()
        bar.valueChanged.connect(self._on_scroll)
        bar.rangeChanged.connect(self._on_range)

    def _on_scroll(self, value: int):
        self._stick_to_bottom = value >= self.verticalScrollBar().maximum() - 48
        self._update_down_button()

    def _on_range(self, _minimum: int, maximum: int):
        if self._stick_to_bottom:
            self.verticalScrollBar().setValue(maximum)
        self._update_down_button()

    def _update_down_button(self):
        show = not self._stick_to_bottom and self.verticalScrollBar().maximum() > 0
        if show:
            self.down_button.move((self.width() - self.down_button.width()) // 2,
                                  self.height() - self.down_button.height() - 14)
            self.down_button.raise_()
        self.down_button.setVisible(show)

    def set_locked(self, locked: bool):
        self._locked = locked
        self.refresh_actions()

    def add_entry(self, entry: dict):
        kind = entry.get("type")
        if kind == "user":
            row = MessageRow("user", entry.get("text", ""), images=entry.get("images"))
            row.edit_requested.connect(self.edit_requested)
            row.regenerate_requested.connect(self.regenerate_requested)
        elif kind == "assistant":
            row = MessageRow("ai", entry.get("text", ""), final=not entry.get("streaming", False),
                             meta=entry.get("meta", ""))
            row.speak_requested.connect(self.speak_requested)
            row.regenerate_requested.connect(self.regenerate_requested)
        elif kind == "activity":
            row = ActivityRow(entry.get("status", "info"), entry.get("text", ""))
        else:
            return None
        row.set_content_width(self._width, self._padding)
        self.rows_layout.insertWidget(self.rows_layout.count() - 1, row)
        self._rows.append(row)
        self._by_entry[id(entry)] = row
        self._stick_to_bottom = True
        self.refresh_actions()
        return row

    def widget_for(self, entry: dict):
        return self._by_entry.get(id(entry))

    def remove_entry(self, entry: dict):
        row = self._by_entry.pop(id(entry), None)
        if row is not None:
            self._rows.remove(row)
            self.rows_layout.removeWidget(row)
            row.deleteLater()
            self.refresh_actions()

    def refresh_actions(self):
        """
        Regenerate: only on the latest reply. Edit: only on your latest message.
        Retry: on your latest message when no reply follows it (e.g. after an error).
        Nothing is shown while a reply or launch is running.
        """
        messages = [row for row in self._rows if isinstance(row, MessageRow)]
        latest = messages[-1] if messages else None
        latest_user = next((row for row in reversed(messages) if row.role == "user"), None)
        for row in messages:
            if row.role == "ai":
                row.set_regenerate_visible(row is latest and not self._locked)
            else:
                row.set_user_actions(edit=row is latest_user and not self._locked,
                                     retry=row is latest and not self._locked)

    def clear(self):
        for row in self._rows:
            self.rows_layout.removeWidget(row)
            row.deleteLater()
        self._rows.clear()
        self._by_entry.clear()

    def scroll_to_bottom(self):
        self._stick_to_bottom = True
        QTimer.singleShot(0, lambda: self.verticalScrollBar().setValue(self.verticalScrollBar().maximum()))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        viewport_width = self.viewport().width()
        self._padding = 16 if viewport_width < 700 else 48
        self._width = max(220, min(CHAT_COLUMN_MAX, viewport_width - 2 * self._padding))
        for row in self._rows:
            row.set_content_width(self._width, self._padding)
        self._update_down_button()


class PromptChip(QPushButton):
    """Suggested prompt button: bold label on the left, chevron on the right."""

    def __init__(self, label: str):
        super().__init__()
        self.setObjectName("promptChip")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(label)
        self.setMinimumHeight(54)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 0, 16, 0)
        text = QLabel(label)
        text.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        text.setStyleSheet("font-weight: 600; background: transparent;")
        chevron = QLabel()
        chevron.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        IconRegistry.bind(chevron, "ph.caret-right", "faint", kind="pixmap", size=15)
        layout.addWidget(text)
        layout.addStretch(1)
        layout.addWidget(chevron)


class WelcomeScreen(QWidget):
    """Empty-chat screen: sparkle tile, gradient title and four suggested prompts."""

    prompt_clicked = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(32, 32, 32, 32)
        outer.addStretch(3)

        tile_row = QHBoxLayout()
        tile_row.addStretch(1)
        tile_row.addWidget(SparkleTile(64))
        tile_row.addStretch(1)
        outer.addLayout(tile_row)
        outer.addSpacing(16)
        self.title = GradientTitle(tr("How can I help you?"), 18)
        outer.addWidget(self.title, 0, Qt.AlignmentFlag.AlignHCenter)
        outer.addSpacing(6)
        subtitle = QLabel(tr("Write code, translate, or just chat with YamanAI. "
                             "You can also ask it to open apps on your PC."))
        subtitle.setObjectName("welcomeSubtitle")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setWordWrap(True)
        self.subtitle = subtitle
        outer.addWidget(subtitle, 0, Qt.AlignmentFlag.AlignHCenter)
        outer.addSpacing(30)

        self.grid_host = QWidget()
        self.grid_host.setMaximumWidth(448)
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(12)
        self.chips = []
        for label, prompt in SUGGESTED_PROMPTS:
            chip = PromptChip(tr(label))
            chip.clicked.connect(lambda _checked=False, p=tr(prompt): self.prompt_clicked.emit(p))
            self.chips.append(chip)
        self._columns = 0
        self._arrange(2)
        outer.addWidget(self.grid_host, 0, Qt.AlignmentFlag.AlignHCenter)
        outer.addStretch(4)

    def _arrange(self, columns: int):
        if columns == self._columns:
            return
        self._columns = columns
        for chip in self.chips:
            self.grid.removeWidget(chip)
        for index, chip in enumerate(self.chips):
            self.grid.addWidget(chip, index // columns, index % columns)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._arrange(1 if self.width() < 500 else 2)
        self.grid_host.setFixedWidth(min(448, max(220, self.width() - 64)))
        # A fixed width lets the wrapped subtitle compute its real height
        width = min(440, max(220, self.width() - 64))
        self.subtitle.setFixedWidth(width)
        self.subtitle.setFixedHeight(self.subtitle.heightForWidth(width))


class ChatArea(QStackedWidget):
    """Switches between the welcome screen and the message stream."""

    prompt_clicked = pyqtSignal(str)
    speak_requested = pyqtSignal(str)
    regenerate_requested = pyqtSignal()
    edit_requested = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.welcome = WelcomeScreen()
        self.welcome.prompt_clicked.connect(self.prompt_clicked)
        self.stream = ChatStream()
        self.stream.speak_requested.connect(self.speak_requested)
        self.stream.regenerate_requested.connect(self.regenerate_requested)
        self.stream.edit_requested.connect(self.edit_requested)
        self.addWidget(self.welcome)
        self.addWidget(self.stream)

    def load(self, entries: list):
        self.stream.clear()
        for entry in entries:
            self.stream.add_entry(entry)
        self.setCurrentWidget(self.stream if entries else self.welcome)
        self.stream.scroll_to_bottom()

    def add_entry(self, entry: dict):
        self.setCurrentWidget(self.stream)
        return self.stream.add_entry(entry)

    def widget_for(self, entry: dict):
        return self.stream.widget_for(entry)

    def remove_entry(self, entry: dict):
        self.stream.remove_entry(entry)

    def refresh_actions(self):
        self.stream.refresh_actions()

    def set_locked(self, locked: bool):
        self.stream.set_locked(locked)


# =====================================================================
#  COMPOSER (the big rounded input box)
# =====================================================================
class PromptEdit(QTextEdit):
    """Borderless multi-line input that grows with its text. Enter sends, Shift+Enter = new line."""

    submitted = pyqtSignal()
    recall_requested = pyqtSignal()
    files_dropped = pyqtSignal(list)
    image_pasted = pyqtSignal(object)
    MIN_HEIGHT, MAX_HEIGHT = 36, 240

    def __init__(self):
        super().__init__()
        self.setObjectName("promptInput")
        self.setAcceptRichText(False)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setTabChangesFocus(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.document().setDocumentMargin(4)
        self.document().documentLayout().documentSizeChanged.connect(self._adjust_height)
        self.setFixedHeight(self.MIN_HEIGHT)

    def keyPressEvent(self, event):
        if (event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
                and not event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            self.submitted.emit()
            return
        if (event.key() == Qt.Key.Key_Up and not self.toPlainText()
                and event.modifiers() == Qt.KeyboardModifier.NoModifier):
            self.recall_requested.emit()     # Up in an empty box = edit the last message
            return
        super().keyPressEvent(event)

    # Dropping (or pasting) files attaches them instead of inserting their path
    def canInsertFromMimeData(self, source) -> bool:
        return source.hasUrls() or source.hasImage() or super().canInsertFromMimeData(source)

    def insertFromMimeData(self, source):
        if source.hasUrls():
            paths = [url.toLocalFile() for url in source.urls() if url.isLocalFile()]
            if paths:
                self.files_dropped.emit(paths)
                return
        if source.hasImage():            # A screenshot pasted with Ctrl+V
            image = source.imageData()
            if isinstance(image, QPixmap):
                image = image.toImage()
            if isinstance(image, QImage) and not image.isNull():
                self.image_pasted.emit(image)
                return
        super().insertFromMimeData(source)

    def _adjust_height(self, *_):
        wanted = int(self.document().size().height()) + 4
        height = max(self.MIN_HEIGHT, min(wanted, self.MAX_HEIGHT))
        self.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded if wanted > self.MAX_HEIGHT else Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        if self.height() != height:
            self.setFixedHeight(height)


class Composer(FocusFrame):
    """Input card: text, microphone and a send button that turns into Stop while replying."""

    submitted = pyqtSignal(str)
    stop_clicked = pyqtSignal()
    mic_clicked = pyqtSignal()
    attach_clicked = pyqtSignal()
    recall_requested = pyqtSignal()
    files_dropped = pyqtSignal(list)
    image_pasted = pyqtSignal(object)

    PLACEHOLDER = "Ask YamanAI anything, or type \"open discord\"..."
    MIC_PLACEHOLDERS = {
        "preparing": "Preparing the microphone...",
        "listening": "Listening... speak now",
        "processing": "Converting speech to text...",
    }

    def __init__(self):
        super().__init__()
        self.setObjectName("composer")
        self._mode = "idle"   # idle | ai (streaming, can stop) | busy (launching)
        self._images = []     # Pending image attachments (dicts from encode_image)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 12, 12, 12)
        outer.setSpacing(8)
        self.images_bar = QWidget()
        self.images_layout = QHBoxLayout(self.images_bar)
        self.images_layout.setContentsMargins(0, 0, 0, 0)
        self.images_layout.setSpacing(8)
        self.images_layout.addStretch(1)
        self.images_bar.setVisible(False)
        outer.addWidget(self.images_bar)
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        outer.addLayout(layout)

        self.edit = PromptEdit()
        self.edit.setPlaceholderText(tr(self.PLACEHOLDER))
        self.edit.submitted.connect(self._on_send)
        self.edit.textChanged.connect(self._refresh_send)
        self.edit.recall_requested.connect(self.recall_requested)
        self.edit.files_dropped.connect(self.files_dropped)
        self.edit.image_pasted.connect(self.image_pasted)
        self.watch(self.edit)
        layout.addWidget(self.edit, 1, Qt.AlignmentFlag.AlignVCenter)

        buttons = QHBoxLayout()
        buttons.setSpacing(4)
        self.attach_button = make_icon_button("ph.paperclip", tr("Attach a file or image (or drag or paste it here)"),
                                              "attachButton", 18)
        self.attach_button.setFixedSize(40, 40)
        self.attach_button.clicked.connect(self.attach_clicked)
        buttons.addWidget(self.attach_button)
        self.mic_button = make_icon_button("ph.microphone", tr("Voice input"), "micButton", 18)
        self.mic_button.setFixedSize(40, 40)
        self.mic_button.clicked.connect(self.mic_clicked)
        self.send_button = QToolButton()
        self.send_button.setObjectName("sendButton")
        self.send_button.setFixedSize(40, 40)
        self.send_button.setIconSize(QSize(18, 18))
        self.send_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.send_button.clicked.connect(self._on_send)
        buttons.addWidget(self.mic_button)
        buttons.addWidget(self.send_button)
        layout.addLayout(buttons)
        layout.setAlignment(buttons, Qt.AlignmentFlag.AlignBottom)

        self.set_mic_state("idle")
        self._refresh_send()

    def mousePressEvent(self, event):
        self.edit.setFocus()
        super().mousePressEvent(event)

    def _on_send(self):
        if self._mode == "ai":
            self.stop_clicked.emit()
            return
        text = self.edit.toPlainText().strip()
        if (text or self._images) and self._mode == "idle":
            self.submitted.emit(text)

    def text(self) -> str:
        return self.edit.toPlainText()

    def set_text(self, text: str):
        self.edit.setPlainText(text)
        cursor = self.edit.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.edit.setTextCursor(cursor)
        self.edit.setFocus()

    def clear(self):
        self.edit.clear()

    def focus(self):
        self.edit.setFocus()

    # ----- Pending images -----
    def add_image(self, image: dict) -> bool:
        if len(self._images) >= MAX_IMAGES_PER_MESSAGE:
            return False
        self._images.append(image)
        self._rebuild_images()
        return True

    def take_images(self) -> list:
        images, self._images = self._images, []
        self._rebuild_images()
        return images

    def _remove_image(self, image: dict):
        self._images = [item for item in self._images if item is not image]
        self._rebuild_images()

    def _rebuild_images(self):
        while self.images_layout.count() > 1:          # Keep the trailing stretch
            widget = self.images_layout.takeAt(0).widget()
            if widget is not None:
                widget.deleteLater()
        for index, image in enumerate(self._images):
            self.images_layout.insertWidget(index, self._image_chip(image))
        self.images_bar.setVisible(bool(self._images))
        self._refresh_send()

    def _image_chip(self, image: dict) -> QFrame:
        chip = QFrame()
        chip.setObjectName("imageChip")
        layout = QHBoxLayout(chip)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)
        thumb = QLabel()
        pixmap = pixmap_from_image(image)
        if not pixmap.isNull():
            thumb.setPixmap(pixmap.scaled(QSize(40, 40), Qt.AspectRatioMode.KeepAspectRatio,
                                          Qt.TransformationMode.SmoothTransformation))
        name = ElidedLabel(image.get("name", ""))
        name.setObjectName("imageChipName")
        name.setMaximumWidth(120)
        remove = make_icon_button("ph.x", tr("Remove"), "trashButton", 12, "muted", active="red")
        remove.clicked.connect(lambda _checked=False, img=image: self._remove_image(img))
        layout.addWidget(thumb)
        layout.addWidget(name)
        layout.addWidget(remove)
        return chip

    def insert_attachment(self, name: str, language: str, content: str):
        """Appends a file to the prompt as a fenced code block."""
        fence = "````" if "```" in content else "```"
        block = f"{name}:\n{fence}{language}\n{content.rstrip()}\n{fence}\n"
        current = self.edit.toPlainText()
        separator = "" if not current or current.endswith("\n") else "\n"
        self.set_text(current + separator + block)

    def set_mode(self, mode: str):
        self._mode = mode
        self.mic_button.setEnabled(mode == "idle")
        self._refresh_send()

    def _refresh_send(self):
        if self._mode == "ai":
            state, icon_name, color, tip = "stop", "ph.stop-circle", "red", tr("Stop generating")
        elif self._mode == "idle" and (self.edit.toPlainText().strip() or self._images):
            state, icon_name, color, tip = "ready", "ph.paper-plane-right", "#FFFFFF", tr("Send (Enter)")
        else:
            state, icon_name, color, tip = "idle", "ph.paper-plane-right", "dim", tr("Send (Enter)")
        if self.send_button.property("state") != state:
            self.send_button.setProperty("state", state)
            IconRegistry.bind(self.send_button, icon_name, color, active=color)
            repolish(self.send_button)
        self.send_button.setToolTip(tip)
        self.send_button.setAccessibleName(tip)
        self.send_button.setEnabled(state != "idle")

    def set_mic_state(self, state: str):
        self.mic_button.setProperty("state", state)
        dark = state in ("listening", "processing")
        IconRegistry.bind(self.mic_button, "ph.microphone", "#FFFFFF" if dark else "muted",
                          active="#FFFFFF" if dark else "accent_text")
        repolish(self.mic_button)
        self.edit.setPlaceholderText(tr(self.MIC_PLACEHOLDERS.get(state, self.PLACEHOLDER)))


# =====================================================================
#  HEADER & SIDEBAR
# =====================================================================
class StatusPill(QFrame):
    """'GPT-4o ● Online' pill in the middle of the header; click to switch models."""

    clicked = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setObjectName("statusPill")
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(tr("Change model"))
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(8)
        self.model_label = QLabel()
        self.model_label.setObjectName("pillModel")
        self.dot = PulseDot(6)
        self.state_label = QLabel()
        self.state_label.setObjectName("pillState")
        layout.addWidget(self.model_label)
        layout.addWidget(self.dot)
        layout.addWidget(self.state_label)

    def set_state(self, model: str, state: str, color: str):
        self.model_label.setText(model)
        self.state_label.setText(state)
        self.state_label.setStyleSheet(f"color: {color};")
        self.dot.set_color(color)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class Header(DragArea):
    """Top bar: sidebar toggle | status pill (centered) | tools + window controls. Drag to move."""

    def __init__(self):
        super().__init__()
        self.setObjectName("header")
        self.setFixedHeight(56)
        grid = QGridLayout(self)
        grid.setContentsMargins(14, 0, 0 if USE_CUSTOM_TITLEBAR else 14, 0)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(2, 1)

        left = QHBoxLayout()
        self.menu_button = make_icon_button("ph.list", tr("Show sidebar (Ctrl+B)"), size=20)
        self.menu_button.setVisible(False)
        left.addWidget(self.menu_button)
        left.addStretch(1)

        self.pill = StatusPill()

        right = QHBoxLayout()
        right.setSpacing(2)
        right.addStretch(1)
        self.tts_button = make_icon_button("ph.speaker-slash", tr("Text-to-Speech: Off"))
        self.tts_button.setCheckable(True)
        self.launch_button = make_icon_button("ph.monitor", tr("Launch an app"))
        self.launch_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.help_button = make_icon_button("ph.question", tr("Help"))
        self.settings_button = make_icon_button("ph.gear-six", tr("Settings"))
        for button in (self.tts_button, self.launch_button, self.help_button, self.settings_button):
            right.addWidget(button)

        self.window_controls = QWidget()
        controls = QHBoxLayout(self.window_controls)
        controls.setContentsMargins(10, 0, 0, 0)
        controls.setSpacing(0)
        self.min_button = WindowButton("minimize", tr("Minimize"))
        self.max_button = WindowButton("maximize", tr("Maximize"))
        self.close_button = WindowButton("close", tr("Close"))
        for button in (self.min_button, self.max_button, self.close_button):
            controls.addWidget(button, 0, Qt.AlignmentFlag.AlignTop)
        self.window_controls.setVisible(USE_CUSTOM_TITLEBAR)

        right_host = QWidget()
        right_host.setLayout(right)
        right_wrap = QHBoxLayout()
        right_wrap.setSpacing(0)
        right_wrap.addWidget(right_host, 1, Qt.AlignmentFlag.AlignVCenter)
        right_wrap.addWidget(self.window_controls, 0, Qt.AlignmentFlag.AlignTop)

        grid.addLayout(left, 0, 0)
        grid.addWidget(self.pill, 0, 1, Qt.AlignmentFlag.AlignCenter)
        grid.addLayout(right_wrap, 0, 2)

    def set_maximized(self, maximized: bool):
        self.max_button.set_maximized(maximized)
        self.max_button.setToolTip(tr("Restore") if maximized else tr("Maximize"))


class ThreadRow(QWidget):
    """Sidebar chat row: icon, title, and a delete button that appears on hover."""

    def __init__(self, thread_id: str, title: str, active: bool, busy: bool, on_delete, pinned: bool = False):
        super().__init__()
        self._on_delete = on_delete
        self._thread_id = thread_id
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 6, 0)
        layout.setSpacing(10)
        icon_label = QLabel()
        IconRegistry.bind(icon_label, "ph.push-pin" if pinned else "ph.chat-centered",
                          "accent_text" if busy or pinned else "dim", kind="pixmap", size=14)
        self.title_label = ElidedLabel(tr(title) if title == NEW_THREAD_TITLE else title)
        self.title_label.setObjectName("threadTitle")
        self.title_label.setProperty("active", active)
        self.trash = make_icon_button("ph.trash", tr("Delete chat"), "trashButton", 14, "dim", active="red")
        self.trash.setVisible(False)
        self.trash.clicked.connect(lambda: QTimer.singleShot(0, lambda: self._on_delete(self._thread_id)))
        layout.addWidget(icon_label)
        layout.addWidget(self.title_label, 1)
        layout.addWidget(self.trash)

    def enterEvent(self, event):
        self.trash.setVisible(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.trash.setVisible(False)
        super().leaveEvent(event)


class Sidebar(QFrame):
    """Left panel: brand, New chat, Launch an app, chats by date, Help and Settings."""

    new_chat_clicked = pyqtSignal()
    collapse_clicked = pyqtSignal()
    help_clicked = pyqtSignal()
    settings_clicked = pyqtSignal()
    thread_selected = pyqtSignal(str)
    thread_action = pyqtSignal(str, str)  # (thread_id, "rename" | "export" | "delete")
    search_changed = pyqtSignal(str)

    def eventFilter(self, obj, event):
        # Esc in the search box clears it instead of reaching the window shortcut
        if (obj is getattr(self, "search_input", None)
                and event.type() in (QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress)
                and event.key() == Qt.Key.Key_Escape and self.search_input.text()):
            if event.type() == QEvent.Type.ShortcutOverride:
                event.accept()          # Deliver Esc to the box, not to the window shortcut
                return True
            self.search_input.clear()
            return True
        return super().eventFilter(obj, event)

    def recolor(self):
        self._search_action.setIcon(icon("ph.magnifying-glass", "faint"))

    def __init__(self):
        super().__init__()
        self.setObjectName("sidebar")
        self._pinned_ids = set()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 10)
        layout.setSpacing(8)

        # Brand row (also drags the window)
        header = DragArea()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(2, 4, 0, 6)
        header_layout.setSpacing(10)
        header_layout.addWidget(AvatarTile("ai", 26, 7))
        brand = QLabel(APP_SHORT_NAME)
        brand.setObjectName("brandLabel")
        header_layout.addWidget(brand)
        header_layout.addStretch(1)
        self.collapse_button = make_icon_button("ph.x", tr("Hide sidebar (Ctrl+B)"), size=16)
        self.collapse_button.clicked.connect(self.collapse_clicked)
        header_layout.addWidget(self.collapse_button)
        layout.addWidget(header)

        self.new_button = QPushButton("  " + tr("New chat"))
        self.new_button.setObjectName("newChatButton")
        IconRegistry.bind(self.new_button, "ph.plus", "text")
        self.new_button.setIconSize(QSize(16, 16))
        self.new_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.new_button.clicked.connect(self.new_chat_clicked)
        layout.addWidget(self.new_button)

        self.launch_button = QPushButton("  " + tr("Launch an app"))
        self.launch_button.setObjectName("launchButton")
        IconRegistry.bind(self.launch_button, "ph.monitor", "accent_text")
        self.launch_button.setIconSize(QSize(16, 16))
        self.launch_button.setCursor(Qt.CursorShape.PointingHandCursor)
        layout.addWidget(self.launch_button)
        layout.addSpacing(2)

        self.search_input = QLineEdit()
        self.search_input.setObjectName("searchInput")
        self.search_input.setPlaceholderText(tr("Search chats (Ctrl+F)"))
        self.search_input.setClearButtonEnabled(True)
        self._search_action = self.search_input.addAction(icon("ph.magnifying-glass", "faint"),
                                                          QLineEdit.ActionPosition.LeadingPosition)
        # Debounced so typing stays smooth with many saved chats
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(150)
        self._search_timer.timeout.connect(lambda: self.search_changed.emit(self.search_input.text()))
        self.search_input.textChanged.connect(lambda _t: self._search_timer.start())
        self.search_input.installEventFilter(self)
        layout.addWidget(self.search_input)
        layout.addSpacing(2)

        self.thread_list = QListWidget()
        self.thread_list.setObjectName("threadList")
        self.thread_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.thread_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.thread_list.customContextMenuRequested.connect(self._context_menu)
        self.thread_list.currentItemChanged.connect(self._on_current_changed)
        layout.addWidget(self.thread_list, 1)
        self.empty_label = QLabel(tr("No chats yet"))
        self.empty_label.setObjectName("emptyThreads")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.empty_label.setVisible(False)
        layout.addWidget(self.empty_label)

        footer = QFrame()
        footer.setObjectName("sidebarFooter")
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(0, 10, 0, 0)
        footer_layout.setSpacing(2)
        for icon_name, text, signal in (("ph.question", "Help", self.help_clicked),
                                        ("ph.gear-six", "Settings", self.settings_clicked)):
            button = QPushButton(f"  {tr(text)}")
            button.setObjectName("navRow")
            IconRegistry.bind(button, icon_name, "muted", active="text")
            button.setIconSize(QSize(16, 16))
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(signal)
            footer_layout.addWidget(button)
        caption = QLabel(tr("{app} {version} for Windows").format(app=APP_NAME, version=APP_VERSION_LABEL))
        caption.setObjectName("sidebarCaption")
        caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        footer_layout.addSpacing(4)
        footer_layout.addWidget(caption)
        layout.addWidget(footer)

    def set_threads(self, groups, current_id, busy_id=None, searching=False):
        """Rebuilds the list with Today / Yesterday / Older headers."""
        # Keep the scroll position: the list is rebuilt after every message and once a
        # minute, which previously jumped it back to the top each time
        bar = self.thread_list.verticalScrollBar()
        scroll_position = bar.value()
        self.thread_list.blockSignals(True)
        self.thread_list.clear()
        count = 0
        self._pinned_ids = {t.id for _label, group in groups for t in group if t.pinned}
        for label, threads in groups:
            if not threads:
                continue
            header = QListWidgetItem()
            header.setFlags(Qt.ItemFlag.NoItemFlags)
            header.setSizeHint(QSize(0, 30))
            self.thread_list.addItem(header)
            header_label = QLabel(caps(tr(label)))
            header_label.setObjectName("groupLabel")
            header_label.setAlignment(Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft)
            header_label.setContentsMargins(0, 0, 0, 4)
            set_tracking(header_label, 0.8)
            self.thread_list.setItemWidget(header, header_label)
            for thread in threads:
                item = QListWidgetItem()
                item.setData(Qt.ItemDataRole.UserRole, thread.id)
                item.setSizeHint(QSize(0, 36))
                item.setToolTip(thread.title)
                self.thread_list.addItem(item)
                row = ThreadRow(thread.id, thread.title, thread.id == current_id, thread.id == busy_id,
                                lambda tid: self.thread_action.emit(tid, "delete"), pinned=thread.pinned)
                self.thread_list.setItemWidget(item, row)
                if thread.id == current_id:
                    self.thread_list.setCurrentItem(item)
                count += 1
        self.empty_label.setText(tr("No matching chats") if searching else tr("No chats yet"))
        self.empty_label.setVisible(count == 0)
        self.thread_list.blockSignals(False)
        QTimer.singleShot(0, lambda: bar.setValue(scroll_position))

    def _on_current_changed(self, current, _previous):
        if current is not None and current.data(Qt.ItemDataRole.UserRole):
            thread_id = current.data(Qt.ItemDataRole.UserRole)
            # Deferred: selecting rebuilds this list, which must not happen inside its own signal
            QTimer.singleShot(0, lambda: self.thread_selected.emit(thread_id))

    def _context_menu(self, pos):
        item = self.thread_list.itemAt(pos)
        if item is None or not item.data(Qt.ItemDataRole.UserRole):
            return
        thread_id = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        pinned = thread_id in self._pinned_ids
        menu.addAction(icon("ph.push-pin", "text"), tr("Unpin") if pinned else tr("Pin"),
                       lambda: self.thread_action.emit(thread_id, "pin"))
        menu.addAction(icon("ph.pencil-simple", "text"), tr("Rename"),
                       lambda: self.thread_action.emit(thread_id, "rename"))
        menu.addAction(icon("ph.download-simple", "text"), tr("Export as Markdown"),
                       lambda: self.thread_action.emit(thread_id, "export"))
        menu.addSeparator()
        menu.addAction(icon("ph.trash", "red"), tr("Delete"), lambda: self.thread_action.emit(thread_id, "delete"))
        menu.exec(self.thread_list.viewport().mapToGlobal(pos))


# =====================================================================
#  MODALS (in-window, with a dark backdrop like the web app)
# =====================================================================
class ModalOverlay(QWidget):
    """Dark backdrop over the window with a centered card. Click outside or Esc closes it."""

    closed = pyqtSignal()

    def __init__(self, host: QWidget, title: str, icon_name: str, max_width: int = 512):
        super().__init__(host)
        self.host = host
        self.max_width = max_width
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.hide()

        self.card = QFrame(self)
        self.card.setObjectName("modalCard")
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)

        header = QFrame()
        header.setObjectName("modalHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(24, 16, 16, 16)
        header_layout.setSpacing(10)
        title_icon = QLabel()
        IconRegistry.bind(title_icon, icon_name, "accent_text", kind="pixmap", size=19)
        title_label = QLabel(tr(title))
        title_label.setObjectName("modalTitle")
        close_button = make_icon_button("ph.x", tr("Close"), size=18)
        close_button.clicked.connect(self.close_modal)
        header_layout.addWidget(title_icon)
        header_layout.addWidget(title_label)
        header_layout.addStretch(1)
        header_layout.addWidget(close_button)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("modalScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.body = QWidget()
        self.body.setObjectName("modalBody")
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(24, 20, 24, 22)
        self.body_layout.setSpacing(22)
        self.scroll.setWidget(self.body)

        self.footer = QFrame()
        self.footer.setObjectName("modalFooter")
        self.footer_layout = QHBoxLayout(self.footer)
        self.footer_layout.setContentsMargins(24, 14, 24, 14)
        self.footer_layout.setSpacing(10)

        card_layout.addWidget(header)
        card_layout.addWidget(self.scroll)
        card_layout.addWidget(self.footer)
        self._header = header
        host.installEventFilter(self)

    def open(self):
        self.setGeometry(self.host.rect())
        self.show()
        self.raise_()
        self._place()
        self.setFocus()

    def close_modal(self):
        self.hide()
        self.closed.emit()

    def _place(self):
        width = max(300, min(self.max_width, self.width() - 32))
        self.card.setFixedWidth(width)
        self.body.setFixedWidth(width - 2)
        self.body.adjustSize()
        chrome = self._header.sizeHint().height() + self.footer.sizeHint().height() + 2
        body_height = min(self.body.sizeHint().height(), int(self.height() * 0.84) - chrome)
        self.scroll.setFixedHeight(max(120, body_height))
        self.body.setMinimumWidth(0)
        self.body.setMaximumWidth(16777215)
        self.card.adjustSize()
        self.card.move((self.width() - self.card.width()) // 2, (self.height() - self.card.height()) // 2)

    def eventFilter(self, obj, event):
        if obj is self.host and event.type() == QEvent.Type.Resize and self.isVisible():
            self.setGeometry(self.host.rect())
            self._place()
        return super().eventFilter(obj, event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 153))
        painter.end()

    def mousePressEvent(self, event):
        if not self.card.geometry().contains(event.position().toPoint()):
            self.close_modal()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close_modal()
            return
        super().keyPressEvent(event)

    # ----- Helpers for building sections -----
    @staticmethod
    def field_label(text: str, danger: bool = False) -> QLabel:
        label = QLabel(caps(tr(text)))
        label.setObjectName("dangerLabel" if danger else "fieldLabel")
        set_tracking(label, 0.8)
        return label

    @staticmethod
    def hint(text: str) -> QLabel:
        label = QLabel(tr(text))
        label.setObjectName("fieldHint")
        label.setWordWrap(True)
        return label

    def section(self, title: str, *widgets, danger: bool = False):
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self.field_label(title, danger))
        for widget in widgets:
            if isinstance(widget, QWidget):
                layout.addWidget(widget)
            else:
                layout.addLayout(widget)
        self.body_layout.addWidget(box)
        return box


class OptionButton(QPushButton):
    """Selectable option (theme, font size, model) with an optional check mark on the right."""

    def __init__(self, text: str, icon_name=None, icon_size=16, show_check=False):
        super().__init__()
        self.setObjectName("optionButton")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(tr(text))
        self.setMinimumHeight(44)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 14, 0)
        layout.setSpacing(8)
        self._icon_label = None
        self._icon_name = icon_name
        self._icon_size = icon_size
        if not show_check:
            layout.addStretch(1)
        if icon_name:
            self._icon_label = QLabel()
            self._icon_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            layout.addWidget(self._icon_label)
        self._text_label = QLabel(tr(text))
        self._text_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(self._text_label)
        layout.addStretch(1)
        self._check = None
        if show_check:
            self._check = QLabel()
            self._check.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            layout.addWidget(self._check)
        self.toggled.connect(self._refresh)
        self._refresh(False)

    def refresh_colors(self):
        """Re-applies colors after a theme change (labels use inline palette colors)."""
        self._refresh(self.isChecked())

    def _refresh(self, checked: bool):
        color = P["accent_text"] if checked else P["muted"]
        self._text_label.setStyleSheet(f"color: {color}; background: transparent; font-weight: 500;")
        if self._icon_label is not None:
            IconRegistry.bind(self._icon_label, self._icon_name, color, kind="pixmap", size=self._icon_size)
        if self._check is not None:
            if checked:
                IconRegistry.bind(self._check, "ph.check", "accent_text", kind="pixmap", size=16)
            else:
                self._check.clear()


class SettingsModal(ModalOverlay):
    """Language, theme, font size, model, local server, API key, system prompt, voice, chats."""

    saved = pyqtSignal(dict)
    connect_key_requested = pyqtSignal(str)
    export_requested = pyqtSignal()
    import_requested = pyqtSignal()
    delete_all_requested = pyqtSignal()

    def __init__(self, host: QWidget):
        super().__init__(host, "Settings", "ph.gear-six", 512)

        # Language: interface, replies, voice input
        self.ui_language_buttons = {key: OptionButton(label) for key, label in UI_LANGUAGES.items()}
        self.reply_language_buttons = {key: OptionButton(label) for key, label in REPLY_LANGUAGES.items()}
        self.speech_language_buttons = {key: OptionButton(label) for key, (label, _code) in SPEECH_LANGUAGES.items()}
        language_rows = []
        for group in (self.ui_language_buttons, self.reply_language_buttons, self.speech_language_buttons):
            row = QHBoxLayout()
            row.setSpacing(8)
            for key, button in group.items():
                button.clicked.connect(lambda _c=False, g=group, k=key: self._select(g, k))
                row.addWidget(button)
            language_rows.append(row)
        self.section("Language",
                     self.hint("Interface"), language_rows[0],
                     self.hint("Replies"), language_rows[1],
                     self.hint("Voice input"), language_rows[2],
                     self.hint("A new interface language is applied after YamanAI restarts."))

        # Theme
        self.theme_buttons = {"dark": OptionButton("Dark", "ph.moon"), "light": OptionButton("Light", "ph.sun")}
        theme_row = QHBoxLayout()
        theme_row.setSpacing(8)
        for key, button in self.theme_buttons.items():
            button.clicked.connect(lambda _c=False, k=key: self._select(self.theme_buttons, k))
            theme_row.addWidget(button)
        self.section("Theme", theme_row)

        # Font size
        self.font_buttons = {}
        font_row = QHBoxLayout()
        font_row.setSpacing(8)
        for key, size in (("sm", 12), ("base", 16), ("lg", 20)):
            button = OptionButton(FONT_SIZES[key][0], "ph.text-aa", size)
            button.clicked.connect(lambda _c=False, k=key: self._select(self.font_buttons, k))
            self.font_buttons[key] = button
            font_row.addWidget(button)
        self.section("Text size", font_row)

        # Model (+ custom OpenAI model ID)
        self.model_buttons = {}
        model_box = QVBoxLayout()
        model_box.setSpacing(8)
        for model in MODELS:
            button = OptionButton(model["label"], show_check=True)
            button.clicked.connect(lambda _c=False, k=model["id"]: self._select(self.model_buttons, k))
            self.model_buttons[model["id"]] = button
            model_box.addWidget(button)
        self.custom_model_input = QLineEdit()
        self.custom_model_input.setPlaceholderText(tr("Model ID, e.g. gpt-4.1"))
        self.custom_model_input.textEdited.connect(
            lambda text: text.strip() and self._select(self.model_buttons, "custom"))
        self.section("AI model", model_box,
                     self.hint("Custom model ID (used with \"Custom OpenAI model\"). "
                               "Pick a model that can see images if you attach pictures."),
                     self.custom_model_input)

        # Creativity (temperature)
        self.temperature_buttons = {}
        temperature_row = QHBoxLayout()
        temperature_row.setSpacing(8)
        for key, (label, _value) in TEMPERATURES.items():
            button = OptionButton(label)
            button.clicked.connect(lambda _c=False, k=key: self._select(self.temperature_buttons, k))
            self.temperature_buttons[key] = button
            temperature_row.addWidget(button)
        self.section("Creativity", temperature_row,
                     self.hint("Precise gives focused, repeatable answers (good for code). "
                               "Creative gives more varied ideas."))

        # Local model server
        local_grid = QGridLayout()
        local_grid.setHorizontalSpacing(10)
        local_grid.setVerticalSpacing(8)
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText(DEFAULT_LOCAL_BASE_URL)
        self.local_model_input = QLineEdit()
        self.local_model_input.setPlaceholderText(DEFAULT_LOCAL_MODEL)
        local_grid.addWidget(self.hint("Server URL"), 0, 0)
        local_grid.addWidget(self.url_input, 0, 1)
        local_grid.addWidget(self.hint("Model name"), 1, 0)
        local_grid.addWidget(self.local_model_input, 1, 1)
        self.section("Local model server", local_grid,
                     self.hint("Used with \"Local model\". Any OpenAI-compatible server works, "
                               "e.g. Ollama (port 11434) or LM Studio (port 1234). No API key needed."))

        # OpenAI API key
        key_row = QHBoxLayout()
        key_row.setSpacing(8)
        self.key_input = QLineEdit()
        self.key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_input.setPlaceholderText("sk-...")
        self.key_input.returnPressed.connect(self._connect_key)
        self.show_key_button = QPushButton(tr("Show"))
        self.show_key_button.setObjectName("textButton")
        self.show_key_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.show_key_button.clicked.connect(self._toggle_key)
        self.connect_button = QPushButton(tr("Connect"))
        self.connect_button.setObjectName("primaryButton")
        self.connect_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.connect_button.clicked.connect(self._connect_key)
        key_row.addWidget(self.key_input, 1)
        key_row.addWidget(self.show_key_button)
        key_row.addWidget(self.connect_button)
        self.key_status = self.hint("")
        self.section("OpenAI API key", key_row, self.key_status)

        # System prompt
        self.system_prompt_input = QPlainTextEdit()
        self.system_prompt_input.setObjectName("systemPromptInput")
        self.system_prompt_input.setPlaceholderText(tr("For example: \"You are a Python expert.\""))
        self.system_prompt_input.setFixedHeight(96)
        self.section("System prompt (optional)", self.system_prompt_input)

        # Voice
        self.tts_switch = ToggleSwitch(tr("Read replies aloud (Text-to-Speech)"))
        self.section("Voice", self.tts_switch,
                     self.hint("Voice input uses Google speech recognition and needs an internet connection."))

        # Your chats: automatic titles, export / import
        self.auto_title_switch = ToggleSwitch(tr("Name new chats automatically"))
        data_row = QHBoxLayout()
        data_row.setSpacing(8)
        export_button = QPushButton("  " + tr("Export chats"))
        export_button.setObjectName("optionButton")
        IconRegistry.bind(export_button, "ph.download-simple", "muted")
        export_button.setCursor(Qt.CursorShape.PointingHandCursor)
        export_button.clicked.connect(self.export_requested)
        import_button = QPushButton("  " + tr("Import chats"))
        import_button.setObjectName("optionButton")
        IconRegistry.bind(import_button, "ph.upload-simple", "muted")
        import_button.setCursor(Qt.CursorShape.PointingHandCursor)
        import_button.clicked.connect(self.import_requested)
        data_row.addWidget(export_button, 1)
        data_row.addWidget(import_button, 1)
        self.section("Your chats", self.auto_title_switch, data_row)

        # Danger zone
        self.delete_button = QPushButton()
        self.delete_button.setObjectName("dangerButton")
        self.delete_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.delete_button.clicked.connect(self._delete_clicked)
        self._reset_delete()
        self.section("Danger zone", self.delete_button, danger=True)

        # Footer
        self.footer_layout.addStretch(1)
        cancel = QPushButton(tr("Cancel"))
        cancel.setObjectName("textButton")
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.clicked.connect(self.close_modal)
        save = QPushButton(tr("Save"))
        save.setObjectName("primaryButton")
        save.setCursor(Qt.CursorShape.PointingHandCursor)
        save.clicked.connect(self._save)
        self.footer_layout.addWidget(cancel)
        self.footer_layout.addWidget(save)

    def _option_groups(self):
        return (self.ui_language_buttons, self.reply_language_buttons, self.speech_language_buttons,
                self.theme_buttons, self.font_buttons, self.model_buttons, self.temperature_buttons)

    @staticmethod
    def _select(buttons: dict, key: str):
        for name, button in buttons.items():
            button.setChecked(name == key)

    @staticmethod
    def _selected(buttons: dict, default: str) -> str:
        return next((name for name, button in buttons.items() if button.isChecked()), default)

    def load(self, prefs: dict, api_key: str):
        self._select(self.ui_language_buttons, prefs["ui_language"])
        self._select(self.reply_language_buttons, prefs["reply_language"])
        self._select(self.speech_language_buttons, prefs["speech_language"])
        self._select(self.theme_buttons, prefs["theme"])
        self._select(self.font_buttons, prefs["font_size"])
        self._select(self.model_buttons, prefs["model_id"])
        self._select(self.temperature_buttons, prefs["temperature"])
        for group in self._option_groups():
            for button in group.values():
                button.refresh_colors()     # Colors were stale after switching theme
        self.custom_model_input.setText(prefs["custom_model"])
        self.url_input.setText(prefs["local_base_url"])
        self.local_model_input.setText(prefs["local_model"])
        self.system_prompt_input.setPlainText(prefs["system_prompt"])
        self.tts_switch.setChecked(prefs["tts"])
        self.auto_title_switch.setChecked(prefs["auto_title"])
        self.key_input.setText(api_key)
        self.set_key_status(tr("A key is saved.") if api_key else tr("No key saved yet."),
                            P["green_text"] if api_key else P["faint"])
        self._reset_delete()

    def values(self) -> dict:
        return {
            "ui_language": self._selected(self.ui_language_buttons, UI_LANG),
            "reply_language": self._selected(self.reply_language_buttons, "auto"),
            "speech_language": self._selected(self.speech_language_buttons, UI_LANG),
            "theme": self._selected(self.theme_buttons, "dark"),
            "font_size": self._selected(self.font_buttons, DEFAULT_FONT_SIZE),
            "model_id": self._selected(self.model_buttons, DEFAULT_MODEL_ID),
            "temperature": self._selected(self.temperature_buttons, DEFAULT_TEMPERATURE),
            "api_key": self.key_input.text().strip(),
            "custom_model": self.custom_model_input.text().strip(),
            "local_base_url": self.url_input.text().strip() or DEFAULT_LOCAL_BASE_URL,
            "local_model": self.local_model_input.text().strip() or DEFAULT_LOCAL_MODEL,
            "system_prompt": self.system_prompt_input.toPlainText().strip(),
            "tts": self.tts_switch.isChecked(),
            "auto_title": self.auto_title_switch.isChecked(),
        }

    def set_key_status(self, text: str, color: str):
        self.key_status.setText(text)
        self.key_status.setStyleSheet(f"color: {color};")

    def set_connecting(self, connecting: bool):
        self.connect_button.setEnabled(not connecting)

    def _toggle_key(self):
        hidden = self.key_input.echoMode() == QLineEdit.EchoMode.Password
        self.key_input.setEchoMode(QLineEdit.EchoMode.Normal if hidden else QLineEdit.EchoMode.Password)
        self.show_key_button.setText(tr("Hide") if hidden else tr("Show"))

    def _connect_key(self):
        self.connect_key_requested.emit(self.key_input.text().strip())

    def _delete_clicked(self):
        if self.delete_button.property("confirm"):
            self._reset_delete()
            self.delete_all_requested.emit()
        else:
            self.delete_button.setProperty("confirm", True)
            self.delete_button.setText(tr("Are you sure? Click again"))
            self.delete_button.setIcon(QIcon())
            repolish(self.delete_button)

    def _reset_delete(self):
        self.delete_button.setProperty("confirm", False)
        self.delete_button.setText("  " + tr("Delete all chats"))
        IconRegistry.bind(self.delete_button, "ph.trash", "red")
        repolish(self.delete_button)

    def _save(self):
        self.saved.emit(self.values())
        self.close_modal()


class HelpModal(ModalOverlay):
    """What YamanAI can do; clicking an example puts it in the input box."""

    example_chosen = pyqtSignal(str)

    def __init__(self, host: QWidget):
        super().__init__(host, "Help", "ph.question", 540)
        self._label = QLabel()
        self._label.setObjectName("helpBody")
        self._label.setTextFormat(Qt.TextFormat.RichText)
        self._label.setWordWrap(True)
        self._label.linkActivated.connect(self._on_link)
        self.body_layout.addWidget(self._label)
        self.footer_layout.addWidget(self.hint("Click an example to put it in the input box."), 1)
        close_button = QPushButton(tr("Close"))
        close_button.setObjectName("primaryButton")
        close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        close_button.clicked.connect(self.close_modal)
        self.footer_layout.addWidget(close_button)

    def open(self):
        self._label.setText(self._content())  # Rebuilt so colors follow the theme
        super().open()

    @staticmethod
    def _sections_en():
        kb = MAX_ATTACHMENT_BYTES // 1000
        return [
            ("Chat", "Ask questions, write code, translate or brainstorm.",
             ["Explain how a VPN works", "Write a Python script that renames files"]),
            ("Built-in apps", "Open instantly, without contacting the AI.",
             ["open calculator", "open notepad", "task manager", "open cmd"]),
            ("Apps and websites", "Desktop app first, web version as a fallback.",
             ["open discord", "open spotify", "open whatsapp", "open steam", "open youtube"]),
            ("Any program or file", "Searches PATH, App Paths, the Start Menu and Program Files.",
             ["open sample.exe", "open obs", "open C:/Windows/notepad.exe"]),
            ("Windows tools and folders", "Folders open in File Explorer.",
             ["open downloads", "open documents", "open file explorer", "open windows settings",
              "open control panel", "open paint", "open recycle bin", "lock my computer"]),
            ("Websites", "Any web address after open / launch opens in your browser.",
             ["open github.com", "open wikipedia.org"]),
            ("Files and images", "Click the paperclip, drag a file onto the input box or paste a screenshot "
                                 f"with Ctrl+V. Text and code files go into your prompt (up to {kb} KB). "
                                 "Images are sent to the model, so use one that can see images "
                                 "(GPT-4o can).", []),
            ("Fix a message", "Use the pencil under your last message to edit and resend it. "
                              "Press Up in an empty box to reuse your last message. "
                              "The circular arrow retries after an error.", []),
            ("Chats", "Right-click a chat to pin, rename or export it. New chats get a short title "
                      "automatically (you can turn this off in Settings).", []),
            ("Voice", "Click the microphone and speak. The voice input language is chosen in "
                      "Settings > Language. Turn on the speaker icon in the header to hear replies.", []),
            ("Shortcuts", "Enter sends, Shift+Enter adds a line, Up recalls your last message, "
                          "Ctrl+V pastes a screenshot, Ctrl+N new chat, Ctrl+L focus the input, "
                          "Ctrl+B sidebar, Ctrl+F search chats, Ctrl+Shift+R regenerate / retry, "
                          "Ctrl+Shift+C copy the last reply, Ctrl+= / Ctrl+- / Ctrl+0 text size, "
                          "Esc stops a reply, F11 full screen.", []),
        ]

    @staticmethod
    def _sections_tr():
        kb = MAX_ATTACHMENT_BYTES // 1000
        return [
            ("Sohbet", "Soru sor, kod yazdır, çeviri yap ya da fikir üret.",
             ["VPN nasıl çalışır, açıkla", "Dosyaları yeniden adlandıran bir Python betiği yaz"]),
            ("Hazır uygulamalar", "Yapay zekâya sormadan anında açılır.",
             ["hesap makinesini aç", "not defterini aç", "görev yöneticisi", "komut istemini aç"]),
            ("Uygulamalar ve web siteleri", "Önce masaüstü uygulaması denenir, yoksa web sürümü açılır.",
             ["discord'u aç", "spotify'ı aç", "whatsapp'ı aç", "steam'i aç", "youtube'u aç"]),
            ("Herhangi bir program veya dosya", "PATH, App Paths, Başlat menüsü ve Program Files içinde aranır.",
             ["sample.exe'yi aç", "obs'yi aç", "C:/Windows/notepad.exe aç"]),
            ("Windows araçları ve klasörler", "Klasörler Dosya Gezgini'nde açılır.",
             ["indirilenleri aç", "belgelerimi aç", "dosya gezginini aç", "windows ayarlarını aç",
              "denetim masasını aç", "paint'i aç", "geri dönüşüm kutusunu aç", "bilgisayarı kilitle"]),
            ("Web siteleri", "\"aç\" ya da \"başlat\" ile birlikte yazılan her web adresi tarayıcıda açılır.",
             ["github.com'u aç", "wikipedia.org'u aç"]),
            ("Dosyalar ve görseller", "Ataç düğmesine tıkla, dosyayı yazı kutusuna sürükle ya da Ctrl+V ile "
                                      f"ekran görüntüsü yapıştır. Metin ve kod dosyaları mesajına eklenir (en fazla "
                                      f"{kb} KB). Görseller modele gönderilir; görsel görebilen bir model seç "
                                      "(GPT-4o görebilir).", []),
            ("Mesajı düzelt", "Son mesajını düzenleyip yeniden göndermek için altındaki kaleme tıkla. "
                              "Boş kutuda Yukarı ok tuşu son mesajını geri getirir. "
                              "Dairesel ok, hatadan sonra yeniden dener.", []),
            ("Sohbetler", "Sabitlemek, yeniden adlandırmak veya dışa aktarmak için sohbete sağ tıkla. "
                          "Yeni sohbetlere otomatik kısa bir başlık verilir (Ayarlar'dan kapatılabilir).", []),
            ("Ses", "Mikrofona tıkla ve konuş. Sesli giriş dili Ayarlar > Dil bölümünden seçilir. "
                    "Cevapları dinlemek için üst çubuktaki hoparlör simgesini aç.", []),
            ("Kısayollar", "Enter gönderir, Shift+Enter yeni satır ekler, Yukarı ok son mesajı geri getirir, "
                           "Ctrl+V ekran görüntüsü yapıştırır, Ctrl+N yeni sohbet, Ctrl+L yazı kutusu, "
                           "Ctrl+B kenar çubuğu, Ctrl+F sohbet ara, Ctrl+Shift+R yeniden oluştur / dene, "
                           "Ctrl+Shift+C son cevabı kopyala, Ctrl+= / Ctrl+- / Ctrl+0 yazı boyutu, "
                           "Esc cevabı durdurur, F11 tam ekran.", []),
        ]

    @classmethod
    def _content(cls) -> str:
        def example(text):
            return (f'<a href="run:{html.escape(text)}" style="color:{P["accent_text"]}; text-decoration:none;">'
                    f'{html.escape(text)}</a>')

        def section(heading, description, examples):
            items = "&nbsp;&nbsp;&nbsp;".join(example(e) for e in examples)
            return (f'<p style="margin:0 0 3px 0; font-weight:700; color:{P["text"]};">{heading}</p>'
                    f'<p style="margin:0 0 5px 0; color:{P["muted"]};">{description}</p>'
                    f'<p style="margin:0 0 16px 0;">{items}</p>')

        sections = cls._sections_tr() if UI_LANG == "tr" else cls._sections_en()
        return "".join(section(*parts) for parts in sections)

    def _on_link(self, link: str):
        if link.startswith("run:"):
            self.example_chosen.emit(html.unescape(link[4:]))
            self.close_modal()


# =====================================================================
#  MAIN WINDOW
# =====================================================================
class MainPanel(QFrame):
    """Right-hand panel; reports its width so the input box can follow."""

    resized = pyqtSignal(int)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.resized.emit(self.width())


class MainWindow(QMainWindow):
    """Connects the web-style UI to the commands, AI and voice workers."""

    QUICK_ICONS = {
        "Calculator": "ph.calculator", "Notepad": "ph.notepad", "Task Manager": "ph.chart-line",
        "Command Prompt": "ph.terminal-window", "Discord": "ph.chat-circle-dots",
        "WhatsApp": "ph.chat-circle", "Spotify": "ph.music-notes", "Steam": "ph.game-controller",
        "YouTube": "ph.youtube-logo", "Chrome": "ph.globe",
        "Paint": "ph.paint-brush", "Snipping Tool": "ph.scissors", "File Explorer": "ph.folder-open",
        "Downloads": "ph.download-simple", "Documents": "ph.file-text", "Desktop folder": "ph.folder",
        "Windows Settings": "ph.gear-six", "Control Panel": "ph.sliders",
        "Lock computer": "ph.lock", "Recycle Bin": "ph.trash",
    }

    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        if USE_CUSTOM_TITLEBAR:
            self.setWindowFlags(
                Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowMinMaxButtonsHint | Qt.WindowType.WindowSystemMenuHint
            )
        self.setMinimumSize(560, 480)

        # Preferences first: the theme must be active before widgets are created
        self.settings = QSettings(ORG_NAME, SETTINGS_APP_NAME)
        self.api_key = ""
        self.prefs = self._load_prefs()
        apply_theme(self.prefs["theme"])
        self._apply_stylesheet()

        self.command_handler = WindowsCommandHandler()
        self.store = ThreadStore()
        self.threads = [t for t in self.store.load() if not t.is_empty()]
        self.current_thread = None

        self.ai_worker = None
        self.key_worker = None
        self.launch_worker = None
        self.stt_worker = None
        self.tts_worker = None
        self._retired_workers = set()
        self._busy = False
        self._busy_mode = None
        self._busy_thread = None
        self._live_entry = None
        self._search_entry = None      # "Searching for X..." row of the running launch
        self._launch_request = None
        self._pending_ai = None        # (thread, text) to send to the AI after a failed app search
        self._sidebar_auto_hidden = False
        self._was_narrow = False
        self._search_query = ""
        self._ai_started = 0.0
        self._ai_label = ""
        self._restart_requested = False
        self._title_workers = set()

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(400)
        self._save_timer.timeout.connect(lambda: self.store.save(self.threads))

        self._build_ui()
        self._setup_shortcuts()
        self._fit_to_screen()
        self._restore_window_state()

        if not self.threads:
            self.threads.append(ChatThread())
        self.threads.sort(key=lambda t: t.updated, reverse=True)
        self.select_thread(self.threads[0].id)
        if self.prefs["tts"]:
            self.set_tts_enabled(True)
        self._refresh_status()

        self._clock = QTimer(self)
        self._clock.setInterval(60_000)
        self._clock.timeout.connect(self.refresh_thread_list)  # Moves chats into Yesterday / Older
        self._clock.start()

    # =================================================================
    #  PREFERENCES & APPEARANCE
    # =================================================================
    def _load_prefs(self) -> dict:
        self.secrets = SecretStore(self.settings)
        self.api_key = self.secrets.load()
        model_id = self.settings.value("model_id", DEFAULT_MODEL_ID, type=str)
        if not any(m["id"] == model_id for m in MODELS):
            model_id = DEFAULT_MODEL_ID
        theme = self.settings.value("theme", "dark", type=str)
        font_size = self.settings.value("font_size", DEFAULT_FONT_SIZE, type=str)
        temperature = self.settings.value("temperature", DEFAULT_TEMPERATURE, type=str)
        reply = self.settings.value("reply_language", "auto", type=str)
        speech = self.settings.value("speech_language", UI_LANG, type=str)
        return {
            "temperature": temperature if temperature in TEMPERATURES else DEFAULT_TEMPERATURE,
            "theme": theme if theme in THEMES else "dark",
            "font_size": font_size if font_size in FONT_SIZES else DEFAULT_FONT_SIZE,
            "model_id": model_id,
            "system_prompt": self.settings.value("system_prompt", "", type=str),
            "tts": self.settings.value("tts_enabled", False, type=bool),
            "local_base_url": self.settings.value("local_base_url", DEFAULT_LOCAL_BASE_URL, type=str),
            "local_model": self.settings.value("local_model", DEFAULT_LOCAL_MODEL, type=str),
            "custom_model": self.settings.value("custom_model", DEFAULT_CUSTOM_MODEL, type=str),
            "ui_language": UI_LANG,
            "reply_language": reply if reply in REPLY_LANGUAGES else "auto",
            "speech_language": speech if speech in SPEECH_LANGUAGES else UI_LANG,
            "auto_title": self.settings.value("auto_title", True, type=bool),
        }

    def _save_prefs(self):
        values = self.prefs
        self.settings.setValue("theme", values["theme"])
        self.settings.setValue("font_size", values["font_size"])
        self.settings.setValue("model_id", values["model_id"])
        self.settings.setValue("temperature", values["temperature"])
        self.settings.setValue("system_prompt", values["system_prompt"])
        self.settings.setValue("tts_enabled", values["tts"])
        self.settings.setValue("local_base_url", values["local_base_url"])
        self.settings.setValue("local_model", values["local_model"])
        self.settings.setValue("custom_model", values["custom_model"])
        self.settings.setValue("ui_language", values["ui_language"])
        self.settings.setValue("reply_language", values["reply_language"])
        self.settings.setValue("speech_language", values["speech_language"])
        self.settings.setValue("auto_title", values["auto_title"])

    def _apply_stylesheet(self):
        QApplication.instance().setStyleSheet(build_stylesheet(FONT_SIZES[self.prefs["font_size"]][1]))

    def apply_appearance(self):
        """Re-applies theme colors and text size everywhere."""
        apply_theme(self.prefs["theme"])
        self._apply_stylesheet()
        IconRegistry.refresh()
        self.sidebar.recolor()
        if self.current_thread is not None:
            self.chat.load(self.current_thread.entries)   # Re-renders messages in the new colors
        self.refresh_thread_list()
        self._refresh_status()
        self._set_tts_button(self.prefs["tts"])
        for widget in self.findChildren(QWidget):
            widget.update()

    @property
    def current_model(self) -> dict:
        return next((m for m in MODELS if m["id"] == self.prefs["model_id"]), MODELS[0])

    def set_model(self, model_id: str):
        self.prefs["model_id"] = model_id
        self._save_prefs()
        self._refresh_status()

    # =================================================================
    #  UI SETUP
    # =================================================================
    def _build_ui(self):
        self.frame = ResizableFrame(self)
        self.setCentralWidget(self.frame)
        self.frame_layout = QVBoxLayout(self.frame)
        margin = ResizableFrame.MARGIN if USE_CUSTOM_TITLEBAR else 0
        self.frame_layout.setContentsMargins(margin, margin, margin, margin)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setHandleWidth(1)
        self.splitter.setChildrenCollapsible(False)

        self.sidebar = Sidebar()
        self.sidebar.setMinimumWidth(220)
        self.sidebar.setMaximumWidth(360)

        self.main_panel = MainPanel()
        self.main_panel.setObjectName("mainPanel")
        main_layout = QVBoxLayout(self.main_panel)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.header = Header()
        self.chat = ChatArea()

        # Input box + footer note, centered (max 896 px like the web app)
        self.composer_host = QWidget()
        host_layout = QVBoxLayout(self.composer_host)
        host_layout.setContentsMargins(16, 6, 16, 18)
        host_layout.setSpacing(10)
        self.composer_host_layout = host_layout
        self.composer = Composer()
        self.footer_note = QLabel()
        self.footer_note.setObjectName("footerNote")
        self.footer_note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        set_tracking(self.footer_note, 1.4)
        host_layout.addWidget(self.composer, 0, Qt.AlignmentFlag.AlignHCenter)
        host_layout.addWidget(self.footer_note)

        main_layout.addWidget(self.header)
        main_layout.addWidget(self.chat, 1)
        main_layout.addWidget(self.composer_host)

        self.splitter.addWidget(self.sidebar)
        self.splitter.addWidget(self.main_panel)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([SIDEBAR_WIDTH, 1000])
        self.frame_layout.addWidget(self.splitter)

        # Modals live on top of the whole window
        self.settings_modal = SettingsModal(self.frame)
        self.help_modal = HelpModal(self.frame)

        # Menus
        self.header.launch_button.setMenu(self._build_quick_menu(self.header.launch_button))
        self.sidebar.launch_button.setMenu(self._build_quick_menu(self.sidebar.launch_button))

        # Signals
        self.sidebar.new_chat_clicked.connect(self.new_thread)
        self.sidebar.collapse_clicked.connect(lambda: self.set_sidebar_visible(False, manual=True))
        self.sidebar.help_clicked.connect(self.help_modal.open)
        self.sidebar.settings_clicked.connect(self.open_settings)
        self.sidebar.thread_selected.connect(self.select_thread)
        self.sidebar.thread_action.connect(self._on_thread_action)
        self.sidebar.search_changed.connect(self._on_search)
        self.header.menu_button.clicked.connect(lambda: self.set_sidebar_visible(True, manual=True))
        self.header.pill.clicked.connect(self._show_model_menu)
        self.header.tts_button.clicked.connect(lambda checked: self.set_tts_enabled(checked))
        self.header.help_button.clicked.connect(self.help_modal.open)
        self.header.settings_button.clicked.connect(self.open_settings)
        self.header.min_button.clicked.connect(self.showMinimized)
        self.header.max_button.clicked.connect(self._toggle_maximized)
        self.header.close_button.clicked.connect(self.close)
        self.chat.prompt_clicked.connect(self.composer.set_text)
        self.chat.speak_requested.connect(self.speak_now)
        self.chat.regenerate_requested.connect(self.regenerate_last)
        self.chat.edit_requested.connect(self.edit_last_message)
        self.composer.recall_requested.connect(self._recall_last_message)
        self.composer.attach_clicked.connect(self._choose_attachments)
        self.composer.files_dropped.connect(self.attach_files)
        self.composer.image_pasted.connect(self.attach_qimage)
        self.composer.submitted.connect(self.send_text)
        self.composer.stop_clicked.connect(self.stop_generation)
        self.composer.mic_clicked.connect(self.start_listening)
        self.main_panel.resized.connect(self._on_main_resized)
        self.settings_modal.saved.connect(self._on_settings_saved)
        self.settings_modal.connect_key_requested.connect(self.save_api_key)
        self.settings_modal.export_requested.connect(self.export_all)
        self.settings_modal.import_requested.connect(self.import_chats)
        self.settings_modal.delete_all_requested.connect(self.delete_all_threads)
        self.help_modal.example_chosen.connect(self.composer.set_text)

    def _setup_shortcuts(self):
        QShortcut(QKeySequence("F11"), self, activated=self.toggle_fullscreen)
        QShortcut(QKeySequence("Escape"), self, activated=self._on_escape)
        QShortcut(QKeySequence("Ctrl+N"), self, activated=self.new_thread)
        QShortcut(QKeySequence("Ctrl+F"), self, activated=self.focus_search)
        QShortcut(QKeySequence("Ctrl+Shift+R"), self, activated=self.regenerate_last)
        QShortcut(QKeySequence("Ctrl+L"), self, activated=self.composer.focus)
        QShortcut(QKeySequence("Ctrl+Shift+C"), self, activated=self.copy_last_reply)
        for keys, step in (("Ctrl+=", 1), ("Ctrl++", 1), ("Ctrl+-", -1), ("Ctrl+0", 0)):
            QShortcut(QKeySequence(keys), self, activated=lambda s=step: self.change_font_size(s))
        QShortcut(QKeySequence("Ctrl+B"), self,
                  activated=lambda: self.set_sidebar_visible(not self.sidebar.isVisible(), manual=True))

    def _build_quick_menu(self, parent) -> QMenu:
        menu = QMenu(parent)
        for command in self.command_handler.commands:
            menu.addAction(icon(self.QUICK_ICONS.get(command["name"], "ph.app-window"), "text"),
                           tr(command["name"]), lambda cmd=command: self._run_quick_command(cmd))
        menu.addSeparator()
        menu.addAction(icon("ph.folder-open", "text"), tr("Open file or program…"), self._open_file_dialog)
        menu.aboutToShow.connect(lambda m=menu: self._recolor_menu(m))
        return menu

    def _recolor_menu(self, menu: QMenu):
        for action, command in zip(menu.actions(), self.command_handler.commands):
            action.setIcon(icon(self.QUICK_ICONS.get(command["name"], "ph.app-window"), "text"))
        menu.actions()[-1].setIcon(icon("ph.folder-open", "text"))

    def _show_model_menu(self):
        menu = QMenu(self)
        for model in MODELS:
            action = QAction(tr(model["label"]), menu, checkable=True)
            action.setChecked(model["id"] == self.prefs["model_id"])
            action.triggered.connect(lambda _c=False, mid=model["id"]: self.set_model(mid))
            menu.addAction(action)
        pill = self.header.pill
        menu.exec(pill.mapToGlobal(QPoint(0, pill.height() + 6)))

    def _fit_to_screen(self):
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            self.resize(1240, 800)
            return
        area = screen.availableGeometry()
        width, height = min(1280, int(area.width() * 0.85)), min(820, int(area.height() * 0.85))
        self.resize(width, height)
        self.move(area.x() + (area.width() - width) // 2, area.y() + (area.height() - height) // 2)

    # =================================================================
    #  SETTINGS MODAL
    # =================================================================
    def open_settings(self):
        self.settings_modal.load(self.prefs, self.api_key)
        self.settings_modal.open()

    def _on_settings_saved(self, values: dict):
        # A key typed into the box is saved with "Save" too (previously only "Connect" saved it)
        key = values.pop("api_key", self.api_key)
        if key != self.api_key:
            if key:
                self.save_api_key(key)
            else:
                self.api_key = ""
                self.secrets.delete()
        appearance_changed = (values["theme"] != self.prefs["theme"]
                              or values["font_size"] != self.prefs["font_size"])
        tts_changed = values["tts"] != self.prefs["tts"]
        language_changed = values["ui_language"] != self.prefs["ui_language"]
        self.prefs.update(values)
        self._save_prefs()
        if tts_changed:
            self.set_tts_enabled(values["tts"])
        if appearance_changed:
            self.apply_appearance()
        self._refresh_status()
        if language_changed:
            QTimer.singleShot(0, self._offer_restart)

    def _offer_restart(self):
        """The interface language is applied at start-up; asked in the newly chosen language."""
        texts = {
            "tr": ("Yeniden başlat", "Dil değişikliği için YamanAI yeniden başlatılmalı. Şimdi yeniden başlatılsın mı?"),
            "en": ("Restart", "YamanAI needs to restart to change the language. Restart now?"),
        }
        title, question = texts.get(self.prefs["ui_language"], texts["en"])
        if QMessageBox.question(self, title, question) == QMessageBox.StandardButton.Yes:
            self._restart_requested = True
            self.close()

    def save_api_key(self, key: str):
        modal = self.settings_modal
        if not key:
            modal.set_key_status(tr("Please enter your API Key first!"), P["amber"])
            return
        if not OPENAI_AVAILABLE:
            modal.set_key_status(tr("The openai library is not installed. Run: pip install openai"), P["red"])
            return
        self.api_key = key
        self.secrets.save(key)
        note = "" if key.startswith("sk-") else " " + tr("(OpenAI keys usually start with \"sk-\")")
        modal.set_key_status(tr("Verifying...") + note, P["amber"])
        modal.set_connecting(True)
        self.key_worker = KeyValidationWorker(key, self)
        self.key_worker.validated.connect(self._on_key_validated)
        self.key_worker.finished.connect(self.key_worker.deleteLater)
        self.key_worker.start()

    def _on_key_validated(self, ok: bool, message: str, is_auth_error: bool):
        # Ignore results from an older check: pressing Connect twice used to let a slow
        # first check (old key) report "invalid" and delete the new, valid key
        if self.sender() is not self.key_worker:
            return
        self.key_worker = None
        modal = self.settings_modal
        modal.set_connecting(False)
        if ok:
            text = (tr("Connected. Your API Key is saved in Windows Credential Manager and working.")
                    if self.secrets.secure else
                    tr("Connected. Your API Key is saved in the app settings and working."))
            color = P["green_text"]
        elif is_auth_error:
            self.api_key = ""
            self.secrets.delete()
            text, color = tr("Invalid API Key. Enter a valid key and connect again."), P["red"]
        else:
            text, color = tr("Key saved but could not be verified ({error}).").format(error=message), P["amber"]
        modal.set_key_status(text, color)
        if not modal.isVisible() and not ok and self.current_thread is not None:
            # Settings was closed with "Save": tell the user in the chat instead
            self._append(self.current_thread, {"type": "activity",
                                               "status": "error" if is_auth_error else "info", "text": text})
        self._refresh_status()

    # =================================================================
    #  THREADS
    # =================================================================
    def _thread_by_id(self, thread_id):
        return next((t for t in self.threads if t.id == thread_id), None)

    def refresh_thread_list(self):
        busy_id = self._busy_thread.id if self._busy_thread is not None else None
        current_id = self.current_thread.id if self.current_thread else None
        query = self._search_query
        threads = [t for t in self.threads if not query or self._matches(t, query)]
        self.sidebar.set_threads(group_by_date(threads), current_id, busy_id, searching=bool(query))

    @staticmethod
    def _matches(thread: ChatThread, query: str) -> bool:
        """Every word of the query must appear in the title or in a message."""
        haystack = (thread.title + "\n" + "\n".join(e.get("text", "") for e in thread.entries)).casefold()
        return all(word in haystack for word in query.casefold().split())

    def _on_search(self, text: str):
        self._search_query = text.strip()
        self.refresh_thread_list()

    def _schedule_save(self):
        self._save_timer.start()

    def new_thread(self):
        if self.current_thread is not None and self.current_thread.is_empty():
            self.composer.focus()
            return
        thread = ChatThread()
        self.threads.insert(0, thread)
        self.select_thread(thread.id)

    def select_thread(self, thread_id: str):
        thread = self._thread_by_id(thread_id)
        if thread is None:
            return
        previous = self.current_thread
        if (previous is not None and previous is not thread and previous.is_empty()
                and previous is not self._busy_thread and previous in self.threads):
            self.threads.remove(previous)  # Don't keep empty chats around
            self._schedule_save()
        self.current_thread = thread
        self.chat.load(thread.entries)
        self.refresh_thread_list()
        self.composer.focus()

    def _on_thread_action(self, thread_id: str, action: str):
        if action == "rename":
            self.rename_thread(thread_id)
        elif action == "export":
            self.export_thread(thread_id)
        elif action == "delete":
            self.delete_thread(thread_id)
        elif action == "pin":
            self.toggle_pin(thread_id)

    def toggle_pin(self, thread_id: str):
        thread = self._thread_by_id(thread_id)
        if thread is None or thread.is_empty():
            return
        thread.pinned = not thread.pinned
        self.refresh_thread_list()
        self._schedule_save()

    def rename_thread(self, thread_id: str):
        thread = self._thread_by_id(thread_id)
        if thread is None:
            return
        title, ok = QInputDialog.getText(self, tr("Rename chat"), tr("Chat name:"), text=thread.title)
        if ok and title.strip():
            thread.title = title.strip()
            thread.renamed = True
            self.refresh_thread_list()
            self._schedule_save()

    def delete_thread(self, thread_id: str):
        thread = self._thread_by_id(thread_id)
        if thread is None:
            return
        if self._busy and thread is self._busy_thread:
            self.stop_generation()
        self.threads.remove(thread)
        if not self.threads:
            self.threads.append(ChatThread())
        if thread is self.current_thread:
            self.current_thread = None
            self.select_thread(self.threads[0].id)
        else:
            self.refresh_thread_list()
        self._schedule_save()

    def delete_all_threads(self):
        if self._busy:
            self.stop_generation()
        self.threads = [ChatThread()]
        self.current_thread = None
        self.select_thread(self.threads[0].id)
        self.store.save(self.threads)

    def export_thread(self, thread_id: str):
        thread = self._thread_by_id(thread_id)
        if thread is None or thread.is_empty():
            return
        safe_name = re.sub(r"[^\w\- ]+", "", thread.title).strip() or "chat"
        path, _ = QFileDialog.getSaveFileName(self, tr("Export chat"),
                                              os.path.join(os.path.expanduser("~"), f"{safe_name}.md"),
                                              "Markdown (*.md);;Text (*.txt)")
        if path:
            try:
                with open(path, "w", encoding="utf-8") as file:
                    file.write(thread.to_markdown())
            except OSError as exc:
                QMessageBox.warning(self, tr("Export failed"), str(exc))

    def export_all(self):
        default = os.path.join(os.path.expanduser("~"), f"yamanai-{datetime.now():%Y-%m-%d}.json")
        path, _ = QFileDialog.getSaveFileName(self, tr("Export chats"), default, "JSON (*.json)")
        if path:
            try:
                with open(path, "w", encoding="utf-8") as file:
                    json.dump([t.to_dict() for t in self.threads if not t.is_empty()], file,
                              ensure_ascii=False, indent=2)
            except OSError as exc:
                QMessageBox.warning(self, tr("Export failed"), str(exc))

    def import_chats(self):
        """Adds chats from an "Export chats" file (or a threads.json backup). Existing chats are kept."""
        path, _ = QFileDialog.getOpenFileName(self, tr("Import chats"), os.path.expanduser("~"),
                                              "JSON (*.json);;All files (*)")
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as file:
                data = json.load(file)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, tr("Import failed"), tr("Could not read this file:\n{error}").format(error=exc))
            return
        items = data.get("threads") if isinstance(data, dict) else data
        if not isinstance(items, list):
            QMessageBox.warning(self, tr("Import failed"), tr("This file doesn't contain YamanAI chats."))
            return
        existing = {thread.id for thread in self.threads}
        added = skipped = 0
        for item in items:
            try:
                thread = ChatThread.from_dict(item)
            except Exception:
                skipped += 1
                continue
            if thread.is_empty() or thread.id in existing:
                skipped += 1
                continue
            for attr in ("created", "updated"):
                if not isinstance(getattr(thread, attr), (int, float)):
                    setattr(thread, attr, time.time())
            if not isinstance(thread.title, str):
                thread.title = NEW_THREAD_TITLE
            existing.add(thread.id)
            self.threads.append(thread)
            added += 1
        self.threads.sort(key=lambda t: t.updated, reverse=True)
        self.refresh_thread_list()
        self._schedule_save()
        note = " " + tr("({count} skipped: already present or empty)").format(count=skipped) if skipped else ""
        QMessageBox.information(self, tr("Import chats"), tr("{count} chat(s) imported").format(count=added) + note + ".")

    def _append(self, thread: ChatThread, entry: dict, save: bool = True):
        """Adds an entry to a thread and shows it if that thread is open."""
        thread.entries.append(entry)
        thread.updated = time.time()
        if thread in self.threads:
            if thread is self.current_thread:
                self.chat.add_entry(entry)
            self.refresh_thread_list()
            if save:
                self._schedule_save()

    def _remove_entry(self, thread: ChatThread, entry: dict):
        if entry in thread.entries:
            thread.entries.remove(entry)
        if thread is self.current_thread:
            self.chat.remove_entry(entry)

    # =================================================================
    #  SENDING MESSAGES
    # =================================================================
    def send_text(self, text: str):
        """Launch request -> LaunchWorker; anything else (or anything with images) -> streaming AIWorker."""
        text = (text or "").strip()
        if self._busy:
            return
        images = self.composer.take_images()
        if not text and not images:
            return
        if not text:
            text = tr("Describe the attached image(s).")
        thread = self.current_thread
        self.composer.clear()
        entry = {"type": "user", "text": text}
        if images:
            entry["images"] = images
        self._append(thread, entry)
        if thread.title == NEW_THREAD_TITLE:
            thread.title = make_title(text)
            self.refresh_thread_list()

        request = None if images else self.command_handler.parse(text)
        if request:
            request["text"] = text
            self._start_launch(thread, request)
            return
        self._ask_ai(thread, text, images)

    def _ai_ready(self, thread: ChatThread) -> bool:
        """Checks the AI can be called; otherwise explains why in the chat."""
        if not OPENAI_AVAILABLE:
            self._append(thread, {"type": "activity", "status": "error",
                                  "text": tr("The openai library is not installed. Run: pip install openai")})
            return False
        if self.current_model["provider"] == "openai" and not self.api_key:
            self._append(thread, {"type": "activity", "status": "error",
                                  "text": tr("Please enter your API Key first! Open Settings to add it.")})
            self.open_settings()
            return False
        if self.current_model["id"] == "custom" and not self.prefs["custom_model"].strip():
            self._append(thread, {"type": "activity", "status": "error",
                                  "text": tr("Enter a custom model ID in Settings first.")})
            self.open_settings()
            return False
        return True

    def _ask_ai(self, thread: ChatThread, text: str, images=None):
        """Adds the user message to the model history and streams a reply into the thread."""
        model = self.current_model
        if not self._ai_ready(thread):
            return

        system_prompt = build_system_prompt(self.prefs["reply_language"], self.prefs["system_prompt"])
        thread.history.append({"role": "user", "content": user_content(text, images)})
        messages = [{"role": "system", "content": system_prompt}] + prepare_history(thread.history[-MAX_HISTORY:])

        temperature = TEMPERATURES[self.prefs["temperature"]][1]
        if model["provider"] == "local":
            worker = AIWorker("local", messages, self.prefs["local_model"],
                              self.prefs["local_base_url"], "local", temperature, self)
            self._ai_label = self.prefs["local_model"]
        else:
            model_id = self.prefs["custom_model"].strip() if model["id"] == "custom" else model["id"]
            worker = AIWorker(self.api_key, messages, model_id, None, "openai", temperature, self)
            self._ai_label = model_id if model["id"] == "custom" else model["short"]
        self._ai_started = time.monotonic()

        # The reply row appears right away with typing dots and fills in as text streams
        entry = {"type": "assistant", "text": "", "streaming": True}
        self._append(thread, entry, save=False)
        self._live_entry = entry
        self._busy_thread = thread
        self.ai_worker = worker
        worker.partial.connect(self._on_ai_partial)
        worker.response_ready.connect(self._on_ai_response)
        worker.error_occurred.connect(self._on_ai_error)
        worker.finished.connect(self._on_ai_finished)
        self.set_busy(True, "ai")
        worker.start()

    def _live_widget(self):
        if self._busy_thread is self.current_thread and self._live_entry is not None:
            return self.chat.widget_for(self._live_entry)
        return None

    def _on_ai_partial(self, text: str):
        if self.sender() is not self.ai_worker or self._live_entry is None:
            return
        self._live_entry["text"] = text
        widget = self._live_widget()
        if widget is not None:
            widget.set_text(text, final=False)

    def _finalize_live(self, text: str, meta: str = ""):
        entry, thread = self._live_entry, self._busy_thread
        entry["text"] = text
        entry.pop("streaming", None)
        if meta:
            entry["meta"] = meta
        widget = self._live_widget()
        if widget is not None:
            widget.set_text(text, final=True)
            widget.set_meta(meta)
            self.chat.refresh_actions()
        if thread is not None:
            thread.updated = time.time()
        self._schedule_save()

    def _on_ai_response(self, answer: str, usage=None):
        if self.sender() is not self.ai_worker or self._live_entry is None:
            return
        thread = self._busy_thread
        thread.history.append({"role": "assistant", "content": answer})
        elapsed = time.monotonic() - self._ai_started
        meta = f"{self._ai_label} · {elapsed:.1f} s"
        if usage and usage.get("total"):
            meta += " · " + tr("{count} tokens").format(count=usage["total"])
        self._finalize_live(answer, meta)
        self.speak(answer)
        self._maybe_auto_title(thread)
        if not self.isActiveWindow():
            QApplication.alert(self)     # Flash the taskbar button when the reply is ready

    def _maybe_auto_title(self, thread: ChatThread):
        """After the first reply, asks the model for a short title (runs in the background)."""
        if (not self.prefs["auto_title"] or len(thread.history) != 2
                or getattr(thread, "renamed", False) or not OPENAI_AVAILABLE):
            return
        model = self.current_model
        if model["provider"] == "local":
            key, model_id, base_url = "local", self.prefs["local_model"], self.prefs["local_base_url"]
        elif self.api_key:
            key, base_url = self.api_key, None
            model_id = self.prefs["custom_model"].strip() if model["id"] == "custom" else TITLE_MODEL
        else:
            return
        worker = TitleWorker(thread.id, key, model_id, base_url, content_text(thread.history[0]["content"]),
                             content_text(thread.history[1]["content"]), self)
        worker.done.connect(self._on_title_ready)
        worker.finished.connect(lambda w=worker: (self._title_workers.discard(w), w.deleteLater()))
        self._title_workers.add(worker)
        worker.start()

    def _on_title_ready(self, thread_id: str, title: str):
        thread = self._thread_by_id(thread_id)
        if thread is None or getattr(thread, "renamed", False):
            return
        thread.title = title
        self.refresh_thread_list()
        self._schedule_save()

    def _on_ai_error(self, message: str):
        if self.sender() is not self.ai_worker or self._live_entry is None:
            return
        thread, entry = self._busy_thread, self._live_entry
        partial = entry.get("text", "")
        if partial:
            self._finalize_live(partial)
            thread.history.append({"role": "assistant", "content": partial})
        else:
            self._remove_entry(thread, entry)
            if thread.history and thread.history[-1]["role"] == "user":
                thread.history.pop()  # Keep the context consistent
        self._append(thread, {"type": "activity", "status": "error", "text": message})

    def stop_generation(self):
        """Stop button: keeps what was written so far and frees the UI immediately."""
        worker = self.ai_worker
        if worker is None or self._live_entry is None:
            return
        worker.cancel()
        self._retired_workers.add(worker)
        thread, entry = self._busy_thread, self._live_entry
        partial = entry.get("text", "")
        if partial:
            thread.history.append({"role": "assistant", "content": partial})
            self._finalize_live(partial)
        else:
            if thread.history and thread.history[-1]["role"] == "user":
                thread.history.pop()
            self._finalize_live(tr("*Response stopped.*"))
        self.ai_worker = None
        self._live_entry = None
        self.set_busy(False)

    def _on_ai_finished(self):
        worker = self.sender()
        if worker in self._retired_workers:
            self._retired_workers.discard(worker)
        elif worker is self.ai_worker:
            self.ai_worker = None
            self._live_entry = None
            self.set_busy(False)
        if worker is not None:
            worker.deleteLater()

    # ----- Regenerate -----
    @staticmethod
    def _last_turn(thread: ChatThread):
        """The last user or assistant entry (activity rows after it are ignored)."""
        for entry in reversed(thread.entries):
            kind = entry.get("type")
            if kind == "assistant":
                return None if entry.get("streaming") else entry
            if kind == "user":
                return entry
        return None

    def _cut_after(self, thread: ChatThread, index: int):
        """Removes entries[index:] from the thread and the screen."""
        for old in thread.entries[index:]:
            self.chat.remove_entry(old)
        del thread.entries[index:]

    @staticmethod
    def _trim_history(thread: ChatThread, user_text: str, reply_text=None):
        """Drops the last user message (and the reply to it) from the model history."""
        history = thread.history
        if (reply_text is not None and history and history[-1]["role"] == "assistant"
                and history[-1]["content"] == reply_text):
            history.pop()
        if history and history[-1]["role"] == "user" and content_text(history[-1]["content"]) == user_text:
            history.pop()

    def regenerate_last(self):
        """
        Regenerates the latest reply, or retries your last message when it got no reply
        (after an error or a stopped reply). Launch commands are simply run again.
        """
        thread = self.current_thread
        if self._busy or thread is None:
            return
        entry = self._last_turn(thread)
        if entry is None:
            return
        index = thread.entries.index(entry)
        if entry.get("type") == "assistant":
            user_entry = next((e for e in reversed(thread.entries[:index]) if e.get("type") == "user"), None)
            cut, reply_text = index, entry.get("text")
        else:
            user_entry, cut, reply_text = entry, index + 1, None
        if user_entry is None:
            return
        user_text = user_entry.get("text", "")
        user_images = user_entry.get("images")

        request = (self.command_handler.parse(user_text)
                   if entry.get("type") == "user" and not user_images else None)
        if request is None and not self._ai_ready(thread):
            return   # Keep the old reply when a new one can't be requested
        self._cut_after(thread, cut)
        if request is not None:
            request["text"] = user_text
            self.chat.refresh_actions()
            self._start_launch(thread, request)
            return
        self._trim_history(thread, user_text, reply_text)
        self.chat.refresh_actions()
        self._ask_ai(thread, user_text, user_images)

    def edit_last_message(self):
        """Pencil: takes your last message (and everything after it) back into the input box."""
        thread = self.current_thread
        if self._busy or thread is None:
            return
        index = next((i for i in range(len(thread.entries) - 1, -1, -1)
                      if thread.entries[i].get("type") == "user"), None)
        if index is None:
            return
        text = thread.entries[index].get("text", "")
        images = thread.entries[index].get("images") or []
        reply = next((e.get("text") for e in thread.entries[index + 1:] if e.get("type") == "assistant"), None)
        self._trim_history(thread, text, reply)
        self._cut_after(thread, index)
        if not thread.entries:
            self.chat.load([])
        self.chat.refresh_actions()
        thread.updated = time.time()
        self.refresh_thread_list()
        self._schedule_save()
        for image in images:
            self.composer.add_image(image)
        self.composer.set_text(text)

    def _recall_last_message(self):
        """Up arrow in an empty input box: puts your last message back for reuse."""
        if self.current_thread is None:
            return
        last = next((e.get("text", "") for e in reversed(self.current_thread.entries)
                     if e.get("type") == "user"), "")
        if last:
            self.composer.set_text(last)

    def copy_last_reply(self):
        thread = self.current_thread
        text = next((e.get("text", "") for e in reversed(thread.entries)
                     if e.get("type") == "assistant" and not e.get("streaming")), "") if thread else ""
        if text:
            QApplication.clipboard().setText(text)
            QToolTip.showText(self.composer.mapToGlobal(QPoint(24, -8)), tr("Last reply copied"), self.composer)

    def change_font_size(self, step: int):
        """Ctrl+= / Ctrl+- / Ctrl+0."""
        keys = list(FONT_SIZES)
        if step == 0:
            new = DEFAULT_FONT_SIZE
        else:
            index = keys.index(self.prefs["font_size"]) + step
            new = keys[max(0, min(len(keys) - 1, index))]
        if new != self.prefs["font_size"]:
            self.prefs["font_size"] = new
            self._save_prefs()
            self.apply_appearance()

    # ----- Attachments -----
    def _choose_attachments(self):
        patterns = " ".join(f"*{ext}" for ext in [*ATTACHMENT_LANGS, *sorted(IMAGE_EXTS)])
        image_patterns = " ".join(f"*{ext}" for ext in sorted(IMAGE_EXTS))
        filters = (f"{tr('Text, code and image files')} ({patterns});;{tr('Images')} ({image_patterns});;"
                   f"{tr('All files')} (*)")
        paths, _filter = QFileDialog.getOpenFileNames(self, tr("Attach files"), os.path.expanduser("~"), filters)
        if paths:
            self.attach_files(paths)

    def attach_files(self, paths: list):
        for path in paths:
            if os.path.splitext(path)[1].lower() in IMAGE_EXTS:
                ok, result = read_image_attachment(path)
                if ok and not self.composer.add_image(result):
                    ok, result = False, tr("You can attach up to {count} images per message.").format(
                        count=MAX_IMAGES_PER_MESSAGE)
            else:
                ok, result = read_attachment(path)
                if ok:
                    language, content = result
                    self.composer.insert_attachment(os.path.basename(path), language, content)
            if not ok and self.current_thread is not None:
                self._append(self.current_thread, {"type": "activity", "status": "error", "text": result},
                             save=False)

    def attach_qimage(self, image):
        """A screenshot pasted into the input box."""
        result = encode_image(image, f"{tr('screenshot')}-{datetime.now():%H%M%S}.jpg")
        if result is None:
            return
        if not self.composer.add_image(result) and self.current_thread is not None:
            self._append(self.current_thread, {"type": "activity", "status": "error",
                                               "text": tr("You can attach up to {count} images per message.").format(
                                                   count=MAX_IMAGES_PER_MESSAGE)}, save=False)

    # ----- Launching -----
    def _run_quick_command(self, command: dict):
        if self._busy:
            return
        self._start_launch(self.current_thread, {"kind": "known", "command": command, "label": command["name"]})

    def _open_file_dialog(self):
        if self._busy:
            return
        path, _ = QFileDialog.getOpenFileName(self, tr("Open file or program"), os.path.expanduser("~"),
                                              tr("Programs") + " (*.exe *.bat *.cmd *.lnk *.msc);;"
                                              + tr("All files") + " (*)")
        if path:
            path = os.path.normpath(path)
            self._start_launch(self.current_thread, {"kind": "path", "path": path, "label": os.path.basename(path)})

    def _start_launch(self, thread: ChatThread, request: dict):
        self._search_entry = None
        if request["kind"] == "search":
            self._search_entry = {"type": "activity", "status": "running",
                                  "text": tr("Searching for {name}...").format(name=request["label"])}
            self._append(thread, self._search_entry, save=False)
        self._busy_thread = thread
        self._launch_request = request
        self.set_busy(True, "launch")
        self.launch_worker = LaunchWorker(self.command_handler, request, self)
        self.launch_worker.launched.connect(self._on_launch_result)
        self.launch_worker.finished.connect(self._on_launch_finished)
        self.launch_worker.start()

    def _on_launch_result(self, ok: bool, message: str):
        thread, request = self._busy_thread, self._launch_request or {}
        # The "Searching..." row is replaced by the result instead of spinning forever
        if thread is not None and self._search_entry is not None:
            self._remove_entry(thread, self._search_entry)
        self._search_entry = None
        if thread is None:
            return
        if not ok and request.get("fallback_to_ai") and request.get("text"):
            # "start a flask server" is not an app: let the AI answer once the UI is free
            self._append(thread, {"type": "activity", "status": "info",
                                  "text": tr("No app named \"{name}\" was found, so YamanAI will "
                                             "answer instead.").format(name=request["label"])})
            self._pending_ai = (thread, request["text"])
            return
        self._append(thread, {"type": "activity", "status": "success" if ok else "error", "text": message})
        self.speak(message, UI_LANG)

    def _on_launch_finished(self):
        if self.launch_worker is not None:
            self.launch_worker.deleteLater()
            self.launch_worker = None
        self._launch_request = None
        self.set_busy(False)
        pending, self._pending_ai = self._pending_ai, None
        if pending is not None and pending[0] in self.threads:
            self._ask_ai(*pending)

    # =================================================================
    #  TEXT-TO-SPEECH
    # =================================================================
    def _set_tts_button(self, on: bool):
        button = self.header.tts_button
        button.setChecked(on)
        IconRegistry.bind(button, "ph.speaker-high" if on else "ph.speaker-slash",
                          "accent_text" if on else "muted", active="accent_text")
        button.setToolTip(tr("Text-to-Speech: On") if on else tr("Text-to-Speech: Off"))

    def set_tts_enabled(self, on: bool):
        if on and not TTS_AVAILABLE:
            self._append(self.current_thread, {"type": "activity", "status": "error",
                                               "text": tr("pyttsx3 is not installed. Run: pip install pyttsx3")})
            on = False
        elif on:
            self._ensure_tts_worker()
        elif self.tts_worker is not None:
            self.tts_worker.stop_current()
        self.prefs["tts"] = on
        self.settings.setValue("tts_enabled", on)
        self._set_tts_button(on)

    def _ensure_tts_worker(self) -> bool:
        if not TTS_AVAILABLE:
            return False
        if self.tts_worker is None:
            self.tts_worker = TTSWorker(self)
            self.tts_worker.error_occurred.connect(self._on_tts_error)
            self.tts_worker.info.connect(
                lambda msg: self._append(self.current_thread, {"type": "activity", "status": "info", "text": msg})
            )
            self.tts_worker.finished.connect(self._on_tts_finished)
            self.tts_worker.start()
        return True

    def _voice_language(self, text: str, lang: str = None) -> str:
        if lang:
            return lang
        reply = self.prefs["reply_language"]
        return reply if reply in ("tr", "en") else guess_language(text)

    def speak(self, text: str, lang: str = None):
        if self.prefs["tts"] and self.tts_worker is not None:
            self.tts_worker.speak(clean_for_speech(text), self._voice_language(text, lang))

    def speak_now(self, text: str):
        """'Read aloud' under a reply: works even when automatic TTS is off."""
        if not self._ensure_tts_worker():
            self._append(self.current_thread, {"type": "activity", "status": "error",
                                               "text": tr("pyttsx3 is not installed. Run: pip install pyttsx3")})
            return
        self.tts_worker.stop_current()
        self.tts_worker.speak(clean_for_speech(text), self._voice_language(text))

    def _on_tts_error(self, message: str, fatal: bool = False):
        self._append(self.current_thread, {"type": "activity", "status": "error", "text": message})
        if fatal:
            self.set_tts_enabled(False)

    def _on_tts_finished(self):
        if self.tts_worker is not None:
            self.tts_worker.deleteLater()
            self.tts_worker = None

    # =================================================================
    #  SPEECH-TO-TEXT
    # =================================================================
    def start_listening(self):
        if self.stt_worker is not None or self._busy:
            return
        if not STT_AVAILABLE:
            self._append(self.current_thread, {"type": "activity", "status": "error",
                                               "text": tr("speechrecognition is not installed. "
                                                          "Run: pip install speechrecognition pyaudio")})
            return
        if self.tts_worker is not None:
            self.tts_worker.stop_current()
        self.composer.set_mic_state("preparing")
        self.stt_worker = STTWorker(SPEECH_LANGUAGES[self.prefs["speech_language"]][1], self)
        self.stt_worker.listening_started.connect(self._on_listening)
        self.stt_worker.processing_started.connect(lambda: self.composer.set_mic_state("processing"))
        self.stt_worker.recognized.connect(self._on_recognized)
        self.stt_worker.failed.connect(self._on_speech_failed)
        self.stt_worker.finished.connect(self._on_stt_finished)
        self.stt_worker.start()

    def _on_listening(self):
        self.composer.set_mic_state("listening")
        self.header.pill.set_state(self.current_model["short"], tr("Listening"), P["red"])

    def _on_recognized(self, text: str):
        self.composer.set_mic_state("idle")
        self._refresh_status()
        self.composer.set_text(text)
        self.send_text(text)

    def _on_speech_failed(self, message: str, is_error: bool):
        self.composer.set_mic_state("idle")
        self._refresh_status()
        self._append(self.current_thread, {"type": "activity", "status": "error" if is_error else "info",
                                           "text": message})

    def _on_stt_finished(self):
        if self.stt_worker is not None:
            self.stt_worker.deleteLater()
            self.stt_worker = None
        self.composer.set_mic_state("idle")
        self._refresh_status()

    # =================================================================
    #  STATUS & BUSY STATE
    # =================================================================
    def _refresh_status(self):
        model = self.current_model
        short = model["short"]
        if model["id"] == "custom":
            short = self.prefs["custom_model"].strip() or tr("Custom")
        if model["provider"] == "local":
            state, color = tr("Local"), P["accent_text"]
            powered = tr("a local model")
        elif self.api_key and OPENAI_AVAILABLE:
            state, color = tr("Online"), P["green"]
            powered = "OpenAI"
        else:
            state, color = tr("No API key"), P["amber"]
            powered = "OpenAI"
        self.header.pill.set_state(short, state, color)
        self.footer_note.setText(caps(tr("{app} {version}  •  Powered by {provider}").format(
            app=APP_NAME, version=APP_VERSION_LABEL, provider=powered)))
        speech = tr(SPEECH_LANGUAGES[self.prefs["speech_language"]][0])
        self.composer.mic_button.setToolTip(tr("Voice input") + f" ({speech})")

    def set_busy(self, busy: bool, mode: str = None):
        self._busy = busy
        self._busy_mode = mode if busy else None
        self.composer.set_mode(mode if busy and mode == "ai" else ("busy" if busy else "idle"))
        self.chat.set_locked(busy)
        if not busy:
            self._busy_thread = None
            self.composer.focus()
        self.refresh_thread_list()

    # =================================================================
    #  WINDOW, SIDEBAR & RESPONSIVE LAYOUT
    # =================================================================
    def set_sidebar_visible(self, visible: bool, manual: bool = False):
        if manual:
            self._sidebar_auto_hidden = False
        self.sidebar.setVisible(visible)
        self.header.menu_button.setVisible(not visible)
        if visible:
            self.splitter.setSizes([SIDEBAR_WIDTH, max(400, self.width() - SIDEBAR_WIDTH)])

    def _on_main_resized(self, width: int):
        padding = 12 if width < 640 else 24
        self.composer_host_layout.setContentsMargins(padding, 6, padding, 16)
        self.composer.setFixedWidth(max(240, min(896, width - 2 * padding)))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        narrow = self.width() < SIDEBAR_AUTO_HIDE_WIDTH
        # Only react when the width crosses the threshold. Before, the sidebar you
        # opened with Ctrl+B on a narrow window was hidden again by the next resize.
        if narrow == self._was_narrow:
            return
        self._was_narrow = narrow
        if narrow and not self.sidebar.isHidden():   # isVisible() is False before show()
            self._sidebar_auto_hidden = True
            self.sidebar.setVisible(False)
            self.header.menu_button.setVisible(True)
        elif not narrow and self._sidebar_auto_hidden:
            self._sidebar_auto_hidden = False
            self.set_sidebar_visible(True)

    def changeEvent(self, event):
        if event.type() == QEvent.Type.WindowStateChange:
            edge_to_edge = self.isMaximized() or self.isFullScreen() or not USE_CUSTOM_TITLEBAR
            margin = 0 if edge_to_edge else ResizableFrame.MARGIN
            self.frame_layout.setContentsMargins(margin, margin, margin, margin)
            self.header.set_maximized(self.isMaximized() or self.isFullScreen())
        super().changeEvent(event)

    def _restore_window_state(self):
        """Window size/position and sidebar visibility from the last session."""
        geometry = self.settings.value("window_geometry")
        if geometry is not None:
            try:
                self.restoreGeometry(geometry)
            except TypeError:
                pass
        if not self.settings.value("sidebar_visible", True, type=bool):
            self.set_sidebar_visible(False, manual=True)

    def _save_window_state(self):
        self.settings.setValue("window_geometry", self.saveGeometry())
        self.settings.setValue("sidebar_visible", self.sidebar.isVisible() or self._sidebar_auto_hidden)

    def _toggle_maximized(self):
        self.showNormal() if (self.isMaximized() or self.isFullScreen()) else self.showMaximized()

    def toggle_fullscreen(self):
        self.showNormal() if self.isFullScreen() else self.showFullScreen()

    def _on_escape(self):
        for modal in (self.settings_modal, self.help_modal):
            if modal.isVisible():
                modal.close_modal()
                return
        if self.ai_worker is not None:
            self.stop_generation()       # Esc also stops a reply that is being written
            return
        if self.isFullScreen():
            self.showNormal()

    def focus_search(self):
        if not self.sidebar.isVisible():
            self.set_sidebar_visible(True, manual=True)
        self.sidebar.search_input.setFocus()
        self.sidebar.search_input.selectAll()

    # =================================================================
    #  SHUTDOWN
    # =================================================================
    def closeEvent(self, event):
        if self.ai_worker is not None:
            self.stop_generation()
        self._save_timer.stop()
        self.store.save(self.threads)
        self._save_window_state()
        for worker in [self.key_worker, self.launch_worker, *self._retired_workers, *self._title_workers]:
            if worker is not None and worker.isRunning():
                worker.wait(3000)
        if self.tts_worker is not None:
            self.tts_worker.shutdown()
            self.tts_worker.wait(3000)
        if self.stt_worker is not None and self.stt_worker.isRunning():
            if not self.stt_worker.wait(2000):
                self.stt_worker.terminate()  # Last resort so closing never hangs
                self.stt_worker.wait(500)
        event.accept()


# =====================================================================
#  ENTRY POINT
# =====================================================================
def load_app_icon() -> QIcon:
    """Window/taskbar icon: bundled icon.ico, then the development path, then a built-in icon."""
    here = os.path.dirname(os.path.abspath(__file__))
    for path in (os.path.join(here, APP_ICON_FILE), APP_ICON_DEV_PATH):
        if os.path.isfile(path):
            return QIcon(path)
    return icon("ph.sparkle", "accent_text")


def main():
    global UI_LANG
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
        except Exception:
            pass
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORG_NAME)
    app.setFont(QFont("Segoe UI", 10))
    app.setWindowIcon(load_app_icon())
    UI_LANG = detect_ui_language(QSettings(ORG_NAME, SETTINGS_APP_NAME))

    window = MainWindow()
    window.show()
    QTimer.singleShot(3000, cleanup_old_previews)
    code = app.exec()
    if window._restart_requested:          # Language changed: start a fresh copy
        args = sys.argv[1:] if getattr(sys, "frozen", False) else sys.argv
        subprocess.Popen([sys.executable, *args])
    sys.exit(code)


if __name__ == "__main__":
    main()
