# minqlx plugins
Collection of plugins for Quake Live - Add to your server's minqlx-plugins folder<br>
<br>
[afkplus](https://github.com/D00MSDAYDEVICE/minqlx/blob/main/README.md#afkpluspy)<br>
[aliasesplus](https://github.com/D00MSDAYDEVICE/minqlx/blob/main/README.md#aliasespluspy)<br>
[autokick](https://github.com/D00MSDAYDEVICE/minqlx/blob/main/README.md#autokickpy)<br>
[backfire](https://github.com/D00MSDAYDEVICE/minqlx/blob/main/README.md#backfirepy)<br>
[factoryvote](https://github.com/D00MSDAYDEVICE/minqlx/blob/main/README.md#factoryvotepy)<br>
[lastmaps](https://github.com/D00MSDAYDEVICE/minqlx/blob/main/README.md#lastmapspy)<br>
[livescoreboard](https://github.com/D00MSDAYDEVICE/minqlx/blob/main/README.md#livescoreboardpy)<br>
[mapmanager](https://github.com/D00MSDAYDEVICE/minqlx/blob/main/README.md#mapmanagerpy)<br>
[motd (replacement)](https://github.com/D00MSDAYDEVICE/minqlx/blob/main/README.md#motdpy-replacement)<br>
[namesplus](https://github.com/D00MSDAYDEVICE/minqlx/blob/main/README.md#namespluspy-replaces-namespy)<br>
<br>
## afkplus.py [right-click & save](https://raw.githubusercontent.com/D00MSDAYDEVICE/minqlx/refs/heads/main/afkplus.py) <br>
This plugin expands on iouonegirl's AFK plugin found here:<br>
https://github.com/dsverdlo/minqlx-plugins.<br>


`qlx_afk_enable_punishment 1` - Works as original<br>
`qlx_afk_enable_punishment 0` - Spectates player immediately upon value of:<br>
`qlx_afk_detection_seconds`

Gives admins the choice of an immediate move to spectate without waiting for a death

## aliasesplus.py [right-click & save](https://raw.githubusercontent.com/D00MSDAYDEVICE/minqlx/refs/heads/main/aliasesplus.py) <br>
Modified aliases.py to list player aliases without lagging the server.<br>
Results are displayed in chunks and/or limited (configurable)<br>
**CVARS:**<br>
`qlx_aliasesmode "limit"`   - limit or chunk<br>
`qlx_limitresults "10"`     - number of results to show<br>
`qlx_chunktime "500"`       - delay in ms between chunk sends

## autokick.py [right-click & save](https://raw.githubusercontent.com/D00MSDAYDEVICE/minqlx/refs/heads/main/autokick.py) <br>
This plugin will automatically kick users (after 1 warning) for using words added to the word list.<br>
<br>
**Commands:**<br>
**!addword** - Adds a word the list<br>
**!delword** - Removes/deletes word from the list<br>
**!listwords**  - Displays the word list<br>

**CVARS:**<br>
`qlx_autokickWarnings`  - number of warnings before kick <br>
`qlx_autokickMode` - Settings:<br>
kick   - warn N times then kick (original behavior)<br>
warn   - suppress message and notify the player, never kick<br>
silent - suppress message with no notification at all

**Optional:**<br> Regex patterns can also be added to autokick_patterns.txt<br>
An autokick.log file is also kept.

## backfire.py [right-click & save](https://raw.githubusercontent.com/D00MSDAYDEVICE/minqlx/refs/heads/main/backfire.py) <br>
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

## factoryvote.py [right-click & save](https://raw.githubusercontent.com/D00MSDAYDEVICE/minqlx/refs/heads/main/factoryvote.py) <br>

Allow the voting of factories you specify in baseq3/factories.txt<br>
Default admin level: 3<br>
Using without a number will list the factories.<br>
<br>
**Commands:**<br>
**!fv #** - Starts vote for the number selected<br>
**!factory** - Shows current factory<br>
**!check**  - Checks what factory is set on both the server and plugin<br>
**!fvv**  - Displays plugin version number
**!restorecfg**  - Reset cvars back to defaults (restore.cfg)

`ql_restorecfg_perm 2` (default: 2) Permission Level to use !restorecfg

PER-FACTORY CONFIG SUPPORT:<br>
 When a factory vote passes, the plugin will look for a matching .cfg file in
 the minqlx-plugins folder.<br>
<br>
   Example:<br>
   factory "ctf"  →  looks for  <plugins_dir>/ctf.cfg<br>
   factory "ca"   →  looks for  <plugins_dir>/ca.cfg<br>

If the file exists, it is executed as a server console command before the map change/factory update.<br>
This is useful for updating things like sv_mappoolfile to change the rotating maps for that mode.

## lastmaps.py [right-click & save](https://raw.githubusercontent.com/D00MSDAYDEVICE/minqlx/refs/heads/main/lastmaps.py) <br>
Shows a lists of the last 5 played maps<br>
Useful to avoid voting overplayed maps.<br>
<br>
**Commands:**<br>
**!lm** - Lists the last 5 played maps<br>
**!lmv**  - Displays plugin version number

## livescoreboard.py [right-click & save](https://raw.githubusercontent.com/D00MSDAYDEVICE/minqlx/refs/heads/main/livescoreboard.py)<br>
Outputs a simple scoreboard to HTML<br>
Made this for a quick and dirty way to import scores from other games into OBS.<br>
<br>
**Commands:**<br>
**!lscheck** - Check if plugin is running<br>
**!lsv**  - Displays plugin version number<br>
**!lsstyle**  - Set scoreboard style, Default: 1 , One-line: 2<br>
**!lstitle** - Set scoreboard title, blank to clear<br>
**!lsredname** - Set Red team name<br>
**!lsbluename** - Set Blue team name<br>
**!lscolor** - Set font color<br>
**!lsbgcolor** - Set background color<br>
**!lsupdate** - Force update of scoreboard<br>
**!lspath** - Set your own output path, such as: /var/www/html/server2, leave blank to see current value, clear to clear<br>
**!lscustom** - Add your own custom text to end of Style 2, blank to clear.


**CVARS for configs:**<br>
`qlx_scorerefresh` "20" - time in seconds to auto-refresh<br>
`qlx_livescorecolor`<br>
`qlx_livescorebgcolor`<br>
`qlx_lstitle`<br>
`qlx_lsredname`<br>
`qlx_lsbluename`<br>
`qlx_lspath`<br>
`qlx_lscustom`<br>

## mapmanager.py [right-click & save](https://raw.githubusercontent.com/D00MSDAYDEVICE/minqlx/refs/heads/main/mapmanager.py)<br>
Manages map rotation, enforces cooldowns on recently played maps, and tracks off-pool callvotes too. Also replaces/includes features of lastmaps.py
<br><br>
**Commands:**<br>
**!lm** - Lists the last 5 played maps<br>
**!mappool**  - Shows the next maps in rotation, marking which will be offered as vote candidates. Notes if the current map is off-pool.<br>
**!skipmaps** - Advance the rotation pointer by n steps (default 1). Useful for skipping unwanted upcoming maps. (Admin only)<br>
**!resetrotation** - Reload mappool.txt from disk and resync the rotation pointer to the current map. Use after editing mappool.txt without restarting. (Admin only)<br><br>
**!mmv** - Display the plugin version.<br>
**!mmdebug** - Dump full plugin state: pool contents, rotation index, map history, off-pool maps, cvar path, and internal flags. Useful for diagnosing issues.<br>
<br>
**CVARS for configs:**<br>
`mapmanager_mappool` - Full path to mappool.txt including filename<br>
`mapmanager_history_size` "5" - Number of recently played maps to block from voting<br>
`mapmanager_vote_maps` "3" - Number of maps shown as candidates in end-of-game votemap<br>
`manager_allownewvotes` "1"  - Allow callvote map after a vote already passed this round, 0 = block it<br>


## motd.py (replacement) [right-click & save](https://raw.githubusercontent.com/D00MSDAYDEVICE/minqlx/refs/heads/main/motd.py)<br>
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

## namesplus.py (replaces names.py) [right-click & save](https://raw.githubusercontent.com/D00MSDAYDEVICE/minqlx/refs/heads/main/namesplus.py)<br>
Added ability for admins to change players names <br>
Useful for those with blank names or lazy aliasing guys during tournaments :)<br>
Existing !name still functions for players<br>
Names now persist between reconnects until a !clear `<player ID #>` is performed.<br>
> [!NOTE]
> **qlx_plugins** must not contain "DEFAULT" as this includes the original "names" and will break namesplus<br>
> Therefore, add all default plugin names and/or your other plugins:<br>
> set qlx_plugins "plugin_manager, essentials, motd, permission, ban, silence, clan, namesplus, log, workshop"<br>

Additional settings:<br>
`qlx_enforceAdminName`<br>
`qlx_enforceSteamName`<br>

**Commands:**<br>
**!name** `<name>` - Player sets their own name<br>
**!setname** `<player ID #>` OR `<steam ID #>` `<New Name>`	- Admin sets a players name<br>
**!clear** `<player ID #>` - Removes Admin set name<br>
**!listnames** - Shows a list of Admin-set names<br>
**!npv** - Show version number<br>
