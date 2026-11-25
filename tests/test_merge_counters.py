"""D3 : mergeCounters() — mauvaise boucle de fusion, KeyError sur `value_year`, `except:` muet.

Scénario nominal du plugin : un PRM en consommation seule (A) et un PRM en production seule (B) sont
fusionnés en un compteur virtuel "A / B". `saveDataToDb` est remplacée par un mock (effet de bord vers
la base Domoticz hors périmètre de ces tests).
"""
from datetime import datetime
from unittest.mock import MagicMock

import pytest

PRM_A = "PRM-SENTINEL-A"
PRM_B = "PRM-SENTINEL-B"
D1 = "2026-01-10"
D2 = "2026-01-11"


def calc(conso=0, prod=0):
    """dCalculate d'un PRM, tel que rempli par doCalculation() (clé `value_year` si donnée dans l'année)."""
    def bloc(v):
        return {"value_year": v}
    return {
        "consumption1": bloc(conso), "consumption2": bloc(0),
        "production1": bloc(prod), "production2": bloc(0),
        "consumptionpeak": {}, "productionpeak": {},
    }


def jour(plugin_module, sDate, conso=None, prod=None):
    """Journée de données au format de initData(), avec heures de consommation et/ou de production."""
    d = plugin_module.initData()
    y, m, j = (int(x) for x in sDate.split("-"))
    d["consoproddate"] = datetime(y, m, j)
    d["hasconsoprod"] = True
    if conso:
        d["consumption1_hours"] = dict(conso)
    if prod:
        d["production1_hours"] = dict(prod)
    return d


@pytest.fixture
def deux_prm(plugin_module, plugin, monkeypatch):
    """A : consommation seule (jour D1). B : production seule (jours D1 et D2)."""
    state = plugin_module.initState
    plugin.dData = {
        PRM_A: {"data": {D1: jour(plugin_module, D1, conso={10: 1.5, 11: 2.5})}, "state": state()},
        PRM_B: {"data": {D1: jour(plugin_module, D1, prod={12: 7.0}),
                         D2: jour(plugin_module, D2, prod={13: 8.0, 14: 9.0})}, "state": state()},
    }
    plugin.dCalculate = {PRM_A: calc(conso=4.0), PRM_B: calc(prod=24.0)}
    mock_save = MagicMock(return_value=True)
    monkeypatch.setattr(plugin, "saveDataToDb", mock_save)
    return plugin, mock_save


class TestMergeNominal:
    """Caractérisation : comportement déjà correct, à conserver après correctif."""

    def test_fusion_cree_le_compteur_virtuel(self, deux_prm):
        plugin, mock_save = deux_prm
        assert plugin.mergeCounters() is True
        sMerged = PRM_A + " / " + PRM_B
        assert sMerged in plugin.dData
        mock_save.assert_called_once_with(sMerged)

    def test_fusion_copie_la_production_sur_les_dates_communes(self, deux_prm):
        plugin, _ = deux_prm
        plugin.mergeCounters()
        merged = plugin.dData[PRM_A + " / " + PRM_B]["data"][D1]
        assert merged["consumption1_hours"] == {10: 1.5, 11: 2.5}
        assert merged["production1_hours"] == {12: 7.0}

    def test_fusion_ne_modifie_pas_les_sources(self, deux_prm):
        plugin, _ = deux_prm
        plugin.mergeCounters()
        assert plugin.dData[PRM_A]["data"][D1]["production1_hours"] == {}
        assert plugin.dData[PRM_B]["data"][D1]["consumption1_hours"] == {}

    def test_pas_de_fusion_si_un_seul_prm(self, plugin_module, plugin, monkeypatch):
        mock_save = MagicMock(return_value=True)
        monkeypatch.setattr(plugin, "saveDataToDb", mock_save)
        plugin.dData = {PRM_A: {"data": {D1: jour(plugin_module, D1, conso={10: 1.0})}, "state": plugin_module.initState()}}
        plugin.dCalculate = {PRM_A: calc(conso=1.0)}
        assert plugin.mergeCounters() is True
        assert list(plugin.dData) == [PRM_A]
        mock_save.assert_not_called()

    def test_echec_de_saveDataToDb_remonte_false(self, deux_prm):
        plugin, mock_save = deux_prm
        mock_save.return_value = False
        assert plugin.mergeCounters() is False


class TestD3Bugs:
    def test_dates_de_production_sans_consommation_sont_fusionnees(self, deux_prm):
        plugin, _ = deux_prm
        plugin.mergeCounters()
        dMerged = plugin.dData[PRM_A + " / " + PRM_B]["data"]
        assert D2 in dMerged, "la date de production seule %s est perdue dans le compteur fusionné" % D2
        assert dMerged[D2]["production1_hours"] == {13: 8.0, 14: 9.0}
        assert dMerged[D2]["hasconsoprod"] is True

    def test_dCalculate_vide_retourne_true(self, plugin_module, plugin):
        plugin.dData = {PRM_A: {"data": {}, "state": plugin_module.initState()}}
        plugin.resetCalculate(PRM_A)  # dictionnaires vides, sans clé value_year
        assert plugin.mergeCounters() is True

    def test_prm_vide_n_empeche_pas_la_fusion_des_autres(self, deux_prm, plugin_module):
        plugin, mock_save = deux_prm
        plugin.dData["PRM-SENTINEL-C"] = {"data": {}, "state": plugin_module.initState()}
        plugin.resetCalculate("PRM-SENTINEL-C")
        assert plugin.mergeCounters() is True
        mock_save.assert_called_once_with(PRM_A + " / " + PRM_B)

    def test_prm_absent_de_dData_est_ignore(self, deux_prm):
        plugin, mock_save = deux_prm
        del plugin.dData[PRM_B]  # présent dans dCalculate, absent de dData
        assert plugin.mergeCounters() is True
        mock_save.assert_not_called()

    def test_exception_interne_est_journalisee(self, deux_prm, domoticz):
        plugin, mock_save = deux_prm
        mock_save.side_effect = RuntimeError("panne-simulee")
        assert plugin.mergeCounters() is False
        assert any("fusion" in m.lower() for m in domoticz.logs["Error"]), \
            "aucune erreur journalisée : %r" % domoticz.logs["Error"]
