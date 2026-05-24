# Copyright (C) 2026 Doomsday
# mapmanager.py — minqlx plugin for dynamic map rotation management
#
# Replaces lastmaps.py with extended functionality:
#   - Sequential map rotation from mappool.txt
#   - Blocks recently played maps from end-of-game votes and callvotes
#   - Tracks last N played maps (configurable via cvar)
#   - Off-pool maps (won via callvote) are tracked in history and blocked equally
#   - !lm / !lastmaps, !mappool, !skipmaps (admin), !resetrotation (admin)
#
# You can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation,
# either version 3 of the License, or (at your option) any later version.
#
# Created by Doomsday
# https://github.com/D00MSDAYDEVICE
# https://www.youtube.com/@HIT-CLIPS

import minqlx
import time
import os

MAPPOOL_PATH = "/home/ql/qlds-27960/baseq3/mappool.txt"

# ---------------------------------------------------------------------------
# Cvars (set in server.cfg or via rcon)
#
#   mapmanager_history_size   — how many recent maps to block        (default 5)
#   mapmanager_mappool        — path to mappool.txt                  (default above)
#   mapmanager_vote_maps      — how many maps offered at vote        (default 3)
#   mapmanager_allownewvotes  — allow callvote map after a map vote
#                               already passed this round  1=yes 0=no (default 1)
# ---------------------------------------------------------------------------


class mapmanager(minqlx.Plugin):
    def __init__(self):
        self.version = "1.2.3"

        # ── cvars ──────────────────────────────────────────────────────────
        self.set_cvar_once("mapmanager_history_size", "5")
        self.set_cvar_once("mapmanager_mappool",      MAPPOOL_PATH)
        self.set_cvar_once("mapmanager_vote_maps",     "3")
        self.set_cvar_once("mapmanager_allownewvotes", "1")

        # ── hooks ──────────────────────────────────────────────────────────
        self.add_hook("map",          self.on_map_load)
        self.add_hook("game_end",     self.on_game_end)
        self.add_hook("vote_called",  self.on_vote_called)
        self.add_hook("vote_ended",   self.on_vote_ended)

        # ── commands ───────────────────────────────────────────────────────
        self.add_command(("lastmaps", "lm"),    self.cmd_lastmaps)
        self.add_command("mappool",             self.cmd_mappool)
        self.add_command("skipmaps",            self.cmd_skipmaps,      5)  # admin
        self.add_command("resetrotation",       self.cmd_resetrotation, 5)  # admin
        self.add_command("mmv",                 self.cmd_version,       5)  # admin
        self.add_command("mmdebug",             self.cmd_mmdebug,       5)  # admin

        # ── state ──────────────────────────────────────────────────────────
        self.map_history      = []   # most-recently played at the end
        self.off_pool_maps    = set()# maps ever played that are not in mappool.txt
        self.current_map      = None
        self.map_start_time   = None
        self.rotation_index   = 0    # pointer into self.pool
        self.pool             = []   # list of map names from mappool.txt
        self.pending_vote_map = None # map name that just won a vote (may be off-pool)
        self._game_end_fired  = False
        self._vote_passed     = False  # a map vote already passed this round

        # ── boot ───────────────────────────────────────────────────────────
        self._reload_pool()
        # Seed current map from the server without waiting for the next hook
        current = self.game.map.lower() if self.game else None
        if current:
            self.current_map    = current
            self.map_start_time = time.time()
            self._sync_rotation_to(current)

    # ═══════════════════════════════════════════════════════════════════════
    # Pool helpers
    # ═══════════════════════════════════════════════════════════════════════

    def _reload_pool(self):
        """Parse mappool.txt and populate self.pool."""
        path = self.get_cvar("mapmanager_mappool")
        self.msg("^6[mapmanager] ^7Loading mappool from: ^3{}".format(path))
        if not path:
            self.msg("^1[mapmanager] ^7mapmanager_mappool cvar is not set.")
            self.pool = []
            return
        if not os.path.isfile(path):
            self.msg("^1[mapmanager] ^7mappool.txt not found at: ^3{}^7 — "
                     "check mapmanager_mappool cvar.".format(path))
            self.pool = []
            return

        maps = []
        try:
            with open(path, "r") as f:
                for raw in f:
                    line = raw.strip()
                    # Skip blank lines and comments
                    if not line or line.startswith("//") or line.startswith("#"):
                        continue
                    # mappool lines: campgrounds|ca  or  mapname gametype  or  mapname
                    # Split on | first to discard factory, then grab the first word.
                    mapname = line.split("|")[0].strip()
                    if mapname:
                        maps.append(mapname.split()[0].lower())
        except Exception as e:
            self.msg("^1[mapmanager] ^7Error reading mappool.txt: {}".format(e))
            self.pool = []
            return

        self.pool = maps
        self.msg("^6[mapmanager] ^7Loaded ^2{}^7 maps from mappool: {}".format(
            len(self.pool), ", ".join(self.pool[:5]) + (" ..." if len(self.pool) > 5 else "")
        ))

    def _sync_rotation_to(self, mapname):
        """Point rotation_index to the slot AFTER mapname (so next 3 are upcoming).
        If mapname is not in the pool the pointer is left unchanged and a notice
        is logged — the rotation simply continues from where it was."""
        if not self.pool:
            return
        name = mapname.lower()
        for i, m in enumerate(self.pool):
            if m == name:
                self.rotation_index = (i + 1) % len(self.pool)
                return
        # Map not in pool — rotation pointer stays put
        self.msg("^6[mapmanager] ^3{} ^7is not in mappool.txt — "
                 "rotation pointer unchanged.".format(name))

    def _upcoming_maps(self, count=None):
        """Return the next `count` maps from the rotation, skipping blocked ones."""
        if count is None:
            count = int(self.get_cvar("mapmanager_vote_maps") or 3)
        if not self.pool:
            return []

        blocked  = set(self._blocked_maps())
        upcoming = []
        idx      = self.rotation_index
        checked  = 0

        while len(upcoming) < count and checked < len(self.pool):
            candidate = self.pool[idx % len(self.pool)]
            if candidate not in blocked:
                upcoming.append(candidate)
            idx    += 1
            checked += 1

        return upcoming

    def _history_size(self):
        try:
            return max(1, int(self.get_cvar("mapmanager_history_size") or 5))
        except (ValueError, TypeError):
            return 5

    def _blocked_maps(self):
        """Maps that cannot be voted for right now."""
        return set(self.map_history[-self._history_size():])

    # ═══════════════════════════════════════════════════════════════════════
    # Hooks
    # ═══════════════════════════════════════════════════════════════════════

    def on_map_load(self, mapname, factory):
        self.current_map      = mapname.lower()
        self.map_start_time   = time.time()
        self._game_end_fired  = False
        self._vote_passed     = False  # a map vote already passed this round
        self.pending_vote_map = None

        # Advance the rotation pointer to sit after the new current map
        self._sync_rotation_to(self.current_map)

        # Fallback: if game_end never fires (e.g. server crash / rcon map change),
        # record this map after 5 minutes anyway.
        minqlx.delay(300)(self._maybe_record_map)

    def on_game_end(self, data):
        self._game_end_fired = True
        self._record_current_map()

    def on_vote_called(self, player, vote, args):
        """Intercept map callvotes and block recently played maps.

        Also blocks new map votes when mapmanager_allownewvotes is 0
        and a map vote has already passed this round.
        """
        if vote.lower() != "map":
            return

        if not args:
            return

        # Block follow-up map votes if the cvar disallows them
        if self._vote_passed:
            try:
                allow = int(self.get_cvar("mapmanager_allownewvotes") or 1)
            except (ValueError, TypeError):
                allow = 1
            if not allow:
                player.tell(
                    "^1A map vote has already passed this round. "
                    "No further map votes are allowed until the next map."
                )
                return minqlx.RET_STOP_ALL

        # Strip |factory suffix if present (e.g. "campgrounds|ca" -> "campgrounds")
        requested = args.lower().strip().split("|")[0].strip()
        blocked   = self._blocked_maps()

        if requested in blocked:
            player.tell(
                "^1{} ^7was played recently and is not available yet. "
                "It will be available after {} more map(s).".format(
                    requested,
                    self._maps_until_available(requested)
                )
            )
            return minqlx.RET_STOP_ALL

        # Map is allowed — let the vote proceed
        return

    def on_vote_ended(self, votes, vote, args, passed):
        """Track which map won a vote.

        If the winning map is NOT in mappool.txt we record it into the history
        immediately (before on_map_load fires) so that a rapid follow-up
        callvote for the same map is blocked, and we flag it as off-pool.
        """
        if not passed:
            return
        if vote.lower() != "map":
            return
        if not args:
            return

        # args may arrive as "campgrounds|ca" (raw mappool entry) or plain "campgrounds"
        won_map = args.lower().strip().split("|")[0].strip()
        self.pending_vote_map = won_map
        self._vote_passed     = True  # flag: a map vote passed this round

        if won_map not in self.pool:
            # Off-pool map won a callvote — mark it and pre-record it
            self.off_pool_maps.add(won_map)
            self.msg("^6[mapmanager] ^3{} ^7is not in mappool.txt but won a "
                     "callvote — adding to history.".format(won_map))
            # Pre-record as if it were the current map so blocking kicks in
            # immediately.  on_map_load will call _record_current_map() again
            # but the duplicate-guard will skip it.
            prev = self.current_map
            self.current_map = won_map
            self._record_current_map()
            self.current_map = prev  # restore so on_map_load sets it cleanly

    # ═══════════════════════════════════════════════════════════════════════
    # History helpers
    # ═══════════════════════════════════════════════════════════════════════

    def _maybe_record_map(self):
        """Called 5 minutes after map load as a fallback if game_end didn't fire."""
        if not self._game_end_fired:
            self._record_current_map()

    def _record_current_map(self):
        if not self.current_map:
            return
        # Avoid duplicating the last entry
        if self.map_history and self.map_history[-1] == self.current_map:
            return

        self.map_history.append(self.current_map)

        # Keep enough history that changing the cvar retroactively still works
        max_keep = max(self._history_size(), 20)
        if len(self.map_history) > max_keep:
            self.map_history = self.map_history[-max_keep:]

        off_pool_tag = " ^3[off-pool]^7" if self.current_map in self.off_pool_maps else ""
        self.msg("^6[mapmanager] ^7Map recorded: ^2{}^7{}. History (last {}): {}".format(
            self.current_map,
            off_pool_tag,
            self._history_size(),
            ", ".join(self.map_history[-self._history_size():])
        ))

    def _maps_until_available(self, mapname):
        """How many more maps need to play before `mapname` exits the block window."""
        size = self._history_size()
        recent = self.map_history[-size:]
        # Find earliest position in recent; it becomes available after it ages out
        for i, m in enumerate(recent):
            if m == mapname:
                return size - i
        return 0

    # ═══════════════════════════════════════════════════════════════════════
    # Commands
    # ═══════════════════════════════════════════════════════════════════════

    def cmd_lastmaps(self, player, msg, channel):
        """!lm / !lastmaps — show recently played maps."""
        size    = self._history_size()
        recent  = self.map_history[-size:]
        blocked = self._blocked_maps()

        if not recent:
            player.tell("^1No maps have been tracked since server restart.")
            return

        parts = []
        for m in recent:
            off_tag = "^8*^7" if m in self.off_pool_maps else ""
            if m in blocked:
                parts.append("^1{}{}^7".format(m, off_tag))   # red = blocked
            else:
                parts.append("^2{}{}^7".format(m, off_tag))   # green = available
        player.tell(
            "^6Last {} maps:^7 {}  "
            "^8(^1red^8=blocked ^2green^8=available ^8*^8=off-pool)".format(
                size, ", ".join(parts)
            )
        )

    def cmd_mappool(self, player, msg, channel):
        """!mappool — show the next maps in rotation and their block status."""
        upcoming = self._upcoming_maps(count=10)
        blocked  = self._blocked_maps()

        if not self.pool:
            player.tell("^1No mappool loaded.")
            return

        lines = ["^6Upcoming rotation^7 (blocked maps are skipped):"]

        if self.current_map and self.current_map in self.off_pool_maps:
            lines.append(
                "^3Note: ^7current map ^3{}^7 is off-pool — "
                "rotation pointer was not advanced.".format(self.current_map)
            )

        if not upcoming:
            lines.append("^1All upcoming pool maps are blocked by recent history. "
                         "Consider reducing ^3mapmanager_history_size^1.")
            player.tell("\n".join(lines))
            return

        count = int(self.get_cvar("mapmanager_vote_maps") or 3)
        for i, m in enumerate(upcoming):
            marker = "^3[vote {}]^7 ".format(i + 1) if i < count else "       "
            lines.append("  {}{}".format(marker, m))

        player.tell("\n".join(lines))

    def cmd_skipmaps(self, player, msg, channel):
        """!skipmaps [n] — advance the rotation pointer by n steps (admin)."""
        if not self.pool:
            player.tell("^1No mappool loaded.")
            return

        n = 1
        if len(msg) > 1:
            try:
                n = int(msg[1])
            except ValueError:
                player.tell("^1Usage: ^7!skipmaps [number]")
                return

        self.rotation_index = (self.rotation_index + n) % len(self.pool)
        upcoming = self._upcoming_maps()
        player.tell("^6[mapmanager] ^7Skipped {} slot(s). Next maps: ^2{}".format(
            n, ", ".join(upcoming) if upcoming else "^1none available"
        ))

    def cmd_resetrotation(self, player, msg, channel):
        """!resetrotation — reload mappool.txt and reset pointer to 0 (admin)."""
        self._reload_pool()
        self.rotation_index = 0
        if self.current_map:
            self._sync_rotation_to(self.current_map)
        player.tell("^6[mapmanager] ^7Rotation reset. Pool has ^2{}^7 maps.".format(
            len(self.pool)
        ))

    def cmd_mmdebug(self, player, msg, channel):
        """!mmdebug — dump pool contents and current state for diagnostics (admin)."""
        player.tell("^6[mapmanager debug]^7 version: ^2{}".format(self.version))
        player.tell("^6mapmanager_mappool cvar:^7 ^3{}".format(
            self.get_cvar("mapmanager_mappool") or "^1(not set)"
        ))
        player.tell("^6pool ({} maps):^7 {}".format(
            len(self.pool), ", ".join(self.pool) if self.pool else "^1empty"
        ))
        player.tell("^6rotation_index:^7 {} -> next pool entry: ^2{}".format(
            self.rotation_index,
            self.pool[self.rotation_index % len(self.pool)] if self.pool else "^1n/a"
        ))
        player.tell("^6off_pool_maps:^7 {}".format(
            ", ".join(sorted(self.off_pool_maps)) if self.off_pool_maps else "none"
        ))
        player.tell("^6map_history:^7 {}".format(
            ", ".join(self.map_history) if self.map_history else "none"
        ))
        player.tell("^6_vote_passed:^7 {}  ^6_game_end_fired:^7 {}".format(
            self._vote_passed, self._game_end_fired
        ))

    def cmd_version(self, player, msg, channel):
        player.tell("^3mapmanager ^7v{}".format(self.version))
