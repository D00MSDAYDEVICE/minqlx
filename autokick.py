# Created by Doomsday, (C)2026
# https://github.com/D00MSDAYDEVICE
# https://www.youtube.com/@HIT-CLIPS

# This is an extension plugin for minqlx to autokick players based on chat
# CVARS:
# qlx_autokickWarnings "1" - offence that triggers the kick (kick/silent modes)
#                            (1 = kick on first offence, 3 = warn twice, kick on third)
# qlx_autokickMode "kick" or "warn" or "silent"
#   kick   - warn in chat, then kick on offence N
#   warn   - always privately warn the player, never kick
#   silent - suppress with no feedback at all, then kick on offence N
# qlx_autokickChatlog "1" - also write moderation events to chatlogs/chat.log
#                           (1 = on, 0 = autokick.log only)

# COMMANDS:
# !addword <word or phrase>
# !delword <word or phrase>
# !listwords (sent privately)
# !reloadpatterns (from your autokick_patterns.txt)

# You can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation,
# either version 3 of the License, or (at your option) any later version.

# You should have received a copy of the GNU General Public License
# along with minqlx. If not, see <http://www.gnu.org/licenses/>.

# You are free to modify this plugin.
# This plugin comes with no warranty or guarantee.


import minqlx
import os
import re
from datetime import datetime

# Quake colour codes (^1, ^7, ...) are stripped before matching so they
# can't be used to split a banned word.
COLOR_CODE = re.compile(r"\^[0-9]")
LIST_WORDS_LIMIT = 50
LIST_PATTERNS_LIMIT = 20

class autokick(minqlx.Plugin):
    def __init__(self):
        self.version = "1.5"
        self.add_command("akv", self.cmd_version, 0)

        # Hooks
        self.add_hook("chat", self.handle_chat)
        self.add_hook("map", self.handle_map_change)

        # Commands
        self.add_command("addword", self.cmd_addword, 5)
        self.add_command("delword", self.cmd_delword, 5)
        self.add_command("listwords", self.cmd_listwords, 5)
        self.add_command("reloadpatterns", self.cmd_reloadpatterns, 5)

        # Log file path (must be set early)
        self.log_path = os.path.join(self.get_minqlx_dir(), "autokick.log")

        # Configurable CVARs
        self.set_cvar_once("qlx_autokickWarnings", "1")
        self.set_cvar_once("qlx_autokickMode", "kick")
        self.set_cvar_once("qlx_autokickChatlog", "1")
        # qlx_autokickMode options:
        #   kick   - warn, then kick on offence N (N = qlx_autokickWarnings)
        #   warn   - suppress message and notify the player, never kick
        #   silent - suppress message with no notification, but still kick
        #            on offence N (N = qlx_autokickWarnings), same as kick mode

        self.reload_cvars()

        # Redis key for literal words
        self.words_key = "minqlx:autokickwords"
        self.banned_words = set(self.db.smembers(self.words_key))

        # Regex patterns file
        self.patterns_file = os.path.join(self.get_minqlx_dir(), "autokick_patterns.txt")
        self.regex_patterns = self.load_regex_patterns()

        # Warning counters per player per map
        self.warnings = {}

        self.log(
            f"[INIT] autokick v{self.version} loaded. Mode: {self.mode} | "
            f"Words: {len(self.banned_words)} | Patterns: {len(self.regex_patterns)} | "
            f"Max warnings: {self.max_warnings}"
        )

    # ------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------

    def get_minqlx_dir(self):
        return os.path.dirname(os.path.abspath(__file__))

    def log(self, message):
        # A failed write must never stop chat filtering or plugin loading.
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(f"[{timestamp}] {message}\n")
        except OSError as e:
            minqlx.get_logger(self).warning("autokick: log write failed: %s", e)

    def chatlog(self, message):
        # Blocked messages never reach the log plugin (the chat hook stops them),
        # so record moderation events in chat.log as well.
        if not self.chatlog_enabled:
            return
        try:
            # Looked up on every call: the log plugin may load after this one.
            log_plugin = self.plugins.get("log")
            if log_plugin is not None and hasattr(log_plugin, "chatlog"):
                # Same logger and handler as the log plugin, so rotation stays correct.
                log_plugin.chatlog.info(self.clean_text(message))
                return
            file_dir = os.path.join(self.get_cvar("fs_homepath"), "chatlogs")
            os.makedirs(file_dir, exist_ok=True)
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(os.path.join(file_dir, "chat.log"), "a", encoding="utf-8") as f:
                f.write(f"[{timestamp}] {self.clean_text(message)}\n")
        except Exception as e:
            minqlx.get_logger(self).warning("autokick: chat.log write failed: %s", e)

    def event(self, message):
        # Moderation outcomes: always in autokick.log, and in chat.log if enabled.
        self.log(message)
        self.chatlog(f"[AUTOKICK] {message}")

    def cmd_version(self, player, msg, channel):
        player.tell("^3AutoKick Plugin Version:^7 {}".format(self.version))

    def reload_cvars(self):
        try:
            self.max_warnings = int(self.get_cvar("qlx_autokickWarnings"))
        except (TypeError, ValueError):
            self.max_warnings = 1
        self.mode = (self.get_cvar("qlx_autokickMode") or "").strip().lower()
        if self.mode not in ("kick", "warn", "silent"):
            self.log(f"[WARN] Unknown mode '{self.mode}', defaulting to 'kick'")
            self.mode = "kick"
        try:
            self.chatlog_enabled = int(self.get_cvar("qlx_autokickChatlog")) != 0
        except (TypeError, ValueError):
            self.chatlog_enabled = True

    # ------------------------------------------------------------
    # Pattern Loading
    # ------------------------------------------------------------

    def load_regex_patterns(self):
        patterns = []
        if not os.path.exists(self.patterns_file):
            self.log(f"[INFO] No regex file found at {self.patterns_file}")
            return patterns

        with open(self.patterns_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                try:
                    if line.lower().startswith("(?i)"):
                        regex = re.compile(line[4:], re.IGNORECASE)
                    else:
                        regex = re.compile(line, re.IGNORECASE)
                    patterns.append(regex)
                except re.error as e:
                    self.log(f"[ERROR] Invalid regex in file: '{line}' -> {e}")
        self.log(f"[LOAD] Loaded {len(patterns)} regex patterns from file.")
        return patterns

    # ------------------------------------------------------------
    # Event Hooks
    # ------------------------------------------------------------

    def handle_map_change(self, mapname, factory):
        self.warnings.clear()
        self.log(f"[MAP] Changed to {mapname}, cleared warnings.")
        self.reload_cvars()

    def handle_chat(self, player, msg, channel):
        if not msg or player.steam_id == 0:
            return

        # Match first, so clean chat costs no DB lookup and no disk write.
        trigger = self.find_trigger(msg)
        if trigger is None:
            return

        if self.is_admin(player):
            return

        self.event(f"[MATCH] {player.name} ({player.steam_id}) matched '{trigger}': {msg}")
        self.process_violation(player, trigger)
        return minqlx.RET_STOP_ALL  # Always suppress the message

    def find_trigger(self, msg):
        clean_msg = COLOR_CODE.sub("", msg)
        lower_msg = clean_msg.lower()

        for word in self.banned_words:
            if word in lower_msg:
                return word

        for pattern in self.regex_patterns:
            if pattern.search(clean_msg):
                return pattern.pattern

        return None

    def is_admin(self, player):
        try:
            return self.db.get_permission(player.steam_id) >= 5
        except Exception as e:
            self.log(f"[WARN] Permission check failed for {player.name}: {e}")
            return False

    # ------------------------------------------------------------
    # Violation Handling
    # ------------------------------------------------------------

    def process_violation(self, player, trigger):
        sid = player.steam_id

        if self.mode == "silent":
            # Suppress with no feedback at all, but still escalate to a kick
            # after qlx_autokickWarnings offences, same threshold as kick mode.
            count = self.warnings.get(sid, 0) + 1
            self.warnings[sid] = count

            if count < self.max_warnings:
                self.event(f"[SILENT] {player.name}'s message suppressed for '{trigger}' "
                            f"({count}/{self.max_warnings})")
            else:
                self.kick_player(player, trigger)
                self.event(f"[SILENT-KICK] {player.name} kicked after {count} warnings for '{trigger}'")
                del self.warnings[sid]
            return

        if self.mode == "warn":
            # Suppress and privately notify the player only, never kick
            player.tell("^1Your message was blocked^7: inappropriate language is not allowed.")
            self.event(f"[SUPPRESS] {player.name}'s message suppressed for '{trigger}'")
            return

        # Default: kick mode — warn N times then kick
        count = self.warnings.get(sid, 0) + 1
        self.warnings[sid] = count

        if count < self.max_warnings:
            self.msg(f"^3Warning to {player.name}: ^7Inappropriate language detected.")
            self.event(f"[WARN] {player.name} warned ({count}/{self.max_warnings}) for '{trigger}'")
        else:
            self.msg(f"^1Player ^7{player.name} ^1was kicked for inappropriate language.")
            self.kick_player(player, trigger)
            self.event(f"[KICK] {player.name} kicked after {count} warnings for '{trigger}'")
            del self.warnings[sid]

    def kick_player(self, player, trigger):
        try:
            player.kick("Inappropriate language")
        except Exception as e:
            self.log(f"[ERROR] Failed to kick {player.name}: {e}")

    # ------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------

    def cmd_addword(self, player, msg, channel):
        if len(msg) < 2:
            return minqlx.RET_USAGE
        word = " ".join(msg[1:]).lower().strip()
        if not word:
            return minqlx.RET_USAGE
        if word in self.banned_words:
            return channel.reply(f"^3'{word}'^7 already banned.")
        self.db.sadd(self.words_key, word)
        self.banned_words.add(word)
        channel.reply(f"^2Added banned word:^7 {word}")
        self.event(f"[CMD] {player.name} added word '{word}'")

    def cmd_delword(self, player, msg, channel):
        if len(msg) < 2:
            return minqlx.RET_USAGE
        word = " ".join(msg[1:]).lower().strip()
        if word not in self.banned_words:
            return channel.reply(f"^3'{word}'^7 not in list.")
        self.db.srem(self.words_key, word)
        self.banned_words.remove(word)
        channel.reply(f"^1Removed banned word:^7 {word}")
        self.event(f"[CMD] {player.name} removed word '{word}'")

    def cmd_listwords(self, player, msg, channel):
        # Sent privately so the list is never shown to the whole server.
        words = sorted(self.banned_words)
        patterns = [r.pattern for r in self.regex_patterns]
        if not words and not patterns:
            player.tell("^7No banned words or regex patterns set.")
            return
        if words:
            player.tell("^3Words:^7 " + ", ".join(words[:LIST_WORDS_LIMIT]))
        if patterns:
            player.tell("^3Regex:^7 " + ", ".join(patterns[:LIST_PATTERNS_LIMIT]))
        if len(words) > LIST_WORDS_LIMIT or len(patterns) > LIST_PATTERNS_LIMIT:
            player.tell(f"^7Showing the first {LIST_WORDS_LIMIT} words and {LIST_PATTERNS_LIMIT} patterns "
                        f"({len(words)} words, {len(patterns)} patterns total).")
        self.log(f"[CMD] {player.name} listed banned entries.")

    def cmd_reloadpatterns(self, player, msg, channel):
        self.regex_patterns = self.load_regex_patterns()
        self.reload_cvars()
        channel.reply(
            f"^2Reloaded {len(self.regex_patterns)} regex patterns. "
            f"Mode: {self.mode} | Max warnings: {self.max_warnings}"
        )
        self.event(f"[CMD] {player.name} reloaded regex patterns.")
