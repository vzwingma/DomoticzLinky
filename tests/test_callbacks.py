"""Callbacks Domoticz : D1/D1a (onCommand, onNotification), D2 (iVersion), D16 (fDebug fermé à l'arrêt).

Tests de BUG (désormais verts, correctifs livrés) et tests de caractérisation (verts avant et après).
"""
import pytest

SENT_NOTIF_TEXT = "NOTIF-TEXT-SENTINEL"


# ---------------------------------------------------------------------------
# D1 / D1a : onCommand / onNotification définis au niveau module, sans méthode dans BasePlugin
# ---------------------------------------------------------------------------
class TestD1CommandNotification:
    def test_module_onCommand_ne_leve_pas(self, plugin_module, plugin):
        plugin_module._plugin = plugin
        plugin_module.onCommand(1, "On", 0, 0)

    def test_module_onNotification_ne_leve_pas(self, plugin_module, plugin):
        plugin_module._plugin = plugin
        plugin_module.onNotification("Nom", "Sujet", "Texte", 0, 0, "", "")

    def test_methode_onCommand_ne_leve_pas(self, plugin):
        plugin.isStarted = True
        plugin.onCommand(1, "On", 0, 0)

    def test_methode_onNotification_ne_log_pas_le_texte(self, plugin, captured):
        # Le texte d'une notification peut contenir n'importe quoi : il ne doit pas être journalisé
        plugin.isStarted = True
        plugin.onNotification("Nom", "Sujet", SENT_NOTIF_TEXT, 0, 0, "", "")
        assert SENT_NOTIF_TEXT not in captured(plugin), "Text de la notification journalisé"

    def test_autres_callbacks_module_ne_levent_pas(self, plugin_module, plugin):
        # Caractérisation : les callbacks déjà fonctionnels (non démarré) restent sans effet de bord
        plugin_module._plugin = plugin
        plugin_module.onDeviceAdded(1)
        plugin_module.onDeviceModified(1)
        plugin_module.onDeviceRemoved(1)
        plugin_module.onDisconnect(None)
        plugin_module.onStop()
        assert plugin.isStarted is False


# ---------------------------------------------------------------------------
# D2 : onStart() lève UnboundLocalError si DomoticzVersion n'est pas reconnue
# ---------------------------------------------------------------------------
class TestD2DomoticzVersion:
    def test_version_inconnue_arret_explicite(self, plugin_module, plugin, domoticz):
        plugin.fDebug = None  # Mode3 = 0 en production : pas de fichier de debug
        plugin.iDebugLevel = 0
        plugin_module.Parameters["DomoticzVersion"] = "inconnue"
        plugin.onStart()
        assert plugin.isStarted is False
        assert any("Version de Domoticz non reconnue" in m for m in domoticz.logs["Error"]), \
            "message d'erreur attendu absent : %r" % domoticz.logs["Error"]

    @pytest.mark.parametrize("sVersion, iAlternate", [
        ("2026.1", 0),
        ("4.11774", 0),
        ("4.11773", 1),
        ("4.11070", 1),
    ])
    def test_versions_reconnues_demarrent(self, plugin_module, plugin, sVersion, iAlternate):
        # Caractérisation : seuil d'énergie produite/tarification à 4.11774, minimum 4.11070
        plugin.fDebug = None
        plugin.iDebugLevel = 0
        plugin_module.Parameters["DomoticzVersion"] = sVersion
        plugin.onStart()
        assert plugin.isStarted is True
        assert plugin.iAlternateDevice == iAlternate

    def test_version_trop_ancienne_arret_explicite(self, plugin_module, plugin, domoticz):
        # Caractérisation : "4.10717" est reconnue mais < 4.11070 -> erreur + arrêt
        plugin.fDebug = None
        plugin.iDebugLevel = 0
        plugin_module.Parameters["DomoticzVersion"] = "4.10717"
        plugin.onStart()
        assert plugin.isStarted is False
        assert any("trop ancienne" in m for m in domoticz.logs["Error"])


# ---------------------------------------------------------------------------
# D16 : fDebug n'est jamais fermé
# ---------------------------------------------------------------------------
class TestD16DebugFile:
    def test_onStop_ferme_et_libere_fDebug(self, plugin):
        fichier = plugin.fDebug
        plugin.isStarted = True
        plugin.onStop()
        assert fichier.closed is True, "fDebug non fermé"
        assert plugin.fDebug is None, "fDebug non remis à None"

    def test_onStop_arrete_le_plugin(self, plugin):
        # Caractérisation : isStarted repasse à False (avant et après correctif)
        plugin.isStarted = True
        plugin.onStop()
        assert plugin.isStarted is False

    def test_journalisation_apres_onStop_ne_leve_pas(self, plugin):
        # Caractérisation : écrire après l'arrêt reste sans exception (fichier fermé ou None)
        plugin.isStarted = True
        plugin.onStop()
        plugin.myDebug("message après arrêt")
        plugin.myStatus("statut après arrêt")
