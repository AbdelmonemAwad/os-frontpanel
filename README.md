# Front Panel for OPNsense

A plugin that puts the firewall's own information on the **LCD built into the front of the
appliance** — hostname and address, WAN state, throughput, CPU, memory, uptime, temperature — and
gives the buttons beside it something to do.

**This plugin writes no display code.** That is the first thing to say about it, because it decides
everything else. LCDproc already speaks to panels like this one, and OPNsense already carries
LCDproc in its own repository. What was missing was never a driver. It was the part that decides
what a firewall should say on two lines of sixteen characters, and a page in the GUI to configure
that from — instead of hand-editing a file on the firewall and restarting a daemon by hand every
time you want the screens to go a little slower.

| Layer | Where it comes from |
| --- | --- |
| The engine: `LCDd`, its clients, and 36 drivers | the `lcdproc` package in the OPNsense repository — `lcdproc-0.5.9_1` (measured here) |
| The driver for the panel in this machine | `hd44780` with `ConnectionType=ezio` on `/dev/cuau1` (measured here) |
| Which screens exist, what they say, how fast they move, and the settings page | this plugin |

So there is no serial code in this repository. The plugin generates LCDd's configuration from your
settings, runs its own service, and hands screens to LCDd as one more LCDproc client on the loopback
interface. When the panel does not light, the fault is in a configuration file you can read rather
than in code you cannot.

Tested on OPNsense 26.7.4_1 / FreeBSD 15.1, on one machine: an ex-Sophos XG 330 rev 2 whose front
panel is 16×2 characters with four keys, on the second of its two serial ports. Everything below
that says **measured here** was measured on that machine; everything else is marked where it
matters. The hardware table ships with **exactly one confirmed entry**, and
[Other appliances](#other-appliances) says what that means for yours.

## The screen that said SOPHOS for months

This appliance ran Sophos firmware before it ran OPNsense. On the day OPNsense was installed, the
front LCD kept the last thing the vendor's firmware had written to it — a splash line with the
vendor's name on it — and there it stayed, month after month, while the machine underneath was
reinstalled, reconfigured and rebooted.

That is not a fault, and it is worth understanding before you go looking for one. A character LCD of
this family has its own controller and its own memory: whatever was written to it last stays on the
glass for as long as the panel has power, and nothing in a stock OPNsense ever writes to that serial
port. The screen was not frozen. Nobody was talking to it.

What it turned out to be, in the end, was three facts and two lines of configuration:

- **The panel is on the second serial port.** `uart1` at `0x2f8`, IRQ 3 (measured here) — which is
  `/dev/cuau1` on FreeBSD, the port Linux calls `ttyS1`. The first port, `uart0` at `0x3f8`, is the
  system console and must be left alone.
- **The protocol is ordinary.** It is an HD44780 panel behind an EZIO-style serial interface, which
  LCDproc has driven for years: driver `hd44780`, `ConnectionType=ezio`, at the 2400 baud that
  connection type uses by default. Sophos's own firmware drove this same panel with LCDproc's own
  daemon on `/dev/ttyS1` (reported, not verified here). The panel never spoke anything proprietary,
  and nobody was ever going to have to reverse-engineer it.
- **The default that makes a correct configuration look broken is the heartbeat.** LCDproc blinks a
  small icon in a corner to show the server is alive. It draws that icon with a user-defined
  character which this panel renders as a **solid black block** (measured here). With
  `Heartbeat=off`, the same configuration that looked half-broken is simply correct.

Two more lines earned their place while watching it run: `DelayMult=2`, because a slow panel drops
characters when the host talks to it at full speed, and `RefreshDisplay=4`, which redraws the whole
screen every four seconds so that corruption — if any gets through — cannot sit there for an hour.
That second line is not free, and what it costs is paid in key presses; [The keys](#the-keys) is
where that bill is itemised.

With those in place the panel showed live CPU, memory and uptime, and the owner photographed it.
That photograph is the entire evidence behind the one confirmed row in the hardware table, and it is
the standard this plugin asks of anybody adding a second row.

## What you need

One package, from the repository OPNsense already uses:

```sh
pkg install lcdproc
```

That is the whole prerequisite. It brings the server, the demo client and the drivers (measured
here, `lcdproc-0.5.9_1`):

```sh
ls -l /usr/local/sbin/LCDd /usr/local/bin/lcdproc
ls /usr/local/lib/lcdproc/*.so | wc -l          # 36 here
```

Nothing in this plugin works without it, and there is no fallback: the plugin configures LCDd, and
LCDd drives the panel. There is no compiler, no ports tree and no out-of-tree driver anywhere in the
story.

You also need a panel LCDproc can actually drive, on a serial port that is **not** carrying a console
and that nothing else has open. On this machine `/dev/cuau1` carries no console — `/etc/ttys` starts
a getty on `ttyu1` only `onifconsole`, and the console is `ttyu0` (measured here). Checking that on
your own machine is two commands, and [docs/panels.md](docs/panels.md) walks through them.

## Nothing runs until you turn it on

`enabled` is off after installation, and the plugin applies nothing by itself.

When the page opens it looks your appliance up in its table and, if it finds a match, **proposes** a
driver and its settings — driver name, device, size, whether to poll the keys. It fills the form in
and stops there. You look at it, and you press Apply.

That is deliberate. Writing an unknown protocol at an unknown speed to a serial port that might be
somebody's console is not a mistake a plugin gets to make on its own initiative, on a machine that is
at that moment routing somebody's traffic.

## Settings, and the speeds

Every speed on this page is adjustable from the GUI, and that is not decoration: it is the one thing
the owner asked for by name after watching the first version run. A pace that is right on one
appliance is unreadable on another — the glass is slower, the bus is slower, or the person reading it
is walking past rather than standing still — and none of that should require editing a file on a
firewall.

| Setting | Default | The LCDd setting it writes | What it does |
| --- | --- | --- | --- |
| `enabled` | off | — | nothing runs until this is on |
| `driver` | from the table | `Driver` | which of the 36 LCDproc drivers to load |
| `device` | `/dev/cuau1` | the driver's `Device` | the serial port, offered from the ports the machine actually has |
| `size` | `16x2` | the driver's `Size` | columns × rows |
| `keypad` | on | the driver's `Keypad` | whether the keys are polled at all |
| **`screen_seconds`** | 3 | `WaitTime` | how long each screen is shown before the next one |
| **`scroll_speed`** | 10 | `TitleSpeed` | how fast a line longer than the display scrolls — 0 to 10, where 0 does not scroll at all |
| **`bus_delay`** | 2 | `DelayMult` | the delay multiplier: how long the driver waits between bytes |
| **`refresh_seconds`** | 4 | `RefreshDisplay` | how often the whole screen is redrawn from scratch |
| **`heartbeat`** | off | `Heartbeat` | LCDproc's blinking "I am alive" icon |
| `screens` | a grid | — | which screens appear, and in which order |
| `keys` | a grid | the driver's `KeyMatrix_…` | one row per key: the label printed on your panel, the name LCDd is told, and what the plugin does with the press |

The first three speeds are the server's own settings and exist whatever the panel is. The last two
belong to the **driver**: `DelayMult` is an `hd44780` and `sed1520` option and `RefreshDisplay` an
`hd44780` one, and writing either into a section that has never heard of it makes LCDd complain on
every start. So a driver without them simply does not get them, and the page says which knobs it had
to leave out rather than showing you a control that does nothing.

The defaults in that table are the values arrived at on this machine by watching it (measured here):
three seconds a screen rather than the six it was first tried at, because six felt like standing
there waiting — LCDd's own default is four; scrolling at 10, because a 16-column line runs out
quickly; and `DelayMult=2` rather than 1 or 4, because 1 drops characters on this panel and 4 is
slower than it needs to be.

Which knob to reach for:

- **The screens change too fast, or you stand there waiting for the one you want** — `screen_seconds`.
- **A long line crawls, or whips past before you can read it** — `scroll_speed`. Set it to 0 and long
  lines stop moving altogether, which is the right answer on a panel people only glance at.
- **Characters go missing, or a line comes out shifted by one** — raise `bus_delay` to 2, then to 4.
  That is the classic symptom of a panel that cannot keep up with the host, and it is a property of
  the hardware rather than a bug.
- **Corruption appears once and then just sits there** — lower `refresh_seconds`, and know what it
  costs. A full redraw is cheap in time on a 16×2 panel, but on a serial panel it is not free: the
  display and the keypad share the line, and a redraw every few seconds swallows key presses
  (measured here: two thirds of them, with screens changing every three seconds and a redraw every
  four). On a panel whose keys you use, buy the insurance at the widest interval that still cleans up
  after a glitch.
- **Key presses go missing** — the same trade-off from the other side. Give each screen longer with
  `screen_seconds` and raise `refresh_seconds`, or set it to 0 and let a glitch wait for the next
  screen change. A quiet line is a responsive keypad.
- **A solid black block in a corner** — that is the heartbeat, and it is off by default here for
  exactly that reason. Turn it on only if your panel draws it as the small pulsing icon it is meant
  to be.

Changing any of these rewrites the generated LCDd configuration and restarts the plugin's service.
Nothing else on the firewall is touched and no other service is restarted.

## Screens

Each screen is two lines of at most `size` columns, and you choose which ones appear and in what
order:

| Screen | What it shows |
| --- | --- |
| identity | hostname and the LAN address |
| wan | the WAN address, and whether the gateway answers |
| throughput | in and out on an interface you pick |
| system | CPU, memory, uptime |
| temperature | the CPU sensor, on machines that have one |
| ports | the worst port and its verdict — `PortA3 FAIL`, `3.8% bad frames` — **only when os-linkhealth is installed** |
| message | a fixed line you write yourself |

The **message** screen is there because a firewall in a rack is usually read by somebody who is not
its administrator. "Do not power off - ask Abdelmonem" is a perfectly good use of sixteen characters.

The **ports** screen is the only contact this plugin has with my other plugin, os-linkhealth: it
reads `/var/db/linkhealth/status.json` if that file happens to exist, and the screen simply does not
appear in the list if it does not. There is no dependency, no shared code and no package requirement
in either direction. Install one, both, or neither.

## The keys

The panel on this appliance has four keys — ENTER, ESC, up and down — and **all four report**
(measured here, 2026-09-21: each one pressed three times, each press in LCDd's log, nothing lost).
Getting there took two corrections to the obvious procedure, and both of them are worth more than the
result:

- **Nothing is printed at the ordinary report level.** The first runs that recorded a press were at
  `ReportLevel=5`; the runs at 3 logged not one, while the same keys were being pressed (measured
  here). "I saw no key events" usually means the log was never going to show them. Level 4 was
  measured afterwards and is what the plugin writes when the keypad is on: it names every keystroke
  and nothing else, where level 5 adds a line of LCDd's own narration per frame — eight a second,
  which buries the presses it was turned up to find.
- **The screen and the keys share one 2400-baud line, and writing starves polling.** With screens
  changing every three seconds and a full redraw every four, two thirds of the presses were lost.
  With the screen held still, every press arrived (measured here). This is the single most useful
  thing on this page: a keypad that feels unreliable is usually a panel being written to too often.

Which key is which is not something the panel tells you. The driver reports a **matrix position**,
and the name is whatever the configuration calls it, so the map was measured a button at a time:

| Printed on the panel | Matrix position | What LCDd is told to call it |
| --- | --- | --- |
| ▼ | 4,1 | `Down` |
| ESC | 4,2 | `Escape` |
| ▲ | 4,3 | `Up` |
| ENTER | 4,4 | `Enter` |

LCDproc's own sample configuration puts `Enter` on 4,1 — which on this appliance is the down arrow.
A plugin that shipped the driver's defaults as though they were facts would give you a panel whose up
arrow scrolls down. So the map is part of the appliance entry, each entry says in words whether its
map was measured or copied from a cousin, and you can change it from the page without editing a file
on the firewall.

None of which the plugin depends on:

- Screens rotate on a timer, so it is completely useful with no working keys at all. That is the
  design and not a fallback.
- Where keys do report, they earn: next screen, previous screen, and a confirm/back pair for a small
  menu. Nothing in the shipped screens needs a key to be reachable.
- The settings page carries a **key test** that says which position last reported, so somebody on
  unknown hardware finds out in ten seconds instead of guessing for an evening.

Why the keys are hard is worth one sentence, because it explains why "I listened and saw nothing" is
not the end of it: on this connection type the keys are **polled**, never volunteered — the host
sends a poll byte and the panel answers with a key code (documented in LCDproc's own
`hd44780-serial.c`). Listening passively to the port therefore shows nothing at all, forever,
whether the keys work or not.

One log line explains the failure most people meet first. `handle_input: left over key` means the
panel reported a press, the driver decoded it, and no client had claimed that key — the keypad is
working and nothing was listening. It is not a reason to change drivers.

If they never report on a given panel, the honest fallback is the `mtc_s16209x` driver, which lights
the screen and can never read a button — its configuration section has no keypad options of any kind
(documented: in LCDproc's own sample configuration that section takes a device, a brightness and a
reboot flag, and nothing else). The page says so rather than pretending.

## Other appliances

The table this plugin ships, `panels.json`, has **one confirmed entry**: the Sophos XG 330 rev 2
above — its display watched and photographed, its four keys measured one at a time, and every word of
that written into the entry so the page can show it to whoever is about to press Apply.

Everything else is a choice the page offers you, not hardware somebody has tested. The settings page
lists the 36 drivers the `lcdproc` package installs, and "support for other appliances" means exactly
that: exposing the choice, with a table of known-good starting points that grows only when somebody
confirms one. An entry in that table is never applied on its own; it fills the form in, and you press
Apply.

If your appliance has a panel and is not in the table, adding it is one block of JSON and no code.
**[docs/panels.md](docs/panels.md)** is the whole procedure: what to read off your machine, how to
narrow 36 drivers down to a shortlist, how to try one without upsetting the panel or the console, and
what evidence to send with the entry. Please read its safety rules before you point anything at a
serial port.

## Installing

The plugin is not in the official repository. Install the package it needs, copy this repository to
the firewall, and run the installer as root:

```sh
pkg install lcdproc
fetch -o /tmp/frontpanel.tar.gz https://github.com/AbdelmonemAwad/os-frontpanel/archive/refs/heads/main.tar.gz
tar -xzf /tmp/frontpanel.tar.gz -C /root
sh /root/os-frontpanel-main/install/install.sh
```

Then open **System → Front Panel**. The page is under System rather than Interfaces because this is
about the appliance itself and not about the network it serves.

Nothing is on the screen yet, and nothing will be until you turn the plugin on: look at what the page
proposes for your hardware, change what you disagree with, and press Apply.

The layout of this repository matches a plugin directory in
[opnsense/plugins](https://github.com/opnsense/plugins), so `Makefile` and `pkg-descr` are only used
when it is built as a package there.

### Removing it

```sh
sh /root/os-frontpanel-main/install/uninstall.sh
```

The settings stay in `config.xml`, so a reinstall comes back with the same driver, the same port and
the same speeds rather than asking you to find them all again.

## How it works

- The settings live in `config.xml` like every other OPNsense setting, and the plugin generates
  LCDd's configuration from them, into a file of its own: `/usr/local/etc/frontpanel/LCDd.conf`,
  written fresh every time the service starts. The `lcdproc` package installs only
  `/usr/local/etc/LCDd.conf.sample`, and if you have written an `LCDd.conf` of your own beside it,
  this plugin never reads or touches it — it runs its own server with its own file, so your
  configuration keeps working exactly as it did.
- `src/opnsense/scripts/frontpanel/` holds the screen generators, the configuration writer and the
  hardware table. Each screen is a small function returning two lines, so adding one is small and
  local.
- LCDd opens the serial port while it is still root and then drops to `User=nobody` (measured here:
  `/dev/cuau1` is `uucp:dialer`, mode 0660, and `fstat` shows the running LCDd holding it as
  `nobody`). That is why the daemon does not keep root, and why the port's permissions never have to
  be loosened to make a panel work.
- Before anything starts, the port is checked: that it exists, that it is a character device and not
  something somebody typed by mistake, and that `/etc/ttys` does not give it a login prompt — reading
  the flags properly, so that a port marked `onifconsole` is refused only when it really is the
  console. What the plugin cannot tell you is whether some other daemon already has the port open;
  `fstat /dev/cuau1` can, and [docs/panels.md](docs/panels.md) makes a rule of asking it first.
- It is cheap. A 16×2 panel is 32 characters, and a redraw is a few dozen bytes down a 2400-baud
  line. Nothing here asks the firewall for more than the dashboard already does.

## The GUI in Arabic

The GUI on the reference machine is used in **Arabic, right to left**. Nothing on the settings page
is positioned with a hard-coded left offset, and every visible string goes through the framework's
translation function, so the existing translation pipeline carries this page like any other.

The panel itself is a different matter, and it is better said here than discovered at the rack: a
16×2 character LCD has no Arabic in its character generator. LCDproc's default map translates
ISO-8859-1 to the panel's own ROM, and the only other maps compiled into the `hd44780` module shipped
here are `hd44780_euro`, `ea_ks0073` and `sed1278f_0b` (measured here), and not one of them has an
Arabic letter in it. So the **screens are English** whatever the GUI language is. Anything outside plain ASCII
is folded before it is ever sent, on purpose: an accented Latin letter loses its accent, because a
panel that can draw `e` should show `e`, and everything left outside ASCII — Arabic, CJK, an emoji —
becomes `?` rather than whichever arbitrary glyph that panel happens to keep at those codes. No
setting in this plugin changes that. What the plugin does instead is show you: the preview renders
the folded line, and says plainly when folding changed what you typed, so an Arabic `message` is seen
on the page rather than discovered at the rack.

## What it does not do

- It does not write to a serial port itself. LCDd does.
- It does not write to a port that `/etc/ttys` gives a login prompt to; it refuses and says which
  line in that file made it refuse. It cannot see another daemon's open file handle and does not
  pretend to — that check is `fstat`, and the panel documentation makes a rule of it.
- It does not turn itself on after installation, and it applies no table entry without you.
- It does not promise keys on hardware whose driver cannot read them.
- It does not depend on os-linkhealth, does not import a line of it, and os-linkhealth does not know
  this plugin exists. The one point of contact is one status file, read-only and optional.
- It does not claim to support an appliance nobody has tested. One row of the table is confirmed; the
  rest of the world is a driver list, and this document saying so.

## License

BSD 2-Clause, the same as OPNsense, and the same header as the rest of my plugins.
Written by `Abdelmonem Awad <eg2@live.com>`.
