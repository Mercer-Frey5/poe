"""
recognizer.py — orchestratore della pipeline di riconoscimento.

In v0.2 la pipeline diventa:

    text  ──→ Deobfuscator ──→ normalized ──→ Extractors ──→ Entities
                                                  │
                                                  └─→ ricostruzione
                                                       di Entity.original
                                                       dalla index_map

Il Deobfuscator preprocessa il testo per neutralizzare i defang
("hxxp://", "[.]", ecc.). Gli extractor vedono testo pulito e lavorano
come in v0.1. La ricostruzione di `original` avviene QUI nel
Recognizer, perché solo lui ha accesso sia al risultato del
Deobfuscator (che contiene la mappa indici) sia ai match degli
extractor (di cui peraltro non conosce gli offset).

Strategia per `original`:
  - Cerchiamo `entity.value` nel testo normalizzato (prima occorrenza)
  - Mappiamo gli indici sul testo originale
  - Estraiamo la substring corrispondente

Se la substring nell'originale differisce dal value, abbiamo trovato
una deobfuscazione e popoliamo `original`. Se coincidono, lasciamo
default (`original` = `value`).

Note:
- Per entità multi-occorrenza (es. due URL distinti che si
  normalizzano allo stesso valore) prendiamo la prima occorrenza.
  Caso raro, accettato come limite di v0.2.
- spaCy NER lavora sul testo normalizzato: è coerente, perché un
  `person_name` non viene mai deobfuscato.
"""

from __future__ import annotations

from urllib.parse import urlparse

from app.deobfuscator import DeobfuscationResult, deobfuscate
from app.models import Entity


class Recognizer:
    """
    Pipeline deterministica di v0.2.

    Riceve due extractor al costruttore. L'iniezione permette di
    mockarli nei test senza dipendenze pesanti (spaCy).
    """

    def __init__(self, regex_extractor, spacy_extractor) -> None:
        self._regex = regex_extractor
        self._spacy = spacy_extractor

    def recognize(self, text: str) -> list[Entity]:
        """Estrae tutte le entità, applica dedup, restituisce lista stabile."""
        deob = deobfuscate(text)

        raw: set[Entity] = set()
        raw.update(self._regex.extract(deob.normalized))
        raw.update(self._spacy.extract(deob.normalized))

        entities = {self._enrich_with_original(e, deob) for e in raw}
        entities = self._dedupe_subsumed_domains(entities)

        # Ordinamento stabile: prima per tipo, poi per valore.
        return sorted(entities, key=lambda e: (e.type, e.value.lower()))

    # ─────────────────────────────────────────────────────────
    # Ricostruzione di original dalla mappa indici
    # ─────────────────────────────────────────────────────────

    @staticmethod
    def _enrich_with_original(entity: Entity, deob: DeobfuscationResult) -> Entity:
        """
        Cerca la prima occorrenza di entity.value nel testo normalizzato,
        ricostruisce la forma originale e ritorna un'Entity arricchita.

        Se il value non si trova nel normalizzato (caso raro: può capitare
        se l'extractor ha applicato normalizzazione interna come il
        lowercase di domini), ritorna l'entità invariata.
        """
        # Caso 1: il value è cercabile direttamente nel normalizzato
        idx = deob.normalized.find(entity.value)

        # Caso 2: l'extractor ha lowercato (domini, hash). Riproviamo.
        if idx == -1:
            idx = deob.normalized.lower().find(entity.value.lower())

        if idx == -1:
            # Non riusciamo a localizzare: lasciamo invariata.
            # Probabile che value sia il risultato di una normalizzazione
            # più aggressiva (es. phone con strip whitespace). In v0.2
            # il telefono non è ancora normalizzato in E.164, quindi
            # questo caso è raro. Da v0.3 servirà strategia diversa.
            return entity

        original_substring = deob.original_substring(idx, idx + len(entity.value))

        # Se le due forme coincidono testualmente (case-insensitive
        # lato originale per coerenza con domini/hash), non c'è
        # deobfuscazione: lasciamo invariata.
        if original_substring == entity.value:
            return entity

        # Preserva tutti i campi dell'Entity originale (v0.4: confidence,
        # metadata, derived_from). Senza questa copia il flag suspicious_tld
        # sui domini deobfuscati (es. evil[.]xyz) andrebbe perso.
        return Entity(
            type=entity.type,
            value=entity.value,
            original=original_substring,
            confidence=entity.confidence,
            metadata=dict(entity.metadata),
            derived_from=entity.derived_from,
        )

    # ─────────────────────────────────────────────────────────
    # Dedup interna (invariata da v0.1)
    # ─────────────────────────────────────────────────────────

    @staticmethod
    def _dedupe_subsumed_domains(entities: set[Entity]) -> set[Entity]:
        """
        Rimuove le entità `domain` il cui valore coincide con l'host
        di un URL o con la parte dominio di un'email già estratti.
        """
        covered: set[str] = set()

        for e in entities:
            if e.type == "url":
                host = _host_of(e.value)
                if host:
                    covered.add(host.lower())
            elif e.type == "email":
                _, _, domain = e.value.partition("@")
                if domain:
                    covered.add(domain.lower())

        return {
            e for e in entities
            if not (e.type == "domain" and e.value.lower() in covered)
        }


def _host_of(url: str) -> str | None:
    """Estrae l'host da un URL. Ritorna None se il parse fallisce."""
    try:
        parsed = urlparse(url)
        return parsed.hostname
    except ValueError:
        return None
