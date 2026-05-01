"""Detector de palmas em background usando sounddevice + numpy."""
from __future__ import annotations

import threading
import time
from typing import Callable

import numpy as np

try:
    import sounddevice as sd
except Exception:  # pragma: no cover - falha de import = sem áudio
    sd = None

from config import (
    CLAP_COOLDOWN_S,
    CLAP_MAX_INTERVAL_S,
    CLAP_MIN_INTERVAL_S,
    CLAP_SAMPLE_RATE,
    CLAP_THRESHOLD,
)


class ClapListener:
    """
    Escuta o microfone e dispara `on_double_clap()` quando detecta 2 palmas
    consecutivas dentro da janela [CLAP_MIN_INTERVAL_S, CLAP_MAX_INTERVAL_S].
    """

    def __init__(self, on_double_clap: Callable[[], None]) -> None:
        self.on_double_clap = on_double_clap
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_clap_at: float = 0.0
        self._last_trigger_at: float = 0.0

    def available(self) -> bool:
        return sd is not None

    def start(self) -> bool:
        if not self.available():
            return False
        self._thread = threading.Thread(target=self._run, daemon=True, name="ClapListener")
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        block_size = 1024
        try:
            with sd.InputStream(
                channels=1,
                samplerate=CLAP_SAMPLE_RATE,
                blocksize=block_size,
                dtype="float32",
                callback=self._callback,
            ):
                while not self._stop.is_set():
                    time.sleep(0.05)
        except Exception as e:  # pragma: no cover - sem mic, etc.
            print(f"[clap-listener] desativado: {e}")

    def _callback(self, indata, frames, time_info, status):
        # RMS do bloco
        block = indata[:, 0] if indata.ndim > 1 else indata
        rms = float(np.sqrt(np.mean(block ** 2)))
        # Pico instantâneo
        peak = float(np.max(np.abs(block)))

        # Heurística simples de palma: pico curto e alto, com energia pontual
        # (palmas têm transientes muito agudos, RMS alto + peak/RMS alto).
        if peak < CLAP_THRESHOLD:
            return
        if rms < CLAP_THRESHOLD * 0.35:
            return

        now = time.monotonic()

        # Cooldown global após disparo
        if now - self._last_trigger_at < CLAP_COOLDOWN_S:
            return

        if self._last_clap_at == 0.0:
            self._last_clap_at = now
            return

        delta = now - self._last_clap_at
        if delta < CLAP_MIN_INTERVAL_S:
            # transientes muito próximos = mesma palma; ignora
            return
        if delta > CLAP_MAX_INTERVAL_S:
            # muito longe — reinicia contagem
            self._last_clap_at = now
            return

        # 2 palmas válidas
        self._last_trigger_at = now
        self._last_clap_at = 0.0
        try:
            self.on_double_clap()
        except Exception as e:  # pragma: no cover
            print(f"[clap-listener] callback falhou: {e}")
