"""D12 : statut HTTP 500 traité comme « pas de donnée » en production, mais comme « à réessayer » en
consommation. Contournement VOLONTAIRE (constat C3) : ne pas corriger, ces tests doivent rester verts.
"""
from datetime import datetime
from unittest.mock import MagicMock

import pytest

PRM = "PRM-SENTINEL-0001"


@pytest.fixture
def machine(plugin_module, plugin, monkeypatch):
    """Machine à états prête à traiter la réponse d'une étape `getdatahours`, effets de bord neutralisés."""
    plugin.sConnectionStep = "getdatahours"
    plugin.sUsagePointId = PRM
    plugin.lUsagePointIndex = [PRM]
    plugin.iUsagePointIndex = 0
    plugin.bFirstBatch = True
    plugin.bNoConsumption = False
    plugin.bNoProduction = False
    plugin.dateBeginHours = datetime(2026, 1, 1)
    plugin.dateEndHours = datetime(2026, 1, 8)
    plugin.dateNextConnection = datetime(2026, 1, 9, 8, 0)
    mocks = {}
    for nom, retour in (("saveDataToDb", True), ("mergeCounters", True), ("saveCache", None),
                        ("savePreviousSuccessfulConnectionDate", None), ("setNextConnection", False),
                        ("setNextConnectionForLater", False)):
        mocks[nom] = MagicMock(return_value=retour)
        monkeypatch.setattr(plugin, nom, mocks[nom])
    return plugin, mocks


class TestD12Statut500:
    def test_500_en_production_est_traite_comme_absence_de_donnee(self, machine):
        plugin, mocks = machine
        plugin.bProdMode = True
        plugin.handleConnection({"Status": 500})
        assert plugin.bNoProduction is True
        mocks["setNextConnectionForLater"].assert_not_called()
        mocks["saveDataToDb"].assert_called_once_with(PRM)
        assert plugin.sConnectionStep == "idle"

    def test_500_en_consommation_declenche_une_nouvelle_tentative(self, machine):
        plugin, mocks = machine
        plugin.bProdMode = False
        plugin.handleConnection({"Status": 500})
        assert plugin.sConnectionStep == "retry"
        mocks["setNextConnectionForLater"].assert_called_once()
        mocks["saveDataToDb"].assert_not_called()
