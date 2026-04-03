# This is a plugin created by Doomsday for House of Blud
# Heavily borrowed code form iouonegirl's AFK plugin found here:
# https://github.com/dsverdlo/minqlx-plugins
#
# You are free to modify this plugin
#
# Detects afk players and specs them
#
# Uses:
# - qlx_afk_warning_seconds "10"
# - qlx_afk_detection_seconds "20"
# - qlx_afk_put_to_spec "1"
# - qlx_afk_enable_punishment "1"
#
# If qlx_afk_enable_punishment is 0, player will be automatically spec'd at time set

import minqlx
import time

VERSION = "v1.1"

# CVAR names
VAR_WARNING = "qlx_afk_warning_seconds"
VAR_DETECTION = "qlx_afk_detection_seconds"
VAR_PUT_SPEC = "qlx_afk_put_to_spec"
VAR_ENABLE_PUN = "qlx_afk_enable_punishment"

# Movement check interval
CHECK_INTERVAL = 0.33


class afkp(minqlx.Plugin):
    def __init__(self):
        super(afkp, self).__init__()

        # Create CVARs if missing
        self.set_cvar_once(VAR_WARNING, "10")
        self.set_cvar_once(VAR_DETECTION, "20")
        self.set_cvar_once(VAR_PUT_SPEC, "1")
        self.set_cvar_once(VAR_ENABLE_PUN, "1")

        # Read CVARs
        try:
            self.warning_time = int(self.get_cvar(VAR_WARNING))
        except Exception:
            self.warning_time = 10
        try:
            self.detect_time = int(self.get_cvar(VAR_DETECTION))
        except Exception:
            self.detect_time = 20
        try:
            self.put_to_spec = int(self.get_cvar(VAR_PUT_SPEC))
        except Exception:
            self.put_to_spec = 1
        try:
            self.enable_punishment = int(self.get_cvar(VAR_ENABLE_PUN))
        except Exception:
            self.enable_punishment = 1

        # steam_id → [last_position, inactive_seconds]
        self.positions = {}

        # AFK players currently being punished
        self.punished = []

        # Thread control
        self.running = False

        # Hooks
        self.add_hook("round_start", self.handle_round_start)
        self.add_hook("round_end", self.handle_round_end)
        self.add_hook("team_switch", self.handle_team_switch)
        self.add_hook("death", self.handle_death)
        self.add_hook("unload", self.handle_unload)

    # ------------------------------
    #     ROUND START / END
    # ------------------------------

    def handle_round_start(self, number):
        teams = self.teams()
        for p in teams.get("red", []) + teams.get("blue", []):
            # protect against players with no position method
            try:
                pos = p.position()
            except Exception:
                pos = None
            self.positions[p.steam_id] = [pos, 0]

        self.running = True
        self.punished = []

        self.start_monitor_thread()

    def handle_round_end(self, number):
        self.running = False
        self.punished = []
        self.positions = {}

    # ------------------------------
    #     PLAYER STATE CHANGES
    # ------------------------------

    def handle_team_switch(self, player, old, new):
        sid = player.steam_id

        if new == "spectator":
            if sid in self.positions:
                del self.positions[sid]
            if player in self.punished:
                try:
                    self.punished.remove(player)
                except ValueError:
                    pass
            return

        if new in ["red", "blue"]:
            try:
                pos = player.position()
            except Exception:
                pos = None
            self.positions[sid] = [pos, 0]

    def handle_death(self, player, killer, data):
        sid = player.steam_id
        if sid in self.positions:
            del self.positions[sid]
        if player in self.punished:
            try:
                self.punished.remove(player)
            except ValueError:
                pass

    def handle_unload(self, plugin):
        if plugin == self.__class__.__name__:
            self.running = False
            self.punished = []

    # ------------------------------
    #     THREAD LOOP
    # ------------------------------

    @minqlx.thread
    def start_monitor_thread(self):
        while self.running and self.game and getattr(self.game, "state", None) == "in_progress":
            teams = self.teams()

            reds = teams.get("red", [])
            blues = teams.get("blue", [])
            for p in reds + blues:
                # skip if not alive or missing methods
                try:
                    if not p.is_alive:
                        continue
                except Exception:
                    continue

                sid = p.steam_id
                try:
                    cur_pos = p.position()
                except Exception:
                    cur_pos = None

                if sid not in self.positions:
                    self.positions[sid] = [cur_pos, 0]

                last_pos, secs = self.positions[sid]

                if cur_pos == last_pos:
                    secs += CHECK_INTERVAL
                    self.positions[sid] = [cur_pos, secs]

                    # Warning
                    if secs >= self.warning_time and secs - CHECK_INTERVAL < self.warning_time:
                        self.warn_afk(p)

                    # Detection
                    if secs >= self.detect_time and secs - CHECK_INTERVAL < self.detect_time:
                        self.handle_afk_detected(p)

                else:
                    self.positions[sid] = [cur_pos, 0]
                    if p in self.punished:
                        try:
                            self.punished.remove(p)
                        except ValueError:
                            pass

            time.sleep(CHECK_INTERVAL)

    # ------------------------------
    #     AFK HANDLING
    # ------------------------------

    @minqlx.next_frame
    def warn_afk(self, player):
        msg = "You have been inactive for {} seconds...".format(self.warning_time)
        try:
            minqlx.send_server_command(player.id, 'cp "{}"'.format(msg))
        except Exception:
            pass

    def handle_afk_detected(self, player):
        sid = player.steam_id
        secs = 0
        if sid in self.positions:
            secs = int(self.positions[sid][1])
        self.msg("^1{}^7 has been inactive for ^1{}^7 seconds!".format(player.name, secs))

        # If punishment disabled
        if not self.enable_punishment:
            if self.put_to_spec:
                self.move_to_spectator(player)
            return

        # If punishment enabled — only start a new loop if not already punishing
        if player not in self.punished:
            self.punished.append(player)
            self.start_punishment_loop(player)

    # ------------------------------
    #     PUNISHMENT LOOP
    # ------------------------------

    @minqlx.thread
    def start_punishment_loop(self, player, damage=10, delay=0.5):
        while (
            self.running
            and self.game
            and getattr(self.game, "state", None) == "in_progress"
            and player in self.punished
        ):
            try:
                alive = player.is_alive
            except Exception:
                alive = False

            try:
                hp = player.health
            except Exception:
                hp = 0

            if not alive or hp < damage:
                if player in self.punished:
                    try:
                        self.punished.remove(player)
                    except ValueError:
                        pass
                if self.put_to_spec:
                    self.move_to_spectator(player)
                break

            # Subtract health
            @minqlx.next_frame
            def do_damage(p, d):
                try:
                    p.health -= d
                except Exception:
                    pass
            do_damage(player, damage)

            # Warning
            sid = player.steam_id
            if sid in self.positions:
                secs = int(self.positions[sid][1])
            else:
                secs = self.detect_time

            msg = "^1Inactive for {} seconds!^7\nMove or keep taking damage!".format(secs)
            try:
                minqlx.send_server_command(player.id, 'cp "{}"'.format(msg))
            except Exception:
                pass

            time.sleep(delay)

    @minqlx.next_frame
    def move_to_spectator(self, player):
        try:
            player.put("spectator")
        except Exception:
            pass
