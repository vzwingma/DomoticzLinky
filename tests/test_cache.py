"""D4 : seuil de complétude du cache en production (caractérisation, aucun correctif prévu).

`getDataHours()` utilise `production1_hours` pour `sTypeHour1` ET `sTypeHour2` en production ; la
condition `len(h1) + len(h2) < 23` revient donc à exiger ~12 heures de production (diurne) :
12 h suffisent (cache utilisé), 11 h ne suffisent pas (nouvelle requête). Comportement VOLONTAIRE
(voir rétrodoc D4) : ces tests doivent rester verts après les correctifs.
"""
from datetime import datetime
from unittest.mock import MagicMock

import pytest

PRM = "PRM-SENTINEL-0001"
SDAY = "2026-01-10"
DT_START = datetime(2026, 1, 10)
DT_END = datetime(2026, 1, 11)


def charger_jour(plugin_module, plugin, **heures):
    """Une journée dans le cache avec `heures` = {nom_du_champ: nb d'heures remplies}."""
    d = plugin_module.initData()
    for champ, nb in heures.items():
        d[champ] = {h: 1.0 for h in range(nb)}
    plugin.dData[PRM] = {"data": {SDAY: d}, "state": plugin_module.initState()}


@pytest.fixture
def mock_getData(plugin, monkeypatch):
    mock = MagicMock()
    monkeypatch.setattr(plugin, "getData", mock)
    return mock


class TestD4CacheProduction:
    def test_12_heures_de_production_suffisent(self, plugin_module, plugin, mock_getData):
        charger_jour(plugin_module, plugin, production1_hours=12)
        assert plugin.getDataHours(PRM, True, DT_START, DT_END) is True
        mock_getData.assert_not_called()

    def test_11_heures_de_production_ne_suffisent_pas(self, plugin_module, plugin, mock_getData):
        charger_jour(plugin_module, plugin, production1_hours=11)
        assert plugin.getDataHours(PRM, True, DT_START, DT_END) is False
        mock_getData.assert_called_once()
        assert mock_getData.call_args.args[0] == plugin_module.API_ENDPOINT_DATA_PRODUCTION_LOAD_CURVE

    def test_production2_hours_n_est_pas_compte(self, plugin_module, plugin, mock_getData):
        # production2_hours n'est jamais rempli par storeData() : il ne compte pas dans le seuil
        charger_jour(plugin_module, plugin, production1_hours=11, production2_hours=12)
        assert plugin.getDataHours(PRM, True, DT_START, DT_END) is False


class TestCacheConsommation:
    def test_23_heures_de_consommation_suffisent(self, plugin_module, plugin, mock_getData):
        charger_jour(plugin_module, plugin, consumption1_hours=23)
        assert plugin.getDataHours(PRM, False, DT_START, DT_END) is True
        mock_getData.assert_not_called()

    def test_22_heures_de_consommation_ne_suffisent_pas(self, plugin_module, plugin, mock_getData):
        charger_jour(plugin_module, plugin, consumption1_hours=22)
        assert plugin.getDataHours(PRM, False, DT_START, DT_END) is False
        assert mock_getData.call_args.args[0] == plugin_module.API_ENDPOINT_DATA_CONSUMPTION_LOAD_CURVE

    def test_heures_pleines_et_creuses_s_additionnent(self, plugin_module, plugin, mock_getData):
        charger_jour(plugin_module, plugin, consumption1_hours=12, consumption2_hours=11)
        assert plugin.getDataHours(PRM, False, DT_START, DT_END) is True

    def test_date_absente_du_cache_declenche_la_requete(self, plugin_module, plugin, mock_getData):
        plugin.dData[PRM] = {"data": {}, "state": plugin_module.initState()}
        assert plugin.getDataHours(PRM, False, DT_START, DT_END) is False
        mock_getData.assert_called_once()

    def test_prm_inconnu_declenche_la_requete(self, plugin, mock_getData):
        assert plugin.getDataHours(PRM, False, DT_START, DT_END) is False
        mock_getData.assert_called_once()

    def test_cache_aucune_donnee_court_circuite_la_requete(self, plugin_module, plugin, mock_getData):
        plugin.dData[PRM] = {"data": {}, "state": plugin_module.initState()}
        plugin.setCacheEmpty(True, PRM, bProdMode=True)
        assert plugin.getDataHours(PRM, True, DT_START, DT_END) is True
        mock_getData.assert_not_called()
