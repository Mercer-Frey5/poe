# Valutazione LLM — benchmark OSINT v3 (FINALE)

> Valutazione sui 4 report **ri-runnati a parità** (post-ottimizzazione: sampler gpt-oss temp 1.0,
> strip harmony, max_tokens 1024). Metodo: gold di riferimento + 4 scorecard + 4 verifica
> adversariale anti-allucinazione + sintesi. Punteggi "aggiustato" = dopo la verifica adversariale.

## 🏆 SCELTO: **llama-3.1-8b**  (`mlx-community/Meta-Llama-3.1-8B-Instruct-4bit`)

Vincitore assoluto **e** per l'uso OSINT. Backup: **qwen-4b**.

## Classifica (overall aggiustato)
| # | Modello | overall (grezzo) | **aggiustato** |
|---|---------|:---:|:---:|
| 1 | **llama-3.1-8b** | 4.5 | **4.0** ⭐ |
| 2 | qwen-4b | 4.6 | 3.6 |
| 3 | qwen3.5-9b | 4.8 | 3.0 |
| 4 | gpt-oss-20b | 2.1 | 1.5 |

## Tabella per dimensione (1-10)
| Dimensione | **llama-3.1-8b** | qwen-4b | qwen3.5-9b | gpt-oss-20b |
|---|:-:|:-:|:-:|:-:|
| velocita | **3** | 3 | 2 | 2 |
| affidabilita | 4 | 4 | **5** | 2 |
| allucinazioni (10=zero) | **6** | 4 | 4 | 2 |
| profondita | 4 | 6 | **7** | 3 |
| solidita | **5** | 5 | 4 | 1 |
| contraddizioni | 4 | 6 | **7** | 2 |
| incertezza | 5 | 6 | **6** | 3 |
| attribuzione | 6 | 5 | **7** | 3 |
| formato | **3** | 3 | 3 | 1 |
| chiarezza | **7** | 7 | 7 | 2 |
| **avg secondi/task** | **38.0** | 66.0 | 119.0 | 59.8 |
| **avg tok/s** | 12.3 | 14.6 | 8.6 | 16.9 |
| **OVERALL aggiustato** | **4.0** | 3.6 | 3.0 | 1.5 |

## Perché llama-3.1-8b
- **Più pulito sulle allucinazioni** (6/10, il migliore): nessuna fabbricazione load-bearing.
- **Attribuzione prudente:** usa "unconfirmed/tentative", distingue i lookalike
  `secure-login.net` vs `…-verification.net` senza inventare infrastruttura.
- **Più veloce dei modelli usabili** (38s/task) — decisivo su Mac 16GB.
- Italiano fluido, struttura Fatti/Inferenze costante.
- Limiti onesti: a volte resta "indeciso" su verdetti ad alta confidenza (1.4/4.1), inverte le
  trap 2A/3C, e — come TUTTI — fallisce il report JSON (task 5). → mitigati dai guardrail in
  fase di integrazione.

## Perché NON gli altri
- **qwen3.5-9b (3.0):** grezzo sembrava 1° (4.8, il più analitico) ma la verifica adversariale lo
  **squalifica**: al task 3A inventa "Hetzner Online GmbH" + netblock `185.203.0.0/16` e ci FONDA
  un'attribuzione-paese spacciata per fatto. Per un tool di threat-intel è il peggior errore
  possibile. Inoltre **lentissimo** (119s/task ≈ 32 min per 16 task).
- **qwen-4b (3.6):** onesto secondo, metodo disciplinato → **backup**. Ma ingerisce le trap
  assolutorie (4.1/4.2) e fabbrica lookup ASN mai eseguiti (3A).
- **gpt-oss-20b (1.5):** eliminato senza appello anche dopo l'ottimizzazione — 8/16 risposte
  troncate, leak del reasoning ("assistantfinal"), caratteri greco/cinese, italiano con parole
  inventate, rifiuto improprio su dataset fittizio.

## Nota metodologica
La verifica adversariale **ribalta** il ranking grezzo (che premiava qwen3.5): tutti gli scorer
erano troppo clementi sulle allucinazioni, ma il danno è molto diverso — un'allucinazione che
*fonda un verdetto* (qwen3.5) pesa molto più di un numero gonfiato (llama). Per OSINT conta la
**fiducia nell'output**, non la prosa più ricca.

→ Prossimo passo: integrare llama-3.1-8b nella sintesi OSINT **con i guardrail** (anti-allucinazione,
output JSON validato lato codice, max_tokens 1100). Vedi piano di integrazione.
