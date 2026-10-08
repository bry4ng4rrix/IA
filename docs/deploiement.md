# Déploiement

## Architecture

```
Internet ──https─▶ nginx (hôte, Certbot) ──▶ 127.0.0.1:8050 ──▶ conteneur laura
   (443)                                                        (uvicorn, 1 worker)
                                                        ├─ volume laura_data   → /data/laura.db
                                                        └─ volume laura_fiches → app/knowledge
```

- **Un seul worker** : `channels.py` et `quotas.py` gardent leur état en mémoire.
- **Le port 8050 n'est pas public** : le conteneur écoute sur `127.0.0.1`, seul
  nginx l'atteint. C'est ce qui rend les quotas réels — `quotas.ip_client` lit
  la première adresse de `X-Forwarded-For`, et nginx l'écrase par `$remote_addr`
  ([deploy/nginx-laura.conf](../deploy/nginx-laura.conf)). Tant que le port
  était exposé sur `0.0.0.0`, il suffisait d'appeler l'API en direct avec un
  `X-Forwarded-For` différent à chaque requête pour n'avoir aucune limite
  (RG-X04), et `ufw` n'y pouvait rien puisque Docker écrit ses propres règles
  iptables.
- **HTTPS obligatoire pour le widget** : le site est en https, il ne peut ouvrir
  qu'un `wss://`. Une page https qui tente un `ws://` est bloquée par le
  navigateur pour contenu mixte, sans message explicite dans l'interface.

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

1. **DNS** — enregistrement A `laura.labeltechnology.mg` → IP du VPS, chez le
   registrar du domaine. Le site reste sur son hébergement actuel : seul le
   sous-domaine pointe vers le VPS. Vérifier la propagation avant la suite,
   sinon certbot échoue :
   ```bash
   dig +short laura.labeltechnology.mg      # doit renvoyer l'IP du VPS
   ```
2. **Pare-feu** — 80 et 443 ouverts (80 est nécessaire au renouvellement
   automatique du certificat, ne pas le fermer après coup) :
   ```bash
   sudo ufw allow 80,443/tcp
   ```
3. **nginx + certificat** :
   ```bash
   sudo cp ~/laura/nginx-laura.conf /etc/nginx/conf.d/laura.conf
   sudo nginx -t && sudo systemctl reload nginx
   sudo certbot --nginx -d laura.labeltechnology.mg
   ```
   Certbot ajoute lui-même le bloc `listen 443 ssl`, le certificat et la
   redirection depuis le port 80. Il installe aussi un timer de renouvellement ;
   le vérifier une fois : `systemctl list-timers | grep certbot`.
4. **Les trois valeurs à aligner** — c'est là que ça casse le plus souvent :

   | Où | Variable | Valeur |
   |---|---|---|
   | Secret GitHub `LAURA_ENV` | `BASE_URL` | `https://laura.labeltechnology.mg` |
   | Secret GitHub `LAURA_ENV` | `ALLOWED_ORIGINS` | `https://labeltechnology.mg,https://www.labeltechnology.mg` |
   | Hébergeur du site | `NEXT_PUBLIC_LAURA_URL` | `https://laura.labeltechnology.mg` |

   `NEXT_PUBLIC_*` est injecté **à la compilation** : après l'avoir ajouté, il
   faut redéployer le site, un simple redémarrage ne suffit pas.

5. **Vérifier** depuis une machine extérieure :
   ```bash
   curl -s https://laura.labeltechnology.mg/sante
   # puis le WebSocket, qui doit répondre 101 Switching Protocols
   curl -isk -o /dev/null -w '%{http_code}\n' \
     -H 'Connection: Upgrade' -H 'Upgrade: websocket' \
     -H 'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==' -H 'Sec-WebSocket-Version: 13' \
     https://laura.labeltechnology.mg/ws/chat
   ```

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
