"""Outils communs aux tests de la source Conso API (plan 011).

* `FakeDatetime` : horloge figée (module importable, donc sérialisable par pickle dans la configuration) ;
* `start_consoapi()` : démarre un plugin via `onStart()` avec les paramètres Conso API ;
* `run_cycle()` : déroule un cycle complet de la machine à états en répondant à chaque requête.

Aucun vrai PRM ni jeton : PRM `00000000000000` (celui des fixtures anonymisées) et jeton sentinelle.
"""
import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "consoapi_v2"
PRM = "00000000000000"
PRM_2 = "11111111111111"
TOKEN = "eyJhbGciOiJIUzI1NiJ9.CONSOAPI-TOKEN-SENTINEL.c2lnbmF0dXJl"


class FakeDatetime(datetime):
    """`datetime` dont `now()` est figé (attribut de classe `current`)."""

    current = None

    @classmethod
    def now(cls, tz=None):
        return cls.current


def freeze(plugin_module, monkeypatch, *args):
    FakeDatetime.current = FakeDatetime(*args)
    monkeypatch.setattr(plugin_module, "datetime", FakeDatetime)
    return FakeDatetime


def load(name):
    return (FIXTURES / (name + ".json")).read_bytes()


def response(name=None, status=200, body=None):
    if body is None:
        body = load(name)
    if isinstance(body, (dict, list)):
        body = json.dumps(body).encode()
    return {"Status": str(status), "Data": body}


def start_consoapi(plugin_module, **params):
    plugin_module.Parameters.update({"Address": "consoapi", "Username": PRM, "Password": TOKEN})
    plugin_module.Parameters.update(params)
    # Devices `Linky <PRM>` existants (le stub Domoticz ne sait pas en créer)
    if not plugin_module.Devices:
        for iUnit, sPrm in enumerate((PRM, PRM_2), start=1):
            plugin_module.Devices[iUnit] = MagicMock(name="Device " + sPrm, DeviceID=sPrm, nValue=0, sValue="")
    plugin = plugin_module.BasePlugin()
    plugin_module._plugin = plugin
    plugin.onStart()
    return plugin


def nominal_responder(request):
    """Répond comme Conso API à partir des fixtures, selon le type demandé dans l'URL."""
    url = request["URL"]
    if "courbe_de_charge_consommation" in url:
        return response("200_courbe_de_charge_consommation")
    if "puissance_conso_max_quotidienne" in url:
        return response("200_puissance_conso_max_quotidienne")
    if "consommation_quotidienne" in url:
        return response("200_consommation_quotidienne")
    raise AssertionError("requête inattendue : " + url)


def run_cycle(plugin, responder=nominal_responder, max_requests=50):
    """Lance un cycle depuis `idle` et renvoie la liste des requêtes envoyées (dicts Verb/URL/Headers)."""
    sent = []
    plugin.sConnectionStep = "idle"
    plugin.handleConnection()
    while plugin.sConnectionStep in ("connecting", "retry"):
        assert len(sent) < max_requests, "boucle de requêtes"
        if plugin.sConnectionStep == "retry":
            # Envoi différé par l'anti-rafale de 5 s : on simule le battement suivant
            plugin.dtLastSend = datetime(2000, 1, 1)
            plugin.handleConnection()
            continue
        request = plugin.sBuffer
        sent.append(request)
        plugin.sConnectionStep = plugin.sConnectionNextStep
        plugin.dtLastSend = datetime(2000, 1, 1)
        plugin.handleConnection(responder(request))
    return sent
