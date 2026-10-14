"""The settings list built from snapshots recorded from the real Swarm II.

The fixtures are UI Automation snapshots taken with ``tools/probe.py
snapshot`` on 2026-10-14 (Swarm II 1.0, Atlas Air), one with the page at the
top and one scrolled to the equalizer.
"""

import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "addon" / "appModules"))

from _swarmAccess import model  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"


def load(name):
    return model.Snapshot.from_dicts(json.loads((FIXTURES / name).read_text(encoding="utf-8")))


class SettingsListTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snap = load("settings_top.json")
        cls.settings = model.build_settings(cls.snap)
        cls.by_label = {s.label: s for s in cls.settings}

    def test_every_control_is_listed_once(self):
        kinds = [s.kind for s in self.settings]
        self.assertEqual(kinds.count(model.SWITCH), 9)
        self.assertEqual(kinds.count(model.COMBO), 4)
        self.assertEqual(kinds.count(model.SLIDER), 18)  # 8 plus ten equalizer bands
        self.assertEqual(len({s.key for s in self.settings}), len(self.settings))

    def test_switches_are_named_from_the_label_on_their_row(self):
        for label in ("Audio master volume", "Superhuman hearing", "Chat boost", "Waves 3D",
                      "Mute microphone", "Noise gate", "Show grid",
                      "Pop-up battery notifications", "Battery status as tray icon"):
            self.assertEqual(self.by_label[label].kind, model.SWITCH, label)

    def test_sliders_are_named_from_the_title_above_them(self):
        for label in ("Sensitivity", "Monitoring", "Game chat mix", "LED brightness"):
            self.assertEqual(self.by_label[label].kind, model.SLIDER, label)

    def test_controls_sharing_a_label_are_told_apart(self):
        self.assertEqual(self.by_label["Noise gate level"].kind, model.SLIDER)
        self.assertEqual(self.by_label["Audio master volume level"].kind, model.SLIDER)
        self.assertEqual(self.by_label["Chat boost mode"].kind, model.COMBO)
        self.assertEqual(self.by_label["Chat boost mode"].element.value, "BOLD")
        self.assertEqual(self.by_label["Waves 3D mode"].element.value, "Games")

    def test_a_vague_label_gets_its_section(self):
        self.assertIn("Voice and tone prompts level", self.by_label)

    def test_slider_ranges_come_from_their_end_labels(self):
        voice = self.by_label["Voice and tone prompts level"]
        self.assertEqual((voice.minimum, voice.maximum, voice.step), (0, 15, 1))
        monitoring = self.by_label["Monitoring"]
        self.assertEqual((monitoring.minimum, monitoring.maximum, monitoring.step), (0, 100, 5))
        mix = self.by_label["Game chat mix"]
        self.assertEqual(mix.end_names, ("game", "chat"))

    def test_equalizer_bands_in_order(self):
        bands = [s for s in self.settings if s.is_equalizer_band]
        self.assertEqual([b.label for b in bands], list(model.EQ_BANDS))
        self.assertTrue(all(b.section == "Equalizer" and b.unit == "dB" for b in bands))
        self.assertEqual((bands[0].minimum, bands[0].maximum), (-9, 9))

    def test_sections_in_page_order(self):
        names = [self.settings[i].section for i in model.sections(self.settings)]
        self.assertEqual(names, ["Audio", "Microphone", "Equalizer", "Device status",
                                 "Power options", "Voice and tone prompts", "Transmitter"])

    def test_status_lines(self):
        self.assertEqual(self.by_label["Battery status"].status_value, "88%")
        self.assertEqual(self.by_label["Transmitter status"].status_value, "Connected")
        self.assertEqual(self.by_label["High bandwidth audio"].status_value, "24 bit, 48000 Hz")

    def test_scrolling_changes_positions_not_the_list(self):
        scrolled = model.build_settings(load("settings_equalizer.json"))
        self.assertEqual([s.label for s in scrolled], [s.label for s in self.settings])


class AppSettingsScreenTests(unittest.TestCase):
    """Swarm II's app Settings open as a panel over the device page, which
    stays in the tree; the list must show only what is on screen."""

    @classmethod
    def setUpClass(cls):
        cls.settings = model.build_settings(load("app_settings.json"))

    def test_only_the_settings_panel_is_listed(self):
        self.assertEqual([s.label for s in self.settings], [
            "Download updates automatically", "Search for updates automatically",
            "Select language", "Autostart Swarm II", "Show update notification"])

    def test_sections_come_from_the_group_headings(self):
        self.assertEqual([s.section for s in self.settings], [
            "Updates", "Updates", "Language", "App settings", "Notifications and tooltips"])

    def test_language_combo_box(self):
        language = self.settings[2]
        self.assertEqual((language.kind, language.element.value), (model.COMBO, "English"))


class HomeScreenTests(unittest.TestCase):
    """Swarm II can open on its home screen, which has nothing Tab can reach."""

    def test_the_headset_tile_is_listed(self):
        settings = model.build_settings(load("home_screen.json"))
        self.assertEqual(len(settings), 1)
        tile = settings[0]
        self.assertEqual((tile.kind, tile.label, tile.status_value), (model.DEVICE, "Atlas Air", "PC"))


class FocusableNameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snap = load("settings_top.json")

    def name_of(self, object_name, within=""):
        element = self.snap.find(object_name, within)
        self.assertIsNotNone(element, object_name)
        return model.name_for_focusable(self.snap, element)

    def test_combo_boxes(self):
        self.assertEqual(self.name_of("cb_chat_boost"), "Chat boost mode")
        self.assertEqual(self.name_of("cb_auto_shutoff"), "Auto shut-off")

    def test_reset_and_help_buttons_name_their_section(self):
        self.assertEqual(self.name_of("btn_reset", "swarm_kernel_fm_c.wg_main.wg_overlay.wg_module_content.wg_tabwidget.qt_tabwidget_stackedwidget.tab_device_widget.main_page_fm_c.scrollArea.qt_scrollarea_viewport.scrollAreaWidgetContents.wg_device.wg_audio_main"), "Reset Audio")
        self.assertEqual(self.name_of("btn_info", "swarm_kernel_fm_c.wg_main.wg_overlay.wg_module_content.wg_tabwidget.qt_tabwidget_stackedwidget.tab_device_widget.main_page_fm_c.scrollArea.qt_scrollarea_viewport.scrollAreaWidgetContents.wg_device.wg_mic_main"), "Microphone help")

    def test_high_bandwidth_buttons(self):
        self.assertEqual(self.name_of("btn_high_band"),
                         "High bandwidth audio, 24 bit, 48000 Hz, Windows sound settings")


class LabelTests(unittest.TestCase):
    def test_tidy_label(self):
        self.assertEqual(model.tidy_label("WAVES 3D"), "Waves 3D")
        self.assertEqual(model.tidy_label("LED BRIGHTNESS"), "LED brightness")
        self.assertEqual(model.tidy_label("VOICE & TONE PROMPTS"), "Voice and tone prompts")
        self.assertEqual(model.tidy_label("AUTO SHUT-OFF"), "Auto shut-off")
        self.assertEqual(model.tidy_label("AUTOSTART SWARM II"), "Autostart Swarm II")
        self.assertEqual(model.tidy_label("Already mixed"), "Already mixed")

    def test_value_like(self):
        for text in ("0", "100", "15", "G", "89%", "-9 dB"):
            self.assertTrue(model.is_value_like(text), text)
        for text in ("NOISE GATE", "LEVELS"):
            self.assertFalse(model.is_value_like(text), text)

    def test_value_formatting(self):
        element = model.Element("x", "roccat_slider_c")
        mix = model.Setting("k", model.SLIDER, "Mix", "", element, end_names=("game", "chat"))
        self.assertEqual(mix.format_value(50), "50, balanced")
        self.assertEqual(mix.format_value(62.4), "62, toward chat")
        self.assertEqual(mix.format_value(30), "30, toward game")
        band = model.Setting("k", model.SLIDER, "32 Hz", "", element, minimum=-9, maximum=9,
                             vertical=True, unit="dB")
        self.assertEqual(band.format_value(3.14), "+3.1 dB")
        self.assertEqual(band.format_value(-0.04), "0 dB")
        self.assertEqual(band.format_value(-12), "-9 dB")
        self.assertEqual(band.format_value(None), "unknown")


if __name__ == "__main__":
    unittest.main()
