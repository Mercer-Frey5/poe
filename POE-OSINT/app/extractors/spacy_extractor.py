"""
spacy_extractor.py — estrazione di nomi di persona via spaCy NER.

Emette solo entità di tipo `person_name`, con una stoplist di
"label words" italiane/inglesi che spaCy NER a volte estrae
erroneamente come persone (es. "Contatto", "Mittente").

In v0.3 la stoplist è esternalizzata in app/config/stoplist_person_name.yaml
(in v0.2 era hardcoded qui). Modificarla non richiede toccare codice;
richiede solo il restart dell'applicazione per ricaricare il file.

Strategia multilingua: eseguiamo sia il modello italiano che quello
inglese sullo stesso testo e uniamo i risultati (deduplicati).
È meno efficiente di un language detector, ma più semplice e più
robusto su testi misti IT/EN — scenario frequente in OSINT.

I modelli pesanti (`_lg`) sono una scelta deliberata:
- Molto più precisi dei `_sm` sulle entità di persona
- Caricamento lento (~3-5s) ma solo una volta all'avvio
"""

from __future__ import annotations

from app.config_loader import load_yaml_list
from app.extractors.base import BaseExtractor
from app.models import Entity


# Etichette NER che spaCy usa per "persona".
# Il modello italiano usa "PER", quello inglese "PERSON".
_PERSON_LABELS = {"PERSON", "PER"}

# Modelli da caricare. L'ordine non conta.
_MODEL_NAMES = ("it_core_news_lg", "en_core_web_lg")

# Stoplist caricata al modulo-load. Lista vuota valida (= nessun filtro).
# Conservatismo: lista parte minimale, voci aggiunte solo dopo aver
# osservato un FP nell'uso reale.
_PERSON_NAME_STOPLIST: frozenset[str] = frozenset(
    w.strip().lower() for w in load_yaml_list("stoplist_person_name.yaml", allow_empty=True)
)


def _is_label_word(text: str) -> bool:
    """True se la stringa è una label-word da scartare (case-insensitive)."""
    return text.strip().lower() in _PERSON_NAME_STOPLIST


class SpacyExtractor(BaseExtractor):
    """
    Estrattore NER via spaCy.

    Carica al costruttore entrambi i modelli (it_lg + en_lg). Il
    caricamento è pesante: si consiglia di istanziare questa classe
    una sola volta (singleton) al bootstrap dell'applicazione.
    """

    def __init__(self) -> None:
        import spacy

        self._models = []
        missing = []
        for name in _MODEL_NAMES:
            try:
                self._models.append(spacy.load(name))
            except OSError:
                missing.append(name)

        if missing:
            raise RuntimeError(
                "Modelli spaCy mancanti: "
                + ", ".join(missing)
                + ".\nInstallali con:\n"
                + "\n".join(f"    python -m spacy download {n}" for n in missing)
            )

    def extract(self, text: str) -> list[Entity]:
        found: set[Entity] = set()
        for nlp in self._models:
            doc = nlp(text)
            for ent in doc.ents:
                if ent.label_ not in _PERSON_LABELS:
                    continue
                name = ent.text.strip()
                if not name:
                    continue
                if _is_label_word(name):
                    # Falso positivo riconosciuto: scartato silenziosamente
                    continue
                found.add(Entity("person_name", name, confidence="low"))
        return list(found)
