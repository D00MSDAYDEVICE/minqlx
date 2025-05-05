# Edited by Doomsday 4 May 2025 - May the 4th be with you.
# Added ability for admins to change players names
# Useful for those with blank names or lazy aliasing guys during tournaments :)
# Updates 5 May 2025 - Names now persist between reconnects until a !clear <player id> is performed.

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

_re_remove_excessive_colors = re.compile(r"(?:\^.)+(\^.)")
_name_key = "minqlx:players:{}:colored_name"


class namesplus(minqlx.Plugin):
    def __init__(self):
        self.add_hook("player_connect", self.handle_player_connect)
        self.add_hook("player_loaded", self.handle_player_loaded)
        self.add_hook("userinfo", self.handle_userinfo)
        self.add_command("name", self.cmd_name, usage="<name>", client_cmd_perm=0)  # Regular command
        self.add_command("setname", self.cmd_setname_admin, usage="<player id> <name>", client_cmd_perm=2)  # Admin command
        self.add_command("clear", self.cmd_clearname_admin, usage="<player id>", client_cmd_perm=2)  # Admin command

        self.set_cvar_once("qlx_enforceSteamName", "1")
        self.name_set = False

    def handle_player_connect(self, player):
        # Store initial clean name
        self.db.set(f"steam:{player.steam_id}:orig_name", player.clean_name)

    def handle_player_loaded(self, player):
        name_key = _name_key.format(player.steam_id)
        if name_key in self.db:
            stored_name = self.db[name_key]
            self.name_set = True
            player.name = stored_name

    def handle_userinfo(self, player, changed):
        if self.name_set:
            self.name_set = False
            return

        if "name" in changed:
            name_key = _name_key.format(player.steam_id)
            stored_name = self.db.get(name_key)
            if stored_name and self.clean_text(changed["name"]) != self.clean_text(stored_name):
                changed["name"] = stored_name
                return changed

    def cmd_name(self, player, msg, channel):
        name_key = _name_key.format(player.steam_id)

        if len(msg) < 2:
            if name_key in self.db:
                del self.db[name_key]
                player.tell("Your custom name has been removed.")
            else:
                return minqlx.RET_USAGE
            return minqlx.RET_STOP_ALL

        name = self.clean_excessive_colors(" ".join(msg[1:])).strip()

        if not self.validate_name(player, name):
            return minqlx.RET_STOP_ALL

        name = "^7" + name
        self.name_set = True
        player.name = name
        self.db[name_key] = name
        player.tell("Your custom name has been registered.")
        return minqlx.RET_STOP_ALL

    def cmd_setname_admin(self, player, msg, channel):
        if len(msg) < 3:
            return minqlx.RET_USAGE

        try:
            target_id = int(msg[1])  # Player ID is msg[1]
            target = self.player(target_id)
        except Exception:
            player.tell("Invalid player ID.")
            return minqlx.RET_STOP_ALL

        # ✅ FIXED: skip msg[0] (!setname) and msg[1] (player ID)
        name = self.clean_excessive_colors(" ".join(msg[2:])).strip()

        if not self.validate_name(player, name, admin_override=True):
            return minqlx.RET_STOP_ALL

        # Set the name and store it in the database
        name = "^7" + name
        self.name_set = True
        target.name = name
        self.db[_name_key.format(target.steam_id)] = name

        player.tell(f"Set name for ^6{target.clean_name}^7 to: {name}")
        target.tell(f"^7An admin has set your name to: {name}")
        return minqlx.RET_STOP_ALL

    def cmd_clearname_admin(self, player, msg, channel):
        if len(msg) != 2:
            return minqlx.RET_USAGE

        try:
            target_id = int(msg[1])
            target = self.player(target_id)
        except Exception:
            player.tell("Invalid player ID.")
            return minqlx.RET_STOP_ALL

        key = _name_key.format(target.steam_id)
        if key in self.db:
            del self.db[key]
            cached_name = target.clean_name  # Cache the name before changing it
            orig_name = self.db.get(f"steam:{target.steam_id}:orig_name")
            if not orig_name:
                orig_name = target.clean_name
            self.name_set = True
            target.name = orig_name
            player.tell(f"Cleared name override for ^6{cached_name}^7.")
            target.tell("^7Your name override has been removed by an admin.")
        else:
            player.tell("No custom name found for that player.")
        return minqlx.RET_STOP_ALL

    def clean_text(self, text):
        return re.sub(r"\^\d", "", text)

    def clean_excessive_colors(self, name):
        def sub_func(match):
            return match.group(1)
        return _re_remove_excessive_colors.sub(sub_func, name)

    def validate_name(self, player, name, admin_override=False):
        if len(name.encode("utf-8")) > 36:
            player.tell("The name is too long. Consider using fewer colors or a shorter name.")
            return False
        if "\\" in name:
            player.tell("The character '\\' cannot be used.")
            return False
        if not self.clean_text(name).strip():
            player.tell("Blank names cannot be used.")
            return False
        if self.get_cvar("qlx_enforceSteamName", bool) and not admin_override:
            if self.clean_text(name).lower() != player.clean_name.lower():
                player.tell("Your custom name must match your Steam name.")
                return False
        return True
