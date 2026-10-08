# Déploiement

## Architecture

```
Internet ──http──▶ <VPS>:8050 ─────────────────────┐
Internet ──https─▶ nginx (hôte, Certbot) ──▶ :8050 ─┴▶ conteneur laura (uvicorn, 1 worker)
                                                       ├─ volume laura_data   → /data/laura.db
                                                       └─ volume laura_fiches → app/knowledge
```

- **Un seul worker** : `channels.py` et `quotas.py` gardent leur état en mémoire.
- **Le port 8050 est public** (`0.0.0.0`), comme les autres projets du VPS ;
  Docker contourne `ufw`. Limite connue : `quotas.ip_client` lit la première
  adresse de `X-Forwarded-For`, donc un client qui appelle directement le port
  peut choisir son IP et contourner les quotas (RG-X04). Via nginx, l'en-tête
  est écrasé ([deploy/nginx-laura.conf](../deploy/nginx-laura.conf)).
- **HTTPS obligatoire pour le widget** : le site est en https, il ne peut ouvrir
  que du `wss://`, donc il doit passer par nginx et non par le port 8050.

## CI/CD — [.github/workflows/deploy.yml](../.github/workflows/deploy.yml)

| Job | Quand | Rôle |
|---|---|---|
| `image` | push, pull request | construit l'image, vérifie `/sante`, publie sur GHCR (sauf PR) |
| `deploy` | push sur `main`, lancement manuel | copie `docker-compose.yml`, `deploy.sh`, `nginx-laura.conf` et `laura.env` dans `~/laura`, pull de l'image, redémarrage, vérification de `/sante` |

### Secrets GitHub

**Settings → Secrets and variables → Actions → New repository secret**

| Nom | Valeur |
|---|---|
| `VPS_HOST` | adresse IP du VPS |
| `VPS_USER` | utilisateur SSH, membre du groupe `docker` |
| `VPS_SSH_KEY` | clé privée de déploiement, fichier complet (`-----BEGIN` … `END-----`) |
| `VPS_KNOWN_HOSTS` | sortie de `ssh-keyscan -t ed25519 <adresse>` |
| `LAURA_ENV` | contenu complet du `laura.env` de production (modèle : [.env.example](../.env.example)) |

Variables facultatives (onglet **Variables**) : `LAURA_PORT` (défaut `8050`,
à reporter dans la conf nginx), `LAURA_DIR` (défaut `laura`).

Changer la configuration : modifier le secret `LAURA_ENV`, puis
**Actions → Build & déploiement → Run workflow**. `DATABASE_URL` est imposé par
`docker-compose.yml` : la base reste dans le volume quoi qu'il arrive.

## HTTPS (une fois)

1. Enregistrement DNS A `laura.labeltechnology.mg` → IP du VPS.
2. Sur le VPS :
   ```bash
   sudo cp ~/laura/nginx-laura.conf /etc/nginx/conf.d/laura.conf
   sudo nginx -t && sudo systemctl reload nginx
   sudo certbot --nginx -d laura.labeltechnology.mg
   ```
3. `BASE_URL=https://laura.labeltechnology.mg` dans `LAURA_ENV` (liens des emails).

## Les fiches en production

Elles vivent dans le volume `laura_fiches`, pour que les modifications faites par
l'équipe via `PUT /admin/fiches/{code}` (RG-F02) survivent aux redéploiements.
Au démarrage, [docker/entrypoint.sh](../docker/entrypoint.sh) **ajoute** les
fiches du dépôt absentes du volume, mais **n'écrase jamais** une fiche existante.

Pour pousser la version du dépôt d'une fiche déjà présente :

```bash
docker compose exec laura cp /app/fiches-initiales/02-logiciels.md /app/app/knowledge/
```

## Sur le serveur

```bash
cd ~/laura
docker compose ps                    # état (doit être « healthy »)
docker compose logs -f               # logs
docker compose restart               # redémarrer (ne relit pas laura.env)
docker compose up -d                 # appliquer un laura.env modifié à la main

# Sauvegarde cohérente de la base, même en fonctionnement
docker compose exec -T laura python -c "import sqlite3; sqlite3.connect('/data/laura.db').backup(sqlite3.connect('/data/sauvegarde.db'))"
docker compose cp laura:/data/sauvegarde.db ./laura-$(date +%F).db
```

Ne jamais lancer `docker compose down -v` : `-v` supprime les volumes, donc la
base et les fiches.
