import minqlx
import os
import re
from datetime import datetime

class autokick(minqlx.Plugin):
    def __init__(self):
        # Hooks
        self.add_hook("chat", self.handle_chat)
        self.add_hook("map", self.handle_map_change)

        # Commands
        self.add_command("addword", self.cmd_addword, 5)
        self.add_command("delword", self.cmd_delword, 5)
        self.add_command("listwords", self.cmd_listwords, 5)
        self.add_command("reloadpatterns", self.cmd_reloadpatterns, 5)
        
        self.log_path = os.path.join(self.get_minqlx_dir(), "autokick.log")

        # Redis key for literal words
        self.words_key = "minqlx:autokickwords"
        self.banned_words = set(self.db.smembers(self.words_key))

        # Regex patterns file
        self.patterns_file = os.path.join(self.get_minqlx_dir(), "autokick_patterns.txt")
        self.regex_patterns = self.load_regex_patterns()

        # One warning per player per map
        self.warnings = {}

        # Log init summary
        self.log(f"[INIT] autokick loaded. Words: {len(self.banned_words)} | Patterns: {len(self.regex_patterns)}")

    # ------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------

    def get_minqlx_dir(self):
        return os.path.dirname(os.path.abspath(__file__))

    def log(self, message):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {message}\n")

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
                    # Respect case-insensitive flag (?i)
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

    def handle_chat(self, player, msg, channel):
        if not msg or player.steam_id == 0:
            return

        lower_msg = msg.lower()
        self.log(f"[CHAT] {player.name} ({player.steam_id}): {msg}")

        # Skip admins (perm >= 5)
        try:
            perm = self.db.get_permission(player.steam_id)
            if perm >= 5:
                self.log(f"[SKIP] {player.name} has admin permission {perm}.")
                return
        except Exception as e:
            self.log(f"[WARN] Permission check failed for {player.name}: {e}")

        # Check literal banned words
        for word in self.banned_words:
            if word in lower_msg:
                self.log(f"[MATCH-WORD] {player.name} matched '{word}'")
                self.process_violation(player, word)
                return minqlx.RET_STOP_ALL

        # Check regex patterns
        for pattern in self.regex_patterns:
            if pattern.search(msg):
                self.log(f"[MATCH-REGEX] {player.name} matched regex '{pattern.pattern}'")
                self.process_violation(player, pattern.pattern)
                return minqlx.RET_STOP_ALL

    # ------------------------------------------------------------
    # Violation Handling
    # ------------------------------------------------------------

    def process_violation(self, player, trigger):
        sid = player.steam_id
        if sid not in self.warnings:
            self.warnings[sid] = 1
            self.msg(f"^3Warning to {player.name}: ^7Inappropriate language detected. Next time you’ll be kicked.")
            self.log(f"[WARN] {player.name} warned for '{trigger}'")
        else:
            self.msg(f"^1Player ^7{player.name} ^1was kicked for inappropriate language.")
            self.kick_player(player, trigger)
            self.log(f"[KICK] {player.name} kicked for '{trigger}'")
            del self.warnings[sid]

    def kick_player(self, player, trigger):
        try:
            minqlx.console_command(f"clientkick {player.id}")
        except Exception as e:
            self.log(f"[ERROR] Failed to kick {player.name}: {e}")

    # ------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------

    def cmd_addword(self, player, msg, channel):
        if len(msg) < 2:
            return minqlx.RET_USAGE
        word = msg[1].lower().strip()
        if not word:
            return minqlx.RET_USAGE
        if word in self.banned_words:
            return channel.reply(f"^3'{word}'^7 already banned.")
        self.db.sadd(self.words_key, word)
        self.banned_words.add(word)
        channel.reply(f"^2Added banned word:^7 {word}")
        self.log(f"[CMD] {player.name} added word '{word}'")

    def cmd_delword(self, player, msg, channel):
        if len(msg) < 2:
            return minqlx.RET_USAGE
        word = msg[1].lower().strip()
        if word not in self.banned_words:
            return channel.reply(f"^3'{word}'^7 not in list.")
        self.db.srem(self.words_key, word)
        self.banned_words.remove(word)
        channel.reply(f"^1Removed banned word:^7 {word}")
        self.log(f"[CMD] {player.name} removed word '{word}'")

    def cmd_listwords(self, player, msg, channel):
        info = []
        if self.banned_words:
            info.append("^3Words:^7 " + ", ".join(sorted(self.banned_words)))
        if self.regex_patterns:
            info.append("^3Regex:^7 " + ", ".join([r.pattern for r in self.regex_patterns]))
        if not info:
            info.append("^7No banned words or regex patterns set.")
        channel.reply(" | ".join(info))
        self.log(f"[CMD] {player.name} listed banned entries.")

    def cmd_reloadpatterns(self, player, msg, channel):
        self.regex_patterns = self.load_regex_patterns()
        channel.reply(f"^2Reloaded {len(self.regex_patterns)} regex patterns from file.")
        self.log(f"[CMD] {player.name} reloaded regex patterns.")
