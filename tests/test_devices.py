"""D5 : getOrCreateDevice() — le test `== 256` est inaccessible (range(1, 256)), échec silencieux."""
from unittest.mock import MagicMock

import pytest


class FakeDevice:
    def __init__(self, deviceId):
        self.DeviceID = deviceId


def remplir_devices(plugin_module, nb):
    """`nb` unités occupées (1..nb) par d'autres dispositifs que ceux du plugin."""
    plugin_module.Devices.clear()
    for i in range(1, nb + 1):
        plugin_module.Devices[i] = FakeDevice("AUTRE-DISPOSITIF-%d" % i)


def installer_creation(domoticz, plugin_module, dicts_kwargs, bSucces=True):
    """Domoticz.Device(...).Create() : ajoute (ou non) le dispositif dans Devices, comme Domoticz."""
    def factory(**kwargs):
        dicts_kwargs.append(kwargs)
        objet = MagicMock()
        objet.DeviceID = kwargs["DeviceID"]
        if bSucces:
            objet.Create.side_effect = lambda: plugin_module.Devices.__setitem__(kwargs["Unit"], objet)
        return objet
    domoticz.Device.side_effect = factory


class TestD5Devices:
    def test_aucune_unite_libre_retourne_none_avec_erreur(self, plugin_module, plugin, domoticz):
        remplir_devices(plugin_module, 255)
        assert plugin.getOrCreateDevice("PRM-SENTINEL-NEW") is None
        assert any("Trop de dispositifs" in m for m in domoticz.logs["Error"]), \
            "aucune erreur 'Trop de dispositifs' : %r" % domoticz.logs["Error"]
        domoticz.Device.assert_not_called()

    def test_dispositif_existant_est_reutilise(self, plugin_module, plugin, domoticz):
        # Caractérisation
        existant = FakeDevice("PRM-SENTINEL-0001")
        plugin_module.Devices[7] = existant
        assert plugin.getOrCreateDevice("PRM-SENTINEL-0001") is existant
        domoticz.Device.assert_not_called()

    def test_creation_utilise_la_premiere_unite_libre(self, plugin_module, plugin, domoticz):
        # Caractérisation
        remplir_devices(plugin_module, 2)
        kwargs = []
        installer_creation(domoticz, plugin_module, kwargs)
        oDevice = plugin.getOrCreateDevice("PRM-SENTINEL-NEW")
        assert oDevice is plugin_module.Devices[3]
        assert kwargs[0]["Unit"] == 3
        assert kwargs[0]["DeviceID"] == "PRM-SENTINEL-NEW"
        assert kwargs[0]["Name"] == "Linky PRM-SENTINEL-NEW"

    def test_unite_255_est_utilisable(self, plugin_module, plugin, domoticz):
        # Caractérisation (borne haute atteignable) : 254 occupées -> unité 255
        remplir_devices(plugin_module, 254)
        kwargs = []
        installer_creation(domoticz, plugin_module, kwargs)
        assert plugin.getOrCreateDevice("PRM-SENTINEL-NEW") is plugin_module.Devices[255]
        assert kwargs[0]["Unit"] == 255

    def test_creation_refusee_par_domoticz_retourne_none_avec_erreur(self, plugin_module, plugin, domoticz):
        # Caractérisation : Create() sans effet (ajout de dispositifs non autorisé)
        installer_creation(domoticz, plugin_module, [], bSucces=False)
        assert plugin.getOrCreateDevice("PRM-SENTINEL-NEW") is None
        assert any("ajout de nouveaux dispositifs est autorisé" in m for m in domoticz.logs["Error"])
