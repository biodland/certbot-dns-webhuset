# certbot-dns-webhuset

En generell DNS-01-plugin for Certbot, med støtte for vanlige domener, wildcard,
underdomener og sertifikater som dekker flere DNS-soner hos Webhuset.

**Status: 0.1.0a1, lokal alfaversjon.** Pakken er ikke publisert på PyPI og er
ikke inkludert i standard Nginx Proxy Manager. Tester med simulerte API-svar
erstatter ikke en vellykket staging-utstedelse med en ekte Webhuset-konto.

Pluginen bruker Webhusets dokumenterte MCP-endepunkt direkte. Ingen AI-modell,
nettleser, HAR-fil eller sesjonscookie brukes. Domenene velges med Certbots vanlige
`-d`-argumenter; ingen domenenavn, kontonummer eller NPM-ID er hardkodet i pakken.

## Installer på Linux

Installer Python 3.10 eller nyere med venv-støtte. Fra denne mappen:

```bash
python3 -m venv /opt/certbot-webhuset
/opt/certbot-webhuset/bin/pip install .
/opt/certbot-webhuset/bin/certbot plugins
```

Listen skal vise `dns-webhuset`. Installer pluginen i **samme Python-miljø som
Certbot**. En installasjon med pip utenfor en eksisterende snap-Certbot gjør
ikke pluginen tilgjengelig i snap-installasjonen. Eksemplene bruker derfor en
egen venv og absolutte stier. Installerte Certbot-versjoner støttes i intervallet
`>=4,<6`.

Opprett en API-nøkkel i Webhuset-kundesenteret med **DNS → Administrere**.
Pluginen bruker ikke `list_domains` og trenger ikke lesetilgang til domeneoversikten.

```bash
install -d -m 700 /etc/letsencrypt/credentials
install -m 600 examples/webhuset.ini.example /etc/letsencrypt/credentials/webhuset.ini
nano /etc/letsencrypt/credentials/webhuset.ini
```

Sett nøkkelen i filen:

```ini
dns_webhuset_api_key = DIN_API_NØKKEL
```

## Kontroller tilgang uten å endre DNS

```bash
/opt/certbot-webhuset/bin/certbot-dns-webhuset-check \
  --credentials /etc/letsencrypt/credentials/webhuset.ini \
  --domain example.com \
  --domain other.no
```

Kommandoen sjekker tilgjengelige API-verktøy, finner DNS-sonene og leser dem.
Den viser ingen API-nøkkel eller DNS-verdier. Hvis Webhuset returnerer en
udokumentert datastruktur som ikke støttes, stopper pluginen med en tydelig feil.
Behold nøkkelen lokalt; ved feilsøking trengs feilmeldingen og eventuelt strukturen
i et anonymisert svar, ikke legitimasjonen.

## Test mot Let's Encrypt staging

Bytt eksempelnavnene og e-postadressen med dine egne. En dry-run lager og sletter
ekte TXT-valideringsposter, men lagrer ikke et nytt produksjonssertifikat.

```bash
/opt/certbot-webhuset/bin/certbot certonly \
  --authenticator dns-webhuset \
  --dns-webhuset-credentials /etc/letsencrypt/credentials/webhuset.ini \
  --non-interactive --agree-tos --email admin@example.com \
  --cert-name example.com \
  -d example.com -d '*.example.com' -d '*.admin.example.com' \
  --dry-run
```

Når testen lykkes, kjør samme kommando uten `--dry-run` for produksjon.
For et annet domene endrer du bare `--cert-name` og `-d`-argumentene. Én nøkkel
kan brukes til flere domener den har tilgang til. Sertifikater fra ulike
Webhuset-kontoer kan bruke hver sin credentials-fil.

Et sertifikat på tvers av soner:

```bash
/opt/certbot-webhuset/bin/certbot certonly \
  --authenticator dns-webhuset \
  --dns-webhuset-credentials /etc/letsencrypt/credentials/webhuset.ini \
  --non-interactive --agree-tos --email admin@example.com \
  --cert-name shared-services \
  -d app.example.com -d '*.other.no' --dry-run
```

## Fornyelse

Certbot lagrer pluginvalg og credentials-sti i sertifikatets fornyelsesoppsett.
Bruk samme Certbot-installasjon ved fornyelse:

```bash
/opt/certbot-webhuset/bin/certbot renew --dry-run
/opt/certbot-webhuset/bin/certbot renew --quiet
```

Bruk en eksisterende timer som kjører denne Certbot-installasjonen, eller installer
`examples/certbot-webhuset.cron` som `/etc/cron.d/certbot-webhuset` med root som eier
og modus 0644. Den sjekker to ganger daglig; Certbot bestemmer når fornyelse trengs.
Ikke legg til en ekstra jobb hvis riktig Certbot allerede kjøres automatisk.
Legg eventuelt til et eget `--deploy-hook` for tjenesten som skal bruke sertifikatet.
Denne DNS-pluginen installerer ikke sertifikater i NPM eller andre webservere.

Eksisterende sertifikat med manuelle DNS-hooks kan flyttes over med:

```bash
/opt/certbot-webhuset/bin/certbot reconfigure \
  --cert-name DITT_EKSISTERENDE_SERTIFIKATNAVN \
  --authenticator dns-webhuset \
  --dns-webhuset-credentials /etc/letsencrypt/credentials/webhuset.ini
```

`reconfigure` tester mot staging før nye innstillinger lagres. En eksisterende
deploy-hook kan fortsatt være aktiv; kontroller den før produksjonsfornyelse.
Skriptene fra den tidligere løsningen ligger under `legacy/` når de er bevart i
repoet. De er ikke en del av Python-pakken eller Docker-imaget.

## Sonevalg, ventetid og avgrensninger

- Automatisk sonevalg bruker DNS SOA-oppslag, ikke «de to siste delene av domenet».
  Det fungerer dermed også med soner som `example.co.uk` og delegerte undersoner,
  forutsatt at Webhuset API-et gir nøkkelen tilgang til akkurat den sonen.
- For spesielle DNS-oppsett kan `dns_webhuset_zone = example.com` settes i
  credentials-filen. Dette begrenser filen til den sonen; utelat det for flere soner.
- CNAME-delegering på `_acme-challenge` støttes ikke i denne versjonen. Pluginen
  stopper i stedet for å skrive en TXT-post i feil sone.
- Alle challenge-verdier opprettes før én felles ventetid, standard **600 sekunder**.
  Endre med `--dns-webhuset-propagation-seconds 900` ved treg DNS-propagasjon.
  Ventetid er ingen garanti for global propagasjon; ACME-serveren gjør valideringen.
- API- og DNS-oppslag har standard 30 sekunders tidsgrense, justerbar med
  `--dns-webhuset-http-timeout`. Ingen automatiske gjentakelser av skrivekall.
- Opprydding sletter kun nøyaktig navn/verdi som denne kjøringen forsøkte å legge
  til. Eksisterende like verdier bevares. Apex og wildcard kan ha flere samtidige
  TXT-verdier på samme navn. Andre DNS-poster endres ikke.
- Feil etter delvis oppretting utløser opprydding. Hvis serveren blir utilgjengelig
  eller prosessen hardt avsluttes, kan en TXT-verdi bli liggende. Oppryddingsfeil
  logges uten API-nøkler eller challenge-verdier; dette bør overvåkes.
- Webhuset dokumenterer verktøynavn og parametere, men ikke alle responsformater.
  Parsingen støtter strukturerte MCP-svar eller JSON i tekstinnhold, med DNS-data
  som `all` (observert i HAR) eller en `records`-liste. Ukjente svar avvises.

## Docker

```bash
docker build -t certbot-webhuset:local .
docker run --rm certbot-webhuset:local plugins
```

Ved utstedelse/fornyelse må `/etc/letsencrypt` og credentials-filen monteres fra
serveren, slik at både sertifikater og fornyelsesoppsett beholdes. Eksempel:

```bash
docker run --rm \
  -v /etc/letsencrypt:/etc/letsencrypt \
  certbot-webhuset:local renew --dry-run
```

Dette er et selvstendig Certbot-image. NPM-integrasjonen beskrives i
[`integrations/npm/README.md`](integrations/npm/README.md).

## Utvikling og pakking

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[test]'
ruff check .
pytest --cov=certbot_dns_webhuset
python -m build
twine check dist/*
```

Eller test med Linux/Docker:

```bash
docker build --target test -t certbot-webhuset:test .
docker run --rm certbot-webhuset:test
```

Testene bruker simulerte HTTP/DNS-svar og ekte Certbot-pluginlasting. Ingen
produksjons-DNS eller ACME-konto endres. Før offentlig publisering gjenstår
staging-utstedelse og fornyelse mot Webhuset, valg av lisens, prosjekteier/
publiseringskonto og verifisert NPM-integrasjon. Ingen automatisk publisering
er konfigurert.

## Referanser

- [Webhuset MCP-verktøy](https://www.webhuset.no/mcp/docs)
- [Webhuset API-nøkler](https://www.webhuset.no/hjelp/min-konto/api-n-kler-koble-ai-assistenter-og-automatisering-til-webhuset-mcp)
- [Certbot DNSAuthenticator](https://eff-certbot.readthedocs.io/en/stable/api/certbot.plugins.dns_common.html)
- [Certbot fornyelse](https://eff-certbot.readthedocs.io/en/stable/using.html#renewing-certificates)
