# ###################################################
# Copyright (C) 2012 The Unknown Horizons Team
# team@unknown-horizons.org
# This file is part of Unknown Horizons.
#
# Unknown Horizons is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the
# Free Software Foundation, Inc.,
# 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
# ###################################################

import hashlib
import logging
import textwrap

from fife.extensions.pychan.widgets import HBox, Icon, Label

from horizons.gui.mainmenu.playerdataselection import PlayerDataSelection
from horizons.gui.widgets.imagebutton import OkButton, CancelButton
from horizons.gui.window import Window, Dialog
from horizons.savegamemanager import SavegameManager
from horizons.constants import MULTIPLAYER
from horizons.network.networkinterface import NetworkInterface
from horizons.network import find_enet_module
from horizons.component.ambientsoundcomponent import AmbientSoundComponent
from horizons.util.color import Color
from horizons.util.python.callback import Callback
from horizons.util.savegameaccessor import SavegameAccessor

enet = find_enet_module()


class GamesList(Window):
	"""The start of the multiplayer menu.

	Shows a list of available games to join and buttons to create/load games.
	"""
	widget_name = 'multiplayermenu'

	def __init__(self, *args, **kwargs):
		self._main = kwargs.pop('main')
		super(GamesList, self).__init__(*args, **kwargs)

	def show(self):
		NetworkInterface().register_game_details_changed_callback(self._update_game_details)

		event_map = {
			'create' : self._show_create_game,
			'load'   : self._show_load_game,
			'join'   : self._join_game,
			'cancel' : self.windows.close,
			'refresh': Callback(self._refresh, play_sound=True),
		}

		self._widget_loader.reload(self.widget_name)
		self._widget = self._widget_loader[self.widget_name]
		self._widget.mapEvents(event_map)

		refresh_worked = self._refresh()
		if not refresh_worked:
			self.windows.close()
			return

		self._widget.findChild(name='gamelist').capture(self._update_game_details)
		self._widget.findChild(name='showonlyownversion').capture(self._refresh)

		self._playerdata = PlayerDataSelection(self._widget, self._widget_loader)

		self._capture_escape(self._widget)
		self._widget.show()
		self._focus(self._widget)

	def hide(self):
		self._widget.hide()

	def close(self):
		super(GamesList, self).close()
		# When this window is closed, the player exits the multiplayer - we need to
		# close the fake MultiplayerMenu window as well.
		self._main._do_close()

	def _refresh(self, play_sound=False):
		"""Refresh list of games.

		@param play_sound: whether to play the refresh sound
		@return bool, whether refresh worked
		"""
		if play_sound:
			AmbientSoundComponent.play_special('refresh')

		only_this_version_allowed = self._widget.findChild(name='showonlyownversion').marked
		self._games = NetworkInterface().get_active_games(only_this_version_allowed)
		if self._games is None:
			return False

		gamelist = [self._game_display_name(g) for g in self._games]
		self._widget.distributeInitialData({'gamelist': gamelist})
		self._widget.distributeData({'gamelist': 0}) # select first map
		self._update_game_details()

		return True

	def _game_display_name(self, game):
		same_version = game.get_version() == NetworkInterface().get_clientversion()
		template = u"{password}{gamename}: {name} ({players}, {limit}){version}"
		return template.format(
			password="(Password!) " if game.has_password() else "",
			name=game.get_map_name(),
			gamename=game.get_name(),
			players=game.get_player_count(),
			limit=game.get_player_limit(),
			version=u" " + _("Version differs!") if not same_version else u"")

	def _get_selected_game(self):
		"""Return currently selected game."""
		index = self._widget.collectData('gamelist')
		if index == -1:
			return

		return self._games[index]

	def _update_game_details(self):
		"""Show information on the current selected game."""
		game = self._get_selected_game()
		if not game:
			return

		self._widget.findChild(name="game_map").text = _("Map: {map_name}").format(map_name=game.get_map_name())
		self._widget.findChild(name="game_name").text = _("Name: {game_name}").format(game_name=game.get_name())
		self._widget.findChild(name="game_creator").text = _("Creator: {game_creator}").format(game_creator=game.get_creator())
		#xgettext:python-format
		self._widget.findChild(name="game_playersnum").text = _("Players: {player_amount}/{player_limit}").format(
		                       player_amount=game.get_player_count(),
							   player_limit=game.get_player_limit())

		self._widget.findChild(name="game_info").adaptLayout()

	def _show_load_game(self):
		"""Show dialog for user to select a multiplayer savegame."""
		# TODO not tested

		self._apply_player_info()

		ret = self.windows.show(self._gui._saveload, mode='mp_load')
		if not ret: # user aborted
			return

		path, gamename, gamepassword = ret
		paths, names = SavegameManager.get_multiplayersaves()
		mapname = names[paths.index(path)]

		path = SavegameManager.get_multiplayersave_map(mapname)
		maxplayers = SavegameAccessor.get_players_num(path)
		maphash = SavegameAccessor.get_hash(path)

		self._create_game(mapname, maxplayers, gamename, gamepassword, maphash)

	def _show_create_game(self):
		self._apply_player_info()

		ret = self.windows.show(self._creategame)
		if ret:
			self._create_game(*ret)
		else:
			pass

	def _join_game(self):
		"""Joins a multiplayer game. Displays lobby for that specific game"""
		game = self._get_selected_game()
		if not game:
			return

		if game.get_uuid() == -1: # -1 signals no game
			AmbientSoundComponent.play_special('error')
			return

		if game.get_version() != NetworkInterface().get_clientversion():
			self.windows.show_popup(_("Wrong version"),
			                   #xgettext:python-format
			                        _("The game's version differs from your version. Every player in a multiplayer game must use the same version. This can be fixed by every player updating to the latest version. Game version: {game_version} Your version: {own_version}").format(
			                        game_version=game.get_version(),
			                        own_version=NetworkInterface().get_clientversion()))
			return

		# actual join
		if game.password:
			dialog = EnterPasswordDialog(self._widget_loader, manager=self.windows, game=game, join=self._actual_join)
			self.windows.show(dialog)
		else:
			self._actual_join(game)

	def _create_game(self, mapname, maxplayers, gamename, password, maphash=""):
		"""Create a game, join it, and display the lobby."""
		password = hashlib.sha1(password).hexdigest() if password != "" else ""
		game = NetworkInterface().creategame(mapname, maxplayers, gamename, maphash, password)
		if game is None:
			return

		self.windows.show(self._lobby)

	def _actual_join(self, game, password=""):
		"""Does the actual joining to the game."""
		self._apply_player_info()

		fetch = False
		if game.is_savegame() and SavegameAccessor.get_hash(SavegameManager.get_multiplayersave_map(game.mapname)) != game.get_map_hash():
			fetch = True

		if not NetworkInterface().joingame(game.get_uuid(), password, fetch):
			return False

		self.windows.show(self._lobby)

	def _apply_player_info(self):
		playername = self._playerdata.get_player_name()
		NetworkInterface().change_name(playername)

		playercolor = self._playerdata.get_player_color()
		NetworkInterface().change_color(playercolor.id)


class EnterPasswordDialog(Dialog):
	"""Dialog where the player can enter a password to join a game."""
	return_events = {
		OkButton.DEFAULT_NAME: True,
		CancelButton.DEFAULT_NAME: False,
	}
	widget_name = 'set_password'

	def __init__(self, *args, **kwargs):
		self._game = kwargs.pop('game')
		self._join = kwargs.pop('join')
		super(EnterPasswordDialog, self).__init__(*args, **kwargs)

	def prepare(self):
		password = self._widget.findChild(name='password')
		password.text = u""

		self._focus(password)

	def post(self, retval):
		if retval:
			password = hashlib.sha1(self._widget.collectData("password")).hexdigest()
			if not self._join(self._game, password):
				return self.windows.show(self)


class CreateGame(Dialog):
	return_events = {
		'cancel': False,
		'create': True
	}
	widget_name = 'multiplayer_creategame'

	def prepare(self):
		self._files, self._maps_display = SavegameManager.get_maps()
		self._widget.distributeInitialData({
			'maplist': self._maps_display,
			'playerlimit': range(2, MULTIPLAYER.MAX_PLAYER_COUNT)
		})

		# Select first entry
		if self._maps_display:
			self._widget.distributeData({
				'maplist': 0,
				'playerlimit': 0
			})
			self._update_infos()

		self._widget.mapEvents({'maplist/action': self._update_infos})

		password = self._widget.findChild(name="password")
		password.text = u""
		self._capture_escape(password)

		gamename = self._widget.findChild(name="gamename")
		gamename.capture(lambda: setattr(gamename, 'text', u''), 'mouseReleased', 'default')
		self._capture_escape(gamename)

	def post(self, retval):
		if retval:
			return (
				self._maps_display[self._widget.collectData('maplist')],
				self._widget.collectData('playerlimit') + 2, # 1 is the first entry
				self._widget.collectData('gamename'),
				self._widget.collectData('password')
			)

		return False

	def _update_infos(self):
		mapindex = self._widget.collectData('maplist')
		mapfile = self._files[mapindex]
		number_of_players = SavegameManager.get_recommended_number_of_players(mapfile)
		#xgettext:python-format
		self._widget.findChild(name="recommended_number_of_players_lbl").text = \
				_("Recommended number of players: {number}").format(number=number_of_players)


class GameLobby(Window):
	widget_name = 'multiplayer_gamelobby'

	def __init__(self, *args, **kwargs):
		super(GameLobby, self).__init__(*args, **kwargs)

		NetworkInterface().register_chat_callback(self._received_chat_message)
		NetworkInterface().register_player_joined_callback(self._player_joined)
		NetworkInterface().register_player_left_callback(self._player_left)
		NetworkInterface().register_player_changed_name_callback(self._player_changed_name)
		NetworkInterface().register_player_changed_color_callback(self._player_changed_color)
		NetworkInterface().register_kick_callback(self._player_kicked)
		NetworkInterface().register_player_toggle_ready_callback(self._player_toggled_ready)

		self._game = None

	def show(self):
		self._game = NetworkInterface().get_game()

		self._widget_loader.reload('multiplayer_gamelobby') # remove old chat messages, etc

		event_map = {
			'cancel': self.windows.close,
			'ready_btn': self._toggle_ready,
		}
		self._widget = self._widget_loader['multiplayer_gamelobby']
		self._widget.mapEvents(event_map)

		self._update_game_details()

		textfield = self._widget.findChild(name="chatTextField")
		textfield.capture(self._send_chat_message)
		textfield.capture(self._chatfield_onfocus, 'mouseReleased', 'default')

		self._widget.show()
		self._focus(self._widget)

	def hide(self):
		self._widget.hide()
		self._game = None

	def _update_game_details(self):
		self._widget.findChild(name="game_map").text = _("Map: {map_name}").format(map_name=self._game.get_map_name())
		self._widget.findChild(name="game_name").text = _("Name: {game_name}").format(game_name=self._game.get_name())
		self._widget.findChild(name="game_creator").text = _("Creator: {game_creator}").format(game_creator=self._game.get_creator())
		#xgettext:python-format
		self._widget.findChild(name="game_playersnum").text = _("Players: {player_amount}/{player_limit}").format(
		                           player_amount=self._game.get_player_count(),
		                           player_limit=self._game.get_player_limit())

		self._update_players_box()

	def _chatfield_onfocus(self):
		textfield = self._widget.findChild(name="chatTextField")
		textfield.text = u""
		textfield.capture(None, 'mouseReleased', 'default')

	def _send_chat_message(self):
		"""Sends a chat message. Called when user presses enter in the input field"""
		msg = self._widget.findChild(name="chatTextField").text
		if msg:
			self._widget.findChild(name="chatTextField").text = u""
			NetworkInterface().chat(msg)

	def _received_chat_message(self, game, player, msg):
		"""Receive a chat message from the network. Only possible in lobby state"""
		line_max_length = 40
		chatbox = self._widget.findChild(name="chatbox")
		full_msg = u""+ player + ": "+msg
		lines = textwrap.wrap(full_msg, line_max_length)
		for line in lines:
			chatbox.items.append(line)
		chatbox.selected = len(chatbox.items) - 1

	def _print(self, msg):
		line_max_length = 40
		chatbox = self._widget.findChild(name="chatbox")
		full_msg = u"* " + msg + " *"
		lines = textwrap.wrap(full_msg, line_max_length)
		for line in lines:
			chatbox.items.append(line)
		chatbox.selected = len(chatbox.items) - 1

	def _player_joined(self, game, player):
		self._print(_("{player} has joined the game").format(player=player.name))

	def _player_left(self, game, player):
		self._print(_("{player} has left the game").format(player=player.name))

	def _player_toggled_ready(self, game, plold, plnew, myself):
		self._update_players_box()
		if myself:
			if plnew.ready:
				self._print(_("You are now ready"))
			else:
				self._print(_("You are not ready anymore"))
		else:
			if plnew.ready:
				self._print(_("{player} is now ready").format(player=plnew.name))
			else:
				self._print(_("{player} not ready anymore").format(player=plnew.name))

	def _player_changed_name(self, game, plold, plnew, myself):
		if myself:
			self._print(_("You are now known as {new_name}").format(new_name=plnew.name))
		else:
			self._print(_("{player} is now known as {new_name}").format(player=plold.name, new_name=plnew.name))

	def _player_changed_color(self, game, plold, plnew, myself):
		if myself:
			self._print(_("You changed your color"))
		else:
			self._print(_("{player} changed its color").format(player=plnew.name))

	def _player_kicked(self, game, player, myself):
		if myself:
			self.windows.show_popup(_("Kicked"), _("You have been kicked from the game by creator"))
			self.windows.close()
		else:
			self._print(_("{player} got kicked by creator").format(player=player.name))

	def _update_players_box(self):
		"""Updates player list in game lobby.

		This function is called when there is a change in players (or their attributes.
		Uses players_vbox in multiplayer_gamelobby.xml and creates a hbox for each player.

		Also adds kick button for game creator.
		"""
		players_vbox = self._widget.findChild(name="players_vbox")

		players_vbox.removeAllChildren()

		gicon = Icon(name="gslider", image="content/gui/images/background/hr.png")
		players_vbox.addChild(gicon)

		def _add_player_line(player):
			pname = Label(name="pname_%s" % player['name'])
			pname.helptext = _("Click here to change your name and/or color")
			pname.text = player['name']
			if player['name'] == NetworkInterface().get_client_name():
				pname.capture(Callback(self._show_change_player_details_popup))
			pname.min_size = pname.max_size = (130, 15)

			pcolor = Label(name="pcolor_%s" % player['name'], text=u"   ")
			pcolor.helptext = _("Click here to change your name and/or color")
			pcolor.background_color = player['color']
			if player['name'] == NetworkInterface().get_client_name():
				pcolor.capture(Callback(self._show_change_player_details_popup))
			pcolor.min_size = pcolor.max_size = (15, 15)

			pstatus = Label(name="pstatus_%s" % player['name'])
			pstatus.text = "\t\t\t" + player['status']
			pstatus.min_size = pstatus.max_size = (120, 15)

			picon = Icon(name="picon_%s" % player['name'])
			picon.image = "content/gui/images/background/hr.png"

			hbox = HBox()
			hbox.addChild(pname)
			hbox.addChild(pcolor)
			hbox.addChild(pstatus)

			if NetworkInterface().get_client_name() == self._game.get_creator() and player['name'] != self._game.get_creator():
				pkick = CancelButton(name="pkick_%s" % player['name'], helptext=_("Kick {player}").format(player=player['name']))
				pkick.capture(Callback(NetworkInterface().kick, player['sid']))
				pkick.up_image = "content/gui/images/buttons/delete_small.png"
				pkick.down_image = "content/gui/images/buttons/delete_small.png"
				pkick.hover_image = "content/gui/images/buttons/delete_small_h.png"
				pkick.min_size = pkick.max_size = (20, 15)
				hbox.addChild(pkick)

			players_vbox.addChild(hbox)
			players_vbox.addChild(picon)

		for player in self._game.get_player_list():
			_add_player_line(player)

		players_vbox.adaptLayout()

	def _show_change_player_details_popup(self):
		"""Shows a dialog where the player can change its name and/or color"""

		def _get_unused_colors():
			"""Returns unused colors list in a game """
			assigned = [p["color"] for p in NetworkInterface().get_game().get_player_list() if p["name"] != NetworkInterface().get_client_name() ]
			available = set(Color) - set(assigned)
			return available

		dialog = self._widget_loader['set_player_details']
		dialog.findChild(name="playerdataselectioncontainer").removeAllChildren()

		playerdata = PlayerDataSelection(dialog, self._widget_loader, color_palette=_get_unused_colors())
		playerdata.set_player_name(NetworkInterface().get_client_name())
		playerdata.set_color(NetworkInterface().get_client_color())

		def _change_playerdata():
			playername = playerdata.get_player_name()
			NetworkInterface().change_name(playername)

			playercolor = playerdata.get_player_color()
			NetworkInterface().change_color(playercolor.id)

			self._update_game_details()
			dialog.hide()

		def _cancel():
			dialog.hide()

		events = {
			OkButton.DEFAULT_NAME: _change_playerdata,
			CancelButton.DEFAULT_NAME: _cancel
		}

		dialog.mapEvents(events)
		dialog.show()

	def _toggle_ready(self):
		NetworkInterface().toggle_ready()



class MultiplayerMenu(Window):
	log = logging.getLogger("networkinterface")

	def show(self):
		"""Shows main multiplayer menu"""
		if enet == None:
			headline = _(u"Unable to find pyenet")
			descr = _(u'The multiplayer feature requires the library "pyenet", '
			          u"which could not be found on your system.")
			advice = _(u"Linux users: Try to install pyenet through your package manager.")
			self.windows.close()
			self.windows.show_error_popup(headline, descr, advice)
			return

		if NetworkInterface() is None:
			try:
				NetworkInterface.create_instance()
			except RuntimeError as e:
				headline = _(u"Failed to initialize networking.")
				descr = _("Network features could not be initialized with the current configuration.")
				advice = _("Check the settings you specified in the network section.")
				self.windows.close()
				self.windows.show_error_popup(headline, descr, advice, unicode(e))
				return

		if not NetworkInterface().isconnected():
			connected = self.__connect_to_server()
			if not connected:
				return

		if NetworkInterface().isjoined():
			if not NetworkInterface().leavegame():
				return

		self._lobby = GameLobby(self._widget_loader, manager=self.windows)
		self._creategame = CreateGame(self._widget_loader, gui=self._gui, manager=self.windows)
		self._creategame.menu = self
		self._gameslist = GamesList(self._widget_loader, gui=self._gui, manager=self.windows, main=self)
		self._gameslist._creategame = self._creategame
		self._gameslist._lobby = self._lobby

		self.windows.show(self._gameslist)

	def close(self):
		# FIXME network connection should be closed once we exit the menu (but not when it
		# is closed because we started a game)
		#self.__cancel()
		pass

	def _do_close(self):
		self.windows.close()

	def hide(self):
		pass

	def __connect_to_server(self):
		NetworkInterface().register_game_prepare_callback(self.__prepare_game)
		NetworkInterface().register_game_starts_callback(self.__start_game)
		NetworkInterface().register_error_callback(self._on_error)
		NetworkInterface().register_game_terminated_callback(self.__game_terminated)
		NetworkInterface().register_player_fetch_game_callback(self.__fetch_game) #TODO

		try:
			NetworkInterface().connect()
		except Exception as err:
			headline = _(u"Fatal Network Error")
			descr = _(u"Could not connect to master server.")
			advice = _(u"Please check your Internet connection. If it is fine, "
			           u"it means our master server is temporarily down.")
			self.windows.close()
			self.windows.show_error_popup(headline, descr, advice, unicode(err))
			return False
		return True

	def _on_error(self, exception, fatal=True):
		"""Error callback"""

		# TODO what does this accomplish?
		if fatal and self._gui.session is not None:
			self._gui.session.timer.ticks_per_second = 0
		"""
		# TODO
		if self.dialog_executed:
			# another message dialog is being executed, and we were called by that action.
			# if we now trigger another message dialog, we will probably loop.
			return
		"""
		if not fatal:
			self.windows.show_popup(_("Error"), unicode(exception))
		else:
			self.windows.close()
			self.windows.show_popup(_("Fatal Network Error"),
		                 _("Something went wrong with the network:") + u'\n' +
		                 unicode(exception) )
			self._gui.quit_session(force=True)

	def __cancel(self):
		if NetworkInterface().isconnected():
			NetworkInterface().disconnect()

	def __game_terminated(self, game, errorstr):
		self.windows.show_popup(_("Terminated"), errorstr)
		self.show()

	def __prepare_game(self, game):
		self._gui.show_loading_screen()
		# send map data
		# NetworkClient().sendmapdata(...)
		import horizons.main
		horizons.main.prepare_multiplayer(game)

	def __start_game(self, game):
		import horizons.main
		horizons.main.start_multiplayer(game)

	def __fetch_game(self, game):
		self.__print_event_message(_("You fetched the savegame data"))
		self.__update_game_details()
