# SPDX-License-Identifier: GPL-3.0-or-later
"""fragq: send Quake Live match results to FragQ, the Discord pickup bot, and let players link their
Steam account to Discord from the game.

One file for both minqlx and minqlxtended. Needs a FragQ connector key (FragQ web panel ->
Connectors -> Create connector, game Quake Live). FragQ connectors are in beta.

When a match ends the plugin works out the highlights (Top Damage, Least Damage, Most Damage Taken,
Most Frags, Highest Accuracy, Quitters) and a per-player table, and sends them to FragQ in one request.
FragQ finds the pickup match the players were in and posts the results in its Discord channel.

Setup, from the server console or rcon (the key must not be typed in chat):
    qlx !fragq url https://fragq.example.com
    qlx !fragq key fq_...
    qlx !fragq test
or in server.cfg:
    set qlx_fragqUrl "https://fragq.example.com"
    set qlx_fragqKey "fq_..."
A URL and key set with the command are kept in the bot's database and take precedence over the cvars.
On minqlx, match stats need the ZMQ stats feed: set zmq_stats_enable 1.

Commands:
    !link <discord id>               link your Steam account to your Discord account (confirm in Discord)
    !link <player id> <discord id>   the same for another player (permission qlx_fragqAdminLevel);
                                     player id = client id as shown by /players
    !linkenforce [on|off]            keep players without a linked Steam account in spectator (qlx_fragqAdminLevel)
    !setdiscord <invite URL>         the Discord invite shown to players who aren't on the server yet
                                     (qlx_fragqAdminLevel); !setdiscord off removes it
    !fragq                           status (qlx_fragqAdminLevel)
    !fragq url <url>                 set the FragQ address (permission 5)
    !fragq key <key>                 set the connector key (permission 5, server console / rcon only)
    !fragq test                      check the connection and the key (permission 5)

Cvars:
    qlx_fragqUrl            FragQ web panel address, e.g. https://fragq.example.com
    qlx_fragqKey            connector key
    qlx_fragqServerName     server name sent with results (default: sv_hostname)
    qlx_fragqResults        1 = send match results (default 1)
    qlx_fragqMinPlayers     fewest players a match needs for its results to be sent (default 2)
    qlx_fragqMinShots       fewest shots for Highest Accuracy (default 50)
    qlx_fragqEnforceLink    1 = unlinked players stay in spectator (default 0; !linkenforce changes it and is remembered)
    qlx_fragqAdminLevel     permission level for !linkenforce, !setdiscord, !fragq and !link for others (default 3)
    qlx_fragqDiscordInvite  Discord invite link shown to players (default empty; !setdiscord changes it and is remembered)
    qlx_fragqVerifyTls      0 = accept a self-signed certificate (default 1)
"""
import collections
import json
import re
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

# The two runtimes are separate forks with their own module name and return-value constants; everything
# else this plugin uses has the same name in both. Handlers that receive extra arguments on minqlxtended
# (team_switch_attempt) take *_ so the same signature registers on both.
try:
    import minqlxtended as ql
    STOP_ALL = ql.Return.STOP_ALL
    RUNTIME = "minqlxtended"
except ImportError:
    import minqlx as ql
    STOP_ALL = ql.RET_STOP_ALL
    RUNTIME = "minqlx"

VERSION = "1.0.0"
DB_URL = "minqlx:fragq:url"
DB_KEY = "minqlx:fragq:key"
DB_ENFORCE = "minqlx:fragq:enforce"
DB_INVITE = "minqlx:fragq:invite"
TIMEOUT = 10              # seconds per HTTP request
FINAL_STATS_WAIT = 3      # PLAYER_STATS of everyone still playing arrive just after MATCH_REPORT
RESULT_RETRIES = (5, 30, 120, 600)   # seconds before each new attempt while FragQ is unreachable
MAX_OUTBOX = 10
LINKED_TTL = 600          # a linked player is checked again after this long
UNLINKED_TTL = 15         # an unlinked player can be checked again this soon (they may have just confirmed)
LINK_WATCH = 15 * 60      # after !link, watch for the Discord confirmation this long
LINK_COOLDOWN = 30        # between !link commands of the same player
WARN_COOLDOWN = 20        # between spectator warnings to the same player
LOOKUP_BATCH = 64
COLOR_RE = re.compile(r"\^[0-9]")
DISCORD_RE = re.compile(r"^(?:\d{15,21}|[A-Za-z0-9_.]{2,32})\Z")
INVITE_RE = re.compile(r"^(?:https?://)?(?:www\.)?(?:discord\.gg|discord(?:app)?\.com/invite)/([A-Za-z0-9-]{2,32})/?\Z", re.I)
TEAM_MODES = {"ca", "tdm", "ctf", "1fctf", "ft", "ad", "dom", "har", "rr", "wipeout"}
TEAMS = {0: "Free", 1: "Red", 2: "Blue"}
SKIP_WEAPONS = {"GAUNTLET"}   # melee: hits and shots don't mean accuracy


def _is_steam_id(sid):
    s = str(sid)
    return len(s) == 17 and s.isdigit() and s.startswith("7656119")


def _api_url(url):
    """'fragq.example.com', 'https://host:4443' or the full .../api/connect/v1 URL -> the API base URL, or None."""
    url = (url or "").strip().rstrip("/")
    if not url:
        return ""
    if "://" not in url:
        url = "https://" + url
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc or parts.query or parts.fragment:
        return None
    return url if url.endswith("/api/connect/v1") else url + "/api/connect/v1"


def _text(s):
    """Safe for tell(): the QL client reads % as a format code and corrupts its state."""
    return str(s).replace("%", "％")


def _clean(s):
    return COLOR_RE.sub("", str(s or ""))


def _invite(text):
    """A Discord invite link in any usual form -> 'discord.gg/<code>', or None."""
    m = INVITE_RE.match((text or "").strip())
    return f"discord.gg/{m.group(1)}" if m else None


def _int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _team(team):
    """'red', 'blue', 'free', 'spectator' or 'any': minqlx gives strings, minqlxtended Team members."""
    return str(getattr(team, "name", team) or "").lower()


def _num(d, *path):
    for key in path:
        d = d.get(key) if isinstance(d, dict) else None
    return d if isinstance(d, (int, float)) and not isinstance(d, bool) else 0


class fragq(ql.Plugin):
    def __init__(self):
        super().__init__()
        self.set_cvar_once("qlx_fragqUrl", "")
        self.set_cvar_once("qlx_fragqKey", "")
        self.set_cvar_once("qlx_fragqServerName", "")
        self.set_cvar_once("qlx_fragqResults", "1")
        self.set_cvar_once("qlx_fragqMinPlayers", "2")
        self.set_cvar_once("qlx_fragqMinShots", "50")
        self.set_cvar_once("qlx_fragqEnforceLink", "0")
        self.set_cvar_once("qlx_fragqAdminLevel", "3")
        self.set_cvar_once("qlx_fragqDiscordInvite", "")
        self.set_cvar_once("qlx_fragqVerifyTls", "1")

        # Shared with the worker thread. Cvars and the database are read on the game thread (load_config)
        # and handed over as a plain dict; the stats hook (the ZMQ thread on minqlx) only updates dicts.
        self._lock = threading.Lock()
        self._cfg = {}
        self._match = {}               # steam_id -> stats summed over the player's time in this match
        self._report = None            # MATCH_REPORT data once the match ended
        self._finish_at = 0.0          # when to send it (after the last PLAYER_STATS)
        self._outbox = collections.deque(maxlen=MAX_OUTBOX)   # [payload, attempts, next try]
        self._linked = {}              # steam_id -> (True / False / None = couldn't check, checked at)
        self._lookups = collections.deque(maxlen=1000)
        self._watch = {}               # steam_id -> (client id, until): waiting for a Discord confirmation
        self._warned = {}              # steam_id -> time of the last spectator warning
        self._link_at = {}             # steam_id -> time of the last !link
        self._command_at = 0.0
        self._last = {"time": None, "message": "nothing sent yet"}
        self._stop = threading.Event()
        self._wake = threading.Event()
        self.load_config()

        self.add_hook("stats", self.handle_stats)
        self.add_hook("player_loaded", self.handle_player_loaded)
        self.add_hook("player_disconnect", self.handle_player_disconnect)
        self.add_hook("team_switch_attempt", self.handle_team_switch_attempt)
        self.add_hook("map", self.handle_map)
        self.add_hook("unload", self.handle_unload)
        self.add_command("link", self.cmd_link, usage="<discord id> | <player id> <discord id>")
        self.add_command("linkenforce", self.cmd_linkenforce, usage="[on|off]")
        self.add_command("setdiscord", self.cmd_setdiscord, usage="<invite URL> | off")
        self.add_command("fragq", self.cmd_fragq, usage="[url <url> | key <key> | test]")

        self._thread = threading.Thread(target=self._worker, name="fragq", daemon=True)
        self._thread.start()

    # ------------------------------------------------------------ config (game thread)

    def load_config(self):
        try:
            url, key, enforce = self.db.get(DB_URL), self.db.get(DB_KEY), self.db.get(DB_ENFORCE)
            invite = self.db.get(DB_INVITE)
        except Exception:  # noqa: BLE001 - no database configured: cvars only
            self.logger.warning("fragq: database unavailable, using the qlx_fragq* cvars")
            url = key = enforce = invite = None
        cfg = {
            "url": _api_url(url or self.get_cvar("qlx_fragqUrl")) or "",
            "key": (key or self.get_cvar("qlx_fragqKey") or "").strip(),
            "server": _clean(self.get_cvar("qlx_fragqServerName") or self.get_cvar("sv_hostname"))[:80],
            "results": _int(self.get_cvar("qlx_fragqResults"), 1) != 0,
            "min_players": max(1, _int(self.get_cvar("qlx_fragqMinPlayers"), 2)),
            "min_shots": max(1, _int(self.get_cvar("qlx_fragqMinShots"), 50)),
            "enforce": (str(enforce) == "1") if enforce is not None else _int(self.get_cvar("qlx_fragqEnforceLink"), 0) != 0,
            "admin_level": _int(self.get_cvar("qlx_fragqAdminLevel"), 3),
            # "" in the database: removed with !setdiscord off, don't fall back to the cvar
            "invite": _invite(self.get_cvar("qlx_fragqDiscordInvite")) if invite is None else _invite(invite),
            "verify_tls": _int(self.get_cvar("qlx_fragqVerifyTls"), 1) != 0,
        }
        with self._lock:
            self._cfg = cfg
        return cfg

    def _config(self):
        with self._lock:
            return dict(self._cfg)

    # ------------------------------------------------------------ hooks: O(1), update and return

    def handle_stats(self, stats):
        kind = stats.get("TYPE")
        data = stats.get("DATA") or {}
        if kind == "MATCH_STARTED":
            with self._lock:
                self._match, self._report, self._finish_at = {}, None, 0.0
        elif kind == "PLAYER_STATS":
            if data.get("WARMUP") or data.get("ABORTED"):
                return
            sid = str(data.get("STEAM_ID") or "")
            if not _is_steam_id(sid):
                return   # bots
            hits = shots = 0
            for weapon, w in (data.get("WEAPONS") or {}).items():
                if weapon not in SKIP_WEAPONS:
                    hits += _num(w, "H")
                    shots += _num(w, "S")
            with self._lock:
                p = self._match.setdefault(sid, {"kills": 0, "deaths": 0, "score": 0, "dealt": 0, "taken": 0,
                                                 "time": 0, "hits": 0, "shots": 0})
                for k, v in (("kills", _num(data, "KILLS")), ("deaths", _num(data, "DEATHS")),
                             ("dealt", _num(data, "DAMAGE", "DEALT")), ("taken", _num(data, "DAMAGE", "TAKEN")),
                             ("time", _num(data, "PLAY_TIME")), ("hits", hits), ("shots", shots)):
                    p[k] += v   # a player who left and came back sends one PLAYER_STATS per stretch
                p["score"] = _num(data, "SCORE")
                p["name"] = _clean(data.get("NAME"))[:64] or sid
                p["team"] = _int(data.get("TEAM"), 0)
                p["rank"] = _int(data.get("RANK"), 0)
                p["quit"] = bool(data.get("QUIT"))
        elif kind == "MATCH_REPORT":
            with self._lock:
                if data.get("ABORTED"):
                    self._match, self._report = {}, None
                    return
                self._report = dict(data)
                self._finish_at = time.time() + FINAL_STATS_WAIT
            self._wake.set()

    def handle_player_loaded(self, player):
        if self._cfg.get("enforce") and _is_steam_id(player.steam_id):
            self._lookups.append(str(player.steam_id))
            self._wake.set()

    def handle_player_disconnect(self, player, *_):
        sid = str(player.steam_id)
        self._watch.pop(sid, None)
        self._warned.pop(sid, None)

    def handle_team_switch_attempt(self, player, old_team, new_team, *_):
        if not self._cfg.get("enforce") or _team(new_team) == "spectator":
            return
        sid = str(player.steam_id)
        if not _is_steam_id(sid):
            return
        linked, at = self._linked.get(sid, (False, 0))
        if linked or linked is None:   # None: FragQ couldn't be asked, don't lock players out
            return
        if time.time() - at >= UNLINKED_TTL:
            self._lookups.append(sid)
            self._wake.set()
        player.tell(_text(self._warning(sid, at)))
        return STOP_ALL

    def handle_map(self, *_):
        self.load_config()   # picks up cvars changed since the last map
        with self._lock:
            self._match, self._report, self._finish_at = {}, None, 0.0

    def handle_unload(self, plugin):
        if plugin == self.__class__.__name__:
            self._stop.set()
            self._wake.set()

    def _warning(self, sid, checked_at):
        if not checked_at:
            return "^1FragQ:^7 checking your linked Steam account, try again in a few seconds."
        invite = self._cfg.get("invite")
        return ("^1FragQ:^7 this server needs a Steam account linked to Discord. You stay in spectator until it is "
                "linked: type ^5!link <your Discord id>^7 and confirm in Discord."
                + (f" Not on our Discord yet? Join ^5{invite}^7 first." if invite else ""))

    def _join_hint(self):
        invite = self._cfg.get("invite")
        return f"^1FragQ:^3 not on our Discord yet? Join ^5{invite}^3, then type ^5!link^3 again." if invite else None

    # ------------------------------------------------------------ commands (game thread)

    def cmd_link(self, player, msg, channel):
        cfg = self._cfg
        console = getattr(channel, "name", "") == "console"
        if len(msg) not in (2, 3):
            player.tell("^1FragQ:^7 usage: ^5!link <your Discord id>^7. Find it in Discord: Settings -> Advanced -> "
                        "Developer Mode, then right-click your name -> Copy User ID.")
            return STOP_ALL
        target = None if console else player
        if len(msg) == 3:
            cid = msg[1]
            try:
                found = self.player(int(cid)) if cid.isdigit() and int(cid) < 64 else None
            except Exception:  # noqa: BLE001 - NonexistentPlayerError on either runtime
                found = None
            if found is None:
                player.tell(_text(f"^1FragQ:^7 no player with id {cid[:10]}. Player ids are shown by /players."))
                return STOP_ALL
            if not console and found.id != player.id and not self.db.has_permission(player, cfg.get("admin_level", 3)):
                player.tell("^1FragQ:^7 you can only link your own Steam account: ^5!link <your Discord id>^7")
                return STOP_ALL
            target = found
        if target is None:
            player.tell("^1FragQ:^7 from the console, name the player: !link <player id> <discord id>")
            return STOP_ALL
        discord = msg[-1].strip().lstrip("@")
        if not DISCORD_RE.match(discord):
            player.tell("^1FragQ:^7 that isn't a Discord user id (a long number) or username.")
            return STOP_ALL
        sid = str(target.steam_id)
        if not _is_steam_id(sid):
            player.tell("^1FragQ:^7 that player has no Steam account to link.")
            return STOP_ALL
        now = time.time()
        if now - self._link_at.get(sid, 0) < LINK_COOLDOWN:
            player.tell(f"^1FragQ:^7 wait {int(LINK_COOLDOWN - (now - self._link_at[sid])) + 1}s.")
            return STOP_ALL
        self._link_at[sid] = now
        player.tell("^1FragQ:^7 asking FragQ...")
        self._request_link(self._reply_target(player, channel), (target.id, sid), _clean(target.name), discord)
        return STOP_ALL

    def cmd_linkenforce(self, player, msg, channel):
        cfg = self._cfg
        if not self.db.has_permission(player, cfg.get("admin_level", 3)):
            player.tell("^1FragQ:^7 you don't have permission to change that.")
            return STOP_ALL
        if len(msg) < 2:
            on = not cfg.get("enforce")
        elif msg[1].lower() in ("on", "1", "yes"):
            on = True
        elif msg[1].lower() in ("off", "0", "no"):
            on = False
        else:
            player.tell("^1FragQ:^7 usage: !linkenforce [on|off]")
            return STOP_ALL
        try:
            self.db.set(DB_ENFORCE, "1" if on else "0")
        except Exception:  # noqa: BLE001 - no database: only until the next map
            self.set_cvar("qlx_fragqEnforceLink", "1" if on else "0")
        self.load_config()
        if on:
            self.msg("^1FragQ:^7 linked Steam accounts are now required to play. Players without one are moved to "
                     "spectator: type ^5!link <your Discord id>^7 to link yours.")
            with self._lock:
                self._linked = {}   # check everyone again
            for p in self.players():
                if _is_steam_id(p.steam_id):
                    self._lookups.append(str(p.steam_id))
            self._wake.set()
        else:
            self.msg("^1FragQ:^7 linked Steam accounts are no longer required to play.")
        return STOP_ALL

    def cmd_setdiscord(self, player, msg, channel):
        cfg = self._cfg
        if not self.db.has_permission(player, cfg.get("admin_level", 3)):
            player.tell("^1FragQ:^7 you don't have permission to change that.")
            return STOP_ALL
        if len(msg) < 2:
            current = cfg.get("invite")
            player.tell(_text(f"^1FragQ:^7 Discord invite: ^5{current}^7. Change it with !setdiscord <invite URL>, remove it with !setdiscord off."
                              if current else "^1FragQ:^7 no Discord invite set. Usage: !setdiscord <invite URL>, such as https://discord.gg/abc123"))
            return STOP_ALL
        if msg[1].lower() in ("off", "none", "clear", "remove"):
            value, invite = "", None
        else:
            invite = _invite(msg[1])
            if not invite:
                player.tell("^1FragQ:^7 that isn't a Discord invite link. Use one like https://discord.gg/abc123 "
                            "(Discord: right-click the server -> Invite People; make it never expire).")
                return STOP_ALL
            value = invite
        try:
            self.db.set(DB_INVITE, value)
        except Exception:  # noqa: BLE001 - no database: only until the next map
            self.set_cvar("qlx_fragqDiscordInvite", value)
        self.load_config()
        player.tell(_text(f"^1FragQ:^7 players who aren't on the Discord are now told to join ^5{invite}^7." if invite
                          else "^1FragQ:^7 Discord invite removed."))
        return STOP_ALL

    def cmd_fragq(self, player, msg, channel):
        sub = msg[1].lower() if len(msg) > 1 else "status"
        cfg = self._cfg
        if sub in ("url", "key", "test") and not self.db.has_permission(player, 5):
            player.tell("^1FragQ:^7 that needs permission level 5.")
            return STOP_ALL
        if sub == "key" and getattr(channel, "name", "") != "console":
            # whatever was typed has already reached the server as chat: refuse it, and ask for a new key
            player.tell("^1FragQ:^7 set the key from the server console or rcon: ^5qlx !fragq key <key>^7. "
                        "If you just typed a key in chat, replace it on the FragQ Connectors page.")
            return STOP_ALL
        if sub in ("url", "key"):
            if len(msg) < 3:
                player.tell(f"^1FragQ:^7 usage: !fragq {sub} <{'address' if sub == 'url' else 'connector key'}>")
                return STOP_ALL
            value = msg[2].strip()
            if sub == "url":
                url = _api_url(value)
                if not url:
                    player.tell("^1FragQ:^7 that is not a web address, e.g. https://fragq.example.com")
                    return STOP_ALL
                self.db.set(DB_URL, url)
                player.tell(_text(f"^1FragQ:^7 address set to ^5{url}^7. Run ^5!fragq test^7 to check it."))
            else:
                if not re.fullmatch(r"fq_[A-Za-z0-9_-]{20,100}\Z", value):
                    player.tell("^1FragQ:^7 that is not a FragQ connector key (they start with fq_).")
                    return STOP_ALL
                self.db.set(DB_KEY, value)
                player.tell(f"^1FragQ:^7 key set ({value[:9]}...). Run ^5!fragq test^7 to check it.")
            self.load_config()
            self._wake.set()
            return STOP_ALL
        if sub == "test":
            now = time.time()
            if now - self._command_at < 5:
                player.tell("^1FragQ:^7 wait a few seconds.")
                return STOP_ALL
            self._command_at = now
            self.load_config()
            self._test(self._reply_target(player, channel))
            return STOP_ALL
        if not self.db.has_permission(player, cfg.get("admin_level", 3)):
            player.tell("^1FragQ:^7 you don't have permission to see the FragQ settings.")
            return STOP_ALL
        with self._lock:
            last = dict(self._last)
        key = cfg["key"][:9] + "..." if cfg.get("key") else "^1not set^7"
        player.tell(_text(f"^1FragQ^7 {VERSION} on {RUNTIME}: {cfg.get('url') or '^1address not set^7'}, key {key}, "
                          f"results {'on' if cfg.get('results') else 'off'}, link required {'yes' if cfg.get('enforce') else 'no'}, "
                          f"Discord invite {cfg.get('invite') or 'not set'}, "
                          f"{len(self._outbox)} result(s) waiting. Last: {last['time'] or 'never'} ({last['message']})."))
        return STOP_ALL

    @staticmethod
    def _reply_target(player, channel):
        """Something a worker thread can reply to safely later: the console channel, or a player's
        client id + Steam ID so the reply can't reach whoever takes over the slot after they leave."""
        if getattr(channel, "name", "") == "console":
            return ("console", channel)
        return ("player", player.id, str(player.steam_id))

    # ------------------------------------------------------------ HTTP (worker threads only)

    def _request(self, cfg, method, path, body=None):
        """Returns (data, error, status). Never raises."""
        if not cfg.get("url") or not cfg.get("key"):
            return None, "FragQ address or connector key not set (!fragq url / !fragq key)", 0
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(cfg["url"] + path, data=data, method=method, headers={
            "Authorization": "Bearer " + cfg["key"], "Content-Type": "application/json",
            "Accept": "application/json", "User-Agent": f"fragq-{RUNTIME}/{VERSION}"})
        ctx = None if cfg.get("verify_tls", True) else ssl._create_unverified_context()  # noqa: S323 - opt-in
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as resp:
                return json.loads(resp.read().decode("utf-8")), None, resp.status
        except urllib.error.HTTPError as e:
            try:
                msg = json.loads(e.read().decode("utf-8")).get("error") or e.reason
            except Exception:  # noqa: BLE001 - not a FragQ reply (proxy page etc.)
                msg = e.reason
            return None, f"HTTP {e.code}: {msg}", e.code
        except Exception as e:  # noqa: BLE001 - network errors, bad JSON, TLS
            return None, str(getattr(e, "reason", e))[:200], 0

    def _worker(self):
        next_watch = 0.0
        while not self._stop.is_set():
            with self._lock:   # a finished match is sent FINAL_STATS_WAIT after its MATCH_REPORT
                wait = max(0.0, self._finish_at - time.time()) if self._report is not None else 5.0
            if wait:
                self._wake.wait(min(wait, 5.0))
            self._wake.clear()
            cfg = self._config()
            try:
                self._finish_match(cfg)
                if self._outbox:
                    self._send_results(cfg)
                now = time.time()
                if self._watch and now >= next_watch:
                    next_watch = now + 10
                    for sid, (_, until) in list(self._watch.items()):
                        if now > until:
                            self._watch.pop(sid, None)
                        else:
                            self._lookups.append(sid)
                if self._lookups:
                    self._run_lookups(cfg)
            except Exception:  # noqa: BLE001 - keep the worker alive whatever a reply contains
                self.logger.exception("fragq: worker error")

    def _finish_match(self, cfg):
        with self._lock:
            if self._report is None or time.time() < self._finish_at:
                return
            report, players = self._report, self._match
            self._report, self._match = None, {}
        payload = self._build(cfg, report, players)
        if payload:
            self._outbox.append([payload, 0, 0.0])
        elif cfg.get("results"):
            self.logger.info("fragq: the match had too few players, no results sent")

    # ------------------------------------------------------------ results

    def _build(self, cfg, report, players):
        """The FragQ result for a finished match, or None when there is nothing worth posting."""
        if not cfg.get("results"):
            return None
        mode = str(report.get("GAME_TYPE") or "").lower()
        played = {sid: p for sid, p in players.items() if p.get("team") in (0, 1, 2) and (p["time"] > 0 or p["quit"])}
        if len(played) < cfg.get("min_players", 2):
            return None
        length = _int(report.get("GAME_LENGTH"), 0)
        teams_on = mode in TEAM_MODES and any(p["team"] in (1, 2) for p in played.values())

        def acc(p):
            return 100.0 * p["hits"] / p["shots"] if p["shots"] else 0.0

        def best(label, key, pool, lowest=False, fmt="{:,}"):
            pool = [(sid, key(p)) for sid, p in pool.items()]
            if not pool:
                return None
            top = (min if lowest else max)(v for _, v in pool)
            return {"label": label, "players": [sid for sid, v in pool if v == top][:16], "value": fmt.format(top)}

        stayed = {sid: p for sid, p in played.items() if not p["quit"]}
        full = {sid: p for sid, p in stayed.items() if not length or p["time"] >= length / 2}
        aimed = {sid: p for sid, p in played.items() if p["shots"] >= cfg.get("min_shots", 50)}
        quitters = [sid for sid, p in played.items() if p["quit"]]
        highlights = [h for h in (
            best("Top Damage", lambda p: p["dealt"], played),
            best("Least Damage", lambda p: p["dealt"], full or stayed, lowest=True),
            best("Most Damage Taken", lambda p: p["taken"], played),
            best("Most Frags", lambda p: p["kills"], played),
            best("Highest Accuracy", acc, aimed, fmt="{:.1f}%"),
        ) if h]
        if not teams_on:
            winner = [sid for sid, p in stayed.items() if p.get("rank") == 1]
            if winner:
                highlights.insert(0, {"label": "Winner", "players": winner[:16]})
        highlights.append({"label": "Quitters", "players": quitters[:16]} if quitters else {"label": "Quitters", "value": "None"})

        order = sorted(played.items(), key=lambda kv: (kv[1]["quit"], -kv[1]["score"]))
        out = {
            "version": 1, "match_uid": str(report.get("MATCH_GUID") or "") or None, "game": "Quake Live",
            "map": str(report.get("MAP") or "") or None, "mode": mode.upper() or None,
            "duration": length or None, "server": cfg.get("server") or None,
            "players": [{
                "id": sid, "id_type": "steam", "name": p["name"], "quit": p["quit"],
                "team": TEAMS.get(p["team"]) if teams_on else None,
                "stats": {"Score": p["score"], "K": p["kills"], "D": p["deaths"], "Dmg": p["dealt"],
                          "Taken": p["taken"], "Acc": f"{acc(p):.0f}%" if p["shots"] else "-"},
            } for sid, p in order],
            "highlights": highlights,
            "table": ["Score", "K", "D", "Dmg", "Acc"],
        }
        if teams_on:
            red, blue = _int(report.get("TSCORE0"), 0), _int(report.get("TSCORE1"), 0)
            out["teams"] = [{"name": "Red", "score": red}, {"name": "Blue", "score": blue}]
            out["winner"] = "Red" if red > blue else "Blue" if blue > red else None
        return out

    def _send_results(self, cfg):
        now = time.time()
        for item in list(self._outbox):
            payload, attempts, next_try = item
            if now < next_try:
                continue
            data, error, status = self._request(cfg, "POST", "/results", payload)
            stamp = time.strftime("%Y-%m-%d %H:%M:%S")
            if error is None:
                self._outbox.remove(item)
                where = f"match #{data.get('match_id')}" if data.get("match_id") else "no FragQ match"
                message = f"{data.get('status')} ({where})"
            elif 400 <= status < 500 and status not in (408, 429):
                self._outbox.remove(item)   # FragQ refused it: sending it again won't help
                message = error + "; result dropped"
            elif attempts >= len(RESULT_RETRIES):
                self._outbox.remove(item)
                message = error + "; result dropped after retries"
            else:
                item[1], item[2] = attempts + 1, now + RESULT_RETRIES[attempts]
                message = error + f"; retrying in {RESULT_RETRIES[attempts]}s"
            with self._lock:
                self._last = {"time": stamp, "message": message}
            (self.logger.info if error is None else self.logger.warning)(f"fragq: match results: {message}")

    # ------------------------------------------------------------ linked players

    def _run_lookups(self, cfg):
        now = time.time()
        ids = []
        while self._lookups and len(ids) < LOOKUP_BATCH:
            sid = self._lookups.popleft()
            linked, at = self._linked.get(sid, (False, 0))
            ttl = LINKED_TTL if linked else UNLINKED_TTL
            if sid not in ids and (now - at >= ttl or sid in self._watch):
                ids.append(sid)
        if not ids:
            return
        data, error, _ = self._request(cfg, "POST", "/players/linked", {"steam_ids": ids})
        if error:
            self.logger.warning(f"fragq: linked-player check failed: {error}")
            with self._lock:
                for sid in ids:
                    self._linked[sid] = (None, now)   # don't keep players out while FragQ can't be asked
            return
        unlinked, confirmed = [], []
        with self._lock:
            for p in data.get("players") or []:
                sid = str(p.get("steam_id"))
                self._linked[sid] = (bool(p.get("linked")), now)
                if p.get("linked") and sid in self._watch:
                    confirmed.append((self._watch.pop(sid)[0], sid, p.get("discord_name") or "Discord"))
                elif not p.get("linked"):
                    unlinked.append(sid)
            if len(self._linked) > 2000:
                self._linked = {k: v for k, v in self._linked.items() if now - v[1] < LINKED_TTL}
        for client_id, sid, name in confirmed:
            self._tell_players([(client_id, sid)], _text(f"^1FragQ:^7 ^2linked^7 to {name}. You can join a team now."))
        if unlinked and cfg.get("enforce"):
            self._enforce(unlinked)

    @ql.next_frame
    def _enforce(self, steam_ids):
        """Move unlinked players who are playing to spectator, with a warning (game thread)."""
        if not self._cfg.get("enforce"):
            return
        now = time.time()
        wanted = set(steam_ids)
        for p in self.players():
            sid = str(p.steam_id)
            if sid not in wanted:
                continue
            if _team(p.team) != "spectator":
                try:
                    p.put("spectator")
                except Exception:  # noqa: BLE001 - minqlxtended may want its Team member
                    p.put(ql.Team.SPECTATOR)
            if now - self._warned.get(sid, 0) >= WARN_COOLDOWN:
                self._warned[sid] = now
                p.tell(_text(self._warning(sid, now)))
                invite = self._cfg.get("invite")
                p.center_print("^1Link your Steam account to play: ^7!link <your Discord id>" + (f"\n^7Discord: ^5{invite}" if invite else ""))

    @ql.thread
    def _request_link(self, reply_to, who, name, discord):
        client_id, sid = who
        data, error, _ = self._request(self._config(), "POST", "/link", {"steam_id": sid, "name": name, "discord": discord})
        if error:
            self._reply(reply_to, f"^1FragQ:^7 couldn't reach FragQ: {error}")
            return
        message = data.get("message") or data.get("status") or "done"
        if data.get("status") == "sent":
            self._watch[sid] = (client_id, time.time() + LINK_WATCH)
            self._wake.set()
        elif data.get("status") == "already_linked":
            with self._lock:
                self._linked[sid] = (True, time.time())
        colour = "^2" if data.get("ok") else "^3"
        lines = [f"^1FragQ:^7 {colour}{message}"]
        if data.get("status") == "not_member" and self._join_hint():
            lines.append(self._join_hint())
        self._reply(reply_to, *lines)

    @ql.thread
    def _test(self, reply_to):
        data, error, _ = self._request(self._config(), "GET", "/status")
        if error:
            self._reply(reply_to, f"^1FragQ:^7 connection failed: {error}")
            return
        c = data.get("connector") or {}
        can = c.get("can") or {}
        missing = [what for what, ok in (("results", can.get("results")), ("linked-player checks", can.get("check")),
                                         ("!link", can.get("link"))) if not ok]
        warn = f" ^3This key isn't allowed: {', '.join(missing)}.^7" if missing else ""
        self._reply(reply_to, f"^1FragQ:^7 connected to FragQ {data.get('fragq_version')} as '{c.get('name')}' "
                              f"({c.get('game')}), queues: {', '.join(c.get('queues') or []) or 'none'}.{warn}")

    # ------------------------------------------------------------ back on the game thread: tells only

    @ql.next_frame
    def _reply(self, reply_to, *lines):
        if reply_to[0] == "console":
            for line in lines:
                reply_to[1].reply(_text(line))
            return
        self._tell_now([reply_to[1:]], lines)

    @ql.next_frame
    def _tell_players(self, targets, line):
        self._tell_now(targets, [line])

    def _tell_now(self, targets, lines):
        for client_id, steam_id in targets:
            try:
                p = self.player(client_id)
            except Exception:  # noqa: BLE001 - NonexistentPlayerError: they left
                continue
            if p is None or str(p.steam_id) != steam_id:
                continue   # the slot now belongs to someone else
            for line in lines:
                p.tell(_text(line))
