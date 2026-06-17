"""
models.py — schema dati interno di POE v0.4.

Entity è l'unità atomica che la pipeline di riconoscimento produce.

Schema cumulativo per versione:
    v0.1: type, value
    v0.2: + original (diverge con deobfuscazione)
    v0.3: (invariato, original esteso a phone E.164)
    v0.4: + confidence, metadata, derived_from

confidence: Literal['high','medium','low'] — livello di fiducia onesto
    sull'entità estratta, assegnato dal Recognizer in base al metodo
    di estrazione. Vocabolario controllato in app/config/confidence_vocabulary.yaml.
    NOTA SYNC: _VALID_CONFIDENCE deve restare allineato al YAML.

metadata: dict — dati supplementari dipendenti dal tipo.
    Esempi: {'country_code': 39, 'national_number': 3471234567} per phone.
    Non partecipa all'hash né all'uguaglianza (è arricchimento, non identità).

derived_from: str | None — id dell'entità da cui questa è derivata.
    Schema A5 fase 1: solo campo, nessuna logica nuova. La relazione
    viene resa esplicita in v0.5 fase 2 con la revisione della dedup.

Immutabilità: frozen=True previene riassegnazione degli attributi ma
non la mutazione di metadata (dict). Per convenzione, metadata non va
mai mutato dopo la costruzione dell'Entity.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# Vocabolario controllato per confidence. Deve restare allineato con
# app/config/confidence_vocabulary.yaml (il YAML è la fonte per UI e
# documentazione, questa frozenset è la guardia runtime).
_VALID_CONFIDENCE: frozenset[str] = frozenset({'high', 'medium', 'low'})


@dataclass(frozen=True)
class Entity:
    type: str
    value: str
    original: str | None = None
    confidence: str = field(default='medium', hash=False, compare=False)
    metadata: dict = field(default_factory=dict, hash=False, compare=False)
    derived_from: str | None = field(default=None, hash=False, compare=False)

    def __post_init__(self) -> None:
        if self.original is None:
            object.__setattr__(self, 'original', self.value)
        if self.confidence not in _VALID_CONFIDENCE:
            raise ValueError(
                f"confidence '{self.confidence}' non valida. "
                f"Valori ammessi: {sorted(_VALID_CONFIDENCE)}"
            )

    def to_dict(self) -> dict:
        """Serializzazione per storage JSON e output API."""
        return {
            'type': self.type,
            'value': self.value,
            'original': self.original,
            'confidence': self.confidence,
            'metadata': self.metadata,
            'derived_from': self.derived_from,
        }

    @property
    def is_deobfuscated(self) -> bool:
        """True se la forma originale differisce dal value normalizzato."""
        return self.original != self.value
