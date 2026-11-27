"""Plan 011 — T1.1, T1.2, T1.5 : paramètres, requêtes Conso API, codes HTTP et budget d'appels.

Règles d'usage Conso API (page blocage-ip) : au plus 3 requêtes par jour et par PRM, retries compris ;
jamais en boucle ni en parallèle ; une nouvelle tentative quelques heures plus tard au plus, sinon le lendemain.
"""
from datetime import datetime, timedelta

import pytest

from consoapi_helpers import PRM, PRM_2, TOKEN, freeze, nominal_responder, response, run_cycle, start_consoapi

# 26/11 à 08:34 : la veille (25/11) est complète dans les fixtures ; 27/11 : la veille (26/11) ne l'est pas
DAY_COMPLETE = (2026, 11, 26, 8, 34, 45)
DAY_INCOMPLETE = (2026, 11, 27, 8, 34, 45)


def count_today(plugin):
    return plugin.getConfigItem("consoapi_budget", {}).get("count", {})


def status_responder(status, body=b"{}"):
    return lambda request: {"Status": str(status), "Data": body}


@pytest.fixture
def started(plugin_module, domoticz, monkeypatch):
    freeze(plugin_module, monkeypatch, *DAY_COMPLETE)
    return start_consoapi(plugin_module)


class TestParametres:
    def test_consoapi_complet(self, started, plugin_module):
        assert started.isStarted is True
        assert started.bConsoApi is True
        assert started.iAlternateAddress == plugin_module.CONSOAPI_ADDRESS_INDEX
        assert started.lConsoApiPrm == [PRM]
        assert started.iPeakBatchDays == 365

    def test_plusieurs_prm(self, plugin_module, domoticz):
        plugin = start_consoapi(plugin_module, Username=PRM + " , " + PRM_2)
        assert plugin.lConsoApiPrm == [PRM, PRM_2]

    def test_adresse_vide_vaut_consoapi(self, plugin_module, domoticz):
        plugin = start_consoapi(plugin_module, Address="")
        assert plugin.bConsoApi is True

    @pytest.mark.parametrize("params, motif", [
        ({"Password": ""}, "jeton"),
        ({"Username": ""}, "14 chiffres"),
        ({"Username": "1234"}, "14 chiffres"),
        ({"Username": PRM + ",abc"}, "14 chiffres"),
    ])
    def test_consoapi_incomplet_aucune_requete(self, plugin_module, domoticz, params, motif):
        plugin = start_consoapi(plugin_module, **params)
        assert plugin.isStarted is False
        assert any(motif in e for e in domoticz.logs["Error"])
        assert not domoticz.Connection.called

    @pytest.mark.parametrize("address", ["legacy", "russandol", "LEGACY"])
    def test_legacy(self, plugin_module, domoticz, address):
        plugin = start_consoapi(plugin_module, Address=address)
        assert plugin.isStarted is True
        assert plugin.bConsoApi is False
        assert plugin.iAlternateAddress == 0
        assert plugin.iPeakBatchDays == 1095

    def test_username_password_retires_des_parametres(self, plugin_module, domoticz):
        start_consoapi(plugin_module)
        assert "Username" not in plugin_module.Parameters
        assert "Password" not in plugin_module.Parameters

    def test_version_3(self, plugin_module):
        assert 'version="3.0.0"' in plugin_module.__doc__


class TestRequetes:
    def test_cycle_nominal_deux_requetes(self, started):
        sent = run_cycle(started)
        assert len(sent) == 2
        assert sent[0]["URL"] == "/api/courbe_de_charge_consommation?pointId=" + PRM + "&dateDebut=2026-11-19&dateFin=2026-11-26"
        assert sent[1]["URL"] == "/api/puissance_conso_max_quotidienne?pointId=" + PRM + "&dateDebut=2026-11-25&dateFin=2026-11-26"
        assert started.sConnectionStep == "idle"
        assert count_today(started) == {PRM: 2}

    def test_entetes(self, started):
        request = run_cycle(started)[0]
        assert request["Verb"] == "GET"
        assert request["Headers"]["Authorization"] == "Bearer " + TOKEN
        assert request["Headers"]["Host"] == "conso.boris.sh"
        assert request["Headers"]["User-Agent"].startswith("DomoticzLinkyPlugin/")
        assert request["Headers"]["User-Agent"].endswith("(+https://github.com/vzwingma/DomoticzLinky)")

    def test_connexion_vers_conso_api(self, started, domoticz):
        run_cycle(started)
        addresses = {c.kwargs.get("Address") for c in domoticz.Connection.call_args_list}
        assert addresses == {"conso.boris.sh"}

    def test_pas_de_device_flow_ni_production(self, started, monkeypatch):
        called = []
        monkeypatch.setattr(started, "getDeviceCode", lambda: called.append("devicecode"))
        monkeypatch.setattr(started, "refreshToken", lambda: called.append("refresh"))
        sent = run_cycle(started)
        assert called == []
        assert not any("production" in r["URL"] for r in sent)

    def test_succes_prochaine_connexion_demain(self, started):
        run_cycle(started)
        assert started.dateNextConnection.date() == datetime(2026, 11, 27).date()
        assert 8 <= started.dateNextConnection.hour < 9

    def test_devices_mis_a_jour(self, started, plugin_module, domoticz):
        run_cycle(started)
        assert started.dData[PRM]["data"]["2026-11-25"]["consumptionpeak"] == 2415.0
        assert plugin_module.Devices[1].Update.called
        assert domoticz.logs["Error"] == []
        assert started.getConfigItem("previous_successful_connection_date", None) is not None


class TestCodesHttp:
    @pytest.mark.parametrize("status", [401, 403])
    def test_jeton_invalide_pas_de_retry(self, started, domoticz, status):
        sent = run_cycle(started, status_responder(status, b'{"status":401,"message":"Votre token est invalide"}'))
        assert len(sent) == 1
        assert any("Jeton Conso API invalide" in e for e in domoticz.logs["Error"])
        assert started.dateNextConnection.date() > datetime(2026, 11, 26).date()
        assert started.isStarted is True  # pas de désactivation du plugin

    def test_400_pas_de_retry(self, started, domoticz):
        sent = run_cycle(started, lambda r: response("err_400_periode_8j", 400))
        assert len(sent) == 1
        assert any("ADAM-DC-0015" in e for e in domoticz.logs["Error"])
        assert started.dateNextConnection.date() > datetime(2026, 11, 26).date()

    def test_404_pas_de_donnees(self, started):
        sent = run_cycle(started, status_responder(404))
        assert len(sent) == 1
        assert started.sConnectionStep == "idle"

    @pytest.mark.parametrize("status", [429, 500, 502, 503])
    def test_indisponible_une_tentative_differee(self, started, status):
        sent = run_cycle(started, status_responder(status))
        assert len(sent) == 1  # aucun renvoi immédiat (ni 5 s, ni horaire)
        assert started.dateNextConnection == datetime(2026, 11, 26, 11, 34, 45)
        # 2e échec le même jour : lendemain
        sent = run_cycle(started, status_responder(status))
        assert len(sent) == 1
        assert started.dateNextConnection.date() == datetime(2026, 11, 27).date()

    def test_sans_statut_tentative_differee(self, started):
        sent = run_cycle(started, lambda r: {"Data": b""})
        assert len(sent) == 1
        assert started.dateNextConnection == datetime(2026, 11, 26, 11, 34, 45)

    def test_delai_depasse_tentative_differee(self, started):
        started.sConnectionStep = "idle"
        started.handleConnection()
        assert started.sConnectionStep == "connecting"
        for _ in range(4):
            started.handleConnection()
        assert started.sConnectionStep == "idle"
        assert started.dateNextConnection == datetime(2026, 11, 26, 11, 34, 45)
        assert count_today(started) == {PRM: 1}

    def test_tentative_differee_pas_apres_22h(self, plugin_module, domoticz, monkeypatch):
        freeze(plugin_module, monkeypatch, 2026, 11, 26, 19, 30, 0)
        plugin = start_consoapi(plugin_module)
        run_cycle(plugin, status_responder(500))
        assert plugin.dateNextConnection.date() == datetime(2026, 11, 27).date()

    def test_200_json_invalide_sans_exception(self, started):
        sent = run_cycle(started, status_responder(200, b"<html>oops</html>"))
        assert len(sent) >= 1
        assert started.sConnectionStep == "idle"


class TestBudget:
    def test_veille_incomplete_une_seule_relance(self, plugin_module, domoticz, monkeypatch):
        freeze(plugin_module, monkeypatch, *DAY_INCOMPLETE)
        plugin = start_consoapi(plugin_module)
        sent = run_cycle(plugin)
        assert len(sent) == 2
        assert plugin.dateNextConnection == datetime(2026, 11, 27, 11, 34, 45)
        sent = run_cycle(plugin)
        assert len(sent) <= 1  # seules les données manquantes sont redemandées
        assert plugin.dateNextConnection.date() == datetime(2026, 11, 28).date()
        assert count_today(plugin)[PRM] <= 3

    @pytest.mark.parametrize("status", [500, 429, 401, 400])
    def test_jamais_plus_de_3_requetes_par_jour(self, started, status):
        total = 0
        for _ in range(8):
            total += len(run_cycle(started, status_responder(status)))
        assert total <= 3
        assert count_today(started)[PRM] <= 3

    def test_budget_persiste_au_redemarrage(self, plugin_module, domoticz, monkeypatch):
        freeze(plugin_module, monkeypatch, *DAY_COMPLETE)
        plugin = start_consoapi(plugin_module)
        for _ in range(3):
            run_cycle(plugin, status_responder(500))
        # Redémarrage de Domoticz / du plugin : nouveau BasePlugin, même configuration
        plugin2 = start_consoapi(plugin_module)
        assert run_cycle(plugin2, status_responder(500)) == []
        assert count_today(plugin2)[PRM] == 3

    def test_budget_remis_a_zero_le_lendemain(self, plugin_module, domoticz, monkeypatch):
        clock = freeze(plugin_module, monkeypatch, *DAY_COMPLETE)
        plugin = start_consoapi(plugin_module)
        for _ in range(4):
            run_cycle(plugin, status_responder(500))
        clock.current = clock(2026, 11, 27, 8, 40, 0)
        assert len(run_cycle(plugin, status_responder(500))) == 1

    def test_garde_fou_a_l_envoi(self, started):
        started.setConfigItem("consoapi_budget", {"day": "2026-11-26", "count": {PRM: 3}, "history": {}, "retry": False})
        started.sUsagePointId = PRM
        assert started.consoApiRegisterRequest() is False
        assert started.sConnectionStep == "done"

    def test_pas_de_resynchronisation_au_redemarrage(self, plugin_module, domoticz, monkeypatch):
        freeze(plugin_module, monkeypatch, *DAY_COMPLETE)
        plugin = start_consoapi(plugin_module)
        run_cycle(plugin)
        plugin2 = start_consoapi(plugin_module)
        assert plugin2.dateNextConnection.date() == datetime(2026, 11, 27).date()

    def test_budget_par_prm(self, plugin_module, domoticz, monkeypatch):
        freeze(plugin_module, monkeypatch, *DAY_COMPLETE)
        plugin = start_consoapi(plugin_module, Username=PRM + "," + PRM_2)

        def responder(request):
            if PRM_2 in request["URL"]:
                body = nominal_responder(request)["Data"].replace(PRM.encode(), PRM_2.encode())
                return {"Status": "200", "Data": body}
            return nominal_responder(request)

        sent = run_cycle(plugin, responder)
        assert len(sent) == 4
        assert count_today(plugin) == {PRM: 2, PRM_2: 2}
        # Séquentiel : chaque requête part après la réponse de la précédente
        assert [PRM_2 in r["URL"] for r in sent] == [False, False, True, True]


class TestHistoriqueEtale:
    @pytest.fixture
    def long_history(self, plugin_module, domoticz, monkeypatch):
        clock = freeze(plugin_module, monkeypatch, *DAY_COMPLETE)
        plugin = start_consoapi(plugin_module, Mode2="30")
        return plugin, clock

    def test_un_seul_lot_d_historique_par_jour(self, long_history):
        plugin, _ = long_history
        sent = run_cycle(plugin)
        urls = [r["URL"] for r in sent]
        assert len(sent) == 3
        assert "dateDebut=2026-11-19&dateFin=2026-11-26" in urls[0]
        assert "dateDebut=2026-11-12&dateFin=2026-11-19" in urls[1]  # lot d'historique
        assert "puissance_conso_max_quotidienne" in urls[2]
        assert plugin.getConfigItem("consoapi_budget")["history"] == {PRM: 1}

    def test_historique_repris_le_lendemain(self, long_history):
        plugin, clock = long_history

        def responder(request):
            # Données couvrant toute la période demandée (courbe de 15 min fictive, peu importe la valeur)
            if "courbe" not in request["URL"]:
                return nominal_responder(request)
            debut = request["URL"].split("dateDebut=")[1][:10]
            fin = request["URL"].split("dateFin=")[1][:10]
            dt = datetime.strptime(debut, "%Y-%m-%d") + timedelta(minutes=15)
            dt_end = datetime.strptime(fin, "%Y-%m-%d")
            points = []
            while dt <= dt_end:
                points.append({"v": "100", "d": dt.strftime("%Y-%m-%d %H:%M:%S")})
                dt += timedelta(minutes=15)
            return response(body={"idPrm": PRM, "grandeur": [{"grandeurMetier": "CONS", "points": points}]})

        day1 = [r["URL"] for r in run_cycle(plugin, responder)]
        clock.current = clock(2026, 11, 27, 8, 34, 45)
        day2 = [r["URL"] for r in run_cycle(plugin, responder)]
        assert len(day1) == 3 and len(day2) == 3
        assert "dateDebut=2026-11-12&dateFin=2026-11-19" in day1[1]
        # Lendemain : lot récent (veille seulement, le reste est en cache) puis lot suivant de l'historique
        assert "dateDebut=2026-11-26&dateFin=2026-11-27" in day2[0]
        assert "dateDebut=2026-11-06&dateFin=2026-11-13" in day2[1]

    def test_lot_puissance_max_365_jours(self, started):
        started.iDaysLeft = 366
        started.savedDateEndDays = datetime(2026, 11, 26)
        started.iDaysLeftHoursView = 0
        started.savedDateEndDaysForHoursView = datetime(2026, 11, 26)
        started.calculateDaysLeft()
        assert (started.dateEndDays - started.dateBeginDays).days == 365
        assert started.iDaysLeft == 1
