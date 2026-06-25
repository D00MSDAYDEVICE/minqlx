# This is a plugin created by Doomsday for House of Blud
# Heavily borrowed code from iouonegirl's AFK plugin found here:
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
import threading
import time

VERSION = "v1.3"

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

        # steam_id → [last_position, inactive_seconds]
        self.positions = {}

        # steam_ids currently being punished
        self._punished_sids = set()
        self._punished_lock = threading.Lock()

        # Thread control
        self.running = False

        # Hooks
        self.add_hook("round_start", self.handle_round_start)
        self.add_hook("round_end", self.handle_round_end)
        self.add_hook("team_switch", self.handle_team_switch)
        self.add_hook("death", self.handle_death)
        self.add_hook("unload", self.handle_unload)

    # --------------------------------------------------
    #     Helpers — read cvars live so runtime changes
    #     take effect without a reload
    # --------------------------------------------------

    @property
    def warning_time(self):
        try:
            return int(self.get_cvar(VAR_WARNING))
        except Exception:
            return 10

    @property
    def detect_time(self):
        try:
            return int(self.get_cvar(VAR_DETECTION))
        except Exception:
            return 20

    @property
    def put_to_spec(self):
        try:
            return int(self.get_cvar(VAR_PUT_SPEC))
        except Exception:
            return 1

    @property
    def enable_punishment(self):
        try:
            return int(self.get_cvar(VAR_ENABLE_PUN))
        except Exception:
            return 1

    # ------------------------------
    #     ROUND START / END
    # ------------------------------

    def handle_round_start(self, number):
        teams = self.teams()
        for p in teams.get("red", []) + teams.get("blue", []):
            try:
                pos = p.position()
            except Exception:
                pos = None
            self.positions[p.steam_id] = [pos, 0]

        self.running = True
        with self._punished_lock:
            self._punished_sids.clear()

        self.start_monitor_thread()

    def handle_round_end(self, number):
        self.running = False
        with self._punished_lock:
            self._punished_sids.clear()
        self.positions = {}

    # ------------------------------
    #     PLAYER STATE CHANGES
    # ------------------------------

    def handle_team_switch(self, player, old, new):
        sid = player.steam_id

        if new == "spectator":
            self.positions.pop(sid, None)
            with self._punished_lock:
                self._punished_sids.discard(sid)
            return

        if new in ["red", "blue"]:
            try:
                pos = player.position()
            except Exception:
                pos = None
            self.positions[sid] = [pos, 0]

    def handle_death(self, player, killer, data):
        sid = player.steam_id
        self.positions.pop(sid, None)
        with self._punished_lock:
            self._punished_sids.discard(sid)

    def handle_unload(self, plugin):
        if plugin == self.__class__.__name__:
            self.running = False
            with self._punished_lock:
                self._punished_sids.clear()

    # ------------------------------
    #     MONITOR THREAD
    # ------------------------------

    @minqlx.thread
    def start_monitor_thread(self):
        while self.running and self.game and getattr(self.game, "state", None) == "in_progress":
            teams = self.teams()
            for p in teams.get("red", []) + teams.get("blue", []):
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

                    wt = self.warning_time
                    dt = self.detect_time

                    # Warning threshold crossing
                    if secs >= wt and secs - CHECK_INTERVAL < wt:
                        self.warn_afk(p)

                    # Detection threshold crossing
                    if secs >= dt and secs - CHECK_INTERVAL < dt:
                        self.handle_afk_detected(p)
                else:
                    self.positions[sid] = [cur_pos, 0]
                    # Player moved — cancel any ongoing punishment
                    with self._punished_lock:
                        self._punished_sids.discard(sid)

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

    # Called from the monitor thread — push all game writes to next_frame
    def handle_afk_detected(self, player):
        sid = player.steam_id
        secs = int(self.positions[sid][1]) if sid in self.positions else 0
        client_id = player.id

        @minqlx.next_frame
        def announce():
            self.msg("^1{}^7 has been inactive for ^1{}^7 seconds!".format(player.name, secs))

        announce()

        if not self.enable_punishment:
            if self.put_to_spec:
                self.move_to_spectator(client_id, sid)
            return

        with self._punished_lock:
            if sid in self._punished_sids:
                return  # already being punished
            self._punished_sids.add(sid)

        self.start_punishment_loop(client_id, sid)

    # ------------------------------
    #     PUNISHMENT LOOP
    # ------------------------------

    @minqlx.thread
    def start_punishment_loop(self, client_id, sid, damage=10, delay=0.5):
        """
        Repeatedly slap the AFK player until they move, die, or the round ends.
        Uses client_id + steam_id for safe re-resolution rather than storing
        a stale Player object.
        """
        while (
            self.running
            and self.game
            and getattr(self.game, "state", None) == "in_progress"
        ):
            with self._punished_lock:
                if sid not in self._punished_sids:
                    break  # movement or death cleared the flag

            # Re-resolve the player on each iteration to guard against
            # disconnect / slot reuse
            try:
                p = self.player(client_id)
            except Exception:
                p = None

            if not p or p.steam_id != sid:
                # Player gone or slot recycled
                with self._punished_lock:
                    self._punished_sids.discard(sid)
                break

            try:
                alive = p.is_alive
                hp = p.health
            except Exception:
                alive = False
                hp = 0

            if not alive or hp <= damage:
                with self._punished_lock:
                    self._punished_sids.discard(sid)
                if self.put_to_spec:
                    self.move_to_spectator(client_id, sid)
                break

            # Deal damage — slap via console command (safe from thread via engine queue)
            self.apply_punishment(client_id, sid, damage)

            time.sleep(delay)

        # Final cleanup
        with self._punished_lock:
            self._punished_sids.discard(sid)

    @minqlx.next_frame
    def apply_punishment(self, client_id, sid, damage):
        """Slap the player from the game frame."""
        try:
            p = self.player(client_id)
        except Exception:
            return
        if not p or p.steam_id != sid:
            return
        try:
            minqlx.console_command("slap {} {}".format(client_id, damage))
        except Exception:
            pass

    @minqlx.next_frame
    def move_to_spectator(self, client_id, sid):
        """Move player to spec from the game frame, with identity check."""
        try:
            p = self.player(client_id)
        except Exception:
            return
        if not p or p.steam_id != sid:
            return
        try:
            p.put("spectator")
        except Exception:
            pass
