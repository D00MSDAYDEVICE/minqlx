# Edited by Doomsday 4 May 2025 - May the 4th be with you.
# Added ability for admins to change players names
# Useful for those with blank names or lazy aliasing guys during tournaments :)
# Updates 6 May 2025 - Names now persist between reconnects until a !clear <player id> is performed.

# minqlx - Extends Quake Live's dedicated server with extra functionality and scripting.
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

import minqlx
import re
import os
import datetime

_re_remove_excessive_colors = re.compile(r"(?:\^.)+(\^.)")
_name_key = "minqlx:players:{}:colored_name"
LOG_FILE = os.path.join(os.path.dirname(__file__), "namesplus.log")

VERSION = "1.2.0"

class namesplus(minqlx.Plugin):
    def __init__(self):
        self.add_hook("player_connect", self.handle_player_connect)
        self.add_hook("player_loaded", self.handle_player_loaded)
        self.add_hook("player_disconnect", self.handle_player_disconnect)
        self.add_hook("userinfo", self.handle_userinfo)
        self.add_command("name", self.cmd_name, usage="<name>")
        self.add_command("setname", self.cmd_setname_admin, usage="<player id> <name>", permission=4)
        self.add_command("clear", self.cmd_clear_name, usage="<player id>", permission=4)
        self.add_command("npv", self.cmd_version)

        self.set_cvar_once("qlx_enforceSteamName", "1")
        self.steam_names = {}
        self.name_set = False

    def handle_player_connect(self, player):
        self.steam_names[player.steam_id] = player.clean_name

    def handle_player_loaded(self, player):
        name_key = _name_key.format(player.steam_id)
        if name_key in self.db:
            db_name = self.db[name_key]
            if not self.get_cvar("qlx_enforceSteamName", bool) or self.clean_text(db_name).lower() == player.clean_name.lower():
                self.name_set = True
                player.name = db_name
                self.log_debug(f"Set loaded name for {player.id} ({player.clean_name}) to: {db_name}")

    def handle_player_disconnect(self, player, reason):
        self.steam_names.pop(player.steam_id, None)

    def handle_userinfo(self, player, changed):
        if self.name_set:
            self.name_set = False
            return

        if "name" in changed:
            name_key = _name_key.format(player.steam_id)
            if name_key not in self.db:
                self.steam_names[player.steam_id] = self.clean_text(changed["name"])
            elif self.steam_names.get(player.steam_id) == self.clean_text(changed["name"]):
                changed["name"] = self.db[name_key]
                return changed
            else:
                del self.db[name_key]
                player.tell("Your registered name has been reset.")

    def cmd_name(self, player, msg, channel):
        name_key = _name_key.format(player.steam_id)

        if len(msg) < 2:
            if name_key in self.db:
                del self.db[name_key]
                player.tell("Your registered name has been removed.")
                return minqlx.RET_STOP_ALL
            return minqlx.RET_USAGE

        name = self.clean_excessive_colors(" ".join(msg[1:])).strip()
        if not self.validate_name(player, name):
            return minqlx.RET_STOP_ALL

        name = "^7" + name
        self.name_set = True
        player.name = name
        self.db[name_key] = name
        player.tell("The name has been registered. To remove it, use ^6!name^7 with no arguments.")
        self.log_debug(f"Player {player.id} set their name to: {name}")
        return minqlx.RET_STOP_ALL

    def cmd_setname_admin(self, player, msg, channel):
        if len(msg) < 3:
            return minqlx.RET_USAGE

        try:
            target_id = int(msg[1])
            target = self.player(target_id)
        except Exception:
            player.tell("Invalid player ID.")
            return minqlx.RET_STOP_ALL

        name = self.clean_excessive_colors(" ".join(msg[2:])).strip()
        if not self.validate_name(player, name, admin_override=True):
            return minqlx.RET_STOP_ALL

        name = "^7" + name
        self.name_set = True
        target.name = name
        self.db[_name_key.format(target.steam_id)] = name

        player.tell(f"Set name for ^6{target.clean_name}^7 to: {name}")
        target.tell(f"^7An admin has set your name to: {name}")
        self.log_debug(f"Admin {player.id} set name for player {target.id} to: {name}")
        return minqlx.RET_STOP_ALL

    def cmd_clear_name(self, player, msg, channel):
        if len(msg) != 2:
            return minqlx.RET_USAGE

        try:
            target_id = int(msg[1])
            target = self.player(target_id)
        except Exception:
            player.tell("Invalid player ID.")
            return minqlx.RET_STOP_ALL

        name_key = _name_key.format(target.steam_id)
        if name_key in self.db:
            del self.db[name_key]
            player.tell(f"Cleared name override for {target.clean_name}.")
            target.tell("An admin has cleared your custom name.")
            self.log_debug(f"Admin {player.id} cleared name for player {target.id}")
        else:
            player.tell("No custom name to clear.")
        return minqlx.RET_STOP_ALL

    def cmd_version(self, player, msg, channel):
        player.tell(f"^3Namesplus version: ^7{VERSION}")

    def clean_excessive_colors(self, name):
        def sub_func(match):
            return match.group(1)
        return _re_remove_excessive_colors.sub(sub_func, name)

    def clean_text(self, text):
        return re.sub(r"\^.", "", text)

    def validate_name(self, player, name, admin_override=False):
        if len(name.encode()) > 36:
            player.tell("Name is too long. Try fewer colors or characters.")
            return False
        if "\\" in name:
            player.tell("Name cannot contain the '^6\\^7' character.")
            return False
        if not self.clean_text(name).strip():
            player.tell("Blank names are not allowed.")
            return False
        if not admin_override and self.get_cvar("qlx_enforceSteamName", bool):
            if self.clean_text(name).lower() != player.clean_name.lower():
                player.tell("Name must match your Steam name.")
                return False
        return True

    def log_debug(self, message):
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"[{timestamp}] {message}\n"
        try:
            with open(LOG_FILE, "a") as f:
                f.write(log_entry)
        except Exception as e:
            self.logger.warning(f"Failed to write to log file: {e}")

