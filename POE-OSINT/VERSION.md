# POE — Version History

Questo file traccia cosa ogni versione di POE contiene e cosa è cambiato.
Aggiornato a mano a ogni rilascio.

Principio: ogni versione è funzionante end-to-end nel suo perimetro,
testabile, reversibile via tag Git.

---

## v0.4 — fondazioni + idee piccole + idee grandi fase 1 (in pianificazione, maggio 2026)

**Scopo**: consolidare le fondazioni del progetto (scope dichiarato,
due nuovi principi architetturali, schema entità esteso), implementare
una serie di idee piccole intere, e avviare in fase 1 quattro idee
grandi che maturano in v0.4 → v0.5.

**Stato**: pianificata in chat *Architettura* il 3 maggio 2026.
Implementazione non ancora avviata.

**Stima di lavoro**: ~11.5 giorni effettivi. Più del doppio di v0.2 e
v0.3 (~5-7 giorni ciascuna), ma giustificato dalle fondazioni nuove
introdotte.

### Fondazioni

- **Scope dichiarato di POE**: registrato in `STATUS.md` come
  *"strumento personale di ricerca, prevalentemente su persone"*.
  Orienta la priorità dei tipi (tax_id, vat_id, social_handle,
  birth_date), il futuro catalogo OSINT, gli enricher LLM
- **Principio architetturale 3 — Trasparenza della confidenza**:
  registrato in `STATUS.md`. Ogni entità ha un livello di confidenza
  onesto, qualitativo (`high` / `medium` / `low`). POE non filtra
  entità a confidenza bassa, le mostra con marcatura onesta
- **Principio architetturale 4 — Offline-first con ridondanza
  investigativa**: registrato in `STATUS.md`. POE è prevalentemente
  offline, le funzionalità deterministiche restano in locale, le
  scelte online sono esplicite. Per ogni domanda esistono più strade,
  non un'autorità singola
- **Schema `Entity` esteso**: nuovi campi `confidence:
  Literal['high','medium','low']` e `metadata: dict` (per country_code,
  derived_from, ecc.). Backfill in lettura per entità di v0.2/v0.3
  (default `confidence='medium'`, `metadata={}`). Nessuna migrazione
  DB esplicita richiesta

### Idee piccole intere

1. **A1 — Country code phone in UI**: il `phone_normalizer` di v0.3
   produce già `country_code` e `national_number`. v0.4 li espone in UI
   (bandiera + nome paese). Esposti via `Entity.metadata`
2. **A2 — Phone con punti come separatori**: estensione regex per
   catturare formati tipo `347.123.4567`. Test bene contro IP, hash,
   URL che usano punti per altre ragioni
3. **A3'.2 — `tax_id` italiano con check digit**: nuovo tipo regex,
   16 caratteri alfanumerici con verifica del codice di controllo.
   Confidenza alta per costruzione
4. **A3'.3 — `vat_id` italiano con check digit**: nuovo tipo regex,
   11 cifre con verifica check digit. Confidenza alta
5. **B1 — Flag `suspicious_tld`**: lista statica curata in
   `app/config/suspicious_tlds.yaml` (~30 voci iniziali). Marca
   domini con TLD sospetto. Datata e versionata. Confidenza media
   (la lista evolve)
6. **C1' — Punteggio osservazione baseline**: algoritmo somma pesata
   delle confidenze entità (alta=3, media=2, bassa=1) + bonus per
   varietà di tipi. Normalizzato 0-100. Visibile nello storico
7. **C3 — Embrione export Markdown**: bottone "Esporta" nella vista
   dettaglio. Output Markdown statico (titolo, data, input, entità
   raggruppate per tipo con confidenza). Niente prosa narrativa
   (LLM in v0.6)
8. **E2 — `BaseEnricher` polimorfico (interfaccia astratta)**: classe
   `BaseEnricher` con metodo `enrich(entity) -> EnrichedEntity`.
   Solo definizione. Implementazioni in v0.6+ (Qwen) e v0.7 (Claude)

### Idee grandi — fase 1 (continuano in v0.5 fase 2)

1. **A3'.1 — `social_handle` come tipo (fase 1)**: riconoscimento
   del pattern `@handle`. Senza classificazione automatica della
   piattaforma. Confidenza media
2. **A3'.4 — `birth_date` con marcatori contestuali (fase 1)**: solo
   date precedute da marcatori espliciti ("nato il", "data di nascita",
   "DOB"). Confidenza bassa per costruzione (la data senza contesto
   è ambigua)
3. **A5 fase 1 — Schema `derived_from` in `Entity`**: solo campo nello
   schema, nessun cambio della logica di dedup. Prepara la fase 2 in
   v0.5 (URL/email producono entità domain derivata con relazione)
4. **C2 fase 1 — Cronologia curabile minimale**: flag `kept: bool`
   in DB osservazioni, vista filtrata semplice (tutto / solo kept /
   solo bozze). Niente note manuali, tag, eliminazione singola — quelli
   in v0.5 fase 2
5. **E1 fase 1 — Schema YAML del catalogo OSINT**: solo struttura
   dichiarativa (formato delle voci, campi obbligatori e opzionali).
   File vuoto. Popolamento del catalogo con risorse vere in v0.5 fase
   2, in coordinamento con chat *OSINT/Metodologia*

### UI — Visualizzazione confidenza

- Schema interno: `confidence: Literal['high', 'medium', 'low']`
- UI: colore (verde/giallo/rosso) + etichetta testuale
  ('Alta' / 'Media' / 'Bassa') + fascia indicativa di percentuale
  (es. "80-100%" per alta, "50-79%" per media, "0-49%" per bassa)
- Niente percentuale puntuale: il dato che POE ha è qualitativo,
  inventare un numero preciso sarebbe disonesto

### B2 — Flag `bogon` su IP — in coda

In coda nello scope di v0.4. Va implementato **solo se v0.4 chiude
sotto budget**. Costo basso (~1 giorno) ma valore d'uso modesto nello
scope "ricerca persone": gli IP bogon scattano raramente in indagini
personali. Se non entra in v0.4 slitta a v0.5 o v0.6.

### Cosa NON è in v0.4

- Catalogo OSINT popolato (solo schema in v0.4 fase 1, popolamento
  in v0.5)
- Template dossier (v0.5)
- LLM (v0.6 Qwen, v0.7 Claude)
- Sistema di confidenza reward-based (v0.6+, sessione architetturale
  dedicata)
- Logging strutturato (v0.6+)
- Test di regressione visiva con browser automatizzato (v0.5+)
- Tipi crypto (`bitcoin_address`, `ethereum_address`) — fuori scope
  "ricerca persone", non previsti
- Tipi SOC (`ipv6`, `asn`, `mac_address`) — fuori scope, non previsti
- Cronologia curabile completa (note, tag, eliminazione) — v0.5 fase 2
- Classificazione piattaforma su social_handle — v0.5 fase 2
- Revisione completa dedup URL/email → domain — v0.5 fase 2

### Test attesi

Stima ~30-40 nuovi test, di cui:
- Validazione check digit `tax_id` e `vat_id` (positivi e negativi)
- Estrazione `social_handle` con varianti
- Estrazione `birth_date` con marcatori
- Pattern phone con punti
- Calcolo punteggio osservazione su input campione
- Schema `confidence` e `metadata` su `Entity`
- Backfill in lettura per entità v0.3 (compatibilità storica)
- Export Markdown (snapshot test)
- Lista suspicious_tld caricamento e match

### Breaking change

- **Schema entità**: nuovi campi `confidence` e `metadata` su `Entity`.
  Backfill in lettura per `entities_json` storici (default `medium`,
  `{}`). Nessuna migrazione DB esplicita
- **`Entity` ha 5 campi ora**: `type`, `value`, `original`,
  `confidence`, `metadata`. Era 3 in v0.3

### Tag Git

`v0.4` (da apporre al rilascio)

---

## v0.3 — backend di base + cleanup theming + fix UX (rilasciata, maggio 2026)

**Scopo**: consolidamento della pipeline di estrazione (whitelist TLD
ufficiale, stoplist esternalizzata, normalizzazione phone E.164),
collasso del sistema multi-tema in identità visiva fissa, debito tecnico
cache busting saldato.

### Capitolo 1 — Cache busting

- Suffisso `?v=0.3.0` su `style.css` e `app.js` in `app/templates/base.html`
- Strategia: stringa hardcoded aggiornata manualmente a ogni rilascio
- Convenzione formalizzata in `STATUS.md` sezione "Convenzioni di rilascio"

### Capitolo 2 — Cleanup theming a singolo tema

- Sistema multi-tema rimosso: 7 blocchi `[data-theme="..."]` cancellati
- Palette `tech-mono` con asset locali Operatore migrata nel `:root` unico
- Anti-flash script eliminato, tendina selettore tema rimossa
- `app.js` ridotto a 3 responsabilità: `charCounter`, `copyButtons`,
  `submitOnEnter`
- Rimosso codice morto: `VALID_THEMES`, `applyTheme`, `getCurrentTheme`,
  `initThemeSwitcher`, persistenza localStorage del tema
- Google Fonts potato da 9 famiglie a 2: `IBM Plex Mono` + `Orbitron`
- Variabile `--font-brand` conservata per il logo POE (regola R3 in
  `STATUS.md`)
- Bilancio righe: `style.css` 909→604, `app.js` 175→131, `base.html` 87→51

### Capitolo 3 — Backend di base

- **IANA TLD list**: nuova cartella `app/config/`, file `tld_list.yaml`
  con seed di 140 TLD comuni, script `scripts/refresh_tlds.py` per
  refresh manuale via `data.iana.org`. Loader `_load_known_tlds()` in
  `regex_extractor.py` con fail-fast su file mancante o malformato
- **Stoplist `person_name` esternalizzata**: file
  `app/config/stoplist_person_name.yaml`, loader `_load_stoplist()` in
  `spacy_extractor.py` con stesso pattern fail-fast
- **Normalizzazione phone E.164**: nuova dipendenza
  `phonenumbers>=8.13.0`, modulo nuovo `app/phone_normalizer.py`. Default
  regionale italiano con rispetto del prefisso esplicito (es. `+44` UK
  riconosciuto correttamente). Pattern `original`/`value` esteso al
  phone. Numeri `is_valid_number=False` scartati silenziosamente.
  `NormalizedPhone` come `dataclass` con `e164`, `country_code`,
  `national_number`, `is_valid` — porta aperta a v0.4 (Recognizer di
  v0.3 usa solo `e164`)

### Fix UX — auto-aggiornamento sezione history

Promosso a v0.3 come scope creep accettato. Motivazione: comportamento
incoerente già latente in v0.2 (history non si aggiornava dopo
un'osservazione, richiedeva reload manuale).

- Pattern HTMX out-of-band swap (OOB) introdotto e formalizzato come
  regola R4 in `STATUS.md`
- Server in una sola response invia frammento principale (`#results`) +
  frammento OOB (`#history`)
- Wrapper `<section id="history">` sempre presente nel DOM, anche con
  DB vuoto
- Nuovo partial `_history.html` riusabile da `index.html` (server-side
  al primo GET) e `results.html` (frammento OOB del POST)
- Convenzione partial `_filename.html` formalizzata come regola R5 in
  `STATUS.md`
- Route `/analyze` ora calcola anche `recent = get_recent(10)` e lo passa
  al template

### Numeri

- Test automatici: 70 (v0.2) → 103 (v0.3), +33
- Nuovi file: 5 di codice/config + 4 di test
- File pre-esistenti modificati: 8
- Bilancio righe front-end: ~−380 (cleanup theming)

### Dipendenze

- Nuova: `phonenumbers>=8.13.0` (richiede `pip install -r requirements.txt`
  o aggiornamento ambiente)
- Rimosse a livello concettuale: 7 famiglie Google Fonts (caricate ma
  non più usate)

### Schema database

Invariato. Nessuna migrazione necessaria per upgrade da v0.2 a v0.3.
Regola formalizzata in `STATUS.md` sezione "Convenzioni di rilascio".

### Limiti noti registrati per v0.4+

- Phone con punti come separatori non catturato dal regex
- Dipendenza cross-modulo `regex_extractor → phone_normalizer`
  (accettabile per ora, da rivalutare se cresce)
- Refresh IANA TLD richiede rete (non air-gapped)
- `phonenumbers` aggiornamento dati regionali via pip

(Tutte registrate in dettaglio in `STATUS.md` sezione "Note aperte".)

### Tag Git

`v0.3`

---

## v0.2 — riverniciatura UI + robustezza pipeline (rilasciata, maggio 2026)

**Scopo**: prima vera personalizzazione dell'interfaccia e tre piccole
aggiunte di robustezza al backend deterministico.

### Front-end

1. **Sistema di theming via CSS custom properties**: tutti i colori e i
   font vivono in variabili CSS. Nessun valore hardcoded in HTML o codice.
   Vincolante come regola di design da qui in avanti.

2. **Quattro temi pre-costruiti** (slug tecnici esposti nell'UI):
   - `raven-elegante` — nero profondo + accenti oro/rame, serif elegante
   - `neon-cyber` — nero/blu + ciano-magenta neon, font sci-fi squadrato
   - `tech-noir` — grigio/nero caldo + ambra, IBM Plex (DEFAULT)
   - `signal-ops` — nero verdastro + verde fosforo, monospace ovunque

3. **Sistema font intercambiabile** con una coppia per tema. Caricamento
   da Google Fonts via un singolo link `?family=...` con `display=swap`.

4. **Selettore tema** (tendina nel header), persistenza via
   `localStorage["poe-theme"]`. Anti-flash via script inline in
   `<head>` che applica `data-theme` prima del rendering body.

5. **Microcopy POE concierge** (3 punti):
   - Saluto home: *"Buongiorno, Operatore. Le osservo con discrezione…"*
   - Placeholder textarea: *"Incolli qui ciò che desidera farmi osservare…"*
   - Spinner: *"Sto osservando…"*

6. **Tasti**: `Enter` lancia il submit, `Shift+Enter` (e altri modificatori)
   inserisce newline.

### Backend

7. **Stoplist label words italiane per `person_name`** in SpacyExtractor.
   Lista iniziale (~17 voci). Match esatto case-insensitive, scarto
   silenzioso. Fix del FP noto su "Contatto".

8. **Due nuovi tipi regex**: `hash_sha256` (64 hex), `cve` (`CVE-YYYY-NNNN+`).

9. **Deobfuscatore** in nuovo modulo `app/deobfuscator.py`.
   Sostituzioni: `hxxp://`, `hxxps://`, `[.]`, `[:]`, `(at)`, `(dot)`.
   Mantiene una `index_map` per ricostruire la forma originale dei
   match. Il Recognizer popola `Entity.original` quando differisce.

### Schema entità

`Entity` ora ha tre campi: `type`, `value`, `original`. In v0.1 i due
ultimi coincidevano per costruzione; il deobfuscator introduce la prima
divergenza reale. `original` ha default = `value` (post-init).

Visualizzazione: `original` mostrato in piccolo accanto a `value`
solo quando differisce.

### Test

70 test totali, tutti passanti.

### Dipendenze

Nessuna nuova dipendenza Python. Le famiglie font sono caricate
runtime da Google Fonts (no self-hosting in v0.2).

### Breaking change

- Schema entità: il campo `original` può divergere da `value`.
- Storage: schema della tabella invariato, MA il payload JSON
  `entities_json` ha un nuovo campo `original`. Backfill automatico
  in lettura per record v0.1 ancora presenti nel DB; raccomandata
  comunque la migrazione esplicita (`rm data/poe.db`).

### Note post-rilascio (sessione di refinement)

Dopo il rilascio v0.2, l'Operatore ha condotto una sessione di esplorazione
font/temi che ha prodotto:

- **Bug 1 (specificità CSS)**: blocco `:root` di fallback duplicato dopo
  i blocchi tema → vinceva sempre lui per posizione, sovrascrivendo i temi
  selezionati. Fixato unificando `:root` all'inizio del file.
- **Bug 2 (cache browser)**: dopo la fix, Chrome continuava a servire il
  CSS bugged perché cachato. Risolto con hard refresh, ma ha generato il
  debito *cache busting* poi saldato in v0.3.
- **Aggiunta sperimentale**: nuova variabile `--font-brand` (Orbitron in
  tutti i temi per il logo POE), e tre temi sperimentali (`tech-cyber`,
  `cyber-ops`, `tech-mono`).
- **Decisione strategica**: l'esplorazione si è chiusa con `tech-mono`
  scelto come unico tema definitivo. v0.3 ha collassato il sistema
  multi-tema.
- **Modifiche locali Operatore su tech-mono**: NON entrate in v0.2,
  preservate e applicate in v0.3.

### Tag Git

`v0.2`

---

## v0.1 — walking skeleton (rilasciata, aprile 2026)

**Scopo**: pipeline di riconoscimento grezzo di tipo di entità,
end-to-end, locale.

### Funzionalità

- Interfaccia web su `http://localhost:8000`
- Textarea multi-riga + bottone "Osserva"
- Output: entità raggruppate per tipo, ciascuna con bottone copia
- Storage SQLite, storico recenti, pagina di dettaglio
- Health probe su `/health`

### Tipi di entità riconosciuti (8)

`email`, `ipv4`, `url`, `domain`, `hash_md5`, `username`, `phone`, `person_name`

### Stack di estrazione

- Regex per 7 tipi a pattern forte
- spaCy NER (`it_core_news_lg` + `en_core_web_lg`) per `person_name`
- Whitelist TLD statica (~90 voci) per filtrare falsi positivi tipo
  "mario.rossi" → debito tecnico saldato in v0.3 (passaggio a IANA)

### Dedup

Se un dominio è coperto dall'host di un URL estratto o dalla parte
dopo `@` di un'email estratta, non viene emesso come entità `domain`
separata.

### Tag Git

`v0.1`

---

## Convenzioni di versionamento

- `v0.X` — rilasci minori che aggiungono funzionalità pianificate in roadmap
- `v0.X.Y` — patch di correzione su un rilascio `v0.X` esistente
- `V1.0` — prima release stabile con tutte le capacità di Livello 2 integrate
- Ogni rilascio è taggato in Git: `git tag v0.X.Y`

---

*POE osserva. Versione dopo versione.*
