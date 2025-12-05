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
import threading

VERSION = "v1.0"

# CVAR names
VAR_WARNING = "qlx_afk_warning_seconds"
VAR_DETECTION = "qlx_afk_detection_seconds"
VAR_PUT_SPEC = "qlx_afk_put_to_spec"
VAR_ENABLE_PUN = "qlx_afk_enable_punishment"

# Movement check interval
CHECK_INTERVAL = 0.33


class afkplus(minqlx.Plugin):
    def __init__(self):
        super().__init__()

        # Create CVARs if missing
        self.set_cvar_once(VAR_WARNING, "10")
        self.set_cvar_once(VAR_DETECTION, "20")
        self.set_cvar_once(VAR_PUT_SPEC, "1")
        self.set_cvar_once(VAR_ENABLE_PUN, "1")

        # Read CVARs
        self.warning_time = int(self.get_cvar(VAR_WARNING))
        self.detect_time = int(self.get_cvar(VAR_DETECTION))
        self.put_to_spec = int(self.get_cvar(VAR_PUT_SPEC))
        self.enable_punishment = int(self.get_cvar(VAR_ENABLE_PUN))

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
        for p in teams["red"] + teams["blue"]:
            self.positions[p.steam_id] = [p.position(), 0]

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
            self.positions.pop(sid, None)
            if player in self.punished:
                self.punished.remove(player)
            return

        if new in ["red", "blue"]:
            self.positions[sid] = [player.position(), 0]

    def handle_death(self, player, killer, data):
        sid = player.steam_id
        self.positions.pop(sid, None)
        if player in self.punished:
            self.punished.remove(player)

    def handle_unload(self, plugin):
        if plugin == self.__class__.__name__:
            self.running = False
            self.punished = []

    # ------------------------------
    #     THREAD LOOP
    # ------------------------------

    @minqlx.thread
    def start_monitor_thread(self):
        while self.running and self.game and self.game.state == "in_progress":
            teams = self.teams()

            for p in teams["red"] + teams["blue"]:
                if not p.is_alive:
                    continue

                sid = p.steam_id
                cur_pos = p.position()

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
                        self.punished.remove(p)

            time.sleep(CHECK_INTERVAL)

    # ------------------------------
    #     AFK HANDLING
    # ------------------------------

    @minqlx.next_frame
    def warn_afk(self, player):
        msg = f"You have been inactive for {self.warning_time} seconds..."
        minqlx.send_server_command(player.id, f'cp "{msg}"')

    def handle_afk_detected(self, player):
        secs = int(self.positions[player.steam_id][1])
        self.msg(f"^1{player.name}^7 has been inactive for ^1{secs}^7 seconds!")

        # If punishment is disabled
        if not self.enable_punishment:
            if self.put_to_spec:
                self.move_to_spectator(player)
            return

        # If punishment enabled
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
            and self.game.state == "in_progress"
            and player in self.punished
        ):
            if not player.is_alive or player.health < damage:
                self.punished.remove(player)
                if self.put_to_spec:
                    self.move_to_spectator(player)
                break

            # Subtract health
            @minqlx.next_frame
            def do_damage(p, d): p.health -= d
            do_damage(player, damage)

            # Update message
            sid = player.steam_id
            secs = int(self.positions[sid][1]) if sid in self.positions else self.detect_time
            msg = f"^1Inactive for {secs} seconds!^7\nMove or keep taking damage!"
            minqlx.send_server_command(player.id, f'cp "{msg}"')

            time.sleep(delay)

    @minqlx.next_frame
    def move_to_spectator(self, player):
        player.put("spectator")
