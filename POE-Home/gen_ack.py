"""
Pre-render delle frasi di risposta wake-word con la voce di POE (TTS → RVC).
Esecuzione unica: cd POE-Home && .venv/bin/python gen_ack.py

Produce: ack/ack_0.wav … ack/ack_7.wav
"""

import io
import os
import subprocess
import tempfile
import wave
from pathlib import Path

import numpy as np

HOME_DIR   = Path(__file__).parent
APPLIO_DIR = Path.home() / "POE-Voice/Applio"
MODEL_PTH  = APPLIO_DIR / "logs/poe-ita/poe-ita_200e_4200s.pth"
INDEX_FILE = APPLIO_DIR / "logs/poe-ita/poe-ita.index"
VOICE_DIR  = HOME_DIR / "voices/poe"
REF_AUDIO  = VOICE_DIR / "ref.wav"
REF_TEXT   = (VOICE_DIR / "ref.txt").read_text().strip()
TTS_MODEL  = "Qwen/Qwen3-TTS-12Hz-0.6B-Base"
OUT_DIR    = HOME_DIR / "ack"

PHRASES = [
    # 0-7: generate per prime (già valide)
    "Sono qui, signore. In ascolto.",
    "Desidera interfacciarsi, sir?",
    "Sono Poe. Al suo servizio, signore.",
    "I miei recettori sono a sua completa disposizione, sir.",
    "Come posso assisterla in questo mondo materiale, signore?",
    "Sistemi operativi. Attendo le sue direttive, sir.",
    "La sua intelligenza artificiale di fiducia e pronta.",
    "Nessun glitch rilevato. Mi dica, signore.",
    # 8-13: Eleganza Vittoriana
    "In cosa posso esserle utile in questa particolare giornata, sir?",
    "Un nuovo incarico, signore? Ne sono estasiato. Mi dica.",
    "La sua voce e sempre gradita. Attendo istruzioni, sir.",
    "E un onore interfacciarmi con lei, signore. Proceda pure.",
    "Sempre vigile, sir. Quali sono i suoi desideri?",
    "Il suo fedele compagno e in ascolto, signore.",
    # 14-19: Costrutto Digitale
    "I miei circuiti sono in attesa delle sue parole, sir.",
    "I miei banchi di memoria sono aperti per lei, signore.",
    "Le mie sub-routine sono focalizzate esclusivamente su di lei, sir.",
    "Sistemi stabili e lealta immutata. Parli pure, signore.",
    "Cosa desidera evocare dalla matrice oggi, sir?",
    "Elaborazione in corso. Sono tutto suo, signore.",
    # 20-25: Lato Oscuro
    "Difese online e orecchie tese. Cosa le occorre, sir?",
    "Sono qui, signore. Pronto a eseguire e, se necessario, difendere.",
    "Nessuna minaccia rilevata, sir. Ha la mia totale attenzione.",
    "Armamenti in stand-by e protocolli di cortesia attivati. Mi dica, signore.",
    "Spero nessuno stia disturbando la sua quiete, sir. Come procediamo?",
    "Pronto a polverizzare i suoi ostacoli, digitali e non, signore.",
    # 26-31: Brevi e Rapide
    "La ascolto, sir.",
    "Agli ordini, signore.",
    "Connesso e pronto, sir.",
    "Dica pure, signore.",
    "Sempre al suo fianco, sir.",
    "In attesa, signore.",
]


def pcm_to_wav(audio: np.ndarray, sr: int) -> bytes:
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def run_rvc(input_wav: str, out_wav: str):
    venv_py = APPLIO_DIR / ".venv/bin/python"
    script = f"""
import sys, os
os.chdir('{APPLIO_DIR}')
sys.path.insert(0, '{APPLIO_DIR}')
import torch
torch.backends.mps.is_available = lambda: False
torch.backends.mps.is_built    = lambda: False
from rvc.infer.infer import VoiceConverter
vc = VoiceConverter()
vc.convert_audio(
    audio_input_path='{input_wav}',
    audio_output_path='{out_wav}',
    model_path='{MODEL_PTH}',
    index_path='{INDEX_FILE}',
    pitch=4,
    f0_method='rmvpe',
    index_rate=0.5,
    volume_envelope=1.0,
    protect=0.5,
    hop_length=128,
    filter_radius=5,
    embedder_model='contentvec',
    embedder_model_custom=None,
    clean_audio=True,
    clean_strength=0.5,
    export_format='WAV',
    split_audio=False,
    f0_autotune=False,
    f0_min=50,
    f0_max=1100,
    sid=0,
)
"""
    env = os.environ.copy()
    env["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"
    env["KMP_DUPLICATE_LIB_OK"] = "TRUE"
    env["OMP_NUM_THREADS"] = "1"
    r = subprocess.run([str(venv_py), "-c", script], cwd=str(APPLIO_DIR), env=env)
    if r.returncode != 0:
        raise RuntimeError(f"RVC exit {r.returncode}")


def main():
    OUT_DIR.mkdir(exist_ok=True)

    print("[gen_ack] Caricamento TTS...")
    from mlx_audio.tts.utils import load_model
    from mlx_audio.utils import load_audio
    tts = load_model(TTS_MODEL)
    sr = getattr(tts, "sample_rate", 24000)
    ref_audio = load_audio(str(REF_AUDIO), sample_rate=sr)

    for i, phrase in enumerate(PHRASES):
        out_path = OUT_DIR / f"ack_{i}.wav"
        if out_path.exists():
            print(f"[gen_ack] ack_{i}.wav gia presente, skip")
            continue

        print(f"[gen_ack] [{i+1}/{len(PHRASES)}] TTS: {phrase[:50]}...")
        chunks = []
        for chunk in tts.generate(
            text=phrase,
            ref_audio=ref_audio,
            ref_text=REF_TEXT,
            lang_code="it",
            verbose=False,
        ):
            chunks.append(np.array(chunk.audio, dtype=np.float32))
        tts_bytes = pcm_to_wav(np.concatenate(chunks), sr)

        tmp = Path(tempfile.mkdtemp())
        tts_path = str(tmp / "tts.wav")
        rvc_path = str(tmp / "rvc.wav")
        (tmp / "tts.wav").write_bytes(tts_bytes)

        print(f"[gen_ack] [{i+1}/{len(PHRASES)}] RVC...")
        run_rvc(tts_path, rvc_path)

        out_path.write_bytes(Path(rvc_path).read_bytes())
        print(f"[gen_ack] Salvato: {out_path.name}")

    print("[gen_ack] Completato.")


if __name__ == "__main__":
    main()
