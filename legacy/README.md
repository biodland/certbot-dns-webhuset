# Automatisk fornyelse: communitynord.com / Webhuset / NPM

Dette oppsettet skal installeres paa Linux-serveren som allerede har Certbot og
`/etc/letsencrypt/live/communitynord.com`. Ingen serverendringer er gjort fra Codex.
Python-koden bruker Webhusets dokumenterte MCP-API direkte over HTTPS; ingen
AI-modell, Codex-jobb eller nettleser er involvert i driften.

## Flyt

Daglig kl. 04:17 i serverens tidssone sjekker Certbot om sertifikatet skal fornyes.
Certbot bestemmer fornyelsesvinduet. Ikke bruk `*/60` i cron: det betyr ikke hver
60. dag. Daglig sjekk gir ogsaa nye forsoek ved midlertidige feil.

Ved fornyelse opprettes TXT-verdier for `_acme-challenge.communitynord.com` og
`_acme-challenge.admin.communitynord.com`. Hoveddomene og wildcard kan ha flere
verdier samtidig. Hookene venter paa alle autoritative navnetjenere og de
konfigurerte offentlige resolverne. Deretter validerer Certbot og rydder opp
akkurat den aktuelle TXT-verdien. Andre DNS-poster endres ikke.

Det nye sertifikatet lastes opp til eksisterende NPM-ID **62**. Skriptet sjekker
provider `other` og forventet navn `communitynord.com` foer opplasting, samt at
noekkel og sertifikat passer sammen, at sertifikatet ikke er utloept, og at alle
tre domenene finnes i SAN. Etter opplasting kjoeres nginx-konfigurasjonstest og
reload. Foerst etter vellykket opplasting og reload lagres et lokalt fingeravtrykk.
Ved feil proever neste daglige kjoering opplastingen igjen, selv om Certbot ikke
trenger en ny fornyelse. Samme sertifikat lastes ikke opp hver dag.

## 1. Installer paa serveren

Kopier denne mappen til serveren, for eksempel til `/tmp/certbot-webhuset`.
Kjoer foelgende som root der. Pakkens `communitynord.sh` erstatter funksjonen til
det gamle manuelle skriptet, men installeres separat under `/opt`.

```bash
apt-get update
apt-get install -y python3 dnsutils openssl util-linux cron
certbot --version
certbot certificates

install -d -m 700 /opt/communitynord-certbot
install -m 700 /tmp/certbot-webhuset/*.sh /opt/communitynord-certbot/
install -m 600 /tmp/certbot-webhuset/automation.py /opt/communitynord-certbot/
install -m 600 /tmp/certbot-webhuset/automation.json.example /opt/communitynord-certbot/automation.json
nano /opt/communitynord-certbot/automation.json
```

Krever Python >= 3.9, OpenSSL med `x509 -ext`, og Certbot >= 2.3 for
`reconfigure`. Behold eksisterende fungerende Certbot-installasjon. Eksemplet
bruker Debian/Ubuntu-pakker; tilpass dersom serveren bruker en annen distribusjon.

I JSON-filen setter du `webhuset_api_key` og `npm_password`. Opprett Webhuset-noekkelen
under Konto → API-noekler med **DNS: Administrere**. Ingen andre omraader trengs.
Bruk vanlig gyldig JSON; anfoerselstegn og backslash i passord maa escapes.
Kontroller at NPM-ID 62 og `npm_certificate_name` stemmer med oppfoeringen din.
Ingen hemmeligheter fra HAR-filen er lagt i denne pakken.

Sett ogsaa riktig containernavn i `npm_test_command` og `npm_reload_command`.
Finn det med `docker ps --format '{{.Names}}'` paa NPM-serveren. Eksemplet
forutsetter at Docker-containeren kjoerer paa samme server som skriptet.
Hvis NPM ligger paa en annen server, maa kommandoene kjoeres der, for eksempel
via ferdig konfigurert SSH-noekkel og `BatchMode=yes`. Kommandoene er JSON-lister
med argumenter, ikke shell-strenger. Ikke legg passord i kommandolinjen.
Skriptet nekter opplasting hvis reload-kommandoene fortsatt inneholder plassholdere.
API-opplasting alene garanterer ikke at nginx har lastet det nye sertifikatet.

NPM-adressen bruker HTTP som i ditt eksisterende oppsett. Passord, token og privatnoekkel
sendes derfor ukryptert paa denne forbindelsen. Bruk den bare over et betrodd nett/VPN,
eller sett `npm_url` til en fungerende HTTPS-adresse. TLS-kontroll deaktiveres ikke.

## 2. Kontroller API og lagre fornyelsesoppsettet

```bash
cd /opt/communitynord-certbot
python3 automation.py preflight
./communitynord.sh configure
```

`preflight` leser DNS og sjekker at noekkelen eksponerer oppretting/sletting.
Den endrer ikke DNS. `configure` bruker Certbots staging-test og lagrer hookene
for eksisterende sertifikat `communitynord.com`. Testen oppretter og rydder opp
virkelige DNS-valideringsposter, men erstatter ikke produksjonssertifikatet.
Hvis Certbot ikke finner sertifikatnavnet, stopp og sammenlign med `certbot certificates`.

Kjoer ved behov en ny ende-til-ende-test:

```bash
./communitynord.sh test
```

Testkjoeringen tester DNS/ACME, ikke NPM-opplastingen. `--run-deploy-hooks` er
bevisst utelatt slik at testen ikke endrer NPM. Certbot kan med dette flagget
kjoere deploy-hooken med det aktive produksjonssertifikatet, men her testes
opplasting separat i neste trinn.

## 3. Test NPM med eksisterende produksjonssertifikat

```bash
./copytonpm.sh
```

Dette oppdaterer ID 62, tester nginx-konfigurasjonen og utfoerer reload.
Det skrives bekreftelse ved suksess. Kontroller i NPM at
utloepsdato og domener stemmer, og at aktuelle proxy-hoster bruker denne ID-en.
Kontroller deretter sertifikatet fra en klient mot en faktisk HTTPS-host:

```bash
openssl s_client -connect DIN_HTTPS_HOST:443 -servername DIN_HTTPS_HOST </dev/null 2>/dev/null | openssl x509 -noout -dates -serial -issuer
```

Bytt `DIN_HTTPS_HOST` med en host som bruker dette sertifikatet.
API-suksess beviser ikke alene at en gitt proxy-host serverer det riktige sertifikatet.

## 4. Aktiver cron etter vellykkede tester

```bash
install -o root -g root -m 644 /tmp/certbot-webhuset/communitynord.cron /etc/cron.d/communitynord-certbot
systemctl enable --now cron
```

Cron-filen maa slutte med linjeskift. Tidssonen er serverens, ikke Codex-maskinens.
Foelg loggen med:

```bash
journalctl -t communitynord-certbot --since '7 days ago'
tail -n 100 /var/log/letsencrypt/letsencrypt.log
```

Det er ingen separat e-post-/SMS-varsling inkludert. Koble disse loggene og
sertifikatutloep til din eksisterende overvaaking. Vellykkede kjoeringer uten
fornyelse/opplasting er stille. Feil gir feilkode og loggmelding.

Eksisterende `certbot.timer` kan fortsette aa ha ansvar for andre sertifikater.
Etter `configure` kjenner det ogsaa hookene for dette sertifikatet. Certbot har
egen laas; daglig wrapper har i tillegg `flock`, og NPM-opplasting har separat laas.
Hvis en annen Certbot-jobb overlapper, kan en kjoering feile med laasefeil og
proeves igjen neste dag. Velg eventuelt et annet klokkeslett.

## Feil og gjenoppretting

- 401/403 fra Webhuset: sjekk noekkel, utloepsdato og DNS-administrasjonstilgang.
- DNS-timeout: sjekk autoritative navnetjenere, eventuell CNAME-delegering paa
  `_acme-challenge`, og utgaaende DNS mot resolverne. Denne pakken forutsetter at
  challenge-postene ligger direkte i Webhuset-sonen, slik HAR-filen viste.
- NPM-feil: sjekk URL, bruker, passord, sertifikat-ID og navn. Kjoer `copytonpm.sh`
  igjen etter retting. Fingeravtrykket lagres bare ved vellykket opplasting og reload.
- Hvis prosessen blir drept eller Webhuset er utilgjengelig under opprydding,
  kan en gammel challenge-verdi bli liggende. Kontroller den konkret; ikke slett
  alle TXT-poster paa navnet under en annen paagaaende validering.
- Hvis sertifikatet ble endret manuelt i NPM etter siste vellykkede opplasting,
  fjern `/var/lib/communitynord-certbot/last-upload.sha256` og kjoer
  `copytonpm.sh` for aa sende serverens produksjonssertifikat paa nytt.
- For aa stoppe bare denne cron-jobben: fjern `/etc/cron.d/communitynord-certbot`.
  Hookene ligger fortsatt i Certbots fornyelsesoppsett, saa `certbot.timer` kan
  fortsatt fornye. Ikke slett `/opt`-mappen mens Certbot viser til hookene.

## HAR-funn og verifisering

HAR viste `GET /domain/communitynord.com/dns`, `POST .../dns/txt` med `fqdn` og
`txt`, og `DELETE .../dns/txt` med samme navn og verdi. Det er kundesenterets
sesjonsbaserte API. Denne implementasjonen bruker i stedet det dokumenterte
MCP-endepunktet med din nye API-noekkel og kommandoene `create_dns_record` og
`delete_dns_record`. HAR-innholdet er behandlet som data, ikke instruksjoner.

11 lokale tester er bestatt med falske API-svar; de fire shell-skriptene er
ogsaa syntakssjekket med Bash. Testene dekker blant annet korrekt DNS-navn,
flere challenge-verdier, presis sletting, MCP/SSE, opprydding ved timeout,
opplastingsfeil med nytt forsoek, reload-feil og beskyttelse mot feil NPM-ID. Kjoer:

```bash
python3 -m unittest -v test_automation.py
```

Live-autentisering, faktiske MCP-svar fra din konto, DNS-propagasjon og NPM-versjonen
maa verifiseres med trinnene over. De er ikke testet fra utviklingsmaskinen.

Kilder:
- https://www.webhuset.no/mcp/docs
- https://www.webhuset.no/hjelp/min-konto/api-n-kler-koble-ai-assistenter-og-automatisering-til-webhuset-mcp
- https://eff-certbot.readthedocs.io/en/stable/using.html#modifying-the-renewal-configuration-of-existing-certificates
- https://github.com/NginxProxyManager/nginx-proxy-manager/blob/develop/backend/schema/swagger.json
- https://modelcontextprotocol.io/specification/2025-03-26/basic/transports
