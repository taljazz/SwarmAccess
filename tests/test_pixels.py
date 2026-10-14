"""Switch and slider readings from pixels captured off the real Swarm II.

Each PNG in ``tests/fixtures`` is one control's rectangle, grabbed with
``tools/probe.py grab`` on 2026-10-14 while the value was confirmed on
screen.  Needs Pillow (tools/requirements.txt) to load them.
"""

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "addon" / "appModules"))

from _swarmAccess import model, pixels  # noqa: E402

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None

FIXTURES = ROOT / "tests" / "fixtures"


def source(name):
    image = Image.open(FIXTURES / name).convert("RGB")
    width, height = image.size
    data = list(image.getdata())
    return pixels.GridSource([data[y * width:(y + 1) * width] for y in range(height)])


def slider(minimum=0, maximum=100, vertical=False, **kwargs):
    return model.Setting("k", model.SLIDER, "test", "", model.Element("x", "roccat_slider_c"),
                         minimum=minimum, maximum=maximum, vertical=vertical, **kwargs)


@unittest.skipIf(Image is None, "Pillow is needed to load the fixtures")
class RecordedPixelTests(unittest.TestCase):
    def test_switch_on(self):
        self.assertIs(pixels.read_switch(source("switch_on.png")), True)

    def test_switch_off(self):
        self.assertIs(pixels.read_switch(source("switch_off.png")), False)

    def test_small_switch_off(self):
        self.assertIs(pixels.read_switch(source("switch_small_off.png")), False)

    def test_slider_at_70(self):
        value, enabled = pixels.read_slider(source("slider_70.png"), slider())
        self.assertTrue(enabled)
        self.assertEqual(slider().snap(value), 70)

    def test_disabled_slider_is_still_read_and_flagged(self):
        value, enabled = pixels.read_slider(source("slider_disabled.png"), slider())
        self.assertFalse(enabled)
        self.assertEqual(slider().snap(value), 60)

    def test_game_chat_mix_centred(self):
        value, enabled = pixels.read_slider(source("slider_mix_50.png"), slider())
        self.assertTrue(enabled)
        self.assertEqual(slider().snap(value), 50)

    def test_sliders_at_their_maximum(self):
        for name, maximum in (("slider_monitoring_100.png", 100), ("slider_led.png", 100),
                              ("slider_voice_15.png", 15)):
            setting = slider(0, maximum)
            value, enabled = pixels.read_slider(source(name), setting)
            self.assertEqual(setting.snap(value), maximum, name)

    def test_noise_gate_low(self):
        value, _ = pixels.read_slider(source("slider_noise_gate.png"), slider())
        self.assertEqual(slider().snap(value), 16)

    def test_microphone_switches(self):
        self.assertIs(pixels.read_switch(source("switch_mute_off.png")), False)
        self.assertIs(pixels.read_switch(source("switch_noise_on.png")), True)

    def test_equalizer_band_flat(self):
        band = slider(-9, 9, vertical=True)
        value, enabled = pixels.read_slider(source("eq_band_0db.png"), band)
        self.assertTrue(enabled)
        self.assertEqual(band.snap(value), 0)


class SyntheticPixelTests(unittest.TestCase):
    """Edge cases the live app could not be put into safely."""

    BACKGROUND = (26, 31, 39)

    def blank(self, width, height):
        return [[self.BACKGROUND] * width for _ in range(height)]

    def test_covered_slider_reads_nothing(self):
        # A white window over the whole slider is not a thumb.
        rows = [[(252, 251, 250)] * 300 for _ in range(37)]
        self.assertEqual(pixels.read_slider(pixels.GridSource(rows), slider()), (None, False))

    def test_thin_tick_mark_is_not_a_thumb(self):
        rows = self.blank(300, 37)
        for y in range(37):
            rows[y][150] = (255, 255, 255)
        self.assertEqual(pixels.read_slider(pixels.GridSource(rows), slider()), (None, False))

    def test_switch_with_no_knob_is_unknown(self):
        self.assertIsNone(pixels.read_switch(pixels.GridSource(self.blank(57, 33))))

    def test_position_and_value_are_inverses(self):
        for vertical in (False, True):
            for value in (0, 15, 50, 85, 100):
                position = pixels.position_for_value(value, 600, 0, 100, vertical)
                self.assertAlmostEqual(pixels.value_from_position(position, 600, 0, 100, vertical), value)

    def test_vertical_sliders_grow_upwards(self):
        top = pixels.position_for_value(9, 537, -9, 9, vertical=True)
        bottom = pixels.position_for_value(-9, 537, -9, 9, vertical=True)
        self.assertLess(top, bottom)


if __name__ == "__main__":
    unittest.main()
