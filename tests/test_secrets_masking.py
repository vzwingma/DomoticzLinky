"""S3 : aucun secret (jeton d'accès, refresh token, device code, cookie, en-tête Authorization) dans
les sorties : journaux Domoticz simulés (Log/Status/Error/Debug) et fichier de debug (io.StringIO).

Sentinelles uniquement (voir conftest). Tests de FUITE : `xfail(strict=True)` tant que le masquage
n'est pas livré. Tests de non-régression (PRM, Verb/URL, consentement en clair) : verts.
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
    @pytest.mark.xfail(strict=True, reason="S3 : getData() journalise Headers.Authorization (type + access_token) via dumpDictToLog")
    def test_getData_masque_authorization(self, configure, captured, sentinels):
        configure.getData("/metering_data_clc/v5/consumption_load_curve",
                          datetime(2026, 1, 1), datetime(2026, 1, 2))
        assert_no_leak(captured(configure), sentinels.ACCESS)

    @pytest.mark.xfail(strict=True, reason="S3 : refreshToken() journalise le corps URL-encodé (refresh_token=...)")
    def test_refreshToken_masque_le_corps(self, configure, captured, sentinels):
        configure.refreshToken()
        assert_no_leak(captured(configure), sentinels.REFRESH)

    @pytest.mark.xfail(strict=True, reason="S3 : getAccessToken() journalise le corps URL-encodé (device_code=...)")
    def test_getAccessToken_masque_le_device_code(self, plugin, captured, sentinels):
        plugin.sDeviceCode = sentinels.DEVICE_CODE
        plugin.getAccessToken()
        assert_no_leak(captured(plugin), sentinels.DEVICE_CODE)


class TestFuitesDansLesReponses:
    @pytest.mark.xfail(strict=True, reason="S3 : dumpDictToLog journalise Data (octets JSON) contenant access_token / refresh_token")
    def test_dump_reponse_token_en_octets(self, plugin, captured, sentinels):
        corps = ('{"access_token":"%s","refresh_token":"%s","id_token":"%s","token_type":"Bearer","expires_in":3600}'
                 % (sentinels.ACCESS, sentinels.REFRESH, sentinels.ID)).encode()
        plugin.dumpDictToLog({"Status": 200, "Data": corps})
        assert_no_leak(captured(plugin), sentinels.ACCESS, sentinels.REFRESH, sentinels.ID)

    @pytest.mark.xfail(strict=True, reason="S3 : dumpDictToLog ne masque pas les en-têtes sensibles (Set-Cookie, Authorization) à la profondeur 2")
    def test_dump_entetes_sensibles(self, plugin, captured, sentinels):
        plugin.dumpDictToLog({"Status": 200,
                              "Headers": {"Set-Cookie": sentinels.COOKIE, "AUTHORIZATION": "Bearer " + sentinels.ACCESS}})
        assert_no_leak(captured(plugin), sentinels.COOKIE, sentinels.ACCESS)

    @pytest.mark.xfail(strict=True, reason="S3 : dumpDictToLog ne masque pas les clés sensibles à la profondeur 3")
    def test_dump_cle_sensible_profondeur_3(self, plugin, captured, sentinels):
        plugin.dumpDictToLog({"a": {"b": {"access_token": sentinels.ACCESS, "Refresh_Token": sentinels.REFRESH}}})
        assert_no_leak(captured(plugin), sentinels.ACCESS, sentinels.REFRESH)

    @pytest.mark.xfail(strict=True, reason="S3 : branche non-dict de dumpDictToLog sans masquage")
    def test_dump_valeur_non_dict(self, plugin, captured, sentinels):
        plugin.dumpDictToLog("refresh_token=%s&x=1" % sentinels.REFRESH)
        assert_no_leak(captured(plugin), sentinels.REFRESH)

    @pytest.mark.xfail(strict=True, reason="S3 : handleConnection() journalise la réponse brute (dumpDictToLog(Data))")
    def test_handleConnection_masque_la_reponse(self, plugin, captured, sentinels):
        plugin.sConnectionStep = "sending"  # branche sans effet de bord : seul le dump nous intéresse
        corps = ('{"access_token":"%s","refresh_token":"%s"}' % (sentinels.ACCESS, sentinels.REFRESH)).encode()
        plugin.handleConnection({"Status": 200, "Headers": {"Set-Cookie": sentinels.COOKIE}, "Data": corps})
        assert_no_leak(captured(plugin), sentinels.ACCESS, sentinels.REFRESH, sentinels.COOKIE)


class TestFiltreDesMessages:
    @pytest.mark.xfail(strict=True, reason="S3 : my*() ne filtrent pas les secrets présents dans un message libre")
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

    @pytest.mark.xfail(strict=True, reason="S3 : setConfigItem() en erreur journalise str(Value), donc la valeur du jeton")
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
