# This is an extension plugin for minqlx to slap/punish players that do team damage
# This works similar to a reverse vampiric effect
# Damage can be set to a specific amount per hit or proportional in your server config
# Until the master minqlx is updated, Shino's version is required to be compiled for your server here: https://github.com/mgaertne/minqlx
# His fork has a hook for damage

# qlx_backfireSlapAmount "10"   // Fixed slap damage
# qlx_backfireProportional "1"  // 1 = Use proportional slap damage, 0 = Use fixed damage
# qlx_logDir                    // Optional log directory

# You can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation,
# either version 3 of the License, or (at your option) any later version.

# You should have received a copy of the GNU General Public License
# along with minqlx. If not, see <http://www.gnu.org/licenses/>.

# Created by Doomsday
# https://github.com/D00MSDAYDEVICE
# https://www.youtube.com/@HIT-CLIPS

# You are free to modify this plugin.
# This plugin comes with no warranty or guarantee.

import os
import time
import minqlx
from minqlx import Plugin, Player


class backfire(Plugin):
    def __init__(self):
        super().__init__()

        self.add_hook("game_countdown", self.handle_game_countdown)
        self.add_hook("damage", self.handle_damage_event)
        self.add_command("bfv", self.cmd_bfv)

        self.version = "1.0"

        # CVars
        self.set_cvar_once("qlx_backfireSlapAmount", "10")
        self.set_cvar_once("qlx_backfireProportional", "0")
        self.set_cvar_once("qlx_backfireMinHealth", "1")
        self.set_cvar_once("qlx_logDir", "logs")

        self.slap_amount = self.get_cvar("qlx_backfireSlapAmount", int) or 10
        self.proportional = self.get_cvar("qlx_backfireProportional", bool) or False
        self.min_health = self.get_cvar("qlx_backfireMinHealth", int) or 1
        self.log_dir = self.get_cvar("qlx_logDir") or "logs"

        os.makedirs(self.log_dir, exist_ok=True)
        self.backfire_log_path = os.path.join(self.log_dir, "backfire.log")

    def handle_game_countdown(self):
        self.team_damages = {}

    def handle_damage_event(self, target, attacker, dmg, dflags, means_of_death):
        if not self.game or self.game.state != "in_progress":
            return

        if not isinstance(target, Player) or not isinstance(attacker, Player):
            return

        if target.team != attacker.team or target.id == attacker.id:
            return

        self.log_team_damage(target, attacker, dmg)

        if attacker.health <= 0:
            return

        if self.proportional:
            slap_damage = min(dmg, attacker.health - self.min_health)
        else:
            slap_damage = min(self.slap_amount, attacker.health - self.min_health)

        if slap_damage > 0:
            attacker.health -= slap_damage
            self.play_sound("sound/feedback/hit_teammate.ogg", player=attacker)

    def log_team_damage(self, target, attacker, dmg):
        log_line = "[{}] {} ({}) hit {} ({}) for {} damage\n".format(
            time.strftime("%Y-%m-%d %H:%M:%S"),
            attacker.name, attacker.steam_id,
            target.name, target.steam_id,
            dmg
        )
        with open(self.backfire_log_path, "a") as f:
            f.write(log_line)

    def cmd_bfv(self, player, msg, channel):
        channel.reply("^2Backfire Plugin v{}".format(self.version))
