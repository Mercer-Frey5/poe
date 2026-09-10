"""
deobfuscator.py — preprocessore per defanging comune di IoC.

Trasforma il testo "defanged" (dove i bad actor neutralizzano i link
per evitare click accidentali e bypass parziale di filtri email) in
testo normalizzato che la pipeline di estrazione può processare
direttamente.

Sostituzioni v0.2 (minimal set, conservative):
    hxxp://    → http://
    hxxps://   → https://
    [.]        → .
    [:]        → :
    (at)       → @
    (dot)      → .

L'output è il testo normalizzato + una mappa che permette, per
ciascun match futuro, di risalire alla forma "originale" che era
nel testo prima della normalizzazione. Questo serve per popolare
il campo `Entity.original` quando la pipeline di estrazione
trova entità nel testo deobfuscato.

L'algoritmo: scorriamo il testo originale carattere per carattere,
quando troviamo una sostituzione la applichiamo e registriamo nella
mappa l'intervallo (start_in_normalized, end_in_normalized) →
substring originale corrispondente. Per le porzioni non toccate la
mappa contiene la sostituzione identità.

Un singolo match nel testo normalizzato (es. un URL) può attraversare
zone "intoccate" e zone "deobfuscate": ricostruire la sua forma
originale richiede di mappare ogni indice del normalizzato all'indice
corrispondente nell'originale. La struttura `_index_map` fa esattamente
questo.
"""

from __future__ import annotations

from dataclasses import dataclass


# Sostituzioni in ordine di priorità.
# Ordine importante: "hxxps://" deve essere tentato PRIMA di "hxxp://"
# perché altrimenti "hxxps://" viene scomposto in "hxxp" + "s://".
_SUBSTITUTIONS = (
    ("hxxps://", "https://"),
    ("hxxp://",  "http://"),
    ("[.]",      "."),
    ("[:]",      ":"),
    ("(at)",     "@"),
    ("(dot)",    "."),
)


@dataclass
class DeobfuscationResult:
    """
    Output del deobfuscator.

    Attributi:
      normalized: il testo dopo deobfuscazione
      index_map:  per ogni indice in normalized (0..len(normalized)),
                  index_map[i] è l'indice corrispondente in original
                  ALL'INIZIO del carattere — utile per mappare match
                  da normalized a original
      original:   il testo di partenza (per ricostruire substring)
    """
    normalized: str
    index_map: list[int]
    original: str

    def original_substring(self, start: int, end: int) -> str:
        """
        Dato un intervallo [start, end) sul testo normalizzato,
        ritorna la substring corrispondente nel testo originale.
        """
        if start >= len(self.index_map):
            return ""
        orig_start = self.index_map[start]
        if end >= len(self.index_map):
            orig_end = len(self.original)
        else:
            orig_end = self.index_map[end]
        return self.original[orig_start:orig_end]


def deobfuscate(text: str) -> DeobfuscationResult:
    """
    Applica le sostituzioni di deobfuscazione e ritorna un
    DeobfuscationResult con la mappa per risalire alle forme originali.
    """
    if not text:
        return DeobfuscationResult(normalized="", index_map=[0], original=text)

    out_chars: list[str] = []
    index_map: list[int] = []
    i = 0
    n = len(text)

    while i < n:
        # Tenta ogni sostituzione in ordine; la prima che matcha vince.
        matched = False
        for src, dst in _SUBSTITUTIONS:
            if text.startswith(src, i):
                # Aggiungiamo dst al risultato. Tutti i caratteri di dst
                # mappano all'indice di partenza del match nell'originale.
                # È un'approssimazione: per un singolo carattere sostituito
                # è esatta; per stringhe come "hxxps://"→"https://" la
                # mappa è "appiattita" (ogni char di "https://" punta a
                # 'h' di "hxxps"), ma per il caso d'uso della ricostruzione
                # di substring ai bordi del match, è perfettamente
                # sufficiente.
                for _ in dst:
                    index_map.append(i)
                out_chars.append(dst)
                i += len(src)
                matched = True
                break

        if not matched:
            out_chars.append(text[i])
            index_map.append(i)
            i += 1

    # Sentinella finale: l'indice "uno oltre l'ultimo" punta a len(original).
    # Permette a original_substring di gestire end == len(normalized).
    index_map.append(n)

    return DeobfuscationResult(
        normalized="".join(out_chars),
        index_map=index_map,
        original=text,
    )
