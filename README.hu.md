<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/banner-dark.png">
  <img alt="Mentat Engine, a Mentat csomag része" src="assets/banner-light.png" width="100%">
</picture>

# Mentat Engine

[![Kiadás](https://img.shields.io/github/v/tag/lipi4242/anytime-engine?label=kiad%C3%A1s)](https://github.com/lipi4242/anytime-engine/tags)
[![CI](https://github.com/lipi4242/anytime-engine/actions/workflows/ci.yml/badge.svg)](https://github.com/lipi4242/anytime-engine/actions/workflows/ci.yml)
[![Licenc](https://img.shields.io/badge/licenc-Apache--2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![HU | EN](https://img.shields.io/badge/nyelv-HU%20%7C%20EN-informational.svg)](README.md)

A legtöbben nem telepítik külön: a [Mentat Brain](https://github.com/lipi4242/mentat-ai-bootstrap/blob/main/README.hu.md) telepítése ezt is beállítja.

A motor ütemezést ad a Mentat-kollégádnak. Elküldi a reggeli összefoglalót és a határidő-emlékeztetőket, amiket különben neked kellene kérned, és minden nyitott ügyet a listán tart, amíg le nem zárul.

- Minden reggel: mi késik, mi esedékes ma és a héten, az ügyeidből, a határidős teendőidből és a határidő-táblázataidból.
- Emlékeztető három nappal minden határidő előtt és aznap, fájlban vagy Telegramon, éjszaka csendben.
- A jóváhagyáshoz kötött üzenet csak akkor megy ki, ha egyezik vele, és egy elvégzett lépés összeomlás után sem ismétlődik.

Fejlesztőknek: a döntés sima Python, modellhívás nélkül, így ugyanabban a pillanatban mindig ugyanaz a terv születik, a munkát pedig az ágensed végzi. Asszisztensenként egy példány fut, tartós systemd- vagy cron-időzítővel, és a `setup --doctor` összeveti a telepített időzítőt azzal, amit a setup írna.

## Telepítés

A legegyszerűbb: kérd meg a Mentat-kollégádat, hogy adja hozzá a motort, ő futtatja a lépéseket. Kézzel, egy már meglévő agyhoz így adod hozzá: nyisd meg a Claude Code-ot abban a mappában, és másold be:

```
Telepítsd az anytime engine-t (github.com/lipi4242/anytime-engine) ebbe a repóba. Futtasd pontosan ezt:
  git clone --depth 1 --branch v0.3.1 https://github.com/lipi4242/anytime-engine /tmp/anytime-engine
  /tmp/anytime-engine/sync-to.sh . --pack cases
  python3 -m anytime_engine.selftest -q
Utána kérdezd meg az időzónámat, és hogy hová menjenek az emlékeztetők (fájl vagy Telegram), és futtasd:
python3 -m anytime_engine.setup --tz <tz> --deliver <file|telegram> --lang hu, az igenem után --install-lal.
```

## Képesség-napló

A legújabb bejegyzések:

- Határidők közvetlenül táblázatból
- Az ütemezett üzenet csak akkor megy ki, ha egyezik a jóváhagyottal
- Szól, ha valaki kézzel átírta az időzítőjét
- Gyorsabb telepítés

Kiadási jegyzetek és frissítési lépések (angolul): [CHANGELOG.md](CHANGELOG.md). Minden változás a teljes csomagban: [képesség-napló](https://github.com/lipi4242/mentat-ai-bootstrap/blob/main/CAPABILITY-LOG.hu.md).

<!-- mentat:family START (a mentat-ai-bootstrap-dev docs/readme/render.py generálja; minden Mentat-repóban azonos) -->
## A Mentat csomag

| Rész | Mit csinál |
|---|---|
| [Mentat Brain](https://github.com/lipi4242/mentat-ai-bootstrap) | Maga a kolléga: memória sima jegyzetekben, gitben, személyiség, biztonsági szabályok, eszközök. |
| [Mentat Engine](https://github.com/lipi4242/anytime-engine) | Az ütemezés: reggeli összefoglaló, határidő-emlékeztetők, és figyel minden nyitott ügyre. |
| [Mentat Fleet](https://github.com/lipi4242/fleet-leader) | Szerveren, éjjel-nappal futtatja az ágenseket, és a Telegramhoz köti őket. |
| Mentat Admin | Kis webalkalmazás az ágens nyilvántartásaihoz. Hamarosan. |
<!-- mentat:family END -->

## Tovább

[Útmutató (angolul)](GUIDE.md) · [Biztonság](SECURITY.md) · [Apache-2.0](LICENSE)
