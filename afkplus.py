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
#
# Activity is judged primarily by view pitch (vertical look angle), not
# raw position. Pitch only ever changes from the player's own mouse/
# joystick input — physics (rocket/grenade knockback, being bumped by
# another player, pushers, teleporters, even this plugin's own slap
# punishment) never touches it. That makes it immune to the false
# negatives raw position tracking had: a truly AFK player getting
# knocked around no longer looks "active", and a player holding an
# angle while tracking a target with the mouse (not moving their feet)
# no longer gets falsely flagged. Position is still tracked, but only
# as a fallback if pitch can't be read on a given minqlx build.

import minqlx
import threading
import time

VERSION = "v1.5"

# CVAR names
VAR_WARNING = "qlx_afk_warning_seconds"
VAR_DETECTION = "qlx_afk_detection_seconds"
VAR_PUT_SPEC = "qlx_afk_put_to_spec"
VAR_ENABLE_PUN = "qlx_afk_enable_punishment"

# Movement check interval
CHECK_INTERVAL = 0.33

# Degrees of pitch change below which the view is considered unchanged.
# A view with zero input should read back bit-identical between samples,
# so this is just a small safety margin against engine-side float/angle
# quantization noise — real mouse movement is far larger than this.
PITCH_EPSILON = 0.05


class afkplus(minqlx.Plugin):
    def __init__(self):
        super().__init__()

        # Create CVARs if missing
        self.set_cvar_once(VAR_WARNING, "10")
        self.set_cvar_once(VAR_DETECTION, "20")
        self.set_cvar_once(VAR_PUT_SPEC, "1")
        self.set_cvar_once(VAR_ENABLE_PUN, "1")

        # steam_id → [last_position, last_pitch, inactive_seconds]
        self.positions = {}
        self._positions_lock = threading.Lock()

        # Set once if viewangles turn out to be unreadable on this
        # minqlx build, so we log the fallback exactly once instead of
        # spamming the log every check interval.
        self._pitch_unavailable_logged = False

        # steam_ids currently being punished
        self._punished_sids = set()
        self._punished_lock = threading.Lock()

        # Thread control
        self.running = False
        # Bumped on every round_start/round_end so a stale monitor
        # thread from a previous round can never keep running (and
        # double-incrementing inactivity counters) once a new round
        # begins. This is what stops the warning/detection thresholds
        # from ever being reachable early.
        self._round_token = 0

        # Hooks
        self.add_hook("round_start", self.handle_round_start)
        self.add_hook("round_end", self.handle_round_end)
        self.add_hook("team_switch", self.handle_team_switch)
        self.add_hook("death", self.handle_death)
        self.add_hook("unload", self.handle_unload)

        # Commands
        self.add_command(
            ("afktime", "afkdetect"),
            self.cmd_afktime,
            permission=3,
            usage="<seconds>",
        )

    # --------------------------------------------------
    #     Helpers — read cvars live so runtime changes
    #     take effect without a reload
    # --------------------------------------------------

    def _log_unexpected(self, context, exc):
        """Log genuinely unexpected errors; stay quiet for the routine
        disconnect/slot-reuse race (NonexistentPlayerError) that the
        surrounding try/except blocks are mainly there to absorb."""
        if isinstance(exc, minqlx.NonexistentPlayerError):
            return
        self.logger.warning("afkplus: unexpected error in %s: %r", context, exc)

    def _read_pitch(self, p):
        """Current vertical view angle (pitch), in degrees.

        Returns None if it can't be read — either a routine disconnect
        race (handled quietly) or, on the first occurrence only, a build
        of minqlx that doesn't expose viewangles the way this expects,
        which is logged once so it can be fixed rather than silently
        degrading forever. Callers fall back to position-only detection
        for that player/tick when this returns None.
        """
        try:
            return p.state().viewangles[0]  # index 0 == pitch
        except minqlx.NonexistentPlayerError:
            return None
        except Exception as e:
            if not self._pitch_unavailable_logged:
                self._pitch_unavailable_logged = True
                self.logger.warning(
                    "afkplus: viewangles not readable (%r) — falling back to "
                    "position-only AFK detection for this session.", e
                )
            return None

    @property
    def warning_time(self):
        try:
            return int(self.get_cvar(VAR_WARNING))
        except Exception as e:
            self._log_unexpected("reading " + VAR_WARNING, e)
            return 10

    @property
    def detect_time(self):
        try:
            return int(self.get_cvar(VAR_DETECTION))
        except Exception as e:
            self._log_unexpected("reading " + VAR_DETECTION, e)
            return 20

    @property
    def put_to_spec(self):
        try:
            return int(self.get_cvar(VAR_PUT_SPEC))
        except Exception as e:
            self._log_unexpected("reading " + VAR_PUT_SPEC, e)
            return 1

    @property
    def enable_punishment(self):
        try:
            return int(self.get_cvar(VAR_ENABLE_PUN))
        except Exception as e:
            self._log_unexpected("reading " + VAR_ENABLE_PUN, e)
            return 1

    # ------------------------------
    #     COMMANDS
    # ------------------------------

    def cmd_afktime(self, player, msg, channel):
        """!afktime <seconds> — sets qlx_afk_detection_seconds at runtime."""
        if len(msg) != 2:
            player.tell("^7Usage: ^2!afktime <seconds>")
            return minqlx.RET_USAGE

        try:
            seconds = int(msg[1])
        except ValueError:
            player.tell("^1Error^7: seconds must be a whole number.")
            return minqlx.RET_STOP_ALL

        if seconds <= 0:
            player.tell("^1Error^7: seconds must be greater than 0.")
            return minqlx.RET_STOP_ALL

        wt = self.warning_time
        if seconds <= wt:
            player.tell(
                "^1Error^7: detection time (^2{}^7) must be greater than "
                "the warning time (^2{}^7).".format(seconds, wt)
            )
            return minqlx.RET_STOP_ALL

        self.set_cvar(VAR_DETECTION, str(seconds))
        self.msg(
            "^7AFK detection time set to ^2{}^7 seconds by ^2{}^7.".format(
                seconds, player.name
            )
        )
        return minqlx.RET_STOP_ALL

    # ------------------------------
    #     ROUND START / END
    # ------------------------------

    def handle_round_start(self, number):
        with self._positions_lock:
            teams = self.teams()
            for p in teams.get("red", []) + teams.get("blue", []):
                try:
                    pos = p.position()
                except Exception as e:
                    self._log_unexpected("round_start position read", e)
                    pos = None
                pitch = self._read_pitch(p)
                self.positions[p.steam_id] = [pos, pitch, 0]

        self.running = True
        self._round_token += 1
        token = self._round_token
        with self._punished_lock:
            self._punished_sids.clear()

        self.start_monitor_thread(token)

    def handle_round_end(self, number):
        self.running = False
        # Invalidate the current token immediately so any monitor thread
        # still mid-sleep exits on its very next wake instead of surviving
        # until the next round_start flips `running` back to True.
        self._round_token += 1
        with self._punished_lock:
            self._punished_sids.clear()
        with self._positions_lock:
            self.positions = {}

    # ------------------------------
    #     PLAYER STATE CHANGES
    # ------------------------------

    def handle_team_switch(self, player, old, new):
        sid = player.steam_id

        if new == "spectator":
            with self._positions_lock:
                self.positions.pop(sid, None)
            with self._punished_lock:
                self._punished_sids.discard(sid)
            return

        if new in ["red", "blue"]:
            try:
                pos = player.position()
            except Exception as e:
                self._log_unexpected("team_switch position read", e)
                pos = None
            pitch = self._read_pitch(player)
            with self._positions_lock:
                self.positions[sid] = [pos, pitch, 0]

    def handle_death(self, player, killer, data):
        sid = player.steam_id
        with self._positions_lock:
            self.positions.pop(sid, None)
        with self._punished_lock:
            self._punished_sids.discard(sid)

    def handle_unload(self, plugin):
        if plugin == self.__class__.__name__:
            self.running = False
            self._round_token += 1
            with self._punished_lock:
                self._punished_sids.clear()

    # ------------------------------
    #     MONITOR THREAD
    # ------------------------------

    @minqlx.thread
    def start_monitor_thread(self, token):
        while (
            self.running
            and self._round_token == token
            and self.game
            and getattr(self.game, "state", None) == "in_progress"
        ):
            teams = self.teams()
            for p in teams.get("red", []) + teams.get("blue", []):
                try:
                    if not p.is_alive:
                        continue
                except Exception as e:
                    self._log_unexpected("monitor is_alive read", e)
                    continue

                sid = p.steam_id
                try:
                    cur_pos = p.position()
                except Exception as e:
                    self._log_unexpected("monitor position read", e)
                    cur_pos = None
                cur_pitch = self._read_pitch(p)

                # Read-modify-write of the shared counter happens under
                # lock so a lingering/duplicate thread can never double
                # -increment a player's inactivity time and make the
                # warning or detection threshold trip earlier than the
                # configured number of real seconds.
                with self._positions_lock:
                    if sid not in self.positions:
                        self.positions[sid] = [cur_pos, cur_pitch, 0]

                    last_pos, last_pitch, secs = self.positions[sid]

                    # Pitch is the deciding signal: it only moves from the
                    # player's own input, so a pitch change is trustworthy
                    # evidence of activity even if position didn't change
                    # (holding an angle while tracking a target), and a
                    # position change with no pitch change is NOT treated
                    # as activity (knockback, a bump from another player,
                    # or our own slap punishment moving them). If pitch is
                    # unreadable this tick, fall back to the old
                    # position-only comparison instead of losing detection.
                    if cur_pitch is None or last_pitch is None:
                        active = cur_pos != last_pos
                    else:
                        active = abs(cur_pitch - last_pitch) >= PITCH_EPSILON

                    if active:
                        self.positions[sid] = [cur_pos, cur_pitch, 0]
                        moved = True
                    else:
                        secs += CHECK_INTERVAL
                        self.positions[sid] = [cur_pos, cur_pitch, secs]
                        moved = False

                if moved:
                    # Player moved — cancel any ongoing punishment
                    with self._punished_lock:
                        self._punished_sids.discard(sid)
                    continue

                wt = self.warning_time
                dt = self.detect_time

                # Warning threshold crossing
                if secs >= wt and secs - CHECK_INTERVAL < wt:
                    self.warn_afk(p)

                # Detection threshold crossing
                if secs >= dt and secs - CHECK_INTERVAL < dt:
                    self.handle_afk_detected(p)

            time.sleep(CHECK_INTERVAL)

    # ------------------------------
    #     AFK HANDLING
    # ------------------------------

    @minqlx.next_frame
    def warn_afk(self, player):
        msg = "You have been inactive for {} seconds...".format(self.warning_time)
        try:
            minqlx.send_server_command(player.id, 'cp "{}"'.format(msg))
        except Exception as e:
            self._log_unexpected("warn_afk send_server_command", e)

    # Called from the monitor thread — push all game writes to next_frame
    def handle_afk_detected(self, player):
        sid = player.steam_id
        with self._positions_lock:
            secs = int(self.positions[sid][2]) if sid in self.positions else 0
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
            except Exception as e:
                self._log_unexpected("punishment loop player resolve", e)
                p = None

            if not p or p.steam_id != sid:
                # Player gone or slot recycled
                with self._punished_lock:
                    self._punished_sids.discard(sid)
                break

            try:
                alive = p.is_alive
                hp = p.health
            except Exception as e:
                self._log_unexpected("punishment loop is_alive/health read", e)
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
        except Exception as e:
            self._log_unexpected("apply_punishment player resolve", e)
            return
        if not p or p.steam_id != sid:
            return
        try:
            minqlx.console_command("slap {} {}".format(client_id, damage))
        except Exception as e:
            self._log_unexpected("apply_punishment slap", e)

    @minqlx.next_frame
    def move_to_spectator(self, client_id, sid):
        """Move player to spec from the game frame, with identity check."""
        try:
            p = self.player(client_id)
        except Exception as e:
            self._log_unexpected("move_to_spectator player resolve", e)
            return
        if not p or p.steam_id != sid:
            return
        try:
            p.put("spectator")
        except Exception as e:
            self._log_unexpected("move_to_spectator put", e)
