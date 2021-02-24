# -*- coding: utf-8 -*-
#
# This file is part of BridgeDB, a Tor bridge distribution system.
#
# :authors: Isis Lovecruft 0xA3ADB67A2CDB8B35 <isis@torproject.org>
#           please also see AUTHORS file
# :copyright: (c) 2007-2013, The Tor Project, Inc.
#             (c) 2007-2013, all entities within the AUTHORS file
# :license: 3-clause BSD, see included LICENSE for information

"""_langs.py - Storage for information on installed language support."""


def get_langs():
    """Return a list of two-letter country codes of translations which were
    installed (if we've already been installed).
    """
    return supported


#: This list will be rewritten by :func:`get_supported_langs` in setup.py at
#: install time, so that the :attr:`bridgedb.__langs__` will hold a list of
#: two-letter country codes for languages which were installed.
supported = set(['ar', 'az', 'be', 'bg', 'bn', 'bs', 'ca', 'cs', 'cy', 'da', 'de', 'el', 'en', 'en_GB', 'en_US', 'eo', 'es', 'es_AR', 'es_CL', 'es_MX', 'et', 'eu', 'fa', 'fi', 'fr', 'fr_CA', 'ga', 'gd', 'gl', 'gu', 'he', 'hi', 'hr', 'hr_HR', 'hu', 'hy', 'id', 'is', 'it', 'ja', 'ka', 'kk', 'km', 'kn', 'ko', 'lt', 'lv', 'mk', 'ml', 'mr', 'ms_MY', 'nb', 'nl', 'nl_BE', 'nn', 'pa', 'pl', 'pt', 'pt_BR', 'pt_PT', 'ro', 'ru', 'si_LK', 'sk', 'sk_SK', 'sl', 'sl_SI', 'sq', 'sr', 'sv', 'sw', 'ta', 'th', 'tr', 'uk', 'ur', 'uz', 'vi', 'zh_CN', 'zh_HK', 'zh_TW'])
