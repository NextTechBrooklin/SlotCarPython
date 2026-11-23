"""Background music, crowd cheering and winner text-to-speech."""

from __future__ import annotations

import os
import subprocess
import threading
from pathlib import Path
from typing import Callable

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
try:
    import pygame
except Exception:  # pragma: no cover - audio is optional
    pygame = None

from .paths import CHEERING_AUDIO_FILE, RACE_MUSIC_FILE

DUCK_FACTOR = 0.28


class AudioEngine:
    def __init__(self, on_error: Callable[[str], None] | None = None, volume: float = 0.35) -> None:
        self._on_error = on_error or (lambda _msg: None)
        self._volume = volume
        self._muted = False
        self._ducked = False
        self._cheer_channel = None
        self._cheer_sound = None
        self.music_playing = False

    # ------------------------------------------------------------- helpers
    def _ready(self) -> bool:
        if pygame is None:
            self._on_error("pygame is not installed - audio disabled")
            return False
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=1024)
            return True
        except Exception as exc:
            self._on_error(f"Audio device unavailable: {exc}")
            return False

    @property
    def effective_volume(self) -> float:
        return 0.0 if self._muted else self._volume

    def _apply(self) -> None:
        if pygame is None or not pygame.mixer.get_init():
            return
        v = self.effective_volume
        pygame.mixer.music.set_volume(v * DUCK_FACTOR if self._ducked else v)
        if self._cheer_channel is not None:
            self._cheer_channel.set_volume(v)

    # --------------------------------------------------------------- volume
    @property
    def volume(self) -> float:
        return self._volume

    def set_volume(self, value: float) -> None:
        self._volume = max(0.0, min(1.0, float(value)))
        self._apply()

    @property
    def muted(self) -> bool:
        return self._muted

    def set_muted(self, muted: bool) -> None:
        self._muted = muted
        self._apply()

    # ---------------------------------------------------------------- music
    def start_music(self, path: Path = RACE_MUSIC_FILE) -> None:
        if not path.exists():
            self._on_error(f"Music file missing: {path.name}")
            return
        if not self._ready():
            return
        try:
            pygame.mixer.music.load(str(path))
            self._ducked = False
            self._apply()
            pygame.mixer.music.play(-1, fade_ms=800)
            self.music_playing = True
        except Exception as exc:
            self.music_playing = False
            self._on_error(f"Music playback failed: {exc}")

    def stop_music(self, fade_ms: int = 600) -> None:
        self.music_playing = False
        if pygame is None or not pygame.mixer.get_init():
            return
        try:
            pygame.mixer.music.fadeout(fade_ms) if fade_ms else pygame.mixer.music.stop()
        except Exception:
            pass

    # ---------------------------------------------------------------- cheer
    def start_cheer(self, path: Path = CHEERING_AUDIO_FILE) -> None:
        if not path.exists():
            self._on_error(f"Cheering audio missing: {path.name}")
            return
        if not self._ready():
            return
        try:
            if pygame.mixer.music.get_busy():
                self._ducked = True
            self._cheer_sound = pygame.mixer.Sound(str(path))
            self._cheer_channel = pygame.mixer.Channel(1)
            self._apply()
            self._cheer_channel.play(self._cheer_sound)
        except Exception as exc:
            self._on_error(f"Cheering audio failed: {exc}")

    def stop_cheer(self) -> None:
        if pygame is not None and pygame.mixer.get_init():
            try:
                if self._cheer_channel is not None:
                    self._cheer_channel.fadeout(400)
            except Exception:
                pass
        self._cheer_channel = None
        self._cheer_sound = None
        self._ducked = False
        self._apply()

    def shutdown(self) -> None:
        self.stop_music(0)
        self.stop_cheer()
        if pygame is not None and pygame.mixer.get_init():
            try:
                pygame.mixer.quit()
            except Exception:
                pass


def speak(text: str, on_done: Callable[[bool], None] | None = None) -> None:
    """Speak ``text`` with Windows System.Speech on a worker thread.

    The text is passed through an environment variable rather than being
    spliced into the PowerShell command, so driver names can't break quoting.
    """

    script = (
        "Add-Type -AssemblyName System.Speech;"
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        "$f = $s.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Gender -eq 'Female' } | Select-Object -First 1;"
        "if ($f) { $s.SelectVoice($f.VoiceInfo.Name) };"
        "$s.Speak($env:SLOTCAR_TTS_TEXT)"
    )

    def worker() -> None:
        ok = False
        try:
            env = dict(os.environ, SLOTCAR_TTS_TEXT=text)
            result = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
                env=env,
                capture_output=True,
                timeout=25,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                check=False,
            )
            ok = result.returncode == 0
        except Exception:
            ok = False
        if on_done:
            on_done(ok)

    threading.Thread(target=worker, name="tts", daemon=True).start()
