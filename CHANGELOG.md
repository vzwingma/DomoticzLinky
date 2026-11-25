# Changelog

Toutes les évolutions notables du fork `vzwingma/DomoticzLinky` sont consignées ici.

Le format s'inspire de [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) ; le projet suit le [versionnage sémantique](https://semver.org/lang/fr/).

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
