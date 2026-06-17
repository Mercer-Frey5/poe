import csv, soundfile as sf
from pathlib import Path
from datasets import Dataset

BASE     = Path(__file__).parent
DATA_DIR = BASE / "venv_tts" / "Lib" / "data" / "POE_char"
WAVS_DIR = DATA_DIR / "wavs"
META     = DATA_DIR / "metadata.csv"

records = []
with open(META, encoding="utf-8") as f:
    for row in csv.DictReader(f):
        wav_path = WAVS_DIR / row["file_name"]
        if not wav_path.exists():
            print(f"  skip: {row['file_name']}")
            continue
        audio_data, sr = sf.read(str(wav_path))
        duration = len(audio_data) / sr
        records.append({
            "audio":    str(wav_path),
            "text":     row["text"],
            "duration": duration,
        })

dataset = Dataset.from_list(records)
raw_path = DATA_DIR / "raw"
dataset.save_to_disk(str(raw_path))
print(f"\n✓ {len(records)} campioni salvati in {raw_path}")
