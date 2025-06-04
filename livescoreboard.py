import minqlx
import os
import datetime
from threading import Timer

LOG_FILE = os.path.join(os.path.dirname(__file__), "livescoreboard.log")
VERSION = "1.6"

class livescoreboard(minqlx.Plugin):
    def __init__(self):
        # Plugin paths
        self.plugin_path = self.get_cvar("qlx_pluginsPath") or os.path.expanduser("~")
        
        # Default values
        self.set_cvar_once("qlx_scorerefresh", "30")
        self.set_cvar_once("qlx_livescorecolor", "#ffffff")
        self.set_cvar_once("qlx_livescorebgcolor", "#000000")
        self.set_cvar_once("qlx_lstitle", "Live Scoreboard")
        self.set_cvar_once("qlx_livescorestyle", "1")
        self.set_cvar_once("qlx_lsredname", "Red Team")
        self.set_cvar_once("qlx_lsbluename", "Blue Team")
        self.set_cvar_once("qlx_lspath", os.path.join(self.plugin_path, "livescores"))

        self.livescore_folder = self.get_cvar("qlx_lspath") or os.path.join(self.plugin_path, "livescores")
        self.file_path = os.path.join(self.livescore_folder, "index.html")
        self.refresh_interval = int(self.get_cvar("qlx_scorerefresh")) 
        self.scoreboard_timer = None  # initialize the timer holder        

        # Commands for status, customization, and reset
        self.add_command("lscheck", self.cmd_check_status)
        self.add_command("lsv", self.cmd_version)
        self.add_command("lscolor", self.cmd_set_text_color, usage="!lscolor <#colorcode>", permission=5)
        self.add_command("lsbgcolor", self.cmd_set_bg_color, usage="!lsbgcolor <#colorcode>", permission=5)
        self.add_command("lsredname", self.cmd_set_red_name, usage="!lsredname <name>", permission=5)
        self.add_command("lsbluename", self.cmd_set_blue_name, usage="!lsbluename <name>", permission=5)
        self.add_command("lstitle", self.cmd_set_title, usage="!lstitle <text>", permission=5)
        self.add_command("lsstyle", self.cmd_set_style, usage="!lsstyle <1 or 2>", permission=5)
        self.add_command("resetls", self.cmd_reset_settings, usage="!resetls", permission=5)
        self.add_command("lsupdate", self.cmd_force_update, usage="!lsupdate", permission=5)
        self.add_command("lspath", self.cmd_set_path, usage="!lspath <folder_path>", permission=5)
        
        # Hooks for updating the scoreboard
        self.add_hook("player_connect", self.handle_player_connect)
        self.add_hook("game_start", self.handle_game_start)
        self.add_hook("round_end", self.handle_round_end)

        # Write initial scoreboard
        self.write_html()
        
        # Start the auto-refresh timer
        self.start_scoreboard_timer()

    def handle_player_connect(self, player):
        """Ensures scoreboard updates when players join."""
        self.write_html()     
    
    def get_team_data(self):
        blue_team_name = self.get_cvar("qlx_lsbluename") or "Blue Team"
        red_team_name = self.get_cvar("qlx_lsredname") or "Red Team"

        try:
            blue_score = int(self.game.blue_score)
            red_score = int(self.game.red_score)
        except:
            blue_score = red_score = 0

        return blue_team_name, red_team_name, blue_score, red_score

    def sanitize_color(self, color_code):
        """Ensures color codes start with '#'."""
        return color_code if color_code.startswith("#") else f"#{color_code}"

    def generate_html(self, blue_team, red_team, blue_score, red_score):
        """Creates a live scoreboard HTML file with customizable colors, title, and layout style."""
        title = self.get_cvar("qlx_lstitle")
        if title is None:
            title = "Live Scoreboard"

        text_color = self.sanitize_color(self.get_cvar("qlx_livescorecolor") or "#ffffff")
        bg_color = self.sanitize_color(self.get_cvar("qlx_livescorebgcolor") or "#000000")
        style = self.get_cvar("qlx_livescorestyle") or "1"

        try:
            map_title = self.game.map_title or "Unknown Map"
        except Exception:
            map_title = "Unknown Map"

        if style == "2":
            score_line = f"{red_team} [{red_score} - {blue_score}] {blue_team} | Map: {map_title}"
            css = f"""
                body {{
                    font-family: Arial, sans-serif;
                    text-align: center;
                    background-color: {bg_color};
                    color: {text_color};
                }}
                .scoreboard {{
                    width: 100%;
                    margin: auto;
                    padding: 20px;
                }}
                .score {{
                    font-size: 24px;
                    font-weight: bold;
                }}
            """
            scoreboard_html = f"""
                <div class="scoreboard">
                    <div class="score">{score_line}</div>
                </div>
            """
        else:
            css = f"""
                body {{
                    font-family: Arial, sans-serif;
                    text-align: center;
                    background-color: {bg_color};
                    color: {text_color};
                }}
                .scoreboard {{
                    width: 300px;
                    margin: auto;
                    padding: 20px;
                    border: 1px solid #fff;
                }}
                .map {{
                    font-size: 16px;
                    margin-bottom: 10px;
                }}
                .team {{
                    font-size: 20px;
                    margin: 10px 0;
                }}
                .score {{
                    font-size: 24px;
                    font-weight: bold;
                }}
            """
            scoreboard_html = f"""
                <div class="scoreboard">
                    <div class="map">Current Map: {map_title}</div>
                    <div class="team">{red_team} <span class="score">{red_score}</span></div>
                    <div class="team">{blue_team} <span class="score">{blue_score}</span></div>
                </div>
            """
    
        return f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <title>{title}</title>
            <style>
                {css}
            </style>
        </head>
        <body>
            {f"<h1>{title}</h1>" if title.strip() else ""}
            {scoreboard_html}
        </body>
        </html>
        """

    def write_html(self):
        """Writes the scoreboard HTML file and logs the event."""
        blue_team, red_team, blue_score, red_score = self.get_team_data()
        html_content = self.generate_html(blue_team, red_team, blue_score, red_score)

        try:
            os.makedirs(self.livescore_folder, exist_ok=True)
            with open(self.file_path, "w") as file:
                file.write(html_content)
            self.log_debug(f"Scoreboard updated successfully! Saved to {self.file_path}")
        except Exception as e:
            self.log_debug(f"Error writing scoreboard: {e}")

    def update_scoreboard(self):
        """Performs an update and restarts the timer."""
        self.write_html()
        self.start_scoreboard_timer()  # re-schedule next update
        self.log_debug("Scoreboard refreshed via timer.")

    def start_scoreboard_timer(self):
        """Starts or restarts the scoreboard update timer."""
        self.stop_scoreboard_timer()
        self.refresh_interval = int(self.get_cvar("qlx_scorerefresh"))
        self.scoreboard_timer = Timer(self.refresh_interval, self.update_scoreboard)
        self.scoreboard_timer.start()

    def stop_scoreboard_timer(self):
        """Stops the running scoreboard timer if active."""
        try:
            if self.scoreboard_timer and self.scoreboard_timer.is_alive():
                self.scoreboard_timer.cancel()
        except:
            pass    
    
    def handle_game_start(self, _):
        """Ensures scoreboard updates after a game starts."""
        self.update_scoreboard()

    def handle_round_end(self, _):
        """Forces a scoreboard update at the end of each round."""
        self.write_html()

    def cmd_check_status(self, player, msg, channel):
        player.tell("^2[LiveScoreboard]^7 is currently loaded and running!")

    def cmd_version(self, player, msg, channel):
        player.tell(f"^2[LiveScoreboard]^7 Version: ^3{VERSION}")

    def cmd_set_text_color(self, player, msg, channel):
        if len(msg) != 2:
            player.tell("Usage: !lscolor <#colorcode>")
            return

        new_color = self.sanitize_color(msg[1])
        self.set_cvar("qlx_livescorecolor", new_color)
        player.tell(f"^2[LiveScoreboard]^7 Text color set to: {new_color}")
        self.write_html()

    def cmd_set_bg_color(self, player, msg, channel):
        if len(msg) != 2:
            player.tell("Usage: !lsbgcolor <#colorcode>")
            return

        new_color = self.sanitize_color(msg[1])
        self.set_cvar("qlx_livescorebgcolor", new_color)
        player.tell(f"^2[LiveScoreboard]^7 Background color set to: {new_color}")
        self.write_html()

    def cmd_set_red_name(self, player, msg, channel):
        if len(msg) < 2:
            player.tell("Usage: !lsredname <name>")
            return
        name = " ".join(msg[1:])
        self.set_cvar("qlx_lsredname", name)
        player.tell(f"^2[LiveScoreboard]^7 Red team name set to: ^1{name}")
        self.write_html()

    def cmd_set_blue_name(self, player, msg, channel):
        if len(msg) < 2:
            player.tell("Usage: !lsbluename <name>")
            return
        name = " ".join(msg[1:])
        self.set_cvar("qlx_lsbluename", name)
        player.tell(f"^2[LiveScoreboard]^7 Blue team name set to: ^4{name}")
        self.write_html()
    
    def cmd_set_title(self, player, msg, channel):
        """Updates the scoreboard title. Use !lstitle or !lstitle none to clear."""
        if len(msg) == 1 or (len(msg) == 2 and msg[1].lower() in ["none", "clear", '""']):
            self.set_cvar("qlx_lstitle", "")
            player.tell("^2[LiveScoreboard]^7 Title has been cleared.")
        else:
            new_title = " ".join(msg[1:])
            self.set_cvar("qlx_lstitle", new_title)
            player.tell(f"^2[LiveScoreboard]^7 Title set to: {new_title}")
    
        self.write_html()  # Update scoreboard immediately

    def cmd_set_style(self, player, msg, channel):
        if len(msg) != 2 or msg[1] not in ["1", "2"]:
            player.tell("Usage: !lsstyle <1 or 2>")
            return

        self.set_cvar("qlx_livescorestyle", msg[1])
        player.tell(f"^2[LiveScoreboard]^7 Style set to: {msg[1]}")
        self.write_html()

    def cmd_reset_settings(self, player, msg, channel):
        self.set_cvar("qlx_livescorecolor", "#ffffff")
        self.set_cvar("qlx_livescorebgcolor", "#000000")
        self.set_cvar("qlx_lstitle", "Live Scoreboard")
        self.set_cvar("qlx_livescorestyle", "1")
        self.set_cvar("qlx_lsbluename", "Blue Team")
        self.set_cvar("qlx_lsredname", "Red Team")
        player.tell("^2[LiveScoreboard]^7 All settings have been reset to default.")
        self.write_html()

    def cmd_set_path(self, player, msg, channel):
        if len(msg) == 1:
            # Show current path if no new path is provided
            player.tell(f"^2[LiveScoreboard]^7 Current path: ^3{self.file_path}")
            return

        new_path = " ".join(msg[1:])
        self.set_cvar("qlx_lspath", new_path)

        # Update internal path references
        self.livescore_folder = new_path
        self.file_path = os.path.join(self.livescore_folder, "index.html")

        player.tell(f"^2[LiveScoreboard]^7 Output path set to: ^3{self.file_path}")
        self.write_html()

    def log_debug(self, message):
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"[{timestamp}] {message}\n"

        try:
            with open(LOG_FILE, "a") as f:
                f.write(log_entry)
        except Exception as e:
            self.logger.warning(f"Failed to write to log file: {e}")
    
    def cmd_force_update(self, player, msg, channel):
        """Forces the scoreboard to regenerate immediately."""
        self.write_html()
        player.tell("^2[LiveScoreboard]^7 Scoreboard updated.")
