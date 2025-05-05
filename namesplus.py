# Edited by Doomsday 4 May 2025 - May the 4th be with you.
# Added ability for admins to change players names
# Useful for those with blank names or lazy aliasing guys during tournaments :)

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

RE_COLOR = re.compile(r"\^.")
_re_remove_excessive_colors = re.compile(r"(?:\^.)+(\^.)")
_name_key = "minqlx:players:{}:colored_name"

class namesplus(minqlx.Plugin):
    def __init__(self):
        self.add_hook("player_connect", self.handle_player_connect)
        self.add_hook("player_loaded", self.handle_player_loaded)
        self.add_hook("player_disconnect", self.handle_player_disconnect)
        self.add_hook("userinfo", self.handle_userinfo)
        self.add_command("name", self.cmd_name, usage="<name>", client_cmd_perm=0)
        self.add_command("setname", self.cmd_setname_admin, usage="<player id> <new name>", permission=1)

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

    def handle_player_disconnect(self, player, reason):
        if player.steam_id in self.steam_names:
            del self.steam_names[player.steam_id]

    def handle_userinfo(self, player, changed):
        if self.name_set:
            self.name_set = False
            return

        if "name" in changed:
            name_key = _name_key.format(player.steam_id)
            if name_key not in self.db:
                self.steam_names[player.steam_id] = self.clean_text(changed["name"])
            elif self.steam_names[player.steam_id] == self.clean_text(changed["name"]):
                changed["name"] = self.db[name_key]
                return changed
            else:
                del self.db[name_key]
                player.tell("Your registered name has been reset.")

    def cmd_name(self, player, msg, channel):
        name_key = _name_key.format(player.steam_id)

        if len(msg) < 2:
            if name_key not in self.db:
                return minqlx.RET_USAGE
            else:
                del self.db[name_key]
                player.tell("Your registered name has been removed.")
                return minqlx.RET_STOP_ALL

        name = self.clean_excessive_colors(" ".join(msg[1:]))
        return self.set_name_for_player(player, name, player)

    def cmd_setname_admin(self, player, msg, channel):
        if len(msg) < 3:
            return minqlx.RET_USAGE

        try:
            target_id = int(msg[1])
            target = self.player(target_id)
        except Exception:
            player.tell("Invalid player ID.")
            return minqlx.RET_STOP_ALL

        name = self.clean_excessive_colors(" ".join(msg[2:]))
        result = self.set_name_for_player(target, name, player, is_admin=True)

        if result == minqlx.RET_STOP_ALL:
            player.tell(f"Set name for ^6{target.name}^7 to: ^7{name}")
        return result

    def set_name_for_player(self, target, name, source_player, is_admin=False):
        if len(name.encode()) > 36:
            source_player.tell("The name is too long. Consider using fewer colors or a shorter name.")
            return minqlx.RET_STOP_ALL
        elif "\\" in name:
            source_player.tell("The character '^6\\^7' cannot be used. Sorry for the inconvenience.")
            return minqlx.RET_STOP_ALL
        elif not self.clean_text(name).strip():
            source_player.tell("Blank names cannot be used. Sorry for the inconvenience.")
            return minqlx.RET_STOP_ALL
        elif not is_admin and self.clean_text(name).lower() != target.clean_name.lower() and self.get_cvar("qlx_enforceSteamName", bool):
            source_player.tell("The new name must match your current Steam name.")
            return minqlx.RET_STOP_ALL

        self.name_set = True
        name = "^7" + name
        target.name = name
        self.db[_name_key.format(target.steam_id)] = name

        if not is_admin:
            source_player.tell("The name has been registered. To make me forget about it, use ^6{}name^7.".format(self.get_cvar("qlx_commandPrefix")))
        return minqlx.RET_STOP_ALL

    def clean_excessive_colors(self, name):
        def sub_func(match):
            return match.group(1)
        return _re_remove_excessive_colors.sub(sub_func, name)

    def clean_text(self, text):
        return RE_COLOR.sub("", text)
