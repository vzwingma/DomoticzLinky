# Changelog

Toutes les évolutions notables du fork `vzwingma/DomoticzLinky` sont consignées ici.

Le format s'inspire de [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) ; le projet suit le [versionnage sémantique](https://semver.org/lang/fr/).

## [3.0.0] - 2026-11-27

Version **incompatible** : nouveaux paramètres du matériel, reconfiguration nécessaire (voir [readme.md](readme.md#migration-depuis-la-version-2x)). Plan d'action 011 et ADR 008 du dépôt [vzwingma/domotique](https://github.com/vzwingma/domotique).

### Ajouté

- **Source de données Conso API** ([conso.boris.sh](https://conso.boris.sh), API Enedis « Mesure synchrone V2 »), source **par défaut**. Pas de Device Flow : jeton personnel (Bearer) obtenu après consentement sur conso.boris.sh, valable 3 ans, révocable dans l'espace client Enedis.
- Nouveaux paramètres du matériel : `Address` = « Source des données » (Conso API / Legacy), `Username` = PRM (14 chiffres, plusieurs séparés par des virgules), `Password` = jeton Conso API (champ masqué). Jeton vide ou PRM invalide : erreur explicite au démarrage, aucune requête.
- Adaptateur des réponses V2 vers le format interne : courbe de charge au pas de **15 min** (W, horodatage de fin d'intervalle), puissance maximale (VA), cœur du calcul (moyenne horaire, HC/HP, devices `Linky <PRM>` et leur historique) inchangé.
- **Budget d'appels** conforme aux [règles d'usage de Conso API](https://conso.boris.sh/blocage-ip) : au plus **3 requêtes par jour et par PRM**, retries compris (compteur conservé en base, y compris après redémarrage) ; cycle normal = 2 requêtes (courbe 7 j + puissance max) ; historique complet **étalé** à raison d'un lot par jour ; **une seule** nouvelle tentative, 3 h plus tard (avant 22 h), en cas d'erreur temporaire ou de données de la veille incomplètes, sinon le lendemain ; pas de nouvelle requête au redémarrage si le cycle du jour a réussi ; requêtes strictement séquentielles.
- En-tête `User-Agent: DomoticzLinkyPlugin/<version> (+https://github.com/vzwingma/DomoticzLinky)`.
- Tests : fixtures V2 anonymisées, `tests/test_consoapi_adapter.py`, `tests/test_consoapi_source.py`, masquage du jeton dans `tests/test_secrets_masking.py` (182 tests).

### Modifié

- L'ancien proxy (API Enedis v5) devient la source **Legacy**, conservée en repli jusqu'à la coupure de l'API v5 (valeur `legacy` ; `russandol` accepté).
- Mode Conso API : 401/403 → message « jeton invalide ou expiré », pas de nouvelle tentative avant le lendemain (le plugin n'est plus désactivé) ; 400 → erreur Enedis (`ADAM-*`) affichée, pas de nouvelle tentative ; 429, 5xx et délai dépassé → une tentative différée (le renvoi après 5 s et la relance horaire restent propres à la source Legacy).
- Mode Conso API : aucune requête de production ; lots de puissance maximale de **365 jours** (1 095 en Legacy).
- `getError()` lit les erreurs imbriquées V2 (`error.error`, `error.error_description`) et le champ `message`.
- Libellés de `Mode3` (« Debug ») clarifiés : « Simple (fichier de log dans /tmp) », « Avancé (fichier de log + debug Domoticz) », « Legacy : effacer consentement et jetons, puis remettre Non », « Vider le cache des données, puis remettre Non ».
- Version du plugin portée à **3.0.0**.

### Supprimé

- Serveur de test (bac à sable `opensrcdev.alwaysdata.net`) et options « Faux client 0 à 9 » (`Mode3` = 10 à 19) — clôt D13.

### Sécurité

- Le jeton Conso API est masqué (`***`) partout dans les journaux du plugin et le fichier de debug, y compris s'il est renvoyé dans une réponse ; la clé `password` est ajoutée aux clés sensibles.
- Limite connue inchangée (D17) : le debug du framework Domoticz (`Mode3` ≥ 2) n'est pas filtré et peut écrire l'en-tête `Authorization` en clair dans le log Domoticz.

## [2.7.0] - 2026-11-25

### Sécurité

- **Masquage des secrets dans les journaux** (log Domoticz **et** fichier de debug `/tmp/DomoticzLinky_*.log`) : les valeurs de `access_token`, `refresh_token`, `device_code`, `id_token`, `client_secret`, des en-têtes `Authorization` (`Bearer` / `Basic`) et des cookies (`Cookie`, `Set-Cookie`) sont remplacées par `***`. Le masquage s'applique par clé à chaque profondeur de `dumpDictToLog()` et par motif à tous les messages (`myLog()`, `myStatus()`, `myError()`, `myDebug()`).
- `setConfigItem()` ne journalise plus la valeur en cas d'erreur d'écriture de configuration (clé et type seulement).
- Laissés en clair volontairement : l'URL et le `user_code` de consentement (nécessaires à l'utilisateur) et le PRM.
- **Limite connue (non corrigée, backlog D17)** : `Mode3` ≥ 2 (Avancé, Reset consentement, Reset cache, Faux clients) active le debug complet du framework Domoticz, qui n'est pas filtré par le plugin et peut écrire des jetons en clair dans le log Domoticz. N'activer que ponctuellement, puis purger le log (voir [readme.md](readme.md#paramètres-du-plugin) et [docs/RETROCONCEPTION.md](docs/RETROCONCEPTION.md) § 13).

### Corrigé

- **D1a** : `onCommand()` et `onNotification()` existent désormais dans `BasePlugin` (trace de debug seulement, le texte des notifications n'est pas journalisé) ; plus d'`AttributeError` quand Domoticz appelle ces callbacks.
- **D2** : version de Domoticz non reconnue → message d'erreur explicite et arrêt propre du plugin (au lieu d'une exception au démarrage).
- **D3** : `mergeCounters()` fusionne correctement les dates de production sans consommation ; accès `value_year` protégés, PRM absents ignorés, erreur interne journalisée (échec global conservé).
- **D5** : message « Trop de dispositifs » lorsque les 255 unités Domoticz sont occupées.
- **D16** : le fichier de debug est fermé à l'arrêt du plugin (`onStop()`). Il n'est toujours pas supprimé (purge manuelle).

### Ajouté

- **Tests** : suite `pytest` (`tests/`) avec un faux module `Domoticz` : correctifs ci-dessus, masquage des secrets (valeurs sentinelles), non-régression du consentement en clair, caractérisation de la persistance (clés et format inchangés), du cache (D4) et de D12.
- **CI** : workflow GitHub Actions `.github/workflows/ci.yml` (`py_compile`, `ruff`, `pytest`) sur **Python 3.11 et 3.13** (la production utilise Python 3.13.5).
- `requirements-dev.txt` (`pytest`, `ruff`), `ruff.toml` (règles d'erreurs seulement), `.gitignore`.
- Documentation : section « Paramètres du plugin » dans [readme.md](readme.md) (`Mode1` à `Mode6`, effets de `Mode3`) ; [docs/RETROCONCEPTION.md](docs/RETROCONCEPTION.md) mise à jour (statuts, masquage, provenance épinglée, supervision).

### Modifié

- Version du plugin portée à **2.7.0** (bloc XML de `plugin.py`) ; `externallink` pointe vers le fork.
- D4 : commentaire explicatif ajouté sur `sTypeHour2 = "production1_hours"` ; **comportement inchangé**.
- Inchangés : clés et format de persistance (`domoticz.db`, jetons et cache), D12 (contournement volontaire du statut 500 en production), protocole d'authentification. Retour arrière possible vers 2.6.1 sans perte de données.

## [2.6.1]

Version de référence de la rétroconception : code identique à l'upstream `guillaumezin/DomoticzLinky` au commit `1ef6adf`. Le tag `v2.6.1` du fork ne porte que de la documentation (`docs/RETROCONCEPTION.md`) ; `plugin.py` est inchangé.
