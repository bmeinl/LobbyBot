###
# Copyright (c) 2015, Benjamin Meinl
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
#   * Redistributions of source code must retain the above copyright notice,
#     this list of conditions, and the following disclaimer.
#   * Redistributions in binary form must reproduce the above copyright notice,
#     this list of conditions, and the following disclaimer in the
#     documentation and/or other materials provided with the distribution.
#   * Neither the name of the author of this software nor the name of
#     contributors to this software may be used to endorse or promote products
#     derived from this software without specific prior written consent.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED.  IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

###

import supybot.utils as utils
from supybot.commands import *
import supybot.plugins as plugins
import supybot.ircutils as ircutils
import supybot.callbacks as callbacks
try:
    from supybot.i18n import PluginInternationalization
    _ = PluginInternationalization('Lobby')
except ImportError:
    # Placeholder that allows to run the plugin on a bot
    # without the i18n module
    _ = lambda x: x
import supybot.ircdb as ircdb
import urllib2
import re
import xml.etree.ElementTree as ET
import json
import sqlite3
import datetime

VERSION = '1.0.4'

class Lobby(callbacks.Plugin):
    """Basic Lobby plugin, expect more soon."""
    def __init__(self, irc):
        self.__parent = super(Lobby, self)
        self.__parent.__init__(irc)
        with open('key') as f:
            self.steamkey = f.read().rstrip()
        with open('plugins/Lobby/locs.json') as json_data:
            self.locs = json.load(json_data)
        self.conn = sqlite3.connect('lobbybot.db')
        c = self.conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS users
                     (nickname text, steam_id text, used real default 0, created_at text default
                     CURRENT_TIMESTAMP)''')
        self.conn.commit()
        self.pm = False # send messages to PM
        self.tm = False # tournament mode (ie. pingtest lookup)


    def lobbyreg(self, irc, msg, args, url):
        """<Steam Profile URL>
        
           Registers with the tournament service. Example: .lobbyreg
           http://steamcommunity.com/id/break_it/"""
        c = self.conn.cursor()
        c.execute('SELECT 1 FROM users WHERE nickname=?', (msg.nick.lower(),))
        results = c.fetchone()
        if results:
            irc.reply("Already registered.", prefixNick=False, private=self.pm)
            return
        try:
            xml = urllib2.urlopen(url + '?xml=1').read()
        except urllib2.HTTPError:
            irc.reply('Could not find profile, maybe incorrect URL?',
                    private=self.pm)
            return

        e = ET.XML(xml)
        if e.findtext('privacyState') != 'public':
            irc.reply('Profile not set to public, please change that and try again.',
                    private=self.pm)
            return

        steam_id = e.findtext('steamID64')
        steam_name = e.findtext('steamID').encode('utf-8')
            
        c.execute('INSERT INTO users (nickname, steam_id) VALUES (?, ?)', (msg.nick.lower(),
                steam_id))
        self.conn.commit()
        irc.reply("{} registered successfully. Current Steam name: {}".format(msg.nick, steam_name),
                prefixNick=False, private=self.pm)
    lobbyreg = wrap(lobbyreg, ['url'])


    def lobby(self, irc, msg, args, nickname, message):
        """[<nickname>] [<message>]

        Checks to see if the calling user, or a given nickname, is in a lobby,
        and if so, will give a tinyurl you can click to join the lobby. You can 
        append an optional message.
        """
        if nickname is None:
            nickname = msg.nick
        if message is None:
            message = ""
        else:
            message = ' - ' + message

        c = self.conn.cursor()
        c.execute('SELECT steam_id FROM users WHERE nickname=?', (nickname.lower(),))
        results = c.fetchone()
        if results is None:
            irc.reply(nickname + " not registered. Use the .lobbyreg command to do so.", private=self.pm)
            return
        steam_id = results[0]

        try:
            url = 'http://api.steampowered.com/ISteamUser/GetPlayerSummaries/v0002/?key={}&steamids={}'.format(
                    self.steamkey, steam_id)
            jsons = urllib2.urlopen(url).read()
        except urllib2.HTTPError:
            irc.reply('Connection problem to Steam, please try again.', private=self.pm)
            return
        data = json.loads(jsons)
        steam_name = data['response']['players'][0]['personaname'].encode('utf-8')

        try:
            country_code = data['response']['players'][0]['loccountrycode']
            if country_code == 'US':
                state = data['response']['players'][0]['locstatecode']
                region = self.locs['US'][state]['region']
            else:
                region = self.locs[country_code]['region']
        except KeyError:
            region = "N/A"

        print_name = nickname + ' (Region: ' + region
        if steam_name != nickname:
            print_name += ', Steam: ' + steam_name
        print_name += ')'

        try:
            html = urllib2.urlopen('http://steamcommunity.com/profiles/' +
                    steam_id).read()
        except urllib2.HTTPError:
            irc.reply('Connection problem to Steam, please try again.', private=self.pm)
            return
        if self.tm:
            pingtest = re.search(r'((http://)?(www.)pingtest.net/result/.*?\.png)', html)
            if not pingtest:
                irc.reply('{} does not have their pingtest set! Please read our tournament rules.'.format(print_name),
                        prefixNick=False, private=self.pm)
                return
        match = re.search(r'<a href="([^"]+?)"' + 
                r' class="btn_green_white_innerfade btn_small_thin">', html)
        if not match:
            irc.reply('{} does not appear to be in a lobby.'.format(print_name),
                    prefixNick=False, private=self.pm)
            return
        try:
            link = urllib2.urlopen('http://tinyurl.com/api-create.php?url=' +
                    match.group(1)).read()
        except urllib2.HTTPError:
            irc.reply('Connection problem to TinyURL, please try again.', private=self.pm)
            return
        else:
            irc.reply("{} lobby: {}{}".format(print_name, link, message), prefixNick=False, private=self.pm)

        c.execute('UPDATE users SET used = used + 1 WHERE nickname=?',
                (nickname.lower(),))
        self.conn.commit()
    lobby = wrap(lobby, [optional('anything'), optional('text')])


    def lobbydelete(self, irc, msg, args, nickname):
        """<nickname>

        Removes the given nickname from the tournament service. Only usable by channel operators.
        """
        c = self.conn.cursor()
        c.execute('SELECT 1 FROM users WHERE nickname=?', (nickname.lower(),))
        results = c.fetchone()
        if results is None:
            irc.reply(nickname + ' not found in database.', private=self.pm)
            return
        if ircdb.checkCapability(msg.prefix, 'op'):
            c.execute('DELETE FROM users WHERE nickname=?', (nickname.lower(),))
            self.conn.commit()
            irc.reply('Deleted ' + nickname + ' from database.', private=self.pm)
        else:
            irc.reply('Insufficient capabilities. ' +
                    'Please contact a channel operator for assistance.', private=self.pm)
    lobbydelete = wrap(lobbydelete, ['anything'])


    def steam(self, irc, msg, args, nickname):
        """[<nickname>]
 
        Returns Steam information for the given nickname, or the calling user if
        no nickname was given.
        """
        if nickname is None:
            nickname = msg.nick
        c = self.conn.cursor()
        c.execute('SELECT steam_id FROM users WHERE nickname=?', (nickname.lower(),))
        results = c.fetchone()
        if results is None:
            irc.reply(nickname + " not registered.", private=self.pm)
            return
        (steam_id,) = results
        try:
            url = 'http://api.steampowered.com/ISteamUser/GetPlayerSummaries/v0002/?key={}&steamids={}'.format(
                    self.steamkey, steam_id)
            jsons = urllib2.urlopen(url).read()
        except urllib2.HTTPError:
            irc.reply('Connection problem to Steam, please try again.', private=self.pm)
            return
        data = json.loads(jsons)
        steam_name = data['response']['players'][0]['personaname'].encode('utf-8')
        steam_url = data['response']['players'][0]['profileurl']
        lastlogoff = data['response']['players'][0]['lastlogoff']
        lastseen = datetime.datetime.utcfromtimestamp(int(lastlogoff)).strftime(
                '%Y-%m-%d %H:%M:%S')
        state = int(data['response']['players'][0]['personastate'])
        if state == 0:
            irc.reply(('Steam name: {} - Last seen on Steam {} UTC - {} - SteamID: {}').format(
                steam_name, lastseen, steam_url, steam_id),
                private=self.pm, prefixNick=False)
        else:
            irc.reply(('Steam name: {} - Currently online - {} - SteamID: {}').format(
                steam_name, steam_url, steam_id),
                private=self.pm, prefixNick=False)
    steam = wrap(steam, [optional('anything')])


    def tmode(self, irc, msg, args, onoff):
        """[<ON|OFF>]

        Toggles tournament mode ON or OFF. Without argument returns the current
        mode. In tournament mode, invocations of .lobby will check existance of a pingtest.
        Only usable by channel operators.
        """
        if onoff is None:
            if self.tm: state = "ON"
            else: state = "OFF"
            irc.reply('Tournament Mode is {}'.format(state))
            return
        if ircdb.checkCapability(msg.prefix, 'op'):
            if onoff.upper() == "ON":
                self.tm = True
                irc.reply('Turned Tournament Mode on.')
            else:
                self.tm = False
                irc.reply('Turned Tournament Mode off.')
        else:
            irc.reply('Insufficient capabilities. ' +
                    'Please contact a channel operator for assistance.', private=self.pm)
    tmode = wrap(tmode, [optional(('literal', ('OFF', 'ON', 'on', 'off')))])


    def lobbystats(self, irc, msg, args, nickname):
        """[<nickname>]

        Gives some more or less useful stats about the given nickname, or the
        calling user if no nickname given.
        """
        if nickname is None:
            nickname = msg.nick
        c = self.conn.cursor()
        c.execute('SELECT used, created_at FROM users WHERE nickname=?', (nickname.lower(),))
        results = c.fetchone()
        if results is None:
            irc.reply(nickname + " not registered.", private=self.pm)
            return
        (used, created_at) = results
        irc.reply("{}: Registered at {} UTC - Lobby link generated {:.0f} times.".format(
            nickname, created_at, used), private=self.pm, prefixNick=False)
    lobbystats = wrap(lobbystats, [optional('anything')])


    def lobbyversion(self, irc, msg, args):
        """

        Returns current version of this plugin. Arbitrary versioning number,
        not supposed to make any sense.
        """
        irc.reply(VERSION, private=self.pm)
    lobbyversion = wrap(lobbyversion, [])


    def pingtest(self, irc, msg, args, nickname):
        """[<nickname>]
 
        Returns pingtest of the given nickname, or information on how to obtain
        the correct pingtest if no nickname was given.
        """
        if nickname is None:
            irc.reply("http://www.pingtest.net - Ping to Ashburn, VA for East Coast and San Francisco, CA for West"
            "Coast. You don't need to test packet loss, but results must be linked in your steam profile for the"
            " tournament", private=self.pm, prefixNick=False)
            return
        c = self.conn.cursor()
        c.execute('SELECT steam_id FROM users WHERE nickname=?', (nickname.lower(),))
        results = c.fetchone()
        if results is None:
            irc.reply(nickname + " not registered.", private=self.pm)
            return
        (steam_id,) = results
        try:
            html = urllib2.urlopen('http://steamcommunity.com/profiles/' +
                    steam_id).read()
        except urllib2.HTTPError:
            irc.reply('Connection problem to Steam, please try again.', private=self.pm)
            return
        pingtest = re.search(r'((http://)?(www.)pingtest.net/result/.*?\.png)', html)
        if not pingtest:
            irc.reply('{} does not have their pingtest set! Use .pingtest for details.'.format(nickname),
                    prefixNick=False, private=self.pm)
            return
        irc.reply("{} pingtest results: {}".format(nickname, pingtest.group(1)), private=self.pm, prefixNick=False)
    pingtest = wrap(pingtest, [optional('anything')])


Class = Lobby


# vim:set shiftwidth=4 softtabstop=4 expandtab textwidth=120:
