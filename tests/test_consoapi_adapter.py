"""Plan 011 — T1.3 : adaptateur Conso API V2 -> forme interne v5, et lecture des erreurs V2.

Fixtures : captures réelles anonymisées du 2026-11-27 (période 23 -> 26/11/2026, PRM masqué).
"""
import json
from datetime import datetime

import pytest

from consoapi_helpers import PRM, load, response

# Consommation quotidienne Enedis (fixture 200_consommation_quotidienne), en Wh
DAILY_WH = {"2026-11-23": 5248.0, "2026-11-24": 6159.0, "2026-11-25": 5071.0}


def _json(name):
    return json.loads(load(name).decode())


class TestConversion:
    def test_courbe_convertie(self, plugin_module):
        out = plugin_module.consoApiV2ToInternal(_json("200_courbe_de_charge_consommation"))
        readings = out["meter_reading"]["interval_reading"]
        assert out["meter_reading"]["usage_point_id"] == PRM
        assert len(readings) == 288  # 3 jours x 96 points de 15 min
        assert readings[0] == {"value": "148", "date": "2026-11-23 00:15:00"}
        assert readings[-1]["date"] == "2026-11-26 00:00:00"

    def test_puissance_max_convertie(self, plugin_module):
        out = plugin_module.consoApiV2ToInternal(_json("200_puissance_conso_max_quotidienne"))
        assert out["meter_reading"]["interval_reading"] == [
            {"value": "3503", "date": "2026-11-23 12:48:53"},
            {"value": "2470", "date": "2026-11-24 07:47:01"},
            {"value": "2415", "date": "2026-11-25 19:42:23"},
        ]

    @pytest.mark.parametrize("body", [
        {"meter_reading": {"usage_point_id": PRM, "interval_reading": []}},  # réponse Legacy v5
        {"status": 401, "message": "Votre token est invalide"},             # erreur V2
        {"error": "invalid_token"},                                          # erreur OAuth
        [], None, "texte",
    ])
    def test_autres_formes_inchangees(self, plugin_module, body):
        assert plugin_module.consoApiV2ToInternal(body) is body

    def test_grandeur_invalide(self, plugin_module):
        assert plugin_module.consoApiV2ToInternal({"idPrm": PRM, "grandeur": "x"}) == {}

    def test_points_incomplets_ignores_et_grandeur_cons_choisie(self, plugin_module):
        body = {"idPrm": PRM, "grandeur": [
            {"grandeurMetier": "PROD", "points": [{"v": "9", "d": "2026-11-23 00:15:00"}]},
            {"grandeurMetier": "CONS", "points": [{"v": "1"}, {"d": "x"}, "bad", {"v": "2", "d": "2026-11-23 00:30:00"}]},
        ]}
        out = plugin_module.consoApiV2ToInternal(body)
        assert out["meter_reading"]["interval_reading"] == [{"value": "2", "date": "2026-11-23 00:30:00"}]

    def test_points_qualite_inhabituelle_conserves(self, plugin_module):
        # n != "B" ou iv != "0" (non observés) : valeur conservée, pas d'exception
        body = {"idPrm": PRM, "grandeur": [{"grandeurMetier": "CONS", "points": [
            {"v": "10", "d": "2026-11-23 00:15:00", "n": "E", "iv": "1"}]}]}
        assert plugin_module.consoApiV2ToInternal(body)["meter_reading"]["interval_reading"][0]["value"] == "10"


class TestExploreData:
    @pytest.fixture
    def prm_plugin(self, plugin):
        plugin.sUsagePointId = PRM
        # Dates utilisées par les messages d'erreur d'étape
        plugin.dateBeginHours = plugin.dateBeginDays = datetime(2026, 11, 23)
        plugin.dateEndHours = plugin.dateEndDays = datetime(2026, 11, 26)
        return plugin

    def test_heures_somme_egale_au_quotidien(self, prm_plugin):
        assert prm_plugin.exploreDataHours(response("200_courbe_de_charge_consommation")) is True
        data = prm_plugin.dData[PRM]["data"]
        # Horodatage fin d'intervalle : l'heure 0 du jour J+1 est la dernière heure du jour J (comme en v5)
        for day, next_day in (("2026-11-23", "2026-11-24"), ("2026-11-24", "2026-11-25"), ("2026-11-25", "2026-11-26")):
            hours = data[day]["consumption1_hours"]
            total = sum(v for h, v in hours.items() if h != 0) + data[next_day]["consumption1_hours"][0]
            assert total == DAILY_WH[day], day

    def test_heures_moyenne_de_4_points_de_15_min(self, prm_plugin):
        prm_plugin.exploreDataHours(response("200_courbe_de_charge_consommation"))
        # 00:15=148, 00:30=132, 00:45=108, 01:00=152 W -> 135 Wh sur l'heure 0h-1h
        assert prm_plugin.dData[PRM]["data"]["2026-11-23"]["consumption1_hours"][1] == 135.0

    def test_pics(self, prm_plugin):
        assert prm_plugin.exploreDataPeaks(response("200_puissance_conso_max_quotidienne")) is True
        data = prm_plugin.dData[PRM]["data"]
        assert data["2026-11-23"]["consumptionpeak"] == 3503.0
        assert data["2026-11-25"]["consumptionpeak"] == 2415.0

    def test_autre_prm_refuse(self, prm_plugin):
        prm_plugin.sUsagePointId = "99999999999999"
        assert prm_plugin.exploreDataHours(response("200_courbe_de_charge_consommation")) is False

    @pytest.mark.parametrize("data", [b"", b"pas du json", b"{}", b'{"idPrm":"00000000000000","grandeur":[]}'])
    def test_reponse_vide_ou_invalide_sans_exception(self, prm_plugin, data):
        assert prm_plugin.exploreDataHours({"Status": "200", "Data": data}) is False
        assert prm_plugin.exploreDataPeaks({"Status": "200", "Data": data}) is False

    def test_doublon_et_trou_horaires_sans_exception(self, prm_plugin):
        # Changement d'heure : doublon puis trou à 02:xx (R10, non observable avant 2027)
        points = [{"v": "100", "d": d} for d in (
            "2026-10-25 01:15:00", "2026-10-25 01:30:00", "2026-10-25 01:45:00", "2026-10-25 02:00:00",
            "2026-10-25 02:15:00", "2026-10-25 02:15:00", "2026-10-25 03:00:00")]
        body = {"idPrm": PRM, "grandeur": [{"grandeurMetier": "CONS", "points": points}]}
        assert prm_plugin.exploreDataHours(response(body=body)) is True

    def test_regression_detectee_si_adaptateur_casse(self, plugin_module, prm_plugin, monkeypatch):
        # Preuve T2.2 : sans adaptateur, la réponse V2 n'est plus lue
        monkeypatch.setattr(plugin_module, "consoApiV2ToInternal", lambda d, *args: d)
        assert prm_plugin.exploreDataHours(response("200_courbe_de_charge_consommation")) is False


class TestErreursV2:
    def test_erreur_enedis_imbriquee(self, plugin_module):
        err = plugin_module.getError(response("err_400_periode_8j", 400))
        assert err == ("ADAM-DC-0015", "La période demandée est supérieure à 7 jours.", "")

    def test_erreur_periode_inversee(self, plugin_module):
        assert plugin_module.getError(response("err_400_periode_inversee", 400))[0] == "ADAM-ERR0002"

    def test_erreur_validation_conso_api(self, plugin_module):
        sError, sDescription, _ = plugin_module.getError(response("err_type_inconnu", 400))
        assert sError == "ZodError"
        assert sDescription == "Paramètres invalides"

    def test_401_message(self, plugin_module):
        sError, sDescription, _ = plugin_module.getError(response("err_401_jeton_invalide", 401))
        assert sError == ""
        assert sDescription == "Votre token est invalide ou ne permet pas d'accéder à ce PRM"

    def test_erreur_oauth_legacy_inchangee(self, plugin_module):
        body = {"error": "invalid_token", "error_description": "expired"}
        assert plugin_module.getError(response(body=body, status=401)) == ("invalid_token", "expired", "")
