# Laura — API de l'assistante virtuelle de Label Technology

Chat du site, formulaire de contact et WhatsApp, avec compte rendu automatique
pour l'équipe commerciale.

Spécification complète : [docs/regles-de-gestion.md](docs/regles-de-gestion.md)
(72 règles de gestion + 6 diagrammes UML). Chaque règle porte un identifiant
(`RG-L03`, `RG-Q04`…) qui est cité en commentaire dans le code.

## Démarrage

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env          # puis renseigner GEMINI_API_KEY et ADMIN_TOKEN
.venv/bin/uvicorn app.main:app --reload
```

Banc d'essai sur <http://localhost:8000> — les 3 canaux, le streaming et le
compte rendu. Documentation interactive sur `/docs`.

**Sans clé API, l'application démarre quand même** en mode dégradé : Laura
renvoie un message d'attente. Pratique pour développer le widget sans
consommer de quota.

## Architecture

```
app/
├── main.py          FastAPI, CORS, cycle de vie
├── config.py        .env
├── enums.py         Canal, StatutConversation, Temperature, MotifAlerte…
├── models.py        7 tables = le diagramme de classes
├── schemas.py       Pydantic, dont les schémas de sortie contrainte
├── db.py            SQLAlchemy 2.0 async + SQLite
│
├── prompts.py       ← les « scripts » de Laura (identité + règles + forme)
├── knowledge.py     ← chargement des fiches, rechargement à chaud
├── knowledge/       ← 15 fiches .md, éditables par l'équipe
├── llm.py           Gemini : streaming, JSON contraint, détection de trou
├── scoring.py       grille de score déterministe
│
├── channels.py      canaux WebSocket (publication/abonnement)
├── quotas.py        garde-fous anti-abus
├── notifications.py Telegram + email, routage par gravité
├── services.py      logique métier
├── maintenance.py   abandon automatique, purge RGPD
└── routes/
    ├── ws.py        /ws/chat et /ws/equipe
    ├── sessions.py  REST : ouvrir, relire, réclamer, terminer
    └── admin.py     fiches, prospects, trous, statistiques
```

## Les deux sens de « canal »

Ne pas les confondre, ils sont orthogonaux :

| | Quoi | Où |
|---|---|---|
| **Canal métier** | par où arrive le visiteur : `site`, `formulaire`, `whatsapp`. Change le ton et la longueur des réponses. | `enums.Canal`, `prompts.FORME_CANAL` |
| **Canal WebSocket** | qui reçoit quoi en temps réel : `conv:<id>`, `equipe`. | `channels.Hub` |

## Protocole WebSocket

### `/ws/chat` — le visiteur

```
ws://host/ws/chat?canal=site&page_url=...&referrer=...
ws://host/ws/chat?conversation_id=<id>&token=<jeton>     # reprise
```

| Visiteur → serveur | Serveur → visiteur |
|---|---|
| `{type:"message", contenu}` | `{type:"pret", conversation_id, resume_token, historique, mode_degrade}` |
| `{type:"terminer"}` | `{type:"fragment", texte}` — streaming |
| `{type:"reclamer", nom, email, consentement}` | `{type:"fin_message", message_id, contenu}` |
| `{type:"ping"}` | `{type:"compte_rendu", objet, resume, temperature, score}` |
| | `{type:"erreur", code, message}` |

Codes d'erreur : `message_trop_long`, `trop_rapide`, `conversation_pleine`,
`trop_de_conversations`, `conversation_terminee`, `consentement_requis`,
`modele_indisponible`, `introuvable`.

### `/ws/equipe` — le tableau de bord interne

```
ws://host/ws/equipe?token=<ADMIN_TOKEN>&observer=<conversation_id>
```

Reçoit toutes les notifications en direct, et peut suivre une conversation en
cours message par message. `{type:"observer", conversation_id}` pour changer de
cible à chaud.

## Comment Laura « apprend »

Aucun réentraînement (RG-T01). Trois couches assemblées à chaque message :

1. **identité et règles** — figées dans `prompts.py` ;
2. **15 fiches** — `app/knowledge/*.md`, éditables par l'équipe, prises en
   compte à la réponse suivante sans redéploiement ;
3. **historique** — 20 derniers tours, en base.

Les 15 fiches font ~4 300 tokens : tout tient dans le prompt système, donc
**pas de RAG, pas de base vectorielle**.

La boucle d'amélioration, c'est la table `trous` : chaque fois que Laura doit
renvoyer vers l'équipe faute d'information, un appel de classification en
tâche de fond l'enregistre. `GET /admin/trous` les classe par fréquence — c'est
la liste de travail de l'équipe, par ordre de ce que les prospects réclament
vraiment.

## Édition des fiches par l'équipe

```bash
curl -H "X-Admin-Token: $ADMIN_TOKEN" localhost:8000/admin/fiches

curl -X PUT -H "X-Admin-Token: $ADMIN_TOKEN" -H 'Content-Type: application/json' \
  -d '{"titre":"...","contenu":"...","a_completer":false}' \
  localhost:8000/admin/fiches/02
```

Une fiche avec `a_completer: true` interdit à Laura toute affirmation sur son
sujet (RG-F03). Trois fiches sont dans cet état : `02` (prix des logiciels),
`04` (prix journalier), `15` (téléphone, WhatsApp, lien de rendez-vous).

## Enregistrement des sessions, sans login

La conversation existe dès le premier message, anonyme. L'email ne sert pas à
s'identifier mais à **réclamer** l'échange : le visiteur saisit nom + email,
reçoit la transcription et un lien signé
`/echange/{id}?t={jeton}` qui lui permet de relire ou poursuivre. Le jeton fait
32 octets aléatoires, et seul le propriétaire de l'adresse le reçoit — ce qui
vaut vérification.

L'IP n'est jamais stockée en clair, seulement hachée et salée.

## Reste à faire

- [ ] **Webhook WhatsApp** — `routes/whatsapp.py`, API Meta Cloud. Le moteur est
      déjà en place : le canal `whatsapp` est géré de bout en bout.
- [ ] **Page de relecture** `/echange/{id}` — l'API `GET
      /api/conversations/{id}?t=` existe, il manque le rendu HTML.
- [ ] **Bilan hebdomadaire** du lundi 7h (RG-N05) — `/admin/statistiques` fournit
      déjà les données, il manque le cron et le formatage de l'email.
- [ ] **Umami** pour l'audience du site, et le croisement avec `page_url` /
      `referrer` déjà stockés par conversation.
- [ ] **Tests** — aucun pour l'instant. Commencer par `scoring.py` (pur, facile)
      et par les quotas.

## Limites assumées

- **Un seul processus.** `channels.py` et `quotas.py` gardent leur état en
  mémoire. Avec plusieurs workers uvicorn, un visiteur connecté au worker A ne
  recevrait pas ce que publie le worker B, et les quotas seraient comptés par
  worker. Pour passer à l'échelle : Redis pub/sub, l'interface de `Hub` ne
  change pas.
- **`boucle_entretien`** repart de zéro à chaque redémarrage. En production,
  préférer un cron système.
- **SQLite** convient jusqu'à quelques milliers de conversations. Au-delà,
  basculer `DATABASE_URL` sur PostgreSQL — le code SQLAlchemy est portable tel
  quel.

## Décisions en attente

Sept points bloquent ou modifient l'implémentation, listés en fin de
[docs/regles-de-gestion.md](docs/regles-de-gestion.md). Les trois plus
structurants :

1. Le canal `formulaire` envoie-t-il automatiquement, ou l'équipe valide-t-elle
   un brouillon ? (RG-L17)
2. La grille de score à 7 critères est-elle validée ? (RG-Q03)
3. Délai de réponse affiché : 72h ou 24h ? Laura l'annonce. (RG-S03)
