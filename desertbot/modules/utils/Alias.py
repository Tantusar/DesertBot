"""
Created on May 21, 2014

@author: HubbeKing, StarlitGhost
"""
from twisted.plugin import IPlugin
from desertbot.moduleinterface import IModule
from desertbot.modules.commandinterface import BotCommand, admin
from zope.interface import implementer

import os
import re
from collections import OrderedDict

from bs4 import UnicodeDammit
from ruamel.yaml import YAML

from desertbot.message import IRCMessage
from desertbot.response import IRCResponse, ResponseType

yaml = YAML()


@implementer(IPlugin, IModule)
class Alias(BotCommand):
    def triggers(self):
        return self.ownTriggers + list(self.aliases.keys())

    def onLoad(self):
        self.ownTriggers = ['alias']

        # load aliases from data file
        try:
            path = os.path.join(self.bot.dataPath, 'alias.yaml')
            with open(path, 'r') as file:
                self.data = yaml.load(file)

            if not self.data:
                self.data = {'aliases': {},
                             'help': {}}
        except FileNotFoundError:
            self.data = {'aliases': {},
                         'help': {}}

        self.aliases = self.data['aliases']
        self.aliasHelp = self.data['help']

        self._helpText = ("{1}alias ({0}) - does alias things. "
                          "Use '{1}help alias <subcommand>' for subcommand help. "
                          .format('/'.join(self.subCommands), self.bot.commandChar))

    @admin("Only my admins may create new aliases!")
    def _add(self, message):
        """add <alias> <command/alias> [<params>] -\
        aliases <alias> to the specified command/alias and parameters.\
        You can specify where parameters given to the alias should be inserted with $1, $2, $n.\
        The whole parameter string is $0. $sender and $channel can also be used"""
        if len(message.parameterList) <= 2:
            return IRCResponse(ResponseType.Say, "Alias what?", message.replyTo)

        alias = message.parameterList[1].lower()
        if alias in self.aliases:
            return IRCResponse(ResponseType.Say,
                               "'{}' is already an alias!".format(alias),
                               message.replyTo)

        if alias in self.bot.moduleHandler.mappedTriggers:
            return IRCResponse(ResponseType.Say,
                               "'{}' is already a command!".format(alias),
                               message.replyTo)

        aliased = message.parameterList[2].lower()
        if aliased not in self.bot.moduleHandler.mappedTriggers:
            return IRCResponse(ResponseType.Say,
                               "'{}' is not a valid command or alias!".format(aliased),
                               message.replyTo)

        newAlias = message.parameterList[2:]
        newAlias[0] = newAlias[0].lower()
        self._newAlias(alias, ' '.join(newAlias))
        self._syncAliases()

        return IRCResponse(ResponseType.Say,
                           "Created a new alias '{}' for '{}'.".format(alias, " ".join(newAlias)),
                           message.replyTo)

    @admin("Only my admins may delete aliases!")
    def _del(self, message):
        """del <alias> - deletes the alias named <alias>.\
        You can list multiple aliases to delete (space separated)"""
        if len(message.parameterList) == 1:
            return IRCResponse(ResponseType.Say, "Delete which alias?", message.replyTo)

        deleted = []
        skipped = []
        for aliasName in [alias.lower() for alias in message.parameterList[1:]]:
            if aliasName not in self.aliases:
                skipped.append(aliasName)
                continue

            deleted.append(aliasName)
            self._delAlias(aliasName)
        return IRCResponse(ResponseType.Say,
                           "Deleted alias(es) '{}', {} skipped".format(", ".join(deleted),
                                                                       len(skipped)),
                           message.replyTo)

    def _list(self, message):
        """list - lists all defined aliases"""
        return IRCResponse(ResponseType.Say,
                           "Current aliases: {}"
                           .format(", ".join(sorted(self.aliases.keys()))),
                           message.replyTo)

    def _show(self, message):
        """show <alias> - shows the contents of the specified alias"""
        if len(message.parameterList) == 1:
            return IRCResponse(ResponseType.Say,
                               "Show which alias?",
                               message.replyTo)
        alias = message.parameterList[1].lower()
        if alias in self.aliases:
            return IRCResponse(ResponseType.Say,
                               "'{}' is aliased to: {}".format(alias, self.aliases[alias]),
                               message.replyTo)
        else:
            return IRCResponse(ResponseType.Say,
                               "'{}' is not a recognized alias".format(alias),
                               message.replyTo)

    @admin("Only my admins may set alias help text!")
    def _help(self, message):
        """help <alias> <alias help> - defines the help text for the given alias"""
        if len(message.parameterList) == 1:
            return IRCResponse(ResponseType.Say,
                               "Set the help text for what alias to what?",
                               message.replyTo)

        alias = message.parameterList[1].lower()
        if alias not in self.aliases:
            return IRCResponse(ResponseType.Say,
                               "There is no alias called '{}'".format(alias),
                               message.replyTo)

        if len(message.parameterList) == 2:
            return IRCResponse(ResponseType.Say,
                               "You didn't give me any help text to set for {}!".format(alias),
                               message.replyTo)

        aliasHelp = " ".join(message.parameterList[2:])
        self._setAliasHelp(alias, aliasHelp)
        self._syncAliases()

        return IRCResponse(ResponseType.Say,
                           "'{}' help text set to '{}'"
                           .format(alias, aliasHelp),
                           message.replyTo)

    def _export(self, message):
        """export [<alias name(s)] - exports all aliases - or the specified aliases - \
        to a pastebin service, and returns a link"""
        if len(message.parameterList) > 1:
            # filter the alias dictionary by the listed aliases
            params = [alias.lower() for alias in message.parameterList[1:]]
            aliases = {alias: self.aliases[alias]
                       for alias in self.aliases
                       if alias in params}
            aliasHelp = {alias: self.aliasHelp[alias]
                         for alias in self.aliasHelp
                         if alias in params}

            if len(aliases) == 0:
                return IRCResponse(ResponseType.Say,
                                   "I don't have any of the aliases listed for export",
                                   message.replyTo)
        else:
            aliases = self.aliases
            aliasHelp = self.aliasHelp

            if len(aliases) == 0:
                return IRCResponse(ResponseType.Say,
                                   "There are no aliases for me to export!",
                                   message.replyTo)

        addCommands = ["{}alias add {} {}".format(self.bot.commandChar, name, command)
                       for name, command in aliases.items()]
        helpCommands = ["{}alias help {} {}".format(self.bot.commandChar, name, helpText)
                        for name, helpText in aliasHelp.items()]

        export = "{}\n\n{}".format("\n".join(sorted(addCommands)),
                                   "\n".join(sorted(helpCommands)))

        mh = self.bot.moduleHandler
        url = mh.runActionUntilValue('upload-dbco', export)
        return IRCResponse(ResponseType.Say,
                           "Exported {} aliases and {} help texts to {}".format(len(addCommands),
                                                                                len(helpCommands),
                                                                                url),
                           message.replyTo)

    @admin("Only my admins may import aliases!")
    def _import(self, message):
        """import <url> [<alias(es)>] -\
        imports all aliases from the given address, or only the listed aliases"""
        if len(message.parameterList) < 2:
            return IRCResponse(ResponseType.Say,
                               "You didn't give a url to import from!",
                               message.replyTo)

        if len(message.parameterList) > 2:
            onlyListed = True
            importList = [alias.lower() for alias in message.parameterList[2:]]
        else:
            onlyListed = False
            importList = None

        url = message.parameterList[1]
        try:
            response = self.bot.moduleHandler.runActionUntilValue('fetch-url', url)
        except ValueError:
            return IRCResponse(ResponseType.Say,
                               "'{}' is not a valid URL".format(url),
                               message.replyTo)
        if not response:
            return IRCResponse(ResponseType.Say,
                               "Failed to open page at {}".format(url),
                               message.replyTo)

        text = response.content
        text = UnicodeDammit(text).unicode_markup
        lines = text.splitlines()
        numAliases = 0
        numHelpTexts = 0
        for lineNumber, line in enumerate(lines):
            # Skip over blank lines
            if line == "":
                continue
            splitLine = line.split()
            if splitLine[0].lower() != "{}alias".format(self.bot.commandChar):
                notAlias = "Line {} at {} does not begin with {}alias".format(lineNumber,
                                                                              url,
                                                                              self.bot.commandChar)
                return IRCResponse(ResponseType.Say, notAlias, message.replyTo)
            subCommand = splitLine[1].lower()
            if subCommand not in ["add", "help"]:
                return IRCResponse(ResponseType.Say,
                                   "Line {} at {} is not an add or help command".format(lineNumber,
                                                                                        url),
                                   message.replyTo)

            aliasName = splitLine[2].lower()
            aliasCommand = splitLine[3:]
            aliasCommand[0] = aliasCommand[0].lower()

            # Skip over aliases that weren't listed, if any were listed
            if onlyListed and aliasName not in importList:
                continue

            if subCommand == "add":
                self._newAlias(aliasName, " ".join(aliasCommand))
                numAliases += 1
            elif subCommand == "help":
                aliasHelp = " ".join(splitLine[3:])
                self._setAliasHelp(aliasName, aliasHelp)
                numHelpTexts += 1

        self._syncAliases()

        importMessage = "Imported {} alias(es) and {} help string(s) from {}".format(numAliases,
                                                                                     numHelpTexts,
                                                                                     url)
        return IRCResponse(ResponseType.Say, importMessage, message.replyTo)

    subCommands = OrderedDict([
        ('add', _add),
        ('del', _del),
        ('list', _list),
        ('show', _show),
        ('help', _help),
        ('export', _export),
        ('import', _import)])

    def help(self, query):
        command = query[0].lower()
        if command in self.ownTriggers:
            if len(query) > 1:
                subCommand = query[1].lower()
                if subCommand in self.subCommands:
                    return ('{1}alias {0}'
                            .format(re.sub(r"\s+", " ", self.subCommands[subCommand].__doc__),
                                    self.bot.commandChar))
                else:
                    return self._unrecognizedSubcommand(subCommand)
            else:
                return self._helpText
        elif command in self.aliases:
            if command in self.aliasHelp:
                return self.aliasHelp[command]
            else:
                return "'{}' is an alias for: {}".format(command, self.aliases[command])

    def _unrecognizedSubcommand(self, subCommand):
        return ("unrecognized subcommand '{0}', "
                "available subcommands for alias are: {1}"
                .format(subCommand,
                        ', '.join(self.subCommands.keys())))

    def execute(self, message: IRCMessage):
        if message.command.lower() in self.ownTriggers:
            if len(message.parameterList) > 0:
                subCommand = message.parameterList[0].lower()
                if subCommand not in self.subCommands:
                    return IRCResponse(ResponseType.Say,
                                       self._unrecognizedSubcommand(subCommand),
                                       message.replyTo)
                return self.subCommands[subCommand](self, message)
            else:
                return IRCResponse(ResponseType.Say,
                                   self._helpText,
                                   message.replyTo)

        elif message.command.lower() in self.aliases:
            newMessage = self._aliasedMessage(message)
            newCommand = newMessage.command.lower()

            # aliased command is a valid trigger
            if newCommand in self.bot.moduleHandler.mappedTriggers:
                return self.bot.moduleHandler.mappedTriggers[newCommand].execute(newMessage)

    def _newAlias(self, alias, command):
        self.aliases[alias] = command
        self.bot.moduleHandler.mappedTriggers[alias] = self

    def _delAlias(self, alias):
        del self.aliases[alias]
        del self.bot.moduleHandler.mappedTriggers[alias]
        if alias in self.aliasHelp:
            del self.aliasHelp[alias]
        self._syncAliases()

    def _setAliasHelp(self, alias, aliasHelp):
        self.aliasHelp[alias] = aliasHelp

    def _syncAliases(self):
        path = os.path.join(self.bot.dataPath, 'alias.yaml')
        with open(path, 'w') as file:
            yaml.dump(self.data, file)

    def _aliasedMessage(self, message):
        if message.command.lower() not in self.aliases:
            return

        alias = self.aliases[message.command.lower()]
        newMsg = "{0}{1}".format(self.bot.commandChar, alias)

        newMsg = newMsg.replace("$sender", message.user.nick)
        if message.channel is not None:
            newMsg = newMsg.replace("$channel", message.channel.name)
        else:
            newMsg = newMsg.replace("$channel", message.user.nick)

        paramList = [self._mangleReplacementPoints(param) for param in message.parameterList]

        # if the alias contains numbered param replacement points, replace them
        if re.search(r'\$[0-9]+', newMsg):
            newMsg = newMsg.replace("$0",  " ".join(paramList))
            for i, param in enumerate(paramList):
                if newMsg.find("${}+".format(i+1)) != -1:
                    newMsg = newMsg.replace("${}+".format(i+1),
                                            " ".join(paramList[i:]))
                else:
                    newMsg = newMsg.replace("${}".format(i+1), param)
        # if there are no numbered replacement points, append the full parameter list instead
        else:
            newMsg += " {}".format(" ".join(paramList))

        newMsg = self._unmangleReplacementPoints(newMsg)

        return IRCMessage(message.type, message.user, message.channel, newMsg, self.bot)

    @staticmethod
    def _mangleReplacementPoints(string):
        # Replace alias replacement points with
        #  something that should never show up in messages/responses
        string = re.sub(r'\$([\w]+)', r'@D\1@', string)
        return string

    @staticmethod
    def _unmangleReplacementPoints(string):
        # Replace the mangled replacement points with unmangled ones
        string = re.sub(r'@D([\w]+)@', r'$\1', string)
        return string


alias = Alias()
