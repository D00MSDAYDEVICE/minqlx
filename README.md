# minqlx plugins
Collection of plugins for Quake Live

Add to your server's minqlx-plugins folder

## backfire.py
This is an extension plugin for minqlx to slap/punish players that do team damage<br>
This works similar to a reverse vampiric effect.<br>
Damage can be set to a specific amount per hit or proportional in your server config<br>
<br>
> [!NOTE]
> **Required:**<br>
> + Shino's minqlx fork until the master is updated. This is needed for the damage hook. You can get it/compile it from [HERE](https://github.com/mgaertne/minqlx).<br>
> + A factory or server with `g_friendlyfire = 1`<br>

Fixed slap damage:<br>

`qlx_backfireSlapAmount 20`

`qlx_backfireProportional 1`
1 = Use proportional slap damage, 0 = Use fixed damage<br>

`qlx_backfireMinHealth 1`
Minimum amout of health before punishing further (1 prevents death)<br>

`qlx_logDir`
Optional log directory, default is serverfolder/logs/backfire.log<br>

## factoryvote.py<br>

Allow the voting of factories you specify in baseq3/factories.txt<br>
Default admin level: 3<br>
Using without a number will list the factories.<br>
<br>
**Commands:**<br>
**!fv #** - Starts vote for the number selected<br>
**!factory** - Shows current factory<br>
**!fvv**  - Displays plugin version number

## lastmaps.py<br>
Lists the last 5 played maps<br>
Useful to avoid voting overplayed maps.<br>
<br>
**Commands:**<br>
**!lm**<br>
**!lmv**  - Displays plugin version number

## livescoreboard.py<br>
Outputs a simple scoreboard to HTML<br>
Made this for a quick and dirty way to import scores from other games into OBS.<br>
<br>
**Commands:**<br>
**!lscheck** - Check if plugin is running<br>
**!lsv**  - Displays plugin version number<br>
**!lsstyle**  - Set scoreboard style, Default: 1 , One-line: 2<br>
**!lstitle** - Set scoreboard title<br>
**!lsredname** - Set Red team name<br>
**!lsbluename** - Set Blue team name<br>
**!lscolor** - Set font color<br>
**!lsbgcolor** - Set backfround color<br>
**!lsupdate** - Force update of scoreboard<br>
**!lspath** - Set your own output path, such as: /var/www/html/server4<br>

CVARS for configs:<br>
qlx_scorerefresh "20" - time in seconds to auto-refresh<br>
qlx_livescorecolor<br>
qlx_livescorebgcolor<br>
qlx_lstitle<br>
qlx_lsredname<br>
qlx_lsbluename<br>
qlx_lspath<br>

## motd.py (replacement)<br>
Extended motd to multiple lines to overcome character length and format limitations/ease of use<br>
<br>
**Commands:**<br>
**!setmotd** `<line #>` `<message>`	- Set specific line of MOTD (1-10).<br>
**!addmotd** `<message>`      - Adds a new line to the next free slot.<br>
**!clearmotd**                - Clears all MOTD lines.<br>
**!reloadmotd** 				      - Reloads MOTD lines from **motd.cfg** in /baseq3<br>
<br>
Use **set qlx_motd1**, **set qlx_motd2**, etc to set from config file.<br>
Add /exec motd.cfg to config.cfg or simply !reloadmotd<br>
Config settings will not override existing motd (use !clearmotd and restart server).

## namesplus.py (replaces names.py)<br>
Added ability for admins to change players names <br>
Useful for those with blank names or lazy aliasing guys during tournaments :)<br>
Existing !name still functions for players<br>
Names now persist between reconnects until a !clear `<player ID #>` is performed.<br>
> [!NOTE]
> **qlx_plugins** must not contain "DEFAULT" as this includes the original "names" and will break namesplus<br>
> Therefore, add all default plugin names and/or your other plugins:<br>
> set qlx_plugins "plugin_manager, essentials, motd, permission, ban, silence, clan, namesplus, log, workshop"<br>

Additional settings:<br>
qlx_enforceAdminName<br>
qlx_enforceSteamName<br>

**Commands:**<br>
**!name** `<name>` - Player sets their own name<br>
**!setname** `<player ID #>` OR `<steam ID #>` `<New Name>`	- Admin sets a players name<br>
**!clear** `<player ID #>` - Removes Admin set name<br>
**!listnames** - Shows a list of Admin-set names<br>
**!npv** - Show version number<br>
