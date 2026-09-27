# motdplus.py - v1.1
#
# Version history:
#   1.1 - Renamed motd.py -> motdplus.py (class motdplus). Dual-runtime: one
#         file now loads on both minqlx and minqlxtended. Fixed !addmotd
#         (called redis GET with a default argument, which redis-py rejects,
#         so it always errored) and !clearmotd (errored when no MOTD was set).
#         Delayed MOTD delivery now skips players who left in the meantime.
#         MOTD is now 10 numbered line slots: !setmotd <line> <message> sets
#         only that line (other lines untouched), !setmotd <line> alone
#         clears it, !addmotd fills the first free slot, and qlx_motd1-10
#         load into their matching slots. Empty slots are skipped when the
#         MOTD is shown, so lines always display in order with no gaps.
#         Added !listmotd (admin) to view the numbered slots for editing.
#   1.0 - Doomsday, April 2025: multi-line MOTD edit of the stock motd.py.
#
# Do not load this alongside the stock motd plugin - both hook player_loaded
# and share the same Redis key, so players would get the MOTD twice.
# Existing MOTDs carry over: the Redis key is unchanged.
#
# Edited by Doomsday April 2025
# Extended motd to multiple lines to overcome character length and format limitations/ease of use

# !setmotd <line> <message>	Set specific line of MOTD (1-10). Other lines are untouched.
# !setmotd <line>           Clear just that line.
# !addmotd <message>        Adds a new line to the next free slot.
# !listmotd                 Show all 10 slots with their line numbers (admin).
# !clearmotd                Clears all MOTD lines.
# !reloadmotd 				reload MOTD lines from motd.cfg in /baseq3 anytime
# Use set qlx_motd1, set qlx_motd2, etc to set from config file.
# Add /exec motd.cfg to config.cfg or simply !reloadmotd
# Config settings will not override existing motd (use !clearmotd and restart server).

# minqlx - A Quake Live server administrator bot.
# Copyright (C) 2015 Mino <mino@minomino.org>
 
# This file is part of minqlx.

# minqlx is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# minqlx is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with minqlx. If not, see <http://www.gnu.org/licenses/>.

import importlib
import sys

# --- Runtime detection -------------------------------------------------------
# The host runtime has already imported its own package before loading
# plugins, so sys.modules tells us which one we're inside; fall back to a
# plain import attempt otherwise.
if "minqlxtended" in sys.modules:
    import minqlxtended as qlx
    IS_EXTENDED = True
elif "minqlx" in sys.modules:
    import minqlx as qlx
    IS_EXTENDED = False
else:
    try:
        import minqlxtended as qlx
        IS_EXTENDED = True
    except ImportError:
        import minqlx as qlx
        IS_EXTENDED = False

_qlx_database = importlib.import_module(qlx.__name__ + ".database")

# minqlxtended replaced the RET_*/PRI_* ints with enums and deliberately does
# not export the old names.
if IS_EXTENDED:
    RET_STOP_EVENT = qlx.Return.STOP_EVENT
    RET_USAGE = qlx.Return.USAGE
    PRI_LOWEST = qlx.Priority.LOWEST
else:
    RET_STOP_EVENT = qlx.RET_STOP_EVENT
    RET_USAGE = qlx.RET_USAGE
    PRI_LOWEST = qlx.PRI_LOWEST

VERSION = "1.1"

# Unchanged from the stock plugin so existing MOTDs carry over.
MOTD_SET_KEY = "minqlx:motd"

# Number of MOTD line slots (matches qlx_motd1 .. qlx_motd10).
MAX_LINES = 10
# Separator between stored lines: a literal backslash-n, same as the
# previous version, so an existing stored MOTD still reads correctly.
LINE_SEP = "\\n"

class motdplus(qlx.Plugin):
    database = _qlx_database.Redis

    def __init__(self):
        super().__init__()
        self.add_hook("player_loaded", self.handle_player_loaded, priority=PRI_LOWEST)
        self.add_command(("setmotd", "newmotd"), self.cmd_setmotd, 4, usage="<line 1-{}> [message]".format(MAX_LINES))
        self.add_command("addmotd", self.cmd_addmotd, 4, usage="<motd line>")
        self.add_command("clearmotd", self.cmd_clearmotd, 4)
        self.add_command("listmotd", self.cmd_listmotd, 4)
        self.add_command("motd", self.cmd_getmotd)
        self.add_command("reloadmotd", self.cmd_reloadmotd, 4)

        self.home = self.get_cvar("fs_homepath")
        self.motd_key = MOTD_SET_KEY + ":{}".format(self.home)

        self.db.sadd(MOTD_SET_KEY, self.home)

        self.set_cvar_once("qlx_motdSound", "sound/vo/crash_new/37b_07_alt.wav")
        self.set_cvar_once("qlx_motdHeader", "^6======= ^7Message of the Day ^6=======^7")

        # Load MOTD from config if Redis is empty
        if self.motd_key not in self.db:
            self.load_motd_from_config()

    def handle_player_loaded(self, player):
        # Delay by client id + steam id rather than holding the Player
        # object, so a player who leaves in the 2s gap is skipped cleanly.
        self._delayed_motd(player.id, player.steam_id)

    @qlx.delay(2)
    def _delayed_motd(self, client_id, steam_id):
        try:
            player = self.player(client_id)
        except qlx.NonexistentPlayerError:
            return
        if not player or player.steam_id != steam_id:
            return

        try:
            motd = self.db[self.motd_key]
        except KeyError:
            return

        sound = self.get_cvar("qlx_motdSound")
        if sound and self.db.get_flag(player, "essentials:sounds_enabled", default=True):
            self.play_sound(sound, player)

        self.send_motd(player, motd)

    # ------------------------------------------------------------
    # Line storage helpers
    # ------------------------------------------------------------

    def _get_lines(self):
        """Stored MOTD as a list of exactly MAX_LINES slots ("" = empty)."""
        try:
            stored = self.db[self.motd_key]
        except KeyError:
            stored = ""
        lines = stored.split(LINE_SEP) if stored else []
        lines = lines[:MAX_LINES]
        return lines + [""] * (MAX_LINES - len(lines))

    def _save_lines(self, lines):
        """Store the slots, keeping their positions. Trailing empty slots are
        dropped; if every slot is empty the key is removed."""
        lines = list(lines[:MAX_LINES])
        while lines and not lines[-1].strip():
            lines.pop()
        if not lines:
            try:
                del self.db[self.motd_key]
            except KeyError:
                pass
            return
        self.db[self.motd_key] = LINE_SEP.join(lines)

    def _has_motd(self):
        return any(line.strip() for line in self._get_lines())

    # ------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------

    def cmd_getmotd(self, player, msg, channel):
        if self._has_motd():
            self.send_motd(player, self.db[self.motd_key])
        else:
            player.tell("No MOTD has been set.")
        return RET_STOP_EVENT

    def cmd_setmotd(self, player, msg, channel):
        if len(msg) < 2:
            return RET_USAGE

        try:
            line_no = int(msg[1])
        except ValueError:
            player.tell("^1Line number must be 1-{}.^7 Usage: !setmotd <line> [message]".format(MAX_LINES))
            return RET_STOP_EVENT
        if not 1 <= line_no <= MAX_LINES:
            player.tell("^1Line number must be 1-{}.".format(MAX_LINES))
            return RET_STOP_EVENT

        lines = self._get_lines()
        text = " ".join(msg[2:]).strip()
        lines[line_no - 1] = text
        self._save_lines(lines)

        if text:
            player.tell("MOTD line {} set.".format(line_no))
        else:
            player.tell("MOTD line {} cleared.".format(line_no))
        return RET_STOP_EVENT

    def cmd_addmotd(self, player, msg, channel):
        if len(msg) < 2:
            return RET_USAGE

        text = " ".join(msg[1:]).strip()
        if not text:
            return RET_USAGE

        lines = self._get_lines()
        for i, line in enumerate(lines):
            if not line.strip():
                lines[i] = text
                self._save_lines(lines)
                player.tell("Added as MOTD line {}.".format(i + 1))
                return RET_STOP_EVENT

        player.tell("^1All {} MOTD lines are in use.^7 Use !setmotd <line> to replace one.".format(MAX_LINES))
        return RET_STOP_EVENT

    def cmd_listmotd(self, player, msg, channel):
        """Numbered view of every slot, so admins know which line to edit."""
        player.tell("^6MOTD lines^7 (edit with !setmotd <line> [message]):")
        for i, line in enumerate(self._get_lines(), start=1):
            player.tell("^3{:>2}^7: {}".format(i, line if line.strip() else "^0(empty)"))
        return RET_STOP_EVENT

    def cmd_clearmotd(self, player, msg, channel):
        if not self._has_motd():
            player.tell("No MOTD is set.")
            return RET_STOP_EVENT
        self._save_lines([])
        player.tell("MOTD has been cleared.")
        return RET_STOP_EVENT

    def cmd_reloadmotd(self, player, msg, channel):
        if self.load_motd_from_config():
            player.tell("MOTD has been reloaded from config and applied.")
        else:
            player.tell("No qlx_motd1-{} cvars are set; MOTD left unchanged.".format(MAX_LINES))
        return RET_STOP_EVENT

    def load_motd_from_config(self):
        """Load qlx_motd1..qlx_motd10 into their matching line slots.
        Returns True if anything was loaded."""
        lines = [self.get_cvar("qlx_motd{}".format(i)) or "" for i in range(1, MAX_LINES + 1)]
        if not any(line.strip() for line in lines):
            return False
        self._save_lines(lines)
        return True

    def send_motd(self, player, motd):
        for line in self.get_cvar("qlx_motdHeader").split(LINE_SEP):
            player.tell(line)
        # Show the lines in slot order; empty slots are skipped so there
        # are no blank gaps between lines.
        for line in motd.split(LINE_SEP)[:MAX_LINES]:
            if line.strip():
                player.tell(line)
