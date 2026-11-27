"""v3.1.0 — production (injection) en mode Conso API, sur option (source « consoapi_prod »).

Fixture `200_courbe_de_charge_production` : courbe synthétique (grandeur PROD, W au pas de 15 min, cloche 9 h - 17 h,
pic 1 800 W) sur la même période que la fixture de consommation (23 -> 26/11/2026), PRM anonymisé.

Budget inchangé : au plus 3 requêtes par jour et par PRM. Cycle normal = courbe conso + courbe production ;
la puissance max n'est redemandée qu'au plus une fois tous les 7 jours.
"""
import json
from datetime import datetime

import pytest
from consoapi_helpers import (
    PRM,
    freeze,
    load,
    nominal_responder,
    response,
    run_cycle,
    start_consoapi,
)

DAY_COMPLETE = (2026, 11, 26, 8, 34, 45)


def count_today(plugin):
    return plugin.getConfigItem("consoapi_budget", {}).get("count", {})


def types_of(sent):
    return [r["URL"].split("?")[0].replace("/api/", "") for r in sent]


@pytest.fixture
def clock(plugin_module, monkeypatch):
    return freeze(plugin_module, monkeypatch, *DAY_COMPLETE)


@pytest.fixture
def prod(plugin_module, domoticz, clock):
    return start_consoapi(plugin_module, Address="consoapi_prod")


class TestOption:
    def test_option_dans_les_parametres(self, plugin_module):
        assert 'value="consoapi_prod"' in plugin_module.__doc__

    def test_consoapi_prod_active_la_production(self, prod, plugin_module, domoticz):
        assert prod.bConsoApi is True
        assert prod.bConsoApiProd is True
        assert prod.iAlternateAddress == plugin_module.CONSOAPI_ADDRESS_INDEX
        assert any("production (injection) activée" in m for m in domoticz.logs["Log"])

    @pytest.mark.parametrize("address", ["consoapi", "", "legacy"])
    def test_production_desactivee_par_defaut(self, plugin_module, domoticz, clock, address):
        plugin = start_consoapi(plugin_module, Address=address)
        assert plugin.bConsoApiProd is False

    def test_sans_option_aucune_requete_de_production(self, plugin_module, domoticz, clock):
        plugin = start_consoapi(plugin_module, Address="consoapi")
        assert not any("production" in t for t in types_of(run_cycle(plugin)))


class TestAdaptateur:
    def test_grandeur_prod_choisie(self, plugin_module):
        body = {"idPrm": PRM, "grandeur": [
            {"grandeurMetier": "CONS", "points": [{"v": "1", "d": "2026-11-23 00:15:00"}]},
            {"grandeurMetier": "PROD", "points": [{"v": "9", "d": "2026-11-23 12:15:00"}]},
        ]}
        assert plugin_module.consoApiV2ToInternal(body, "PROD")["meter_reading"]["interval_reading"] == [
            {"value": "9", "date": "2026-11-23 12:15:00"}]
        assert plugin_module.consoApiV2ToInternal(body)["meter_reading"]["interval_reading"] == [
            {"value": "1", "date": "2026-11-23 00:15:00"}]

    def test_fixture_production(self, plugin_module):
        out = plugin_module.consoApiV2ToInternal(json.loads(load("200_courbe_de_charge_production").decode()), "PROD")
        readings = out["meter_reading"]["interval_reading"]
        assert out["meter_reading"]["usage_point_id"] == PRM
        assert len(readings) == 288
        assert max(float(r["value"]) for r in readings) == 1800.0


class TestCycle:
    def test_premier_cycle_trois_requetes(self, prod):
        sent = run_cycle(prod)
        assert types_of(sent) == ["courbe_de_charge_consommation", "puissance_conso_max_quotidienne",
                                  "courbe_de_charge_production"]
        assert sent[2]["URL"] == "/api/courbe_de_charge_production?pointId=" + PRM + "&dateDebut=2026-11-19&dateFin=2026-11-26"
        assert count_today(prod) == {PRM: 3}

    def test_production_stockee_et_device_mis_a_jour(self, prod, plugin_module, domoticz):
        run_cycle(prod)
        hours = prod.dData[PRM]["data"]["2026-11-25"]["production1_hours"]
        # Moyenne horaire des 4 points de 15 min ; heure 13 = fin d'intervalle 12 h -> 13 h, autour du pic
        assert max(hours.values()) == pytest.approx(1800.0, rel=0.05)
        assert hours.get(3, 0.0) == 0.0
        assert prod.dData[PRM]["data"]["2026-11-25"]["consumptionpeak"] == 2415.0
        assert plugin_module.Devices[1].Update.called
        assert domoticz.logs["Error"] == []
        assert prod.bGlobalHasAFail is False

    def test_puissance_max_hebdomadaire(self, prod, clock):
        run_cycle(prod)
        clock.current = clock(2026, 11, 27, 8, 34, 45)
        day2 = run_cycle(prod)
        assert "puissance_conso_max_quotidienne" not in types_of(day2)
        assert "courbe_de_charge_production" in types_of(day2)
        clock.current = clock(2026, 12, 3, 8, 34, 45)
        day8 = run_cycle(prod)
        assert "puissance_conso_max_quotidienne" in types_of(day8)

    def test_puissance_max_non_marquee_si_echec(self, prod):
        def responder(request):
            if "puissance_conso_max_quotidienne" in request["URL"]:
                return response(status=503, body=b"{}")
            return nominal_responder(request)

        run_cycle(prod, responder)
        assert prod.consoApiPeakDue(PRM) is True

    @pytest.mark.parametrize("status", [400, 404])
    def test_pas_de_production_memorise(self, prod, clock, status):
        def responder(request):
            if "courbe_de_charge_production" in request["URL"]:
                return response(status=status, body={"status": status, "message": "Aucune donnée"})
            return nominal_responder(request)

        run_cycle(prod, responder)
        assert prod.getCacheNoData(PRM, True) is True
        assert prod.bConsoApiDefer is False
        clock.current = clock(2026, 11, 27, 8, 34, 45)
        day2 = run_cycle(prod, responder)
        assert "courbe_de_charge_production" not in types_of(day2)

    @pytest.mark.parametrize("status", [401, 403])
    def test_jeton_invalide_sur_production(self, prod, domoticz, status):
        def responder(request):
            if "courbe_de_charge_production" in request["URL"]:
                return response("err_401_jeton_invalide", status=status)
            return nominal_responder(request)

        run_cycle(prod, responder)
        assert any("Jeton Conso API invalide" in e for e in domoticz.logs["Error"])
        # Pas de tentative différée : prochaine connexion le lendemain
        assert prod.dateNextConnection.date() == datetime(2026, 11, 27).date()
        assert prod.isStarted is True

    @pytest.mark.parametrize("status", [429, 500, 503])
    def test_jamais_plus_de_3_requetes_par_jour(self, prod, status):
        sent = run_cycle(prod, lambda request: {"Status": str(status), "Data": b"{}"})
        sent += run_cycle(prod, lambda request: {"Status": str(status), "Data": b"{}"})
        assert len(sent) <= 3
        assert count_today(prod)[PRM] <= 3


class TestHistorique:
    @pytest.fixture
    def long_history(self, plugin_module, domoticz, clock):
        return start_consoapi(plugin_module, Address="consoapi_prod", Mode2="30")

    def test_puissance_max_due_avant_historique(self, long_history, domoticz):
        # Jour 1 : la puissance max est due, l'historique de consommation attend ; la production garde sa requête
        sent = run_cycle(long_history)
        assert types_of(sent) == ["courbe_de_charge_consommation", "puissance_conso_max_quotidienne",
                                  "courbe_de_charge_production"]
        assert count_today(long_history)[PRM] == 3
        # L'historique de production, sans budget restant, est reporté sans faire échouer le cycle
        assert not any("Budget Conso API du jour atteint" in m for sLevel in ("Status", "Error") for m in domoticz.logs[sLevel])
        assert long_history.dateNextConnection.date() == datetime(2026, 11, 27).date()

    def test_historique_consommation_puis_production(self, long_history, clock):
        run_cycle(long_history)
        clock.current = clock(2026, 11, 27, 8, 34, 45)
        day2 = run_cycle(long_history)
        # Jour 2 : courbe conso du jour, un lot d'historique de consommation, courbe de production du jour
        assert types_of(day2) == ["courbe_de_charge_consommation", "courbe_de_charge_consommation",
                                  "courbe_de_charge_production"]
        assert len(day2) <= 3
