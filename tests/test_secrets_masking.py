"""S3 : aucun secret (jeton d'accès, refresh token, device code, cookie, en-tête Authorization) dans
les sorties : journaux Domoticz simulés (Log/Status/Error/Debug) et fichier de debug (io.StringIO).

Sentinelles uniquement (voir conftest). Tests de FUITE : aucune sentinelle ne doit apparaître dans les
sorties. Tests de non-régression (PRM, Verb/URL, consentement en clair) : le clair est conservé.
"""
from datetime import datetime

import pytest


def assert_no_leak(texte, *secrets):
    fuites = [s for s in secrets if s in texte]
    assert not fuites, "secrets présents dans les sorties : %s" % fuites


@pytest.fixture
def configure(plugin, sentinels):
    """Configuration persistée avec jetons et PRM sentinelles."""
    plugin.setConfigItem("token_type", "Bearer")
    plugin.setConfigItem("access_token", sentinels.ACCESS)
    plugin.setConfigItem("refresh_token", sentinels.REFRESH)
    plugin.setConfigItem("usage_points_id", [sentinels.PRM])
    plugin.sUsagePointId = sentinels.PRM
    return plugin


class TestFuitesDansLesRequetes:
    def test_getData_masque_authorization(self, configure, captured, sentinels):
        configure.getData("/metering_data_clc/v5/consumption_load_curve",
                          datetime(2026, 1, 1), datetime(2026, 1, 2))
        assert_no_leak(captured(configure), sentinels.ACCESS)

    def test_refreshToken_masque_le_corps(self, configure, captured, sentinels):
        configure.refreshToken()
        assert_no_leak(captured(configure), sentinels.REFRESH)

    def test_getAccessToken_masque_le_device_code(self, plugin, captured, sentinels):
        plugin.sDeviceCode = sentinels.DEVICE_CODE
        plugin.getAccessToken()
        assert_no_leak(captured(plugin), sentinels.DEVICE_CODE)


class TestFuitesDansLesReponses:
    def test_dump_reponse_token_en_octets(self, plugin, captured, sentinels):
        corps = ('{"access_token":"%s","refresh_token":"%s","id_token":"%s","token_type":"Bearer","expires_in":3600}'
                 % (sentinels.ACCESS, sentinels.REFRESH, sentinels.ID)).encode()
        plugin.dumpDictToLog({"Status": 200, "Data": corps})
        assert_no_leak(captured(plugin), sentinels.ACCESS, sentinels.REFRESH, sentinels.ID)

    def test_dump_entetes_sensibles(self, plugin, captured, sentinels):
        plugin.dumpDictToLog({"Status": 200,
                              "Headers": {"Set-Cookie": sentinels.COOKIE, "AUTHORIZATION": "Bearer " + sentinels.ACCESS}})
        assert_no_leak(captured(plugin), sentinels.COOKIE, sentinels.ACCESS)

    def test_dump_authorization_sans_schema_masque_par_la_cle(self, plugin, captured, sentinels):
        # Masquage par NOM de clé (indépendant du motif Bearer/Basic) : valeur brute sans schéma
        plugin.dumpDictToLog({"Headers": {"Authorization": sentinels.ACCESS}})
        assert_no_leak(captured(plugin), sentinels.ACCESS)

    def test_dump_cle_sensible_profondeur_3(self, plugin, captured, sentinels):
        plugin.dumpDictToLog({"a": {"b": {"access_token": sentinels.ACCESS, "Refresh_Token": sentinels.REFRESH}}})
        assert_no_leak(captured(plugin), sentinels.ACCESS, sentinels.REFRESH)

    def test_dump_reponse_client_secret_json_en_octets(self, plugin, captured, sentinels):
        # T3.6 : corps JSON (octets) contenant client_secret, masqué par motif
        corps = ('{"client_secret":"%s","token_type":"Bearer"}' % sentinels.CLIENT_SECRET).encode()
        plugin.dumpDictToLog({"Status": 200, "Data": corps})
        assert_no_leak(captured(plugin), sentinels.CLIENT_SECRET)

    def test_dump_client_secret_imbrique(self, plugin, captured, sentinels):
        # T3.6 : masquage par NOM de clé (valeur brute, sans motif reconnaissable), à 3 profondeurs
        plugin.dumpDictToLog({"client_secret": sentinels.CLIENT_SECRET,
                              "a": {"Client_Secret": sentinels.CLIENT_SECRET + "-2",
                                    "b": {"client_secret": sentinels.CLIENT_SECRET + "-3"}}})
        assert_no_leak(captured(plugin), sentinels.CLIENT_SECRET)

    def test_dump_valeur_non_dict(self, plugin, captured, sentinels):
        plugin.dumpDictToLog("refresh_token=%s&x=1" % sentinels.REFRESH)
        assert_no_leak(captured(plugin), sentinels.REFRESH)

    def test_handleConnection_masque_la_reponse(self, plugin, captured, sentinels):
        plugin.sConnectionStep = "sending"  # branche sans effet de bord : seul le dump nous intéresse
        corps = ('{"access_token":"%s","refresh_token":"%s"}' % (sentinels.ACCESS, sentinels.REFRESH)).encode()
        plugin.handleConnection({"Status": 200, "Headers": {"Set-Cookie": sentinels.COOKIE}, "Data": corps})
        assert_no_leak(captured(plugin), sentinels.ACCESS, sentinels.REFRESH, sentinels.COOKIE)


class TestFiltreDesMessages:
    @pytest.mark.parametrize("sMethode", ["myLog", "myStatus", "myError", "myDebug"])
    @pytest.mark.parametrize("sGabarit", [
        "requête refresh_token={s}&usage=1",
        "réponse {{\"access_token\":\"{s}\",\"x\":1}}",
        "en-tête Authorization: Bearer {s}",
        "en-tête Authorization: Basic {s}",
        "id_token={s}",
        "device_code={s}",
    ], ids=["refresh_url", "access_json", "bearer", "basic", "id_token", "device_code"])
    def test_message_libre_masque(self, plugin, captured, sMethode, sGabarit):
        sSecret = "TOK-FREE-SENTINEL"
        getattr(plugin, sMethode)(sGabarit.format(s=sSecret))
        assert_no_leak(captured(plugin), sSecret)

    @pytest.mark.parametrize("sMethode", ["myLog", "myStatus", "myError", "myDebug"])
    @pytest.mark.parametrize("sGabarit", [
        "requête grant_type=x&client_id=ID&client_secret={s}&usage=1",
        "requête client_secret={s}",
        "requête CLIENT_SECRET={s}&x=1",
        "réponse {{\"client_secret\":\"{s}\",\"x\":1}}",
        "réponse {{\"client_secret\" : \"{s}\"}}",
    ], ids=["form_milieu", "form_seul", "form_casse", "json", "json_espaces"])
    def test_client_secret_message_libre_masque(self, plugin, captured, sentinels, sMethode, sGabarit):
        # T3.6 : client_secret en texte form-urlencoded ou JSON via le chemin de log (my*)
        getattr(plugin, sMethode)(sGabarit.format(s=sentinels.CLIENT_SECRET))
        assert_no_leak(captured(plugin), sentinels.CLIENT_SECRET)

    def test_client_secret_form_conserve_les_autres_parametres(self, plugin, domoticz, sentinels):
        # Non-régression : seul la valeur du secret est masquée, le reste de la requête reste lisible
        plugin.myLog("requête client_id=ID-PUBLIC&client_secret=%s&usage=1" % sentinels.CLIENT_SECRET)
        message = "\n".join(domoticz.logs["Log"])
        assert "client_id=ID-PUBLIC" in message and "usage=1" in message and "client_secret=" in message

    def test_setConfigItem_en_erreur_ne_log_pas_la_valeur(self, plugin, domoticz, captured, sentinels):
        domoticz.config_fail_on_set = True  # l'échec survient après le calcul du checksum
        plugin.setConfigItem("access_token", sentinels.ACCESS)
        assert domoticz.logs["Error"], "une erreur est attendue"
        assert_no_leak(captured(plugin), sentinels.ACCESS)

    def test_setConfigItem_en_erreur_journalise_la_cle(self, plugin, domoticz, sentinels):
        # Non-régression : l'erreur reste diagnostiquable (clé concernée)
        domoticz.config_fail_on_set = True
        plugin.setConfigItem("access_token", sentinels.ACCESS)
        assert any("access_token" in m for m in domoticz.logs["Error"])


class TestNonRegressionEnClair:
    def test_consentement_user_code_et_url_en_clair(self, plugin, domoticz, captured, sentinels):
        # Le user_code et l'URL de consentement sont fonctionnels : à conserver en clair.
        # Le device_code, lui, n'est jamais journalisé par parseDeviceCode.
        corps = ('{"device_code":"%s","user_code":"%s"}' % (sentinels.DEVICE_CODE, sentinels.USER_CODE)).encode()
        assert plugin.parseDeviceCode({"Status": 200, "Data": corps}) == "done"
        erreurs = "\n".join(domoticz.logs["Error"])
        assert sentinels.USER_CODE in erreurs
        assert "https://enedis.domoticz.russandol.pro/device?code=" + sentinels.USER_CODE in erreurs
        assert_no_leak(captured(plugin), sentinels.DEVICE_CODE)

    def test_prm_et_messages_ordinaires_inchanges(self, plugin, domoticz, sentinels):
        plugin.myStatus("Traitement pour le point de livraison " + sentinels.PRM)
        plugin.myLog("Prochaine connexion : 2026-01-01 08:00:00")
        assert "Traitement pour le point de livraison " + sentinels.PRM in domoticz.logs["Status"]
        assert "Prochaine connexion : 2026-01-01 08:00:00" in domoticz.logs["Log"]

    def test_dump_conserve_verb_url_et_valeurs_non_sensibles(self, plugin, captured, sentinels):
        plugin.dumpDictToLog({"Verb": "GET",
                              "URL": "/data/proxy/x?usage_point_id=" + sentinels.PRM,
                              "Headers": {"Host": "exemple.invalide"}})
        texte = captured(plugin)
        for attendu in ("Verb", "GET", "/data/proxy/x", sentinels.PRM, "Host", "exemple.invalide"):
            assert attendu in texte, "%r a disparu des sorties" % attendu


class TestJetonConsoApi:
    """Plan 011 — T1.4 / T2.3 : le jeton Conso API n'apparaît dans aucune sortie, même en debug avancé."""

    @pytest.fixture
    def cycle(self, plugin_module, domoticz, monkeypatch):
        from consoapi_helpers import TOKEN, freeze, start_consoapi
        freeze(plugin_module, monkeypatch, 2026, 11, 26, 8, 34, 45)
        plugin = start_consoapi(plugin_module, Mode3="2")
        assert plugin.fDebug is not None  # fichier /tmp/DomoticzLinky_*.log
        return plugin, TOKEN

    @staticmethod
    def _all_outputs(plugin, domoticz):
        plugin.fDebug.flush()
        with open(plugin.fDebug.name, encoding="utf-8") as oFile:
            sFile = oFile.read()
        return "\n".join(sum(domoticz.logs.values(), [])) + "\n" + sFile

    def test_cycle_nominal_debug_avance(self, cycle, domoticz):
        from consoapi_helpers import run_cycle
        plugin, token = cycle
        sent = run_cycle(plugin)
        assert sent[0]["Headers"]["Authorization"] == "Bearer " + token  # le jeton part bien dans la requête
        sOut = self._all_outputs(plugin, domoticz)
        assert "Authorization" in sOut  # l'en-tête est bien journalisé en debug...
        assert_no_leak(sOut, token, token.split(".")[1])  # ...mais masqué

    def test_jeton_renvoye_dans_une_reponse(self, cycle, domoticz):
        from consoapi_helpers import run_cycle
        plugin, token = cycle
        body = ('{"status":401,"message":"jeton ' + token + ' refusé"}').encode()
        run_cycle(plugin, lambda r: {"Status": "401", "Data": body, "Headers": {"X-Echo": token}})
        assert_no_leak(self._all_outputs(plugin, domoticz), token)

    def test_masquage_jeton_sans_schema(self, plugin_module):
        from consoapi_helpers import TOKEN
        plugin_module.registerSecret(TOKEN)
        assert TOKEN not in plugin_module.maskSecrets("token=" + TOKEN + " fin")

    def test_cle_password_masquee(self, plugin_module):
        assert plugin_module.maskValue("Password", "secret-quelconque") == plugin_module.MASK
