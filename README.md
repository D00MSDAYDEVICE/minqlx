# minqlx
Collection of plugins for Quake Live

Add to your server's minqlx-plugins folder

# factoryvote.py
Allow the voting of factories you specify in baseq3/factories.txt<br>
Default admin level: 3<br>
Using without a number will list the factories.<br>
<br>
Commands:<br><br>
**!fv #** - Starts vote for the number selected<br>
**!fvv**  - Displays plugin version number

# lastmaps.py
Lists the last 5 played maps<br>
Useful to avoid voting overplayed maps.<br>
<br>
Commands:<br><br>
**!lm**<br>
**!lmv**  - Displays plugin version number

# motd.py (replacement)
Extended motd to multiple lines to overcome character length and format limitations/ease of use<br>
<br>
Commands:<br><br>
**!setmotd** `<line #>` `<message>`	- Set specific line of MOTD (1-10).<br>
**!addmotd** `<message>`      - Adds a new line to the next free slot.<br>
**!clearmotd**                - Clears all MOTD lines.<br>
**!reloadmotd** 				      - Reloads MOTD lines from **motd.cfg** in /baseq3<br>
<br>
Use **set qlx_motd1**, **set qlx_motd2**, etc to set from config file.<br>
Add /exec motd.cfg to config.cfg or simply !reloadmotd<br>
Config settings will not override existing motd (use !clearmotd and restart server).
