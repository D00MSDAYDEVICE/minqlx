# Copyright (C) 2025 Doomsday
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

import minqlx
import os
import time

class factoryvote(minqlx.Plugin):
    def __init__(self):
        self.version = "1.1"  # Set your version number here
        self.add_command("factoryvote", self.cmd_factoryvote, 3)  # Admin level 3
        self.add_command("fv", self.cmd_factoryvote, 3)           # Shortcut
        self.add_command("fvv", self.cmd_version, 3)              # New command for version display

        self.factories = self.load_factories()
        self.selected_factory = None  # Store the chosen factory
        self.add_hook("game_countdown", self.handle_game_countdown)  # Hook for countdown message
    
    def cmd_version(self, player, msg, channel):
        player.tell("^3FactoryVote Plugin Version:^7 {}".format(self.version))

    def load_factories(self):
        factories_file = os.path.join(self.get_cvar("fs_basepath"), "baseq3", "factories.txt")
        if not os.path.isfile(factories_file):
            self.logger.warning("factories.txt not found in baseq3.")
            return None  # File not found
        with open(factories_file, "r") as f:
            factories = [line.strip() for line in f if line.strip()]
        if not factories:
            self.logger.warning("factories.txt is empty.")
        return factories

    def handle_game_countdown(self):
        if self.selected_factory:
            self.msg("^2Game starting with factory:^7 {}".format(self.selected_factory))
        else:
            self.msg("^2Game starting. No factory selected. Using default settings.")

    def cmd_factoryvote(self, player, msg, channel):
        if self.factories is None:
            player.tell("^1Error:^7 factories.txt not found in baseq3.")
            return

        if not self.factories:
            player.tell("^1Error:^7 factories.txt is empty.")
            return

        if len(msg) == 1:
            player.tell("^3Available Factories:")
            for idx, factory in enumerate(self.factories, start=1):
                player.tell("^7{}: {}".format(idx, factory))
            player.tell("^3Use ^7!fv <number> ^3to start a vote.")
            return

        try:
            selection = int(msg[1])
        except ValueError:
            player.tell("^1Invalid selection. Use a number from the list.")
            return

        if selection < 1 or selection > len(self.factories):
            player.tell("^1Invalid factory number.")
            return

        self.selected_factory = self.factories[selection - 1]  # Store chosen factory
        player.tell("^6You selected factory:^7 {}".format(self.selected_factory))
        self.msg("^6Starting vote to load current map with factory:^7 {}".format(self.selected_factory))
        self.callvote("qlx !map {} {}".format(self.game.map, self.selected_factory), "Change map to selected factory")

        minqlx.delay(30, self.check_vote_result)

    def check_vote_result(self):
        if self.game.vote_passed:
            self.msg("^2Vote passed! Loading factory:^7 {}".format(self.selected_factory))
            self.command("qlx !map {} {}".format(self.game.map, self.selected_factory))
        else:
            self.msg("^1Vote failed for factory:^7 {}".format(self.selected_factory))
