# -*- coding: utf-8 ; test-case-name: bridgedb.test.test_email_templates -*-
#_____________________________________________________________________________
#
# This file is part of BridgeDB, a Tor bridge distribution system.
#
# :authors: Isis Lovecruft <isis@torproject.org> 0xA3ADB67A2CDB8B35
#           please also see AUTHORS file
# :copyright: (c) 2007-2017, The Tor Project, Inc.
#             (c) 2013-2017, Isis Lovecruft
# :license: see LICENSE for licensing information
#_____________________________________________________________________________

"""
.. py:module:: bridgedb.distributors.email.templates
    :synopsis: Templates for formatting emails sent out by the email
               distributor.

bridgedb.distributors.email.templates
========================

Templates for formatting emails sent out by the email distributor.
"""

from __future__ import print_function
from __future__ import unicode_literals

import logging
import os

from datetime import datetime

from bridgedb import strings
from bridgedb.distributors.email.distributor import MAX_EMAIL_RATE


def addCommands(template):
    """Add some text telling a client about supported email command, as well as
    which Pluggable Transports are currently available.
    """
    # Tell them about the various email commands:
    cmdlist = []
    cmdlist.append(template.gettext(strings.EMAIL_MISC_TEXT.get(3)))
    for cmd, desc in strings.EMAIL_COMMANDS.items():
        command  = '  '
        command += cmd
        while not len(command) >= 25:  # Align the command descriptions
            command += ' '
        command += template.gettext(desc)
        cmdlist.append(command)

    commands  = "\n".join(cmdlist) + "\n\n"
    # And include the currently supported transports:
    commands += template.gettext(strings.EMAIL_MISC_TEXT.get(5))
    commands += "\n"
    for pt in strings._getSupportedTransports():
        commands += '  ' + pt + "\n"

    return commands

def addGreeting(template, clientName=None, welcome=False):
    greeting = ""
    clientName = clientName.decode('utf-8') if isinstance(clientName, bytes) else clientName

    if not clientName:
        greeting = template.gettext(strings.EMAIL_MISC_TEXT[7])
    else:
        greeting = template.gettext(strings.EMAIL_MISC_TEXT[6]) % clientName

    if greeting:
        if welcome:
            greeting += u' '
            greeting += template.gettext(strings.EMAIL_MISC_TEXT[4])
        greeting += u'\n\n'

    return greeting

def addKeyfile(template):
    return u'%s\n\n' % strings.BRIDGEDB_OPENPGP_KEY

def addBridgeAnswer(template, answer):
    # Give the user their bridges, i.e. the `answer`:
    bridgeLines  = template.gettext(strings.EMAIL_MISC_TEXT[0])
    bridgeLines += u"\n\n"
    bridgeLines += template.gettext(strings.EMAIL_MISC_TEXT[1])
    bridgeLines += u"\n\n"
    bridgeLines += u"%s\n\n" % answer

    return bridgeLines

def addHowto(template):
    """Add help text on how to add bridges to Tor Browser.

    :type template: ``gettext.NullTranslation`` or ``gettext.GNUTranslation``
    :param template: A gettext translations instance, optionally with fallback
        languages set.
    """
    howToTBB  = template.gettext(strings.HOWTO_TBB[1]) % strings.EMAIL_SPRINTF["HOWTO_TBB1"]
    howToTBB += u'\n\n'
    howToTBB += strings.EMAIL_REFERENCE_LINKS.get("HOWTO_TBB1")
    howToTBB += strings.EMAIL_REFERENCE_LINKS.get("HOWTO_TBB2")
    howToTBB += strings.EMAIL_REFERENCE_LINKS.get("HOWTO_TBB3")
    howToTBB += u'\n\n'
    return howToTBB

def buildKeyMessage(template, clientAddress=None):
    message  = addKeyfile(template)
    return message

def buildWelcomeText(template, clientAddress=None):
    sections = []
    sections.append(addGreeting(template, clientAddress.local, welcome=True))

    commands = addCommands(template)
    sections.append(commands)

    # Include the same messages as the homepage of the HTTPS distributor:
    welcome  = template.gettext(strings.WELCOME[0]) % strings.EMAIL_SPRINTF["WELCOME0"]
    welcome += template.gettext(strings.WELCOME[1])
    welcome += template.gettext(strings.WELCOME[2]) % strings.EMAIL_SPRINTF["WELCOME2"]
    sections.append(welcome)

    message  = u"\n\n".join(sections)
    # Add the markdown links at the end:
    message += strings.EMAIL_REFERENCE_LINKS.get("WELCOME0")

    return message

def buildAnswerMessage(template, clientAddress=None, answer=None):
    try:
        message  = addGreeting(template, clientAddress.local)
        message += addBridgeAnswer(template, answer)
        message += addHowto(template)
        message += u'\n\n'
        message += addCommands(template)
    except Exception as error:  # pragma: no cover
        logging.error("Error while formatting email message template:")
        logging.exception(error)

    return message

def buildSpamWarning(template, clientAddress=None):
    message = addGreeting(template, clientAddress.local)

    try:
        message += template.gettext(strings.EMAIL_MISC_TEXT[0])
        message += u"\n\n"
        message += template.gettext(strings.EMAIL_MISC_TEXT[2]) \
                   % str(MAX_EMAIL_RATE / 3600)
    except Exception as error:  # pragma: no cover
        logging.error("Error while formatting email spam template:")
        logging.exception(error)

    return message
