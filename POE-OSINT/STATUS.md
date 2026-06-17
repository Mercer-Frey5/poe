# POE — Stato del progetto

> Snapshot vivo del progetto POE (Personal Observation Engine).
> Da aggiornare a mano dopo ogni decisione strategica o milestone.
> È la memoria persistente del progetto: se lo trovi obsoleto,
> aggiornalo *prima* di scrivere codice.

**Ultimo aggiornamento**: 10 giugno 2026 (riordino repo post-pipeline vocale)
**Versione corrente**: v0.3 (backend di base + cleanup theming + fix UX history, rilasciata)
**Ambiente di sviluppo principale**: macOS (MacBook Air M1 16GB) dal 3 maggio 2026
**Prossima versione**: v0.4 (pianificata, fondazioni + idee piccole + idee grandi in fase 1)

> **Nota 10 giugno 2026**: tra maggio e giugno il lavoro si è concentrato su POE-Home
> (pipeline vocale, completata — vedi `POE-Home/VOICE-PIPELINE.md`). POE-OSINT è rimasto
> fermo a v0.3, stabile e funzionante. La v0.4 non è partita. Prossimo contatto con OSINT:
> la fase AGNO, dove la pipeline v0.3 verrà avvolta come tool dell'agente OSINT
> (interfaccia modulo, output duale). Principi invariati: base deterministica, LLM ospiti.

---

## Strategia di sviluppo

POE viene costruito con **rilasci incrementali versionati**, non con
una V1 monolitica. Ogni rilascio è funzionante end-to-end nel suo
perimetro, testabile, reversibile via tag Git.

Dettagli di ciascuna versione in `VERSION.md`.

---

## Scope di POE

> **POE è strumento personale di ricerca, prevalentemente su persone.**

Non è un tool SOC né uno strumento di triage di IoC enterprise. È
strumento personale dell'Operatore, orientato a indagini su persone
(profili, recapiti, identificatori), con uso secondario su altri tipi
di entità OSINT.

Questo scope orienta tutte le decisioni di v0.4 in avanti: i tipi
prioritari (tax_id, vat_id, social_handle, birth_date), le risorse
del futuro catalogo OSINT, gli enricher LLM. Anche se POE può
processare IP, hash, CVE — questi restano supporto, non centro.

Dichiarazione introdotta dopo v0.3 (3 maggio 2026), in coordinamento
con il riposizionamento dei principi architetturali.

---

## Principio architetturale fondativo

> **La base di POE è deterministica e verificabile. I LLM sono ospiti
> che entrano su richiesta esplicita dell'Operatore, con ruoli distinti
> e non sovrapposti. Ogni LLM vede solo ciò che gli serve per fare il
> suo mestiere, niente di più.**

Conseguenza diretta: **nessun LLM tocca mai i dati estratti**. Il LLM
non può inventare, modificare o correggere entità. Il LLM scriverà
(da v0.6 in poi) solo prosa commentativa, sopra dati consegnati già
strutturati.

---

## Principio di identità visiva

> **L'identità visiva di POE è fissa, non configurabile.**

v0.2 ha esplorato lo spazio dei temi (4 ufficiali + 3 sperimentali aggiunti
in post-rilascio). L'esplorazione si è chiusa con una scelta univoca:
**da v0.3, POE ha un solo tema visivo** — la variante tech-mono nelle
modifiche locali dell'Operatore.

Coerente con la persona concierge di Altered Carbon: non offre opzioni
di décor, ha la sua eleganza e basta.

---

## Principio di trasparenza della confidenza

> **POE marca ogni entità con un livello di confidenza onesto. Mai
> nasconderlo, mai gonfiarlo. La confidenza riflette la natura della
> verifica, non il desiderio di sembrare affidabili.**

Tassonomia di confidenza in v0.4:

- **Verifica matematica/strutturale** (regex con check digit, range RFC,
  formula deterministica) → confidenza **alta**
- **Verifica formale** (regex senza check digit, pattern morfologico,
  libreria validatrice) → confidenza **media**
- **Estrazione statistica** (NER di spaCy, dictionary lookup) →
  confidenza **media-bassa**, dipende dal contesto
- **Pattern catturato senza verifica esterna** (date generiche,
  username generici) → confidenza **bassa**

POE non filtra le entità a confidenza bassa — le mostra tutte, ma
le marca onestamente. L'Operatore decide cosa pesare e cosa
verificare con altri strumenti.

In v0.4 la confidenza è qualitativa (`high` / `medium` / `low`) e
assegnata per tipo di estrazione. Da v0.6+ il sistema evolve verso
**reward-based**: la confidenza emerge dal calcolo cross-entità —
ridondanza del dato (entità che appare in più forme nel testo),
correlazioni (`tax_id` + `email` + `person_name` coerenti tra loro
si rinforzano a vicenda), supporto contestuale (presenza di
marcatori "nato il", "indirizzo:", ecc.). Il campo `Entity.confidence`
resta lo stesso, l'algoritmo che lo popola si evolve.

Introdotto in v0.4 (3 maggio 2026).

---

## Principio offline-first con ridondanza investigativa

> **POE è prevalentemente offline. Tutto ciò che POE sa fare bene
> deterministicamente in locale resta in locale. Quando si va online,
> è scelta esplicita dell'Operatore, mai automatismo.**
>
> **E per ogni domanda investigativa esistono più strade, non una sola
> autorità. La ridondanza è valore, non spreco.**

Conseguenze pratiche:

- Le funzionalità deterministiche (regex, check digit, dictionary
  locali, normalizzatori, flag basati su liste statiche) sono
  **sempre attive offline** e prioritarie
- Le risorse del catalogo OSINT (in v0.5) saranno marcate con il
  loro requisito di rete: alcune offline, alcune browser-based con
  rete, alcune API pure. L'Operatore vede chiaramente cosa attiva cosa
- Gli enricher LLM (v0.6 Qwen, v0.7 Claude) sono attivati con
  **bottoni espliciti**, mai automaticamente
- Per ogni tipo di entità il catalogo OSINT (v0.5) offrirà
  **più tool/siti/dorks**, non una singola "fonte autorevole".
  L'Operatore incrocia, POE non sceglie per lui

Sottinteso architetturale: diffidenza dell'autorità singola. Nessuna
fonte è infallibile. Triangolare più fonti dà fiducia maggiore di
qualunque fonte singola.

Sottinteso operativo: sovranità dei dati. Le query investigative
dell'Operatore (chi sta cercando, su chi, perché) non vengono
trasmesse a nessuno se POE può lavorare in locale.

Introdotto in v0.4 (3 maggio 2026).

---

## Meta-principio: tipo vs flag

> **Un nuovo tipo di entità si introduce quando si verificano tutti e
> tre questi criteri:**
>
> 1. **Ricorrenza osservata** nei casi reali gestiti dall'Operatore
> 2. **Catalogo OSINT dedicato** — esistono risorse (web, dork, tool CLI)
>    specifiche per quella categoria, distinte da quelle del tipo genitore
> 3. **Domanda investigativa distinta** — l'Operatore pone domande diverse
>    rispetto al tipo genitore
>
> **Sotto tre-su-tre, si estende un tipo esistente con un flag**.
>
> **Al dubbio, flag.**

I tre criteri sono congiuntivi (AND). Il più ostativo è il secondo:
finché non c'è catalogo dedicato, promuovere a tipo è prematuro.

---

## Decisioni architetturali attive

### Stack

| Area | Decisione | Motivazione |
|---|---|---|
| Linguaggio | Python 3.12 (vincolato a `>=3.12,<3.14`) | Ecosistema OSINT nativo. Limite superiore per assenza wheel spaCy 3.8.x su Python 3.14, da rilassare quando la dipendenza supporterà |
| Gestione ambiente Python | `uv` (Astral) come tool primario, `venv` + `pip` come fallback | Workflow identico cross-platform Mac/Windows/Linux, ~100x più veloce di pip, lockfile deterministico (`uv.lock`), gestione automatica della versione Python. Adottato durante porting Mac (v0.3 post-rilascio) |
| Web framework | FastAPI + HTMX + Jinja2 | Server-side rendering leggero, niente build step |
| Storage | SQLite | Zero infrastruttura, portabile |
| Deploy | Docker opzionale, locale diretto supportato | Meno frizione su Windows |
| LLM locale (da v0.6) | Qwen 3 8B via Ollama | Structured output affidabile |
| LLM frontier (da v0.7) | Claude via API Anthropic | Solo on-demand, controllato dall'Operatore |
| Persona POE (da v0.7) | Vive solo nell'output del dossier | No chatbot, solo voce narrante |

### Decisioni di schema

| Area | Decisione | Motivazione |
|---|---|---|
| Schema entità v0.1 | `(type, value)` — niente altro | Minimo vitale |
| Schema entità v0.2 | aggiunto `original` con default = `value` | Divergenza reale introdotta dal deobfuscator |
| Pattern `original` / `value` consolidato come principio | Ogni volta che il Recognizer trasforma il valore tra "come appariva nel testo" e "come va memorizzato/cercato", entrambi i campi sono preservati. Applicazioni esistenti: deobfuscator (v0.2), phone normalizer (v0.3). Applicazioni future previste: canonicalizzazione dictionary-resolved (v0.4) | Non più scelta una-tantum, ma regola architetturale. Ogni nuovo trasformatore deve rispettarla |
| Dedup URL/email → domain | Se dominio coincide con host di URL o parte-dopo-@ di email, non viene emesso come `domain` separata | L'entità più ricca assorbe quella più povera |
| Pattern dedup "entità ricca assorbe povera" | Già osservato in più punti (URL/email → domain in v0.1). Da v0.5 con shortener, URL assorbe anche il "vero" dominio dietro lo shortener. La logica vive nel Recognizer, non negli extractor | Va promosso a principio quando arriverà v0.4/v0.5 |
| Estrazione deterministica | Il Recognizer è puro Python, niente LLM in v0.x | Principio fondativo |
| `app/config/` come home per config dichiarative | In v0.3 sono nate due voci (`tld_list.yaml`, `stoplist_person_name.yaml`). In v0.4 si aggiunge `osint_catalog.yaml`. Caricamento al boot con loader simmetrico, fail-fast su file mancante o malformato | Convenzione consolidata per ogni futura config dichiarativa: catalogo flag (v0.4+), prompt di Claude (v0.7), preferenze enricher (v0.6+) |
| Vocabolari controllati per campi enumerabili | I campi che ammettono solo un insieme finito di valori (es. `confidence: 'high'/'medium'/'low'`, `category` del catalogo OSINT, etichette di affidabilità/privacy/costo) usano **vocabolari controllati definiti in YAML**, mai stringhe libere. Il vocabolario è caricato al boot e verificato fail-fast contro l'uso effettivo | Pattern emerso in v0.4 (schema confidenza + catalogo OSINT). Convenzione esplicita per evitare drift di valori, garantire coerenza UI, abilitare validazione automatica. Da applicare anche al futuro catalogo flag (`suspicious_tld` etichette) e ai dictionary brand/threat_actor (v0.5) |

### Debiti tecnici saldati in v0.3

| Area | Decisione v0.1/v0.2 | Risoluzione in v0.3 |
|---|---|---|
| Whitelist TLD statica (~90 voci) | Filtrava falsi positivi tipo "mario.rossi" | ✅ Sostituita con lista IANA in `app/config/tld_list.yaml` (seed 140 voci, refresh via `scripts/refresh_tlds.py`) |
| Normalizzazione phone minimale | Solo rimozione whitespace | ✅ Normalizzazione E.164 vera via libreria `phonenumbers`, modulo `app/phone_normalizer.py` |
| Stoplist `person_name` (~17 voci) | Lista hardcoded in `spacy_extractor.py` | ✅ Esternalizzata in `app/config/stoplist_person_name.yaml` |
| Cache busting risorse statiche | Assente in v0.2 | ✅ Suffisso `?v=0.3.0` su `style.css` e `app.js` |
| Sistema multi-tema | 4 temi ufficiali + 3 sperimentali | ✅ Collassato a `:root` unico (tech-mono con asset locali Operatore) |

### Debiti tecnici aperti

| Area | Decisione corrente | Da rivedere in |
|---|---|---|
| Self-hosting font | Caricamento da Google Fonts (potato a 2 famiglie in v0.3: IBM Plex Mono + Orbitron) | Da rivalutare se l'uso offline diventa requisito |
| Pipeline sincrona | Estrazione < 100 ms su testi tipici | Nessuna revisione prevista a breve |
| Phone con punti come separatori | Regex non cattura `347.123.4567` (vuole spazi/trattini). Il normalizer saprebbe gestirlo, ma il regex a monte non lo passa | **v0.4 → estensione regex phone** |
| Dipendenza cross-modulo `regex_extractor → phone_normalizer` | Introdotta in v0.3 per un singolo tipo. Piccola perdita di isolamento, accettabile per ora | **v0.5+ → ridisegnare pipeline come *extractor → normalizer step separato* se più tipi richiederanno normalizzazione** |

---

## Regole di design front-end

Convenzioni prescrittive sul codice front-end (CSS, HTML, JS dei template).
Si accumulano nel tempo: ogni rilascio che ne aggiunge le scrive qui.
Chi tocca il front-end deve rispettarle, salvo decisione esplicita di
modifica registrata in questa stessa sezione.

### R1 — Logo POE bianco fisso, indipendente da hover/focus
*(introdotta in v0.3, capitolo 2)*

Il logo `<span class="brand-name">POE</span>` mantiene
`color: var(--color-text-primary)` anche quando il link genitore
`.brand-link` cambia colore al passaggio del mouse o al focus.

Motivazione: il logo è elemento di identità di marca, non si comporta
come link generico. Il colore stabile è parte del riconoscimento del
prodotto.

Implementazione: il colore va sovrascritto direttamente sulla
`.brand-name` con specificità superiore al genitore.

In futuri redesign dell'header, il colore del logo non va legato allo
stato del link.

### R2 — Numerazione sezioni CSS non contigua per scelta
*(introdotta in v0.3, capitolo 2)*

Il file `static/style.css` ha sezioni numerate (es. "1. Design tokens",
"10. Form"). La numerazione **non è contigua**: dopo cleanup di rilascio
possono mancare numeri intermedi (es. "9. Selettore tema" rimossa in
v0.3 con cleanup theming).

Motivazione: rinumerare avrebbe creato un diff Git massiccio senza
beneficio. La numerazione è documentazione di storia, non indice
matematico.

Chi tocca il CSS non deve "sistemare" la numerazione. Le sezioni nuove
prendono numeri liberi alla coda; quelle rimosse lasciano il loro numero
vacante.

### R3 — Variabile `--font-brand` conservata in tema unico
*(introdotta in v0.3, capitolo 2, eredità da v0.2)*

La variabile CSS `--font-brand` (Orbitron per il logo POE) è formalmente
ridondante in tema unico — si potrebbe inlineare il font direttamente
nella regola `.brand-name`. È mantenuta come variabile.

Motivazione:
- Esprime esplicitamente la separazione concettuale "logo vs corpo del testo"
- Costo di manutenzione zero
- Se un giorno il font del logo cambia, il punto di intervento esiste già

Non rifattorizzare per "semplicità apparente".

### R4 — Pattern HTMX out-of-band swap (OOB) per aggiornamenti multi-frammento
*(introdotta in v0.3, fix UX history)*

Quando una response del server deve aggiornare più zone del DOM in una
sola richiesta, si usa il pattern HTMX OOB:

- Frammento principale → torna come body normale, target indicato
  dall'attributo `hx-target`
- Frammenti secondari → tornano nello stesso payload con attributo
  `hx-swap-oob="true"`

Esempio applicato in v0.3: la POST `/analyze` torna sia il box `#results`
(target principale) sia un frammento OOB per `#history` (sezione
cronologia da aggiornare).

Conseguenza prescrittiva: in v0.5+ quando arriverà il dossier o il
catalogo OSINT integrato, capiterà spesso di voler aggiornare più sezioni
del DOM contemporaneamente. Il pattern OOB è la convenzione del progetto,
non si reinventano alternative.

### R5 — Convenzione naming dei partial template
*(introdotta in v0.3, fix UX history)*

I file template che rappresentano partial riusabili (non pagine intere)
hanno il nome che inizia con `_`. Esempio: `_history.html`, `_macros.html`.

Motivazione: scansione visiva immediata della cartella `templates/` —
l'underscore segnala che il file non è una pagina renderizzabile in
autonomia. Convenzione comune in molti framework template (Django, Rails).

In v0.5+ se arriveranno molti partial (componenti del dossier, blocchi
del catalogo), la convenzione vale per tutti.

---

## Convenzioni di rilascio

Procedure operative da rispettare al rilascio di una nuova versione.
Si accumulano nel tempo. Ogni rilascio che ne aggiunge le scrive qui.

### Checklist di release

Quando si rilascia una versione `v0.X.Y`:

1. **Aggiornare il cache busting** in `app/templates/base.html`:
   cambiare `?v=X.Y.Z` su `style.css` e `app.js` al numero della release
   in uscita
2. **Aggiornare la versione anche in**: `pyproject.toml` (riga
   `version = "X.Y.Z"`) e `app/main.py` (riga `version="X.Y.Z"` di FastAPI).
   Mantenere coerenza tra i tre punti — sono tre fonti di verità della
   stessa informazione, vanno aggiornate insieme
3. **Aggiornare il lockfile**: `uv lock` se sono state modificate le
   dipendenze in `pyproject.toml`. Committare `uv.lock` insieme alle
   modifiche
4. **Verificare se serve migrazione DB** (regola sotto)
5. **Eseguire la suite di test completa** (`uv run pytest` o
   `pytest` nel venv attivo) e verificare che tutti passino
6. **Verifica visiva manuale**: aprire l'app in due browser di motore
   diverso (es. WebKit/Safari + Blink/Chrome, oppure Blink/Chrome +
   Gecko/Firefox), eseguire un'osservazione completa, verificare
   il rendering. Lo scopo è coprire più engine di rendering, non più
   brand specifici
7. **Aggiornare i tre file di gestione**: `STATUS.md`, `VERSION.md`,
   `README.md` se la release lo richiede
8. **Commit Git** con messaggio descrittivo
9. **Tag Git**: `git tag v0.X.Y`
10. **Push remoto**: `git push origin main && git push origin --tags`

### Workflow Git

Repository ufficiale: `Mercer-Frey5/poe` su GitHub, privato. Inizializzato
durante il porting Mac (3 maggio 2026).

Regole operative:

- **Branch principale**: `main`. Tutto lo sviluppo passa di qui finché
  il progetto resta a singolo Operatore. Branch dedicati per feature
  saranno valutati se in futuro emergeranno collaboratori
- **Riscrittura della storia consentita solo prima del primo push**.
  Una volta che un commit è stato pushato sul remoto, riscriverlo
  (`git rebase -i`, `git commit --amend`) non è più consentito. Il caso
  affrontato durante il porting (riscrittura email commit con
  `--amend --reset-author --no-edit`) è stato gestito *prima* del primo
  push e per questo era legittimo
- **Tag come fonte di verità del rilascio**: ogni `v0.X.Y` corrisponde
  a un tag Git. Le release notes vivono in `VERSION.md`. Il tag puntato
  al commit di chiusura release rende il rilascio recuperabile in
  qualunque momento

### Regola di migrazione DB

Una migrazione del database SQLite è necessaria **solo se**:

- Cambia lo schema della tabella `observations`
- Cambia il payload `entities_json` (nuovi campi obbligatori, rinomine,
  rimozioni di campi)

Se la nuova versione aggiunge solo campi opzionali, o non tocca il
payload, **nessuna migrazione è necessaria**. Esempi storici:

- v0.1 → v0.2: aggiunto campo opzionale `original` su `Entity`. Backward
  compatible, nessuna migrazione richiesta
- v0.2 → v0.3: schema invariato. Nessuna migrazione richiesta

Quando una migrazione sarà necessaria, va decisa in chat *Architettura*
prima dell'implementazione, e tracciata nelle release notes di
`VERSION.md`.

### Disciplina di test post-rilascio

I test automatici (`pytest` su FastAPI con `TestClient`) verificano:
- L'HTML servito dal server
- Le risposte delle route
- Il comportamento delle estrazioni e dei normalizzatori

I test automatici **non verificano**:
- Il rendering CSS computato dal browser
- Il comportamento JavaScript lato client (HTMX, switch tema,
  scorciatoie)
- L'aspetto visivo delle pagine

La verifica di queste cose resta responsabilità manuale dell'Operatore
al momento del rilascio (punto 4 della checklist sopra).

### Manutenzione periodica

Voci da rinfrescare ogni 6 mesi:

- **Lista IANA TLD**: eseguire `python scripts/refresh_tlds.py` da una
  macchina con accesso a Internet. Lo script aggiorna
  `app/config/tld_list.yaml` da `data.iana.org`. Non funziona in
  ambienti air-gapped
- **`phonenumbers`**: aggiornare con `pip install --upgrade phonenumbers`
  per allineare i dati regionali (nuovi prefissi, regole aggiornate)

### Cadenza di manutenzione del catalogo OSINT

Il catalogo OSINT (`app/config/osint_catalog.yaml`, v0.4+) richiede
manutenzione **ibrida**:

- **On-touch**: ogni volta che l'Operatore usa una risorsa del catalogo
  durante un'indagine reale e la trova morta, modificata, o non più
  affidabile, la marca/aggiorna/rimuove subito. Il catalogo evolve
  con l'uso quotidiano
- **Revisione annuale a gennaio**: una volta l'anno, scorrere il
  catalogo intero per verificare voci che non sono state toccate
  durante l'anno (potrebbero essere morte silenziosamente). Aggiornare
  date di validazione, controllare URL, valutare se nuove risorse
  emerse meritano di entrare

Le due cadenze sono complementari: l'on-touch copre il caso
quotidiano, la revisione annuale copre il silenzio.

Decisione presa in chat *OSINT/Metodologia* il 5 maggio 2026,
ratificata in *Architettura*. Estende il pattern della manutenzione
periodica al di là del solo aggiornamento di dati esterni
(IANA, phonenumbers).

---

## Roadmap

```
V1.0  ← release stabile: tutto integrato, documentato
v0.7  ← enricher Claude + pulsante "Chiedi a Claude"
v0.6  ← enricher Qwen locale + sistema confidenza reward-based + logging strutturato
v0.5  ← template dossier + catalogo OSINT popolato + idee grandi fase 2 (A5, C2, social_handle, birth_date estesa)
v0.4  ← 🎯 PROSSIMO. Fondazioni (scope, principi 3+4, schema confidenza) + idee piccole intere + idee grandi fase 1
v0.3  ← ✅ backend di base + cleanup theming + fix UX history (rilasciata)
v0.2  ← ✅ riverniciatura UI (theming + 4 temi) + 3 robustezze pipeline (rilasciata)
v0.1  ← ✅ walking skeleton (rilasciato)
```

---

## Decisioni rimandate consapevolmente

- **LLM di pre-processing per input ambigui**: non previsto prima di V1.0
- **Fine-tuning di un modello locale**: prematuro
- **Esecuzione automatica dei tool CLI**: rimandata al Livello 3
- **Aggiornamento dinamico dei dictionary**: V1 parte con baseline statica
- **Sistema di temi configurabili**: chiuso, non torna fino a V1.0+
- **Self-hosting font**: Google Fonts resta scelta corrente. Da rivalutare
  solo se uso offline diventa requisito esplicito

---

## Struttura delle chat di progetto

Quattro sezioni tematiche.

| Sezione | Scopo |
|---|---|
| 🏛 **Architettura & Strategia** | Decisioni di alto livello, trade-off, roadmap |
| 🔬 **OSINT & Metodologia** | Contenuto OSINT, framework, test di accettazione |
| 💻 **Sviluppo & Codice** | Implementazione, refactoring, debug |
| 🎭 **POE / Persona & Prompting** | System prompt, voce, comportamento (da v0.6+) |

---

## Hardware e ambiente

### Ambiente di sviluppo principale (dal 3 maggio 2026)

- **Sistema operativo**: macOS (MacBook Air M1)
- **Memoria**: 16GB unified memory (memoria condivisa CPU/GPU integrata)
- **CPU/GPU**: Apple Silicon M1, 8 core CPU + 7-8 core GPU integrata,
  banda di memoria ~70 GB/s

### Compatibilità preservata

Il porting Mac di v0.3 ha confermato che il codice è cross-platform pulito.
**Windows resta supportato come ambiente secondario** via `uv` (workflow
identico). Il README documenta entrambi i percorsi di setup.

### Disaster recovery

Il codice è ora replicato su tre punti:
- Macchina di sviluppo (Mac M1)
- Repo Git locale sul Mac
- Repo Git remoto privato (`Mercer-Frey5/poe` su GitHub)

Il rischio di perdita codice da guasto hardware singolo è azzerato.
Le **osservazioni storiche in `data/poe.db`** sono invece *solo* sul
Mac (file gitignored per privacy). Per backup investigativo dedicato,
da valutare in futuro se l'archivio diventa significativo.

### Implicazioni hardware per v0.6 (LLM locale Qwen)

La scelta originale "Qwen 3 8B come target LLM" era stata fatta sotto
vincolo GTX 1660 6GB VRAM. Su Mac M1 16GB i vincoli sono diversi:

- Memoria unificata 16GB → spazio disponibile per LLM ~10-11GB pratici
  (il resto serve a macOS e altre app)
- Backend di calcolo: CPU pura, oppure Metal (GPU integrata via API Apple)
- Possibili formati: GGUF quantizzati (via Ollama), MLX nativo Apple
  Silicon (qualità superiore a parità di quantizzazione)

Conseguenze da valutare in chat *Architettura* prima di iniziare v0.6:

1. Confermare Qwen 3 8B come target oppure salire a 13B (entra nei 16GB
   con margine stretto, qualità di prosa narrativa migliore)
2. Scegliere backend: Ollama GGUF (compatibile con il piano originale)
   oppure MLX (ottimizzato Apple, perde portabilità Windows)
3. Considerare opzione "PC come Ollama-server remoto": il PC Windows
   con GTX 1660 resta acceso, fa girare Qwen via Ollama HTTP API,
   POE-su-Mac chiama l'endpoint via rete locale. Setup ibrido che
   sfrutta entrambe le macchine

Decisione differita all'apertura di v0.6. Non urgente.

---

## Note aperte

- **Design del template deterministico** (rilevante in v0.5): merita
  una sessione dedicata.
- **Distinzione UI tra "Arricchisci con POE" e "Chiedi a Claude"**
  (rilevante da v0.6/v0.7): i due pulsanti hanno significati diversi
  (voce locale vs consulenza frontier), non gradi di intensità.
- **Telemetria minima d'uso dei flag** (rilevante da v0.4): per la
  futura revisione "tipo vs flag" serve sapere quali flag scattano.
- **Coerenza microcopy v0.3 ↔ voce POE v0.7**: la microcopy di v0.2 è
  stata preservata invariata in v0.3 (decisione del 23 aprile). In v0.7,
  quando si scriverà il system prompt di Claude in chat *POE / Persona
  & Prompting*, includere esplicitamente la revisione delle frasi di
  interfaccia. Senza questo passaggio, voce narrativa e voce UI rischiano
  di divergere.
- **`original` vs `value` — estensione in v0.5**: la divergenza
  introdotta in v0.2 (deobfuscazione) e consolidata in v0.3 (E.164
  telefoni) verrà estesa in v0.5 alla canonicalizzazione
  dictionary-resolved (quando arriveranno i dictionary). Regola
  generale: `value` è la forma per ricerca/match, `original` è la
  forma apparsa.
- **Sistema di confidenza reward-based — pianificato per v0.6+**: v0.4
  implementa una baseline qualitativa per-tipo (`high` / `medium` /
  `low`). La maturazione verso un sistema con calcolo cross-entità
  (ridondanza del dato, correlazioni tra entità coerenti, supporto
  contestuale da marcatori testuali) è il passo successivo. Va
  affrontato in sessione architetturale dedicata prima di v0.6, perché
  richiede definizione dei pesi per fattore, refactor del Recognizer
  per calcolo cross-entità, e meccanismo per spiegare il punteggio
  (trasparenza algoritmica). Il campo `Entity.confidence` resta lo
  stesso, l'algoritmo che lo popola si evolve.
- **Strategia multi-AI — orchestratore di enricher specializzati**:
  Perplexity per ricerca web, Claude per ragionamento, Qwen per privacy.
  Non in V1.0. Pre-condizioni: BaseEnricher polimorfico (in v0.4 fase 1
  come interfaccia astratta), catalogo OSINT popolato (v0.5).
- **Refresh IANA TLD richiede rete**: lo script `scripts/refresh_tlds.py`
  legge da `data.iana.org`. L'Operatore deve eseguirlo manualmente da
  macchina con rete. Il seed iniziale di 140 voci copre i casi quotidiani.
- **Phone con punti come separatori — saldato in v0.4**: estensione
  regex pianificata come voce A2 di v0.4. Verrà rimossa da questa
  lista al rilascio.
- **Revisione strategia LLM locale per v0.6 dopo cambio hardware**: la
  scelta "Qwen 3 8B come target" era stata fatta sotto vincolo GTX 1660
  6GB. Il porting Mac M1 16GB cambia i vincoli: si aprono opzioni nuove
  (modelli più grandi, backend MLX, setup ibrido con PC come Ollama-server
  remoto). Vedere sezione "Hardware e ambiente → Implicazioni per v0.6"
  per le tre decisioni concrete da prendere prima di iniziare v0.6.
- **Lista TLD sospetti per il flag `suspicious_tld` (B1 di v0.4)**:
  da curare manualmente prima dell'implementazione. Stima ~30 voci
  iniziali (esempi: `.xyz`, `.tk`, `.ml`, `.gq`, `.cf`, `.pw`, `.top`,
  `.click`, `.download`). La lista va datata e versionata in `app/config/`
  con stesso pattern di `tld_list.yaml` e `stoplist_person_name.yaml`.
- **Manutenzione cronologia curabile**: in v0.4 fase 1 di C2, la
  vista mostrerà 'tutto / solo kept / solo bozze'. Da decidere in v0.5
  fase 2 se la cronologia ha **eliminazione fisica** delle scartate
  o solo flag di stato. Implicazioni privacy + retention da valutare.
- **Inserimento veloce nel catalogo OSINT — script di append da
  valutare per v0.4 o v0.5**: il flusso on-touch del catalogo richiede
  attrito minimo. Soluzione attuale (Opzione A): chat Claude dedicata
  che restituisce la voce YAML pronta da copia-incollare nel file.
  Soluzione futura (Opzione C): script `scripts/add_catalog_entry.py`
  che riceve in input una voce, valida vocabolari controllati, e
  appende al file YAML correttamente formattato. Costo stimato: mezza
  giornata di lavoro Sviluppo. Decisione data-driven dopo qualche
  settimana di uso dell'Opzione A: se la chat funziona bene, lo script
  aggiunge poco; se l'attrito di copia-incolla è notevole, lo script
  vale lo sforzo. Da rivalutare nella pianificazione di v0.4 (se entra)
  o v0.5 (se slitta).

---

*POE osserva. Sempre.*
