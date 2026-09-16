# votebanplus.py is a plugin for minqlx that permanently stops a player
# from being able to call votes on the server, until an admin removes the
# ban.
#
# This plugin merges two existing vote-ban plugins for stability and simplicity:
#  - voteban.py by BarelyMiSSeD (id/steam id resolution, protected
#    permission tier, a list command)
#  - banvote (voteban.py) by kanzo / cstewart90 (minimal, Redis-backed
#    ban/unban via a persistent Plugin.database)
#
# Design notes / changes from both originals:
#  - Storage is Redis only, via a single hash (steam_id -> display name)
#    rather than a flat file, a zset, or a set - this keeps the ban
#    permanent-until-removed while still letting !listvotebans show names.
#  - There is no in-memory cache of who is banned (the old voteban.py kept
#    a self.voteban list that had to be kept in sync with storage and had
#    a couple of bugs doing so). handle_vote_called checks Redis directly,
#    which is simpler and can't drift out of sync.
#  - No ban duration/expiry, no reason field, and no version-check
#  - hset/hexists/hdel/hgetall are used instead of hmset/zadd, which avoids
#    the redis-py 2.x/3.x signature differences those calls are prone to.
#    So this should work on old and new servers/python versions
"""
Set this cvar in your server.cfg (or wherever you set your minqlx cvars):
qlx_votebanplusAdmin "3" - minqlx permission level required to use the
                    !voteban, !voteunban and !listvotebans/!votebanlist
                    commands.

The protection level (a player's minqlx permission level at or above which
they can never be vote-banned) is hardcoded to 3 and is not configurable.
"""

import minqlx
import minqlx.database

BANVOTE_KEY = "minqlx:votebanplus:banned"
PLAYER_KEY = "minqlx:players:{}"
PROTECTION_LEVEL = 3
MAX_LIST_DISPLAY = 50


class votebanplus(minqlx.Plugin):
    database = minqlx.database.Redis

    def __init__(self):
        super().__init__()
        self.add_hook("vote_called", self.handle_vote_called, priority=minqlx.PRI_HIGH)

        self.set_cvar_once("qlx_votebanplusAdmin", "3")
        admin_level = int(self.get_cvar("qlx_votebanplusAdmin"))

        self.add_command("voteban", self.cmd_voteban, admin_level, usage="<id> [name]")
        self.add_command("voteunban", self.cmd_voteunban, admin_level, usage="<id>")
        self.add_command(("listvotebans", "votebanlist"), self.cmd_list_votebans, admin_level)

    def handle_vote_called(self, player, vote, args):
        """Stops a vote-banned player from calling a vote."""
        if self.db.hexists(BANVOTE_KEY, player.steam_id):
            # Still allow a lone player to call a vote (e.g. to change the
            # map on an otherwise empty server) - only block it once there
            # is someone else around to be annoyed by it.
            if len(self.teams()["free"] + self.teams()["red"] + self.teams()["blue"]) > 1:
                player.tell("^1You are not permitted to callvote on this server.")
                return minqlx.RET_STOP_ALL

    def cmd_voteban(self, player, msg, channel):
        """Vote-bans a player permanently, by client id or SteamID64."""
        if len(msg) < 2:
            return minqlx.RET_USAGE

        steam_id, name = self.resolve_player(msg[1], channel)
        if steam_id is None:
            return minqlx.RET_STOP_EVENT

        if len(msg) > 2:
            name = " ".join(msg[2:])
        if not name:
            name = self.lookup_name(steam_id)
        display_name = name or str(steam_id)

        if self.db.has_permission(steam_id, PROTECTION_LEVEL):
            channel.reply("^7{}^3 has permission level {} or higher and cannot be vote-banned."
                           .format(display_name, PROTECTION_LEVEL))
            return minqlx.RET_STOP_EVENT

        if self.db.hexists(BANVOTE_KEY, steam_id):
            channel.reply("^7{}^3 is already vote-banned.".format(display_name))
            return minqlx.RET_STOP_EVENT

        self.db.hset(BANVOTE_KEY, steam_id, name or "Unknown")
        channel.reply("^7{}^1 has been banned from voting.".format(display_name))
        return minqlx.RET_STOP_EVENT

    def cmd_voteunban(self, player, msg, channel):
        """Removes a player's vote ban."""
        if len(msg) < 2:
            return minqlx.RET_USAGE

        steam_id, name = self.resolve_player(msg[1], channel)
        if steam_id is None:
            return minqlx.RET_STOP_EVENT

        if not name:
            name = self.lookup_name(steam_id)
        display_name = name or str(steam_id)

        if self.db.hexists(BANVOTE_KEY, steam_id):
            self.db.hdel(BANVOTE_KEY, steam_id)
            channel.reply("^7{}^2 is no longer banned from voting.".format(display_name))
        else:
            channel.reply("^7{}^3 is not banned from voting.".format(display_name))
        return minqlx.RET_STOP_EVENT

    def cmd_list_votebans(self, player, msg, channel):
        """Lists everyone currently vote-banned."""
        banned = self.db.hgetall(BANVOTE_KEY)
        if not banned:
            channel.reply("^3No one is currently banned from voting.")
            return minqlx.RET_STOP_EVENT

        entries = sorted(banned.items(), key=lambda kv: int(kv[0]))
        lines = ["^5Vote-banned players^7 ({}):" .format(len(entries))]
        for steam_id, stored_name in entries[:MAX_LIST_DISPLAY]:
            current_name = self.lookup_connected_name(steam_id)
            lines.append(" ^7SteamID ^1{}^7: ^3{}".format(steam_id, current_name or stored_name or "Unknown"))
        if len(entries) > MAX_LIST_DISPLAY:
            lines.append("^7...and {} more.".format(len(entries) - MAX_LIST_DISPLAY))

        channel.reply("\n".join(lines))
        return minqlx.RET_STOP_EVENT

    def resolve_player(self, ident, channel):
        """Resolves a client id or SteamID64 to (steam_id, name).

        Returns (None, None) and replies with an error if ident is invalid.
        """
        try:
            ident = int(ident)
        except ValueError:
            channel.reply("^3Invalid ID. Use either a client ID or a SteamID64.")
            return None, None

        if 0 <= ident <= 63:
            try:
                target_player = self.player(ident)
            except minqlx.NonexistentPlayerError:
                target_player = None
            if not target_player:
                channel.reply("^3There is no one on the server using that Client ID.")
                return None, None
            return int(target_player.steam_id), target_player.name

        if len(str(ident)) != 17:
            channel.reply("^3The SteamID64 given needs to be 17 digits in length.")
            return None, None

        return ident, None

    def lookup_name(self, steam_id):
        """Best-effort name lookup: currently connected, then minqlx's stored name history."""
        return self.lookup_connected_name(steam_id) or self.lookup_stored_name(steam_id)

    def lookup_connected_name(self, steam_id):
        for p in self.players():
            if int(p.steam_id) == int(steam_id):
                return p.name
        return None

    def lookup_stored_name(self, steam_id):
        try:
            name = self.db.lindex(PLAYER_KEY.format(steam_id), 0)
            return name if name else None
        except Exception as e:
            self.logger.debug("votebanplus: name history lookup failed for {}: {}".format(steam_id, e))
            return None
