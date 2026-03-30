# Copyright (C) 2026 Doomsday
# This is an extension plugin for minqlx to callvote factories
# Place the factories you want votable in factories.txt in your /baseq3 folder
# Originally created for Thunderdome tournament servers

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

# ──────────────────────────────────────────────────────────────────────────────
# PER-FACTORY CONFIG SUPPORT
# ──────────────────────────────────────────────────────────────────────────────
# When a factory vote passes, the plugin will look for a matching .cfg file in
# the minqlx-plugins folder (same directory as this script).
#
#   Example:  factory "ctf"  →  looks for  <plugins_dir>/ctf.cfg
#             factory "ca"   →  looks for  <plugins_dir>/ca.cfg
#
# If the file exists, it is executed as a server console command before the map change.
#
# RESTORING DEFAULT SETTINGS
# Place a file named restore.cfg in the same plugins folder.
# The !restorecfg command executes it to reset cvars back to defaults.
# The restore is also offered automatically in the vote-failed message.
#
# Copy any custom settings your server has set in server.cfg into your restore.cfg
# This is extra protection to ensure when a factory is changed back, the defaults are set too.
# Good for when a server restart is not available
#
# Permission level is controlled by:
# ql_restorecfg_perm 2 (default: 2)
# 0 = everyone   1 = regular   2 = mod   3 = admin   4 = superadmin
# Set it in your server config, e.g.:  set ql_restorecfg_perm 3
#
# EXAMPLE  ctf.cfg
# ──────────────────
#   // CTF-specific overrides
#   set g_timelimit 15
#   set g_scorelimit 8
#   set g_friendlyfire 0
#
# EXAMPLE  restore.cfg  (defaults / restore)
# ──────────────────
#   set g_timelimit 10
#   set g_scorelimit 50
#   set g_friendlyfire 0
# ──────────────────────────────────────────────────────────────────────────────

import minqlx
import os

class factoryvote(minqlx.Plugin):
    def __init__(self):
        self.version = "1.8"

        # ql_restorecfg_perm - minimum permission level required to use !restorecfg
        # 0 = everyone, 1 = regular, 2 = mod, 3 = admin, 4 = superadmin (default: 2)
        self.set_cvar_once("ql_restorecfg_perm", "2")
        restore_perm = int(self.get_cvar("ql_restorecfg_perm"))

        self.add_command("factoryvote", self.cmd_factoryvote, 0)
        self.add_command("fv",          self.cmd_factoryvote, 0)
        self.add_command("fvv",         self.cmd_version,     0)
        self.add_command("factory",     self.cmd_factory,     0)
        self.add_command("check",       self.cmd_check,       0)
        self.add_command("restorecfg",  self.cmd_restorecfg,  restore_perm)

        self.plugins_dir    = os.path.dirname(os.path.abspath(__file__))
        self.factories      = self.load_factories()
        self.selected_factory = None

        self.add_hook("game_countdown", self.handle_game_countdown)

    # ──────────────────────────────────────────
    # VERSION
    # ──────────────────────────────────────────
    def cmd_version(self, player, msg, channel):
        player.tell("^3FactoryVote Plugin Version:^7 {}".format(self.version))

    # ──────────────────────────────────────────
    # LOAD FACTORIES LIST
    # ──────────────────────────────────────────
    def load_factories(self):
        primary  = os.path.join(self.get_cvar("fs_basepath"), "baseq3", "factories.txt")
        fallback = os.path.join(self.plugins_dir, "factories.txt")

        if os.path.isfile(primary):
            factories_file = primary
            self.logger.info("factories.txt found in baseq3.")
        elif os.path.isfile(fallback):
            factories_file = fallback
            self.logger.info("factories.txt not found in baseq3, using minqlx-plugins folder.")
        else:
            self.logger.warning("factories.txt not found in baseq3 or minqlx-plugins folder.")
            return None

        with open(factories_file, "r") as f:
            factories = [line.strip() for line in f if line.strip()]
        if not factories:
            self.logger.warning("factories.txt is empty.")
        return factories

    # ──────────────────────────────────────────
    # CFG HELPERS
    # ──────────────────────────────────────────
    def cfg_path_for(self, name):
        """Return the full path to <name>.cfg in the plugins directory."""
        return os.path.join(self.plugins_dir, "{}.cfg".format(name))

    def execute_cfg(self, cfg_path):
        """
        Execute every non-blank, non-comment line in cfg_path as a server
        console command.  Returns (lines_run, skipped_lines).
        """
        lines_run = 0
        skipped   = 0
        with open(cfg_path, "r") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("//") or line.startswith("#"):
                    skipped += 1
                    continue
                self.console(line)
                self.logger.info("factoryvote cfg exec: %s", line)
                lines_run += 1
        return lines_run, skipped

    def try_load_factory_cfg(self, factory_name):
        """
        If a matching .cfg exists for factory_name, execute it and announce
        the result to the server.  Returns True if a cfg was found and run.
        """
        cfg = self.cfg_path_for(factory_name)
        if not os.path.isfile(cfg):
            self.logger.info("No cfg found for factory '%s' (looked for %s).", factory_name, cfg)
            return False

        self.msg("^3Loading settings for factory:^7 {} ^3...".format(factory_name))
        lines_run, _ = self.execute_cfg(cfg)
        self.msg("^2Settings applied ({} commands from {}.cfg).".format(lines_run, factory_name))
        self.logger.info("factoryvote: applied %d commands from %s", lines_run, cfg)
        return True

    # ──────────────────────────────────────────
    # RESTORE DEFAULT SETTINGS  (!restorecfg)
    # ──────────────────────────────────────────
    def cmd_restorecfg(self, player, msg, channel):
        """
        Execute restore.cfg from the plugins folder to restore default settings.
        Access is gated by the ql_restorecfg_perm cvar (default: 2 / mod).
        """
        cfg = self.cfg_path_for("restore")
        if not os.path.isfile(cfg):
            player.tell(
                "^1restore.cfg not found in plugins folder. "
                "Create ^7{} ^1to enable this feature.".format(cfg)
            )
            return

        self.msg("^3{} ^7is restoring default server settings...".format(player.name))
        lines_run, _ = self.execute_cfg(cfg)
        self.msg("^2Default settings restored ({} commands from restore.cfg).".format(lines_run))
        self.logger.info("factoryvote: restore.cfg restored by %s (%d commands)", player.name, lines_run)

    # ──────────────────────────────────────────
    # GAME COUNTDOWN HOOK
    # ──────────────────────────────────────────
    def handle_game_countdown(self):
        if self.selected_factory:
            self.msg("^3Game starting with factory:^7 {}".format(self.selected_factory))
        else:
            self.msg("^3Game starting. No factory selected. Using default settings.")

    # ──────────────────────────────────────────
    # !factory  —  show current selection
    # ──────────────────────────────────────────
    def cmd_factory(self, player, msg, channel):
        if self.selected_factory:
            player.tell("^3Current loaded factory:^7 {}".format(self.selected_factory))
        else:
            player.tell("^3No factory has been selected yet.")

    # ──────────────────────────────────────────
    # !check  —  compare plugin vs server state
    # ──────────────────────────────────────────
    def cmd_check(self, player, msg, channel):
        try:
            server_factory = self.game.factory
        except Exception:
            server_factory = None

        if server_factory:
            player.tell("^3Current Factory (server):^7 {}".format(server_factory))
        else:
            player.tell("^1Could not retrieve current factory from server.")

        if self.selected_factory:
            if self.selected_factory.lower() == (server_factory or "").lower():
                player.tell("^2Plugin selected factory matches the server factory.")
            else:
                player.tell(
                    "^3Plugin selected factory:^7 {} ^3(differs from server)".format(self.selected_factory)
                )
        else:
            player.tell("^3No factory selected via plugin yet.")

        # Show whether a cfg exists for the current server factory
        if server_factory:
            cfg = self.cfg_path_for(server_factory)
            if os.path.isfile(cfg):
                player.tell("^2A .cfg file exists for this factory: ^7{}".format(cfg))
            else:
                player.tell("^3No .cfg file found for this factory (^7{}^3).".format(server_factory))

    # ──────────────────────────────────────────
    # !fv / !factoryvote  —  main vote command
    # ──────────────────────────────────────────
    def cmd_factoryvote(self, player, msg, channel):
        if self.factories is None:
            player.tell("^1Error:^7 factories.txt not found in baseq3.")
            return

        if not self.factories:
            player.tell("^1Error:^7 factories.txt is empty.")
            return

        # No argument → list available factories and hint about cfg files
        if len(msg) == 1:
            player.tell("^3Available Factories:")
            for idx, factory in enumerate(self.factories, start=1):
                has_cfg = "^2[cfg]^7" if os.path.isfile(self.cfg_path_for(factory)) else ""
                player.tell("^7{}: {} {}".format(idx, factory, has_cfg))
            player.tell("^3Use ^7!fv <number> ^3to start a vote.")
            player.tell("^3^2[cfg] ^3= factory-specific settings will be applied on vote pass.")
            return

        try:
            selection = int(msg[1])
        except ValueError:
            player.tell("^1Invalid selection. Use a number from the list.")
            return

        if selection < 1 or selection > len(self.factories):
            player.tell("^1Invalid factory number.")
            return

        self.selected_factory = self.factories[selection - 1]
        player.tell("^3You selected factory:^7 {}".format(self.selected_factory))

        # Hint whether settings will be applied
        if os.path.isfile(self.cfg_path_for(self.selected_factory)):
            player.tell(
                "^3A .cfg exists for this factory — settings will be applied if the vote passes."
            )

        vote_text    = "Change map to {} factory?".format(self.selected_factory)
        vote_command = "qlx !map {} {}".format(self.game.map, self.selected_factory)

        self.callvote(vote_command, vote_text)
        minqlx.delay(30)(self.check_vote_result)

    # ──────────────────────────────────────────
    # VOTE RESULT  (called 30 s after callvote)
    # ──────────────────────────────────────────
    def check_vote_result(self):
        if self.game.vote_passed:
            self.msg("^2Vote passed! Loading factory:^7 {}".format(self.selected_factory))

            # Apply factory-specific settings BEFORE the map change
            cfg_applied = self.try_load_factory_cfg(self.selected_factory)
            if not cfg_applied:
                self.msg(
                    "^3No .cfg found for ^7{} ^3— using current server settings.".format(
                        self.selected_factory
                    )
                )

            # Trigger the actual map/factory change
            self.console("map {} {}".format(self.game.map, self.selected_factory))
        else:
            self.msg("^1Vote failed for factory:^7 {}".format(self.selected_factory))
            # Remind admins that settings can be restored if anything changed mid-vote
            if os.path.isfile(self.cfg_path_for("restore")):
                self.msg("^3Tip: Use ^7!restorecfg ^3to restore default server settings.")
