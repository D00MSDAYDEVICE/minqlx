# Created by Thomas Jones on 14/12/2015 - thomas@tomtecsolutions.com
# aliases.py, a plugin for minqlx to show aliases from the redis database.
# This plugin is released to everyone, for any purpose. It comes with no warranty, no guarantee it works, it's released AS IS.
# You can modify everything, except for lines 1-4 and the !tomtec_versions code. They're there to indicate I whacked this together originally. Please make it better :D
#
# Modified by Doomsday using AI for performance, chunking, and result limiting.
# Added:
# set qlx_aliasesmode "limit"     // limit mode
# set qlx_aliasesmode "chunk"     // chunk mode
# set qlx_limitresults "10"       // limit mode: max # of names/IDs returned
# set qlx_chunktime "500"         // chunk mode: delay in ms between chunks

import minqlx
import minqlx.database


class aliasesplus(minqlx.Plugin):
    database = minqlx.database.Redis

    def __init__(self):
        self.add_command("alias", self.cmd_alias, usage="<id>")
        self.add_command("clearaliases", self.cmd_clearaliases, 5)
        self.add_command("tomtec_versions", self.cmd_showversion)

        # CVARs for output behavior
        self.set_cvar_once("qlx_aliasesmode", "limit")    # limit or chunk
        self.set_cvar_once("qlx_limitresults", "10")      # number of results to show
        self.set_cvar_once("qlx_chunktime", "500")        # delay in ms between chunk sends

        self.plugin_version = "1.0"

    # ----------------------------------------------------------------------
    # Helper: send large lists in chunks to avoid game thread freeze
    # ----------------------------------------------------------------------
    def send_in_chunks(self, items, channel, chunk_size=10):
        delay_ms = self.get_cvar("qlx_chunktime", int)

        for i in range(0, len(items), chunk_size):
            chunk = items[i:i + chunk_size]
            msg = " ^4*^7  " + "\n ^4*^7  ".join(chunk)

            minqlx.delay((delay_ms * (i // chunk_size)) / 1000, channel.reply, msg)

    # ----------------------------------------------------------------------
    # Main alias command
    # ----------------------------------------------------------------------
    def cmd_alias(self, player, msg, channel):
        if len(msg) < 2:
            return minqlx.RET_USAGE

        try:
            ident = int(msg[1])
            if 0 <= ident < 64:
                target = self.player(ident)
                steam_id = target.steam_id
                player_name = target.name
                ip_address = target.ip
            else:
                # SteamID64 given directly
                steam_id = ident
                player_name = str(steam_id)
                iplist = list(self.db.smembers(f"minqlx:players:{steam_id}:ips"))
                ip_address = iplist[-1] if iplist else None
        except ValueError:
            channel.reply("Invalid ID. Use client ID or SteamID64.")
            return
        except minqlx.NonexistentPlayerError:
            channel.reply("Invalid client ID. Use client ID or SteamID64.")
            return

        if not ip_address:
            channel.reply("No alias information found.")
            return

        # Get all Steam IDs used on this IP
        steamid_iplist = list(self.db.smembers(f"minqlx:ips:{ip_address}"))

        # Collect all names for each SteamID
        namelist = []
        for sid in steamid_iplist:
            names = list(self.db.lrange(f"minqlx:players:{sid}", 0, -1))
            namelist.extend(names)

        # Output mode:
        mode = self.get_cvar("qlx_aliasesmode").lower()
        limit = self.get_cvar("qlx_limitresults", int)

        channel.reply(f"{player_name}^7 has used the following names:")

        # ------------------------------
        # LIMIT MODE
        # ------------------------------
        if mode == "limit":
            limited_names = namelist[-limit:]
            limited_ids = steamid_iplist[-limit:]

            if limited_names:
                channel.reply(" ^4*^7  " + "\n ^4*^7  ".join(limited_names))
            else:
                channel.reply("^7(No recorded names.)")

            channel.reply(f"{player_name}^7 has used the following Steam64 IDs:")
            if limited_ids:
                channel.reply(" ^4*^7  " + "\n ^4*^7  ".join(limited_ids))
            else:
                channel.reply("^7(No recorded IDs.)")

            return

        # ------------------------------
        # CHUNK MODE
        # ------------------------------
        elif mode == "chunk":
            if namelist:
                self.send_in_chunks(namelist, channel)
            else:
                channel.reply("^7(No recorded names.)")

            channel.reply(f"{player_name}^7 has used the following Steam64 IDs:")
            if steamid_iplist:
                self.send_in_chunks(steamid_iplist, channel)
            else:
                channel.reply("^7(No recorded IDs.)")

            return

        # ------------------------------
        # Invalid CVAR → fallback to limit
        # ------------------------------
        else:
            channel.reply("^1Invalid qlx_aliasesmode. Use ^7limit^1 or ^7chunk^1.")
            return

    # ----------------------------------------------------------------------
    # Clear alias database (unchanged)
    # ----------------------------------------------------------------------
    def cmd_clearaliases(self, player, msg, channel):
        players = self.db.smembers("minqlx:players")
        for p in players:
            del self.db[f"minqlx:players:{p}"]
        channel.reply(f"Cleared all aliases for {len(players)} players.")

    def cmd_showversion(self, player, msg, channel):
        channel.reply(f"^4aliases.py^7 - version {self.plugin_version}")
