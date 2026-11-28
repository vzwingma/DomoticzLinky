"""v3.1.0 — production (injection) en mode Conso API, sur option (source « consoapi_prod »).

Fixtures : captures réelles anonymisées du 2026-11-28 (PRM masqué) :
* `200_courbe_de_charge_production` : 25/11/2026, grandeur PROD, W, **pas de 30 min** (PT30M, la consommation est
  au pas de 15 min), injection entre 9 h 30 et 17 h ;
* `200_production_quotidienne` : 19 -> 25/11/2026, Wh (non utilisée par le plugin, sert de référence : la somme
  de la courbe du 25/11 doit redonner 7 053 Wh).

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
        assert len(readings) == 48  # pas de 30 min
        assert max(float(r["value"]) for r in readings) == 1934.0

    def test_courbe_absente_pour_cons(self, plugin_module):
        # Réponse de production lue comme de la consommation : aucun point (pas de mélange des grandeurs)
        out = plugin_module.consoApiV2ToInternal(json.loads(load("200_courbe_de_charge_production").decode()))
        assert out["meter_reading"]["interval_reading"] == []


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
        # Pas de 30 min : moyenne des 2 points de l'heure, horodatage de fin d'intervalle (14 h = 13 h -> 14 h)
        assert hours[14] == pytest.approx((1790 + 1934) / 2)
        assert hours[3] == 0.0
        # Moyenne horaire (W) sur 1 h = Wh : la somme de la journée redonne production_quotidienne du 25/11
        daily = json.loads(load("200_production_quotidienne").decode())["grandeur"][0]["points"]
        expected_wh = float(next(p["v"] for p in daily if p["d"] == "2026-11-25"))
        assert sum(hours.values()) == pytest.approx(expected_wh)
        assert prod.dData[PRM]["data"]["2026-11-25"]["consumptionpeak"] == 2415.0
        assert plugin_module.Devices[1].Update.called
        assert domoticz.logs["Error"] == []
        assert prod.bGlobalHasAFail is False

    def test_jour_sans_production_recuperee_non_ecrase(self, prod, plugin_module):
        # Fixtures : conso du 23 au 25/11, production du 25/11 seulement. Les totaux journaliers du 23 et du 24
        # ne doivent pas être écrits (retour à 0 qui écraserait la valeur en base), celui du 25 si.
        run_cycle(prod)
        days = [c.kwargs["sValue"].split(";")[-1] for c in plugin_module.Devices[1].Update.call_args_list]
        assert "2026-11-25" in days
        assert "2026-11-23" not in days
        assert "2026-11-24" not in days

    def test_sans_option_production_jours_ecrits(self, plugin_module, domoticz, clock):
        plugin = start_consoapi(plugin_module, Address="consoapi")
        run_cycle(plugin)
        days = [c.kwargs["sValue"].split(";")[-1] for c in plugin_module.Devices[1].Update.call_args_list]
        assert {"2026-11-23", "2026-11-24", "2026-11-25"} <= set(days)

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

    def test_pas_de_production_nouvel_essai_a_30_jours(self, prod, clock):
        absent = {"on": True}

        def responder(request):
            if absent["on"] and "courbe_de_charge_production" in request["URL"]:
                return response(status=404, body={"status": 404, "message": "Aucune donnée"})
            return nominal_responder(request)

        run_cycle(prod, responder)
        assert prod.getCacheNoData(PRM, True) is True
        # 29 jours plus tard : toujours mémorisé, aucune requête de production
        clock.current = clock(2026, 12, 25, 8, 34, 45)
        assert "courbe_de_charge_production" not in types_of(run_cycle(prod, responder))
        assert prod.getCacheNoData(PRM, True) is True
        # 30 jours plus tard : un nouvel essai, cette fois la production existe
        absent["on"] = False
        clock.current = clock(2026, 12, 26, 8, 34, 45)
        day30 = run_cycle(prod, responder)
        assert types_of(day30).count("courbe_de_charge_production") == 1
        assert prod.getCacheNoData(PRM, True) is False

    def test_pas_de_production_remémorisé_si_toujours_absente(self, prod, clock):
        def responder(request):
            if "courbe_de_charge_production" in request["URL"]:
                return response(status=404, body={"status": 404, "message": "Aucune donnée"})
            return nominal_responder(request)

        run_cycle(prod, responder)
        clock.current = clock(2026, 12, 26, 8, 34, 45)
        day30 = run_cycle(prod, responder)
        assert types_of(day30).count("courbe_de_charge_production") == 1
        assert prod.getCacheNoData(PRM, True) is True
        # Le délai repart de la date du nouvel essai
        clock.current = clock(2026, 12, 27, 8, 34, 45)
        assert "courbe_de_charge_production" not in types_of(run_cycle(prod, responder))

    def test_cache_ancien_sans_date_daté_d_aujourd_hui(self, prod, clock):
        prod.dData[PRM] = {"data": {}, "state": {"noConsumption": False, "noProduction": True}}
        assert prod.getCacheNoData(PRM, True) is True
        assert prod.dData[PRM]["state"]["noProductionDate"] == "2026-11-26"

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
