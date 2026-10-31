# SPDX-License-Identifier: GPL-2.0-or-later
"""fragdex: send every player connection to a Fragdex server as it happens, and warn admins in game
when a tagged or banned player (or someone linked to one) joins.

One file for both minqlx and minqlxtended. Needs a Fragdex API key with "Add records" access
(Fragdex: Settings -> Fragdex API -> Create key).

Setup, from the server console or rcon (the key must not be typed in chat):
    qlx !fragdex url https://fragdex.example.com
    qlx !fragdex key fdx_...
    qlx !fragdex test
or in server.cfg:
    set qlx_fragdexUrl "https://fragdex.example.com"
    set qlx_fragdexKey "fdx_..."
A URL and key set with the command are kept in the bot's database and take precedence over the cvars.

Commands:
    !fragdex                  status: server, key, records waiting, last upload (qlx_fragdexPermission)
    !fragdex url <url>        set the Fragdex server (permission 5)
    !fragdex key <key>        set the API key (permission 5, server console / rcon only)
    !fragdex test             check the connection and the key (permission 5)
    !fragdex check <id>       look up a player by client id (as in /players) or SteamID64 (qlx_fragdexPermission)

Cvars:
    qlx_fragdexUrl              Fragdex server address, e.g. https://fragdex.example.com
    qlx_fragdexKey              API key
    qlx_fragdexServerName       name stored with each record (default: sv_hostname)
    qlx_fragdexRecord           1 = send connections to Fragdex (default 1)
    qlx_fragdexJoinAlerts       1 = check joining players and warn admins (default 1)
    qlx_fragdexAlertTags        tags that trigger a warning, comma separated; * = any tag (default "cheater,banned")
    qlx_fragdexAlertBans        1 = also warn about VAC / game bans (default 1)
    qlx_fragdexPermission       permission level for !fragdex and !fragdex check (default 5)
    qlx_fragdexAlertPermission  permission level that receives join warnings (default 2)
    qlx_fragdexInterval         seconds between uploads (default 15)
    qlx_fragdexVerifyTls        0 = accept a self-signed certificate (default 1)
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
# (player_connect, userinfo) take *_ so the same signature registers on both.
try:
    import minqlxtended as ql
    STOP_ALL = ql.Return.STOP_ALL
    RUNTIME = "minqlxtended"
except ImportError:
    import minqlx as ql
    STOP_ALL = ql.RET_STOP_ALL
    RUNTIME = "minqlx"

VERSION = "1.0.0"
DB_URL = "minqlx:fragdex:url"
DB_KEY = "minqlx:fragdex:key"
MAX_QUEUE = 5000          # records kept while Fragdex is unreachable
BATCH = 500               # records per upload (the server accepts up to 1000)
LOOKUP_BATCH = 100        # Steam IDs per lookup (server limit)
TIMEOUT = 10              # seconds per HTTP request
LOOKUP_TTL = 120          # don't look the same player up again within this many seconds (reconnects)
ALERT_COOLDOWN = 900      # warn about the same player at most once per this many seconds
COMMAND_COOLDOWN = 5      # between !fragdex test / check
MAX_LINKED_SHOWN = 3
COLOR_RE = re.compile(r"\^[0-9]")


def _is_steam_id(sid):
    s = str(sid)
    return len(s) == 17 and s.isdigit() and s.startswith("7656119")


def _api_url(url):
    """'fragdex.example.com', 'https://host:8443' or the full .../api/v1 URL -> the API base URL, or None."""
    url = (url or "").strip().rstrip("/")
    if not url:
        return ""
    if "://" not in url:
        url = "https://" + url
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc or parts.query or parts.fragment:
        return None
    return url if url.endswith("/api/v1") else url + "/api/v1"


def _text(s):
    """Safe for tell(): the QL client reads % as a format code and corrupts its state."""
    return str(s).replace("%", "％")


def _clean(s):
    return COLOR_RE.sub("", str(s or ""))


def _int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class fragdex(ql.Plugin):
    def __init__(self):
        super().__init__()
        self.set_cvar_once("qlx_fragdexUrl", "")
        self.set_cvar_once("qlx_fragdexKey", "")
        self.set_cvar_once("qlx_fragdexServerName", "")
        self.set_cvar_once("qlx_fragdexRecord", "1")
        self.set_cvar_once("qlx_fragdexJoinAlerts", "1")
        self.set_cvar_once("qlx_fragdexAlertTags", "cheater,banned")
        self.set_cvar_once("qlx_fragdexAlertBans", "1")
        self.set_cvar_once("qlx_fragdexPermission", "5")
        self.set_cvar_once("qlx_fragdexAlertPermission", "2")
        self.set_cvar_once("qlx_fragdexInterval", "15")
        self.set_cvar_once("qlx_fragdexVerifyTls", "1")

        # Shared with the worker thread. Cvars and the database are read on the game thread (load_config)
        # and handed over as a plain dict; hooks only append to the queues.
        self._lock = threading.Lock()
        self._records = collections.deque(maxlen=MAX_QUEUE)
        self._lookups = collections.deque(maxlen=MAX_QUEUE)
        self._last_name = {}          # steam_id -> last name queued, to skip userinfo changes that aren't names
        self._looked_up = {}          # steam_id -> time of the last join lookup
        self._alerted = {}            # steam_id -> time of the last warning
        self._command_at = 0.0
        self._cfg = {}
        self._last = {"time": None, "message": "nothing sent yet"}
        self._stop = threading.Event()
        self._wake = threading.Event()
        self.load_config()

        self.add_hook("player_connect", self.handle_player_connect)
        self.add_hook("player_disconnect", self.handle_player_disconnect)
        self.add_hook("userinfo", self.handle_userinfo)
        self.add_hook("map", self.handle_map)
        self.add_hook("unload", self.handle_unload)
        self.add_command("fragdex", self.cmd_fragdex, usage="[url <url> | key <key> | test | check <id>]")

        self._thread = threading.Thread(target=self._worker, name="fragdex", daemon=True)
        self._thread.start()

    # ------------------------------------------------------------ config (game thread)

    def load_config(self):
        try:
            url, key = self.db.get(DB_URL), self.db.get(DB_KEY)
        except Exception:  # noqa: BLE001 - no database configured: cvars only
            self.logger.warning("fragdex: database unavailable, using the qlx_fragdexUrl / qlx_fragdexKey cvars")
            url = key = None
        tags = (self.get_cvar("qlx_fragdexAlertTags") or "").lower()
        cfg = {
            "url": _api_url(url or self.get_cvar("qlx_fragdexUrl")) or "",
            "key": (key or self.get_cvar("qlx_fragdexKey") or "").strip(),
            "server": _clean(self.get_cvar("qlx_fragdexServerName") or self.get_cvar("sv_hostname"))[:80],
            "record": _int(self.get_cvar("qlx_fragdexRecord"), 1) != 0,
            "alerts": _int(self.get_cvar("qlx_fragdexJoinAlerts"), 1) != 0,
            "alert_tags": {t.strip() for t in tags.split(",") if t.strip()},
            "alert_bans": _int(self.get_cvar("qlx_fragdexAlertBans"), 1) != 0,
            "command_level": _int(self.get_cvar("qlx_fragdexPermission"), 5),
            "alert_level": _int(self.get_cvar("qlx_fragdexAlertPermission"), 2),
            "interval": max(5, _int(self.get_cvar("qlx_fragdexInterval"), 15)),
            "verify_tls": _int(self.get_cvar("qlx_fragdexVerifyTls"), 1) != 0,
        }
        with self._lock:
            self._cfg = cfg
        return cfg

    def _config(self):
        with self._lock:
            return dict(self._cfg)

    # ------------------------------------------------------------ hooks: O(1), append and return

    def handle_player_connect(self, player, *_):
        sid = str(player.steam_id)
        if not _is_steam_id(sid):
            return
        self._queue_record(player, sid, player.name)
        if self._cfg.get("alerts"):
            self._lookups.append(sid)
            self._wake.set()

    def handle_player_disconnect(self, player, *_):
        self._last_name.pop(str(player.steam_id), None)

    def handle_userinfo(self, player, changed, *_):
        name = changed.get("name") if isinstance(changed, dict) else None
        sid = str(player.steam_id)
        if name and _is_steam_id(sid) and self._last_name.get(sid) != name:
            self._queue_record(player, sid, name)

    def handle_map(self, *_):
        self.load_config()   # picks up cvars changed since the last map

    def handle_unload(self, plugin):
        if plugin == self.__class__.__name__:
            self._stop.set()
            self._wake.set()

    def _queue_record(self, player, sid, name):
        if not self._cfg.get("record"):
            return
        try:
            ip = player.ip or ""
        except Exception:  # noqa: BLE001 - a player mid-disconnect has no userinfo; the record keeps the name
            ip = ""
        self._last_name[sid] = name
        self._records.append({"steam_id": sid, "name": name or "", "ip": ip,
                              "seen_at": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())})

    # ------------------------------------------------------------ command (game thread)

    def cmd_fragdex(self, player, msg, channel):
        sub = msg[1].lower() if len(msg) > 1 else "status"
        cfg = self._cfg
        if sub in ("url", "key", "test"):
            if not self.db.has_permission(player, 5):
                player.tell("^1Fragdex:^7 that needs permission level 5.")
                return STOP_ALL
        if sub == "key" and getattr(channel, "name", "") != "console":
            # whatever was typed has already reached the server as chat: refuse it, and ask for a new key
            player.tell("^1Fragdex:^7 set the key from the server console or rcon: ^5qlx !fragdex key <key>^7. "
                        "If you just typed a key in chat, replace it under Settings -> Fragdex API -> Rotate.")
            return STOP_ALL

        if sub in ("url", "key"):
            if len(msg) < 3:
                player.tell(f"^1Fragdex:^7 usage: !fragdex {sub} <{'address' if sub == 'url' else 'API key'}>")
                return STOP_ALL
            value = msg[2].strip()
            if sub == "url":
                url = _api_url(value)
                if not url:
                    player.tell("^1Fragdex:^7 that is not a web address, e.g. https://fragdex.example.com")
                    return STOP_ALL
                self.db.set(DB_URL, url)
                player.tell(_text(f"^1Fragdex:^7 server set to ^5{url}^7. Run ^5!fragdex test^7 to check it."))
            else:
                if not re.fullmatch(r"fdx_[A-Za-z0-9_-]{20,100}\Z", value):
                    player.tell("^1Fragdex:^7 that is not a Fragdex API key (they start with fdx_).")
                    return STOP_ALL
                self.db.set(DB_KEY, value)
                player.tell(f"^1Fragdex:^7 API key set ({value[:10]}...). Run ^5!fragdex test^7 to check it.")
            self.load_config()
            self._wake.set()
            return STOP_ALL

        if sub in ("test", "check"):
            if sub == "check" and not self.db.has_permission(player, cfg.get("command_level", 5)):
                player.tell("^1Fragdex:^7 you don't have permission to look up players.")
                return STOP_ALL
            now = time.time()
            if now - self._command_at < COMMAND_COOLDOWN:
                player.tell(f"^1Fragdex:^7 wait {int(COMMAND_COOLDOWN - (now - self._command_at)) + 1}s.")
                return STOP_ALL
            target = None
            if sub == "check":
                if len(msg) < 3:
                    player.tell("^1Fragdex:^7 usage: !fragdex check <client id or SteamID64>")
                    return STOP_ALL
                target = msg[2]
                if not _is_steam_id(target):
                    try:
                        found = self.player(int(target)) if target.isdigit() and int(target) < 64 else None
                    except Exception:  # noqa: BLE001 - NonexistentPlayerError on either runtime
                        found = None
                    if found is None or not _is_steam_id(found.steam_id):
                        player.tell(_text(f"^1Fragdex:^7 no player with client id {target[:20]}."))
                        return STOP_ALL
                    target = str(found.steam_id)
            self._command_at = now
            reply_to = self._reply_target(player, channel)
            self.load_config()
            if sub == "test":
                self._test(reply_to)
            else:
                self._check(reply_to, target)
            return STOP_ALL

        if not self.db.has_permission(player, cfg.get("command_level", 5)):
            player.tell("^1Fragdex:^7 you don't have permission to see the Fragdex settings.")
            return STOP_ALL
        with self._lock:
            last = dict(self._last)
        key = cfg["key"][:10] + "..." if cfg.get("key") else "^1not set^7"
        player.tell(_text(f"^1Fragdex^7 {VERSION} on {RUNTIME}: server {cfg.get('url') or '^1not set^7'}, key {key}, "
                          f"{len(self._records)} record(s) waiting. Last upload: {last['time'] or 'never'} "
                          f"({last['message']})."))
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
        """Returns (data, error). Never raises."""
        if not cfg.get("url") or not cfg.get("key"):
            return None, "Fragdex server or API key not set (!fragdex url / !fragdex key)"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(cfg["url"] + path, data=data, method=method, headers={
            "Authorization": "Bearer " + cfg["key"], "Content-Type": "application/json",
            "Accept": "application/json", "User-Agent": f"fragdex-{RUNTIME}/{VERSION}"})
        ctx = None if cfg.get("verify_tls", True) else ssl._create_unverified_context()  # noqa: S323 - opt-in
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as resp:
                return json.loads(resp.read().decode("utf-8")), None
        except urllib.error.HTTPError as e:
            try:
                msg = json.loads(e.read().decode("utf-8")).get("error") or e.reason
            except Exception:  # noqa: BLE001 - not a Fragdex reply (proxy page etc.)
                msg = e.reason
            return None, f"HTTP {e.code}: {msg}"
        except Exception as e:  # noqa: BLE001 - network errors, bad JSON, TLS
            return None, str(getattr(e, "reason", e))[:200]

    def _worker(self):
        next_upload = 0.0
        while not self._stop.is_set():
            self._wake.wait(5)
            self._wake.clear()
            cfg = self._config()
            try:
                if self._lookups:
                    self._run_lookups(cfg)
                if self._records and time.time() >= next_upload:
                    self._upload(cfg)
                    next_upload = time.time() + cfg.get("interval", 15)
            except Exception:  # noqa: BLE001 - keep the worker alive whatever a reply contains
                self.logger.exception("fragdex: worker error")
        # unloading or reloading: one last attempt so the last few seconds of connections aren't lost
        if self._records:
            self._upload(self._config())

    def _upload(self, cfg):
        while self._records:
            batch = [self._records.popleft() for _ in range(min(BATCH, len(self._records)))]
            data, error = self._request(cfg, "POST", "/records", {"server": cfg.get("server", ""), "records": batch})
            stamp = time.strftime("%Y-%m-%d %H:%M:%S")
            if error:
                keep = not error.startswith(("HTTP 400", "HTTP 401", "HTTP 403", "HTTP 404"))
                if keep:   # Fragdex unreachable or busy: keep them for the next try
                    self._records.extendleft(reversed(batch))
                with self._lock:
                    self._last = {"time": stamp, "message": error + ("" if keep else f"; {len(batch)} records dropped")}
                self.logger.warning(f"fragdex: upload failed: {error}")
                return
            with self._lock:
                self._last = {"time": stamp,
                              "message": f"{data.get('added', 0)} added, {data.get('skipped', 0)} already known"}

    def _run_lookups(self, cfg):
        now = time.time()
        ids = []
        while self._lookups and len(ids) < LOOKUP_BATCH:
            sid = self._lookups.popleft()
            if sid not in ids and now - self._looked_up.get(sid, 0) >= LOOKUP_TTL:
                ids.append(sid)
                self._looked_up[sid] = now
        if len(self._looked_up) > 2000:
            self._looked_up = {k: t for k, t in self._looked_up.items() if now - t < LOOKUP_TTL}
            self._alerted = {k: t for k, t in self._alerted.items() if now - t < ALERT_COOLDOWN}
        if not ids:
            return
        data, error = self._request(cfg, "POST", "/players/lookup", {"steam_ids": ids})
        if error:
            self.logger.warning(f"fragdex: join check failed: {error}")
            return
        for p in data.get("players", []):
            sid = p.get("steam_id")
            reasons = self._reasons(p, cfg)
            if not reasons or now - self._alerted.get(sid, 0) < ALERT_COOLDOWN:
                continue
            self._alerted[sid] = now
            # permission checks are Redis reads: done here, not in the game frame
            admins = [(a.id, str(a.steam_id)) for a in self.players()
                      if self.db.has_permission(a, cfg.get("alert_level", 2))]
            line = f"^1Fragdex:^7 {p.get('name') or sid} ({sid}): {'; '.join(reasons)}"
            self.logger.info(_clean(line))
            if admins:
                self._tell_players(admins, _text(line))

    @staticmethod
    def _reasons(p, cfg):
        """Why an admin should look at this player, or [] if there is nothing to report."""
        if not p.get("known"):
            return []
        tags = cfg.get("alert_tags") or set()

        def flagged(entry):
            return [t for t in entry.get("tags") or [] if "*" in tags or t.lower() in tags]

        reasons = []
        own = flagged(p)
        if own:
            reasons.append("tagged " + ", ".join(own))
        steam = p.get("steam") or {}
        if cfg.get("alert_bans") and (steam.get("vac_bans") or steam.get("game_bans")):
            reasons.append(f"{steam.get('vac_bans') or 0} VAC / {steam.get('game_bans') or 0} game ban(s)")
        linked = []
        for alt in p.get("linked") or []:
            why = flagged(alt)
            if cfg.get("alert_bans") and (alt.get("vac_bans") or alt.get("game_bans")):
                why.append("banned")
            if why:
                linked.append(f"{alt.get('name') or alt.get('steam_id')} ({', '.join(why)})")
        if linked:
            more = f" and {len(linked) - MAX_LINKED_SHOWN} more" if len(linked) > MAX_LINKED_SHOWN else ""
            reasons.append("linked to " + ", ".join(linked[:MAX_LINKED_SHOWN]) + more)
        return reasons

    @ql.thread
    def _test(self, reply_to):
        data, error = self._request(self._config(), "GET", "/status")
        if error:
            self._reply(reply_to, f"^1Fragdex:^7 connection failed: {error}")
            return
        k = data.get("key") or {}
        warn = "" if k.get("write") else " ^1This key can't add records: allow 'Add records' in Settings -> Fragdex API.^7"
        self._reply(reply_to, f"^1Fragdex:^7 connected to Fragdex {data.get('version')} "
                              f"({data.get('players', 0):,} players) with key '{k.get('name')}'.{warn}")

    @ql.thread
    def _check(self, reply_to, steam_id):
        data, error = self._request(self._config(), "POST", "/players/lookup", {"steam_ids": [steam_id]})
        if error:
            self._reply(reply_to, f"^1Fragdex:^7 lookup failed: {error}")
            return
        p = (data.get("players") or [{}])[0]
        if not p.get("known"):
            self._reply(reply_to, f"^1Fragdex:^7 {steam_id} is not in Fragdex yet.")
            return
        steam = p.get("steam") or {}
        parts = [f"{p.get('name') or '?'} ({steam_id})", f"last seen {p.get('last_seen') or 'never'}",
                 f"tags: {', '.join(p.get('tags') or []) or 'none'}",
                 f"{steam.get('vac_bans') or 0} VAC / {steam.get('game_bans') or 0} game bans",
                 f"{p.get('linked_accounts', 0)} linked account(s)"]
        if p.get("discord_id"):
            parts.append(f"Discord {p['discord_id']}")
        lines = ["^1Fragdex:^7 " + ", ".join(parts)]
        alts = [f"{a.get('name') or '?'} ({a.get('steam_id')}{': ' + ', '.join(a['tags']) if a.get('tags') else ''})"
                for a in (p.get("linked") or [])[:MAX_LINKED_SHOWN]]
        if alts:
            lines.append("^1Fragdex:^7 linked: " + "; ".join(alts))
        self._reply(reply_to, *lines)

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
