# os-frontpanel — design contract

Puts the firewall's own information on the LCD built into the front of the appliance, and lets the
buttons beside it do something.

This is a **separate plugin** from os-linkhealth on purpose. It drives hardware, it has its own
daemon and its own hardware matrix, and it is useful to somebody who does not care about cable
diagnostics at all. Where os-linkhealth happens to be installed, its verdicts become one more
screen — read optionally, never depended on.

Claims are marked **V** (verified on the reference machine), **D** (documented in a primary source)
or **R** (reported). Nothing unmarked is a fact.

---

## 1. We write no display code

The panel is a 16×2 character LCD with four keys on the second serial port. LCDproc already speaks
to it, and OPNsense already carries LCDproc:

| Layer | Where it comes from |
|---|---|
| The engine (`LCDd`, clients, 36 drivers) | `lcdproc 0.5.9_1`, in the OPNsense repository (**V**) |
| The driver for this panel | `hd44780` with `ConnectionType=ezio`, 2400 baud on `/dev/cuau1` (**V**) |
| Everything above | this plugin |

**Proven on the machine, 2026-09-21** (**V**): LCDd started with that driver, initialised the panel
without a single error, and the owner photographed the panel showing live CPU, memory and uptime
screens where it had shown the vendor's `SOPHOS Protection` splash since the day OPNsense was
installed.

Sophos's own firmware drove this same panel with LCDproc's own `lcdd` binary on `/dev/ttyS1` — the
Linux name for this exact port (**R**). The panel never spoke a proprietary protocol.

So this plugin ships: a configuration generator, a service, a screen client, a settings page, and
nothing that talks to a serial port.

## 2. What the owner asked for, in order

1. Use the screen and the buttons built into the appliance.
2. Support the built-in displays of **other** appliances too.
3. **Every speed is adjustable from the settings page** — asked for explicitly after watching the
   first version run, and the reason the whole `[speed]` section below exists.

## 3. Hardware support, honestly

LCDproc ships 36 drivers in the OPNsense package (**V**): `hd44780`, `mtc_s16209x`, `sdeclcd`,
`CFontz`, `CFontzPacket`, `CwLnx`, `serialVFD`, `picolcd`, `glcd`, `text`, `curses` and more. The
settings page offers that list, so "support other appliances" means **exposing a choice**, not
writing panel code.

The plugin ships a short table of known appliances, the same shape and the same discipline as
os-linkhealth's `chassis.json`: match on SMBIOS, propose a driver and its settings, and say plainly
that it is a proposal until somebody confirms the screen lit up.

```json
{
  "sophos-xg-3xx": {
    "match": {"maker": "^Sophos$", "product": "^XG$"},
    "driver": "hd44780",
    "options": {"ConnectionType": "ezio", "Device": "/dev/cuau1", "Size": "16x2", "Keypad": "yes"},
    "keymap": {"4_1": "Down", "4_2": "Escape", "4_3": "Up", "4_4": "Enter"},
    "confirmed": "XG 330 rev 2, 2026-09-21: display verified by photograph; all four keys verified one at a time"
  }
}
```

Nothing is auto-applied on install. The page offers the match as a starting point and the owner
presses Apply, because a wrong driver writing to the wrong serial port is not a mistake a plugin
should make on its own initiative.

## 4. The keypad is not assumed

The four keys are **polled**, never volunteered: the host sends a poll byte and the panel answers
with a key code (**D**, from LCDproc's `hd44780-serial.c`). Nothing arrives by listening, which is
why a passive probe on this machine saw nothing.

**The keys are proven on this appliance** (**V**, 2026-09-21). All four report, and the mapping was
measured one button at a time rather than assumed:

| Printed on the panel | Matrix position | What LCDd must call it |
|---|---|---|
| ▼ | 4,1 | `Down` |
| ESC | 4,2 | `Escape` |
| ▲ | 4,3 | `Up` |
| ENTER | 4,4 | `Enter` |

Three were measured directly (three presses each, three events each, no losses); the fourth is the
only position left. LCDproc's own default order for this connection type is NOT this - it would put
`Enter` on 4,1 - so a plugin that ships the driver's defaults gets a panel whose up arrow scrolls
down. The table above is what `panels.json` ships for this model.

**A harder lesson, and the one worth writing down** (**V**): at 2400 baud the display and the keypad
share one line, and writing starves polling. With screens changing every 3 seconds and a full
redraw every 4, two thirds of key presses were lost. With the screen quiet, every press arrived.
So the screen feeder in this plugin must:

  * write only what changed, never redraw on a timer for its own sake;
  * fall silent while a menu is open and a key is expected;
  * poll faster inside a menu and slower while idle.

That is why this plugin writes its own feeder instead of running LCDproc's generic client.

Even so, the design keeps working where the keys do not:

- screens rotate on a timer and the plugin is fully useful with no keys at all;
- if keys report, they gain: next screen, previous screen, and a confirm/back pair for a small menu;
- the settings page shows a key-test panel that says exactly what the driver last reported, so a
  user on unknown hardware can find out in ten seconds rather than guessing.

On hardware where the keys never report, the honest fallback is `mtc_s16209x`, which lights the
screen and can never read a button (**D**) — and the page says so rather than pretending.

One log line explains the failure everybody hits first: `handle_input: left over key` means the
panel reported a press, the driver decoded it, and **no client had claimed that key**, so nothing
happened. People meeting this swap drivers for hours. It belongs in `docs/panels.md`.

## 5. Settings

The `[speed]` group exists because the owner asked for it by name.

| Setting | Default | What it does |
|---|---|---|
| `enabled` | off | nothing runs until it is turned on |
| `driver` | from the table | which LCDproc driver |
| `device` | `/dev/cuau1` | the serial port, offered from what the machine actually has |
| `size` | `16x2` | columns × rows |
| `keypad` | on | poll the keys at all |
| **`screen_seconds`** | 3 | how long each screen is shown |
| **`scroll_speed`** | 10 | how fast a line longer than the display scrolls (LCDd `TitleSpeed`) |
| **`bus_delay`** | 2 | the delay multiplier; raise it if characters go missing |
| **`refresh_seconds`** | 4 | how often the whole screen is redrawn, so corruption cannot persist |
| **`heartbeat`** | off | the blinking icon; off because this panel draws it as a solid block (**V**) |
| `screens` | a grid | which screens are shown, in which order |
| `keys` | a grid | one row per matrix position: the printed label, the LCDd key name, the action — see 5b |

Changing a speed rewrites `LCDd.conf` and restarts the service. Nothing else on the firewall is
touched.

## 5b. The buttons are the owner's to assign

Measuring this panel's key map took four rounds of "press this one three times and I will read the
log". Nobody should have to do that with a log file, and nobody on different hardware should be
stuck with a map that was measured on a Sophos XG 330. So the plugin owns three things here.

**1. Learn.** A panel in the settings page that says *press a button now*. The plugin watches what
the driver reports and answers **which matrix position spoke** — and offers to assign it on the
spot. This is exactly the procedure we ran by hand, minus the log file and the four round trips.

It has to obey the bus rule: while learning, the screen feeder falls silent, because a busy 2400
baud line swallows presses (**V** — two thirds of them, measured).

**2. Remap.** A small grid, one row per matrix position:

| Position | Printed on my panel | LCDd key | What it does |
|---|---|---|---|
| 4,1 | ▼ | `Down` | next screen |
| 4,2 | ESC | `Escape` | back / leave menu |
| 4,3 | ▲ | `Up` | previous screen |
| 4,4 | ENTER | `Enter` | open menu / confirm |

Three columns are the owner's: the label printed on *their* metal, the LCDd key name written into
`LCDd.conf`, and the action the plugin performs. The position column is the hardware's and cannot
be edited. Actions available: next screen, previous screen, open menu, back, show a chosen screen,
toggle the backlight where the driver supports it, and nothing.

**3. Reset.** One button, restoring the map `panels.json` ships for the detected model — and where
no model matches, the driver's own defaults, with the page saying plainly that those defaults are a
guess. LCDproc's defaults for this connection type would put `Enter` on 4,1, which on this appliance
is the down arrow (**V**): shipping a driver default as though it were a fact is how a panel ends up
scrolling the wrong way, so the page always says where a map came from — measured, shipped, or
guessed.

A remap rewrites `LCDd.conf` and restarts the service; an action change does not, because the
actions live in the plugin's own feeder.

## 6. Screens

Each screen is a small generator: it returns two lines of at most `size` columns. Shipped set:

- **identity** — hostname and the LAN address
- **wan** — the WAN address and whether the gateway answers
- **throughput** — in/out on a chosen interface
- **system** — CPU, memory, uptime
- **temperature** — the CPU sensor, where one exists
- **ports** *(only when os-linkhealth is installed)* — the worst port and its verdict:
  `PortA3 FAIL` / `3.8% bad frames`
- **message** — a fixed line the owner writes, for a rack somebody else walks past

The ports screen reads os-linkhealth's status document if it is there and disappears from the list
if it is not. That is the whole of the relationship between the two plugins: one file, read-only,
optional.

## 7. Layout

```
Makefile, pkg-descr, README.md, DESIGN.md
install/{install.sh,uninstall.sh}
src/etc/rc.d/frontpanel                      the service
src/opnsense/service/conf/actions.d/actions_frontpanel.conf
src/opnsense/scripts/frontpanel/{frontpanel.py,screens.py,config.py,panels.json,keys.py}
src/opnsense/mvc/app/models/OPNsense/FrontPanel/{FrontPanel.xml,FrontPanel.php,Menu/Menu.xml,ACL/ACL.xml}
src/opnsense/mvc/app/controllers/OPNsense/FrontPanel/{IndexController.php,forms/general.xml,Api/*.php}
src/opnsense/mvc/app/views/OPNsense/FrontPanel/index.volt
```

Menu: **System → Front Panel** (it is about the appliance, not about the network).

## 8. What this plugin does not do

- It does not write to a serial port itself. LCDd does.
- It does not claim a port that something else is using; it checks first, and `/dev/cuau1` carries
  no console on this machine (**V**: `/etc/ttys` runs a getty there only `onifconsole`, and the
  console is `ttyu0`).
- It does not turn itself on after installation.
- It does not promise keys on hardware where the driver cannot read them.
- It does not depend on os-linkhealth, and os-linkhealth does not know it exists.
