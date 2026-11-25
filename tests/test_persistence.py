"""Caractérisation de la persistance : clés et format de `Domoticz.Configuration`.

Le plan interdit de modifier ces clés / ce format (retour arrière v2.7.0 -> v2.6.1 sûr). Ces tests
doivent rester verts après TOUS les correctifs.
"""
import codecs
import hashlib
import pickle
from datetime import datetime

CLES_TOKENS = ["usage_points_id", "token_type", "refresh_token", "access_token", "expires_at"]


def decode(s64):
    return pickle.loads(codecs.decode(s64.encode(), "base64"))


class TestFormat:
    def test_format_base64_de_pickle_et_checksum_blake2s(self, plugin, domoticz):
        checksum = plugin.setConfigItem("ma_cle", {"a": [1, 2]})
        s64 = domoticz.config_state["ma_cle"]
        assert decode(s64) == {"a": [1, 2]}
        assert checksum == hashlib.blake2s(pickle.dumps({"a": [1, 2]})).hexdigest()

    def test_aller_retour_valeur_simple(self, plugin):
        plugin.setConfigItem("history_days", 365)
        assert plugin.getConfigItem("history_days", 0) == 365

    def test_valeur_par_defaut_si_cle_absente(self, plugin):
        assert plugin.getConfigItem("absente", "defaut") == "defaut"

    def test_datetime_relu_en_timestamp(self, plugin):
        # Contournement historique volontaire : les datetime sont relus en timestamp
        dt = datetime(2026, 1, 2, 3, 4, 5)
        plugin.setConfigItem("expires_at", dt)
        assert plugin.getConfigItem("expires_at", datetime(2000, 1, 1)) == dt.timestamp()


class TestCles:
    def test_resetTokens_ecrit_les_cinq_cles(self, plugin, domoticz):
        plugin.resetTokens()
        assert sorted(domoticz.config_state) == sorted(CLES_TOKENS)

    def test_parseAccessToken_ecrit_les_cles_attendues(self, plugin, domoticz, sentinels):
        corps = ('{"usage_points_id":"%s","refresh_token":"%s","access_token":"%s","token_type":"Bearer","expires_in":3600}'
                 % (sentinels.PRM, sentinels.REFRESH, sentinels.ACCESS)).encode()
        assert plugin.parseAccessToken({"Status": 200, "Data": corps}) == "done"
        assert sorted(domoticz.config_state) == sorted(CLES_TOKENS)
        assert decode(domoticz.config_state["usage_points_id"]) == [sentinels.PRM]
        assert decode(domoticz.config_state["access_token"]) == sentinels.ACCESS
        assert decode(domoticz.config_state["refresh_token"]) == sentinels.REFRESH
        assert decode(domoticz.config_state["token_type"]) == "Bearer"
        assert isinstance(decode(domoticz.config_state["expires_at"]), datetime)

    def test_saveCache_ecrit_cache_et_cache_checksum(self, plugin, plugin_module, domoticz, sentinels):
        plugin.lUsagePointIndex = [sentinels.PRM]
        plugin.dData = {sentinels.PRM: {"data": {}, "state": plugin_module.initState()},
                        "PRM-ORPHELIN": {"data": {}, "state": plugin_module.initState()}}
        plugin.saveCache()
        assert sorted(domoticz.config_state) == ["cache", "cache_checksum"]
        dCache = decode(domoticz.config_state["cache"])
        assert list(dCache) == [sentinels.PRM], "les PRM hors lUsagePointIndex doivent être purgés"
        assert plugin.getConfigItem("cache_checksum", None) == hashlib.blake2s(
            codecs.decode(domoticz.config_state["cache"].encode(), "base64")).hexdigest()

    def test_loadCache_aller_retour(self, plugin, plugin_module, sentinels):
        plugin.lUsagePointIndex = [sentinels.PRM]
        plugin.dData = {sentinels.PRM: {"data": {}, "state": plugin_module.initState()}}
        plugin.saveCache()
        plugin.dData = {}
        assert plugin.loadCache() is True
        assert list(plugin.dData) == [sentinels.PRM]

    def test_loadCache_checksum_incoherent_remet_le_cache_a_zero(self, plugin, plugin_module, domoticz, sentinels):
        plugin.lUsagePointIndex = [sentinels.PRM]
        plugin.dData = {sentinels.PRM: {"data": {}, "state": plugin_module.initState()}}
        plugin.saveCache()
        plugin.setConfigItem("cache_checksum", "checksum-invalide")
        assert plugin.loadCache() is False
        assert plugin.dData == {}
        assert any("Cache incohérent" in m for m in domoticz.logs["Error"])

    def test_onStart_ecrit_history_days(self, plugin, domoticz):
        plugin.fDebug = None
        plugin.iDebugLevel = 0
        plugin.onStart()
        assert decode(domoticz.config_state["history_days"]) == 7
