# SwarmAccess

An NVDA add-on that makes the headset settings in **Turtle Beach Swarm II**
usable with a screen reader.

Swarm II is the desktop app for Turtle Beach headsets such as the Atlas Air.
Out of the box NVDA can reach almost nothing in it: the combo boxes and
buttons have no names, and the switches and sliders that hold most of the
settings cannot be reached from the keyboard at all. SwarmAccess fixes both.

## What it does

**Names.** Tab moves through Swarm II's combo boxes and buttons as before, but
now they say what they are: "Chat boost mode, combo box, BOLD",
"Reset Audio, button", "Microphone help, button".

**A settings list.** While Swarm II's main window has focus, the arrow keys
walk a list of every setting on whichever screen Swarm II is showing:

* **the home screen**, where the list offers your headset ("Atlas Air,
  button, PC") and Enter opens its settings;
* **the headset's settings page** (audio, microphone, equalizer, device
  status, power, voice prompts, transmitter);
* **Swarm II's own Settings** (the gear in its sidebar): updates, language,
  autostart and notifications.

When Swarm II changes screen, the list follows on your next key press.

| Key | Does |
| --- | --- |
| Down / Up arrow | Next / previous setting |
| Page Down / Page Up | Next / previous section (Audio, Microphone, Equalizer, Device status, Power options, Voice and tone prompts, Transmitter) |
| Ctrl+Home / Ctrl+End | First / last setting |
| Space or Enter | Toggle a switch; open a combo box's list; re-read anything else |
| Right / Left arrow | Slider up / down by 5 (by 1 on the 0 to 15 voice prompt level, by 1 dB on the equalizer); switch on / off; combo box next / previous option |
| Shift+Right / Shift+Left | Slider up / down by its smallest step: 1, or 0.1 dB on the equalizer |
| End / Home | Slider to its maximum / minimum |
| NVDA+F5 | Read the page again after it changes |

Each setting is announced as its name, its type and its value, for example
"Noise gate level, slider, 15" or "Waves 3D, switch, on". The section is said
when you move into a new one. Read-only facts are in the list too: battery
level, driver status, connection and transmitter status.

The arrow keys go back to Swarm II whenever a combo box's list, a menu or a
text field is open, and Space and Enter still press a focused button.

## Limits — please read

SwarmAccess works the way a sighted user does: it **looks** at the screen and
**clicks** with the mouse. Swarm II gives a screen reader nothing else to go
on for its switches and sliders. That has consequences:

* **Swarm II must be visible.** Before reading or changing anything,
  SwarmAccess checks that nothing covers the control. If another window,
  the taskbar or the edge of the screen is in the way, you hear
  "not visible" instead of a guess, and nothing is clicked. A window that is
  set to stay on top (some apps do this) will hide whatever part of Swarm II
  it covers.
* **Swarm II must not be minimised.** It scrolls its own page as needed, so
  it does not have to be maximised.
* **The mouse pointer moves briefly** when a switch or slider changes, and is
  put back afterwards.
* **Turtle Beach updates may break it.** Labels are read live from Swarm II,
  but the colours of a switch, the shape of a slider's thumb and the
  equalizer's band names are fixed in the add-on. They were measured on
  Swarm II as of October 2026 with an Atlas Air. A redesign will need new
  measurements; the tools for that are in `tools/`.
* **Values are measured, not reported.** A slider's value is worked out
  from where its thumb is drawn. The readings have matched exactly wherever
  there was something to check against: Audio master volume read 70 when
  Windows reported 70.0%; the equalizer matched Swarm II's own "+3.1 dB",
  "-0.1 dB" and "+0.0 dB" labels; sliders at their ends read 100 and 15 of
  15. Swarm II shows no number for its horizontal sliders, so values in the
  middle of those have no second source.
* **Changes take up to a second.** Swarm II places a dragged thumb to within
  about one step, so after every drag the add-on reads the slider back and,
  if it missed, drags again with the aim corrected, up to five times. What
  you hear is the value read back at the end.
* **Equalizer edits apply as you make them, but saving them is up to you.**
  While a built-in preset such as Turtle Beach Signature Sound is selected,
  Save stays unavailable; the way to keep an edit is "Save as new preset",
  and Swarm II only keeps five custom presets onboard. The Save, Cancel and
  "Save as new preset" buttons are ordinary buttons Tab reaches. The preset
  list itself (Signature Sound, Bass Boost and so on) is drawn by Swarm II
  and not yet in the settings list, and neither is the Game / Mic switch
  above the bands, so check which one is selected before editing.

Macro Manager and Device Manager are not covered yet.

**If Swarm II suddenly reads as silence or gibberish,** check its language:
after one restart it switched itself to Traditional Chinese. The add-on reads
whatever Swarm II shows, so Settings > Language > Select language, which the
list reaches, puts it right.

## Installing

Download `swarmAccess-<version>.nvda-addon`, press Enter on it, and let NVDA
install it and restart. Requires NVDA 2024.1 or later; tested on 2026.1.1.

## How it works

The interesting part is that every Swarm II widget, named or not, carries its
Qt object path as its UI Automation **AutomationId**, for instance
`…wg_area_noise.wg_title_noise.switchbox_noise`, and an accurate bounding
rectangle. From those two facts alone:

1. **Labelling** (`model.py`). A switch or combo box takes the nearest
   naming label on its own row; a slider takes the nearest title above it.
   Numbers and the end markers ("0", "100", "G", "C") are never used as
   names, but they do give the slider its range. A switch, slider and combo
   box that share one label become "Noise gate", "Noise gate level" and
   "Chat boost mode". The text itself comes from Swarm II.
2. **Which screen is showing** (`model.py`, `page.py`). Swarm II marks
   nothing as offscreen. The home screen and the device page replace each
   other in the tree, but its app Settings open as a panel laid over the
   device page, which stays in the tree at stale positions. Qt paints a
   widget's later children over its earlier ones, so a panel wholly inside a
   later sibling's rectangle is treated as hidden. A screen change is spotted
   by comparing the children of two containers, which takes under 2 ms, so
   it is checked on every key press.
3. **Scrolling** (`page.py`). Each scroll area's bar does expose a working
   RangeValue pattern, so off-screen controls are scrolled into view without
   touching the mouse. The bar has no object name; it is found standing
   against its viewport's right edge. Its units are Qt's logical pixels, so
   the add-on converts using the content's own measured travel.
4. **Reading** (`pixels.py`, `screen.py`). The control's rectangle is copied
   off the screen. A switch is on when its middle row is mostly Swarm II's
   purple and the white knob is on the right. A slider's thumb is the only
   tall, light, colourless blob in its rectangle; a dim grey thumb means the
   slider is disabled, which is reported as "unavailable". How far the
   thumb's centre stops short of each end was measured on the live app and
   is stored as a share of the slider's thickness, so it scales with
   Windows' display scaling.
5. **Changing** (`page.py`, `screen.py`). A switch is clicked in its centre.
   A slider's thumb is dragged to the position for the new value; Swarm II
   ignores drags of only a few pixels, so a small correction is made as two
   drags, away and back. The control is then read again and **what the
   screen shows** is announced, so a change that did not take is reported as
   such.

Everything except the final NVDA layer (`swarmAppModule.py`) is plain Python
with no NVDA imports, which is what makes it testable.

## Developing

```bash
python -m venv tools/.venv
tools/.venv/Scripts/python -m pip install -r tools/requirements.txt
tools/.venv/Scripts/python -m unittest discover -s tests
python tools/build.py
```

`tools/probe.py` runs the add-on's own code against the live Swarm II window
without NVDA:

```bash
tools/.venv/Scripts/python tools/probe.py list --scroll
tools/.venv/Scripts/python tools/probe.py snapshot tests/fixtures/new.json
tools/.venv/Scripts/python tools/probe.py set "Show grid" on
```

`list` prints every setting with the value read off the screen. `set`
**really changes** the headset setting it names, so put it back afterwards.

The tests use UI Automation snapshots and pixel grabs recorded from the real
app, so the labelling and reading rules are checked against what Swarm II
actually draws.

## Licence

GPL v2, the same as NVDA.
