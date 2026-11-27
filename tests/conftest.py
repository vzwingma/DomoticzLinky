"""Harnais de tests du plugin Domoticz Linky.

Le plugin importe `Domoticz` (module fourni par l'hôte) et utilise les globales
`Parameters` et `Devices` injectées par Domoticz. Ce fichier :

* installe un faux module `Domoticz` (journaux capturés, `Configuration` à état,
  `Connection`/`Device` = MagicMock) ;
* charge `plugin.py` via `importlib.util.spec_from_file_location` (module neuf à
  chaque test, donc aucun état partagé) ;
* injecte `Parameters` et `Devices` ;
* fournit la fixture `plugin` (un `BasePlugin` neuf avec `fDebug = io.StringIO()`).

Aucun vrai PRM ni jeton : uniquement des sentinelles.
"""
import importlib.util
import io
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

PLUGIN_PATH = Path(__file__).resolve().parent.parent / "plugin.py"

# Sentinelles : aucune vraie donnée Enedis
PRM_SENTINEL = "PRM-SENTINEL-0001"
TOK_ACCESS = "TOK-ACCESS-SENTINEL"
TOK_REFRESH = "TOK-REFRESH-SENTINEL"
TOK_ID = "TOK-ID-SENTINEL"
DEVICE_CODE = "DEVCODE-SENTINEL"
COOKIE = "COOKIE-SENTINEL"
USER_CODE = "USER-CODE-SENTINEL"
CLIENT_SECRET = "CLIENT-SECRET-SENTINEL"


def _default_parameters():
    return {
        # Suites v2.x : chemin Legacy (la source par défaut v3.0.0 est Conso API)
        "Address": "legacy",
        "Mode1": "7",
        "Mode2": "7",
        "Mode3": "0",
        "Mode4": "",
        "Mode5": "peak_day",
        "Mode6": "value_day",
        "Port": "0",
        "Name": "Linky-test",
        "Version": "2.6.1-test",
        "DomoticzVersion": "2026.1",
        "DomoticzHash": "0000000",
        "DomoticzBuildTime": "2026-01-01",
    }


def _build_domoticz_stub():
    fake = types.ModuleType("Domoticz")
    fake.logs = {"Log": [], "Error": [], "Status": [], "Debug": []}
    fake.config_state = {}
    # Permet de simuler une panne de Domoticz.Configuration (lecture / écriture)
    fake.config_fail_on_get = False
    fake.config_fail_on_set = False

    def _recorder(kind):
        def _record(message, *args, **kwargs):
            fake.logs[kind].append(str(message))
        return _record

    for kind in ("Log", "Error", "Status", "Debug"):
        setattr(fake, kind, _recorder(kind))

    def Debugging(level):  # noqa: N802 - API Domoticz
        return None

    def Configuration(d=None):  # noqa: N802 - API Domoticz
        # Sans argument : renvoie une copie de l'état ; avec argument : le remplace et le renvoie
        if d is None:
            if fake.config_fail_on_get:
                raise RuntimeError("Configuration indisponible en lecture (stub)")
            return dict(fake.config_state)
        if fake.config_fail_on_set:
            raise RuntimeError("Configuration indisponible en écriture (stub)")
        fake.config_state = dict(d)
        return dict(fake.config_state)

    fake.Debugging = Debugging
    fake.Configuration = Configuration
    fake.Connection = MagicMock(name="Domoticz.Connection")
    fake.Device = MagicMock(name="Domoticz.Device")
    return fake


@pytest.fixture
def sentinels():
    """Valeurs factices (jamais de vrai PRM / jeton), accessibles par attribut."""
    return types.SimpleNamespace(
        PRM=PRM_SENTINEL,
        ACCESS=TOK_ACCESS,
        REFRESH=TOK_REFRESH,
        ID=TOK_ID,
        DEVICE_CODE=DEVICE_CODE,
        COOKIE=COOKIE,
        USER_CODE=USER_CODE,
        CLIENT_SECRET=CLIENT_SECRET,
    )


@pytest.fixture
def domoticz():
    """Faux module Domoticz, neuf pour chaque test (installé dans sys.modules)."""
    fake = _build_domoticz_stub()
    previous = sys.modules.get("Domoticz")
    sys.modules["Domoticz"] = fake
    try:
        yield fake
    finally:
        if previous is None:
            sys.modules.pop("Domoticz", None)
        else:
            sys.modules["Domoticz"] = previous


@pytest.fixture
def plugin_module(domoticz):
    """plugin.py chargé comme module neuf, avec `Parameters` et `Devices` injectés."""
    spec = importlib.util.spec_from_file_location("linky_plugin", PLUGIN_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.Parameters = _default_parameters()
    module.Devices = {}
    return module


@pytest.fixture
def plugin(plugin_module):
    """Un BasePlugin neuf, debug avancé, fichier de debug en mémoire."""
    instance = plugin_module.BasePlugin()
    instance.iDebugLevel = 2
    instance.fDebug = io.StringIO()
    instance.iAlternateAddress = 0
    instance.clearData()
    return instance


@pytest.fixture
def captured(domoticz):
    """Fabrique `captured(plugin)` -> tout ce qui est sorti (journaux Domoticz + fichier de debug)."""

    def _captured(instance=None):
        parts = []
        for kind in ("Log", "Error", "Status", "Debug"):
            parts.extend(domoticz.logs[kind])
        if instance is not None and instance.fDebug is not None:
            try:
                parts.append(instance.fDebug.getvalue())
            except ValueError:  # fichier fermé
                pass
        return "\n".join(parts)

    return _captured
