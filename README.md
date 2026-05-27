# Automatisation logement Laval

Cette petite automatisation cherche chaque jour des offres de location a Laval (53000) sur Bien'ici, les trie du moins cher au plus cher, puis envoie un email detaille.

## Ce que fait le bot

- recupere la zone `Laval 53000`
- cherche les locations actives a Laval
- filtre par defaut sur les logements residentiels
- trie du moins cher au plus cher
- envoie un mail avec:
  - titre
  - prix
  - surface
  - nombre de pieces
  - localisation approximative
  - agence et telephone
  - resume
  - lien annonce
  - lien source detail

## Fichiers utiles

- `logement_bot.py` : script principal
- `.env.example` : modele de configuration
- `run_daily.sh` : commande de lancement
- `install_launchd.sh` : installation du lancement quotidien sur macOS
- `com.lucifer.logement.daily.plist` : modele `launchd`

## Configuration

1. Copier `.env.example` vers `.env`
2. Renseigner surtout `SMTP_PASSWORD`

Pour Gmail, il faut utiliser un mot de passe d'application, pas ton mot de passe normal.

## Test manuel

```bash
/opt/homebrew/opt/python@3.14/bin/python3.14 logement_bot.py --env-file .env --dry-run
```

## Installation quotidienne sur macOS

```bash
chmod +x run_daily.sh install_launchd.sh
./install_launchd.sh
```

Par defaut, l'execution est prevue tous les jours a `08:00`.

## WhatsApp plus tard

Le plus simple ensuite sera d'ajouter un second canal via:

- Twilio WhatsApp
- ou WhatsApp Cloud API

Le script est deja structure pour qu'on puisse ajouter ce canal ensuite sans tout refaire.

## Deploiement Render

Un blueprint Render est pret dans `render.yaml`.

Type de service:

- `cron`
- execution quotidienne a `08:00 UTC`

Variables Render a renseigner:

- `RECIPIENT_EMAIL`
- `CITY_QUERY`
- `CITY_POSTAL_CODE`
- `MAX_RESULTS`
- `INCLUDE_PARKING`
- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USERNAME`
- `SMTP_PASSWORD`

Important:

- `SMTP_PASSWORD` doit etre ajoute comme secret Render
- Render a besoin d'un depot Git distant pour importer le blueprint
