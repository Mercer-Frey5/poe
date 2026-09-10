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

# Tipi NER 'soft' (spaCy/LLM): person_name/org_name/address. A differenza dei tipi
# strutturati (domain/email/url/ip/hash/...) sono soggetti a falsi positivi e non
# devono coesistere con lo stesso valore già riconosciuto come strutturato.
_SOFT_NER_TYPES = frozenset({"person_name", "org_name", "address"})


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
        entities = self._add_correlated_domains(entities)
        entities = self._suppress_ner_overlaps(entities)

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
    def _add_correlated_domains(entities: set[Entity]) -> set[Entity]:
        """
        Aggiunge domini DERIVATI per correlazione: l'host di ogni URL e la
        parte dominio di ogni email diventano un'entità `domain` a sé,
        marcata (`derived_from` + metadata['derived_source']) così è chiaro
        che proviene dalla correlazione e non dal testo letterale.

        Esempi:
          http://secure-update.xyz/verify → domain secure-update.xyz (da url)
          admin@malware.com               → domain malware.com       (da email)

        Non duplica un dominio già presente letteralmente nel testo.
        """
        # host (lowercase) → (source, valore-origine) da URL ed email
        derived: dict[str, tuple[str, str]] = {}
        for e in entities:
            if e.type == "url":
                h = _host_of(e.value)
                if h:
                    derived.setdefault(h.lower(), ("url", e.value))
            elif e.type == "email":
                _, _, dom = e.value.partition("@")
                if dom:
                    derived.setdefault(dom.lower(), ("email", e.value))

        if not derived:
            return entities

        result: set[Entity] = set()
        seen: set[str] = set()
        for e in entities:
            if e.type == "domain" and e.value.lower() in derived:
                # Dominio già estratto che coincide con host di URL/email:
                # lo MARCHIAMO come derivato (correlazione esplicita).
                src, src_val = derived[e.value.lower()]
                seen.add(e.value.lower())
                result.add(Entity(
                    type="domain", value=e.value, original=e.original,
                    confidence=e.confidence, derived_from=src_val,
                    metadata={**e.metadata, "derived_source": src},
                ))
            else:
                result.add(e)

        # Domini derivati non ancora presenti come entità domain → aggiungili.
        for host, (src, src_val) in derived.items():
            if host not in seen:
                result.add(Entity(
                    type="domain", value=host, confidence="medium",
                    derived_from=src_val, metadata={"derived_source": src},
                ))

        return result

    # ─────────────────────────────────────────────────────────
    # Soppressione falsi positivi NER sovrapposti a tipi strutturati
    # ─────────────────────────────────────────────────────────

    @staticmethod
    def _suppress_ner_overlaps(entities: set[Entity]) -> set[Entity]:
        """Scarta un'entità NER 'soft' (person_name/org_name/address) se lo STESSO
        valore è già riconosciuto come tipo strutturato (domain/email/url/ipv4/hash/
        ...). spaCy a volte tagga un dominio come person_name: senza questa
        soppressione due entità con lo stesso valore ma tipo diverso collidono a
        valle (catalog_resources è keyed per valore) e la sezione dominio non parte."""
        structured = {
            e.value.lower() for e in entities if e.type not in _SOFT_NER_TYPES
        }
        return {
            e for e in entities
            if not (e.type in _SOFT_NER_TYPES and e.value.lower() in structured)
        }


def _host_of(url: str) -> str | None:
    """Estrae l'host da un URL. Ritorna None se il parse fallisce."""
    try:
        parsed = urlparse(url)
        return parsed.hostname
    except ValueError:
        return None
