# BridgeDB by Nick Mathewson.
# Copyright (c) 2007-2009, The Tor Project, Inc.
# See LICENSE for licensing information

import calendar
import logging
import binascii
import sqlite3
import time
import hashlib
from functools import wraps
from ipaddr import IPAddress
from contextlib import contextmanager
import sys
import datetime

from bridgedb.Stability import BridgeHistory
import threading

toHex = binascii.b2a_hex
fromHex = binascii.a2b_hex
HEX_ID_LEN = 40
BRIDGE_REACHABLE, BRIDGE_BLOCKED = 0, 1

def _escapeValue(v):
    return "'%s'" % v.replace("'", "''")

def timeToStr(t):
    return time.strftime("%Y-%m-%d %H:%M", time.gmtime(t))
def strToTime(t):
    return calendar.timegm(time.strptime(t, "%Y-%m-%d %H:%M"))

#  The old DB system was just a key->value mapping DB, with special key
#  prefixes to indicate which database they fell into.
#
#     sp|<ID> -- given to bridgesplitter; maps bridgeID to ring name.
#     em|<emailaddr> -- given to emailbaseddistributor; maps email address
#            to concatenated ID.
#     fs|<ID> -- Given to BridgeTracker, maps to time when a router was
#            first seen (YYYY-MM-DD HH:MM)
#     ls|<ID> -- given to bridgetracker, maps to time when a router was
#            last seen (YYYY-MM-DD HH:MM)
#
# We no longer want to use em| at all, since we're not doing that kind
# of persistence any more.

# Here is the SQL schema.
SCHEMA2_SCRIPT = """
 CREATE TABLE Config (
     key PRIMARY KEY NOT NULL,
     value
 );

 CREATE TABLE Bridges (
     id INTEGER PRIMARY KEY NOT NULL,
     hex_key,
     address,
     or_port,
     distributor,
     first_seen,
     last_seen
 );

 CREATE UNIQUE INDEX BridgesKeyIndex ON Bridges ( hex_key );

 CREATE TABLE EmailedBridges (
     email PRIMARY KEY NOT NULL,
     when_mailed
 );

 CREATE INDEX EmailedBridgesWhenMailed on EmailedBridges ( email );

 CREATE TABLE BridgeMeasurements (
     id INTEGER PRIMARY KEY NOT NULL,
     hex_key,
     bridge_type,
     address,
     port,
     blocking_country,
     blocking_asn,
     measured_by,
     last_measured,
     verdict INTEGER
 );

 CREATE INDEX BlockedBridgesBlockingCountry on BridgeMeasurements(hex_key);

 CREATE TABLE WarnedEmails (
     email PRIMARY KEY NOT NULL,
     when_warned
 );

 CREATE INDEX WarnedEmailsWasWarned on WarnedEmails ( email );

 INSERT INTO Config VALUES ( 'schema-version', 2 ); 
"""

SCHEMA_2TO3_SCRIPT = """
 CREATE TABLE BridgeHistory (
     fingerprint PRIMARY KEY NOT NULL,
     address,
     port INT,
     weightedUptime LONG,
     weightedTime LONG,
     weightedRunLength LONG,
     totalRunWeights DOUBLE,
     lastSeenWithDifferentAddressAndPort LONG,
     lastSeenWithThisAddressAndPort LONG,
     lastDiscountedHistoryValues LONG,
     lastUpdatedWeightedTime LONG
 );

 CREATE INDEX BridgeHistoryIndex on BridgeHistory ( fingerprint );

 INSERT OR REPLACE INTO Config VALUES ( 'schema-version', 3 ); 
 """
SCHEMA3_SCRIPT = SCHEMA2_SCRIPT + SCHEMA_2TO3_SCRIPT


class BridgeData(object):
    """Value class carrying bridge information:
       hex_key      - The unique hex key of the given bridge
       address      - Bridge IP address
       or_port      - Bridge TCP port
       distributor  - The distributor (or pseudo-distributor) through which 
                      this bridge is being announced
       first_seen   - When did we first see this bridge online?
       last_seen    - When was the last time we saw this bridge online?
    """
    def __init__(self, hex_key, address, or_port, distributor="unallocated", 
                 first_seen="", last_seen=""):
        self.hex_key = hex_key
        self.address = address
        self.or_port = or_port
        self.distributor = distributor
        self.first_seen = first_seen
        self.last_seen = last_seen


class Database(object):
    def __init__(self, sqlite_fname):
        self._conn = openDatabase(sqlite_fname)
        self._cur = self._conn.cursor()
        self.sqlite_fname = sqlite_fname

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        #print "Closing DB"
        self._cur.close()
        self._conn.close()

    def getBridgeDistributor(self, bridge, validRings):
        """If a ``bridge`` is already in the database, get its distributor.

        :rtype: None or str
        :returns: The ``bridge`` distribution method, if one was
            already assigned, otherwise, returns None.
        """
        distribution_method = None
        cur = self._cur

        cur.execute("SELECT id, distributor FROM Bridges WHERE hex_key = ?",
                    (bridge.fingerprint,))
        result = cur.fetchone()

        if result:
            if result[1] in validRings:
                distribution_method = result[1]

        return distribution_method

    def insertBridgeAndGetRing(self, bridge, setRing, seenAt, validRings,
                               defaultPool="unallocated"):
        '''Updates info about bridge, setting ring to setRing.  Also sets
        distributor to `defaultPool' if setRing isn't a valid ring.

           Returns the name of the distributor the bridge is assigned to.
        '''
        cur = self._cur

        t = timeToStr(seenAt)
        h = bridge.fingerprint
        assert len(h) == HEX_ID_LEN

        # Check if this is currently a valid ring name. If not, move into
        # default pool.
        if setRing not in validRings:
            setRing = defaultPool

        cur.execute("SELECT id FROM Bridges WHERE hex_key = ?", (h,))
        v = cur.fetchone()
        if v is not None:
            bridgeId = v[0]
            # Update last_seen, address, port and (possibly) distributor.
            cur.execute("UPDATE Bridges SET address = ?, or_port = ?, "
                        "distributor = ?, last_seen = ? WHERE id = ?",
                        (str(bridge.address), bridge.orPort, setRing,
                         timeToStr(seenAt), bridgeId))
            return setRing
        else:
            # Insert it.
            cur.execute("INSERT INTO Bridges (hex_key, address, or_port, "
                        "distributor, first_seen, last_seen) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (h, str(bridge.address), bridge.orPort, setRing, t, t))
            return setRing

    def cleanEmailedBridges(self, expireBefore):
        cur = self._cur
        t = timeToStr(expireBefore)
        cur.execute("DELETE FROM EmailedBridges WHERE when_mailed < ?", (t,))

    def getEmailTime(self, addr):
        addr = hashlib.sha1(addr.encode('utf-8')).hexdigest()
        cur = self._cur
        cur.execute("SELECT when_mailed FROM EmailedBridges WHERE email = ?", (addr,))
        v = cur.fetchone()
        if v is None:
            return None
        return strToTime(v[0])

    def setEmailTime(self, addr, whenMailed):
        addr = hashlib.sha1(addr.encode('utf-8')).hexdigest()
        cur = self._cur
        t = timeToStr(whenMailed)
        cur.execute("INSERT OR REPLACE INTO EmailedBridges "
                    "(email,when_mailed) VALUES (?,?)", (addr, t))

    def getAllBridges(self):
        """Return a list of BridgeData value classes of all bridges in the
           database
        """
        retBridges = []
        cur = self._cur
        cur.execute("SELECT hex_key, address, or_port, distributor, "
                    "first_seen, last_seen  FROM Bridges")
        for b in cur.fetchall():
            bridge = BridgeData(b[0], b[1], b[2], b[3], b[4], b[5])
            retBridges.append(bridge)

        return retBridges

    def getBlockedBridges(self):
        """Return a dictionary of bridges that are blocked.

        :rtype: dict
        :returns: A dictionary that maps bridge fingerprints (as strings) to a
            three-tuple that captures its blocking state: (country,  address,
            port).
        """
        ms = self.__fetchBridgeMeasurements()
        return getBlockedBridgesFromSql(ms)

    def __fetchBridgeMeasurements(self):
        """Return all bridge measurement rows from the last three years.

        We limit our search to three years for performance reasons because the
        bridge measurement table keeps growing and therefore slowing down
        queries.

        :rtype: list
        :returns: A list of tuples.
        """
        cur = self._cur
        old_year = datetime.datetime.utcnow() - datetime.timedelta(days=365*3)
        cur.execute("SELECT * FROM BridgeMeasurements WHERE last_measured > "
                    "'%s' ORDER BY blocking_country DESC" %
                    old_year.strftime("%Y-%m-%d"))
        return cur.fetchall()

    def getBridgesForDistributor(self, distributor):
        """Return a list of BridgeData value classes of all bridges in the
           database that are allocated to distributor 'distributor'
        """
        retBridges = []
        cur = self._cur
        cur.execute("SELECT hex_key, address, or_port, distributor, "
                    "first_seen, last_seen FROM Bridges WHERE "
                    "distributor = ?", (distributor, ))
        for b in cur.fetchall():
            bridge = BridgeData(b[0], b[1], b[2], b[3], b[4], b[5])
            retBridges.append(bridge)

        return retBridges

    def updateDistributorForHexKey(self, distributor, hex_key):
        cur = self._cur
        cur.execute("UPDATE Bridges SET distributor = ? WHERE hex_key = ?",
                    (distributor, hex_key))

    def getWarnedEmail(self, addr):
        addr = hashlib.sha1(addr.encode('utf-8')).hexdigest()
        cur = self._cur
        cur.execute("SELECT * FROM WarnedEmails WHERE email = ?", (addr,))
        v = cur.fetchone()
        if v is None:
            return False
        return True

    def setWarnedEmail(self, addr, warned=True, whenWarned=time.time()):
        addr = hashlib.sha1(addr.encode('utf-8')).hexdigest()
        t = timeToStr(whenWarned)
        cur = self._cur
        if warned == True:
            cur.execute("INSERT INTO WarnedEmails"
                        "(email,when_warned) VALUES (?,?)", (addr, t,))
        elif warned == False:
            cur.execute("DELETE FROM WarnedEmails WHERE email = ?", (addr,))

    def cleanWarnedEmails(self, expireBefore):
        cur = self._cur
        t = timeToStr(expireBefore)

        cur.execute("DELETE FROM WarnedEmails WHERE when_warned < ?", (t,))

    def updateIntoBridgeHistory(self, bh):
        cur = self._cur
        cur.execute("INSERT OR REPLACE INTO BridgeHistory values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (bh.fingerprint, str(bh.ip), bh.port,
                bh.weightedUptime, bh.weightedTime, bh.weightedRunLength,
                bh.totalRunWeights, bh.lastSeenWithDifferentAddressAndPort,
                bh.lastSeenWithThisAddressAndPort, bh.lastDiscountedHistoryValues,
                bh.lastUpdatedWeightedTime))
        return bh

    def delBridgeHistory(self, fp):
        cur = self._cur
        cur.execute("DELETE FROM BridgeHistory WHERE fingerprint = ?", (fp,))

    def getBridgeHistory(self, fp):
        cur = self._cur
        cur.execute("SELECT * FROM BridgeHistory WHERE fingerprint = ?", (fp,))
        h = cur.fetchone()
        if h is None: 
            return
        return BridgeHistory(h[0],IPAddress(h[1]),h[2],h[3],h[4],h[5],h[6],h[7],h[8],h[9],h[10])

    def getAllBridgeHistory(self):
        cur = self._cur
        v = cur.execute("SELECT * FROM BridgeHistory")
        if v is None: return
        for h in v:
            yield BridgeHistory(h[0],IPAddress(h[1]),h[2],h[3],h[4],h[5],h[6],h[7],h[8],h[9],h[10])

    def getBridgesLastUpdatedBefore(self, statusPublicationMillis):
        cur = self._cur
        v = cur.execute("SELECT * FROM BridgeHistory WHERE lastUpdatedWeightedTime < ?",
                        (statusPublicationMillis,))
        if v is None: return
        for h in v:
            yield BridgeHistory(h[0],IPAddress(h[1]),h[2],h[3],h[4],h[5],h[6],h[7],h[8],h[9],h[10])


def openDatabase(sqlite_file):
    conn = sqlite3.Connection(sqlite_file)
    cur = conn.cursor()
    try:
        try:
            cur.execute("SELECT value FROM Config WHERE key = 'schema-version'")
            val, = cur.fetchone()
            if val == 2:
                logging.info("Adding new table BridgeHistory")
                cur.executescript(SCHEMA_2TO3_SCRIPT)
            elif val != 3:
                logging.warn("Unknown schema version %s in database.", val)
        except sqlite3.OperationalError:
            logging.warn("No Config table found in DB; creating tables")
            cur.executescript(SCHEMA3_SCRIPT)
            conn.commit()
    finally:
        cur.close()
    return conn


_DB_FNAME = None
_LOCK = None
_LOCKED = 0
_OPENED_DB = None
_REFCOUNT = 0

class BridgeMeasurement(object):
    def __init__(self, id, fingerprint, bridge_type, address, port,
            country, asn, measured_by, last_measured, verdict):
        self.fingerprint = fingerprint
        self.country = country
        self.address = address
        self.port = port
        try:
            self.date = datetime.datetime.strptime(last_measured, "%Y-%m-%d")
        except ValueError:
            logging.error("Could not convert SQL date string '%s' to "
                            "datetime object." % last_measured)
            self.date = datetime.datetime(1970, 1, 1, 0, 0)
        self.verdict = verdict

    def compact(self):
        return (self.country, self.address, self.port)

    def __contains__(self, item):
        return (self.country == item.country and
                self.address == item.address and
                self.port == item.port)

    def newerThan(self, other):
        return self.date > other.date

    def conflicts(self, other):
        return (self.verdict != other.verdict and
                self.country == other.country and
                self.address == other.address and
                self.port == other.port)

def getBlockedBridgesFromSql(sql_rows):
    """Return a dictionary that maps bridge fingerprints to a list of
    bridges that are known to be blocked somewhere.

    :param list sql_rows: A list of tuples.  Each tuple represents an SQL row.
    :rtype: dict
    :returns: A dictionary that maps bridge fingerprints (as strings) to a
        three-tuple that captures its blocking state: (country,  address,
        port).
    """
    # Separately keep track of measurements that conclude that a bridge is
    # blocked or reachable.
    blocked = {}
    reachable = {}

    def _shouldSkip(m1):
        """Return `True` if we can skip this measurement."""
        # Use our 'reachable' dictionary if our original measurement says that
        # a bridge is blocked, and vice versa.  The purpose is to process
        # measurements that are possibly conflicting with the one at hand.
        d = reachable if m1.verdict == BRIDGE_BLOCKED else blocked
        maybe_conflicting = d.get(m1.fingerprint, None)
        if maybe_conflicting is None:
            # There is no potentially conflicting measurement.
            return False

        for m2 in maybe_conflicting:
            if m1.compact() != m2.compact():
                continue
            # Conflicting measurement.  If m2 is newer than m1, we believe m2.
            if m2.newerThan(m1):
                return True
            # Conflicting measurement.  If m1 is newer than m2, we believe m1,
            # and remove m1.
            if m1.newerThan(m2):
                d[m1.fingerprint].remove(m2)
                # If we're left with an empty list, get rid of the dictionary
                # key altogether.
                if len(d[m1.fingerprint]) == 0:
                    del d[m1.fingerprint]
                return False
        return False

    for fields in sql_rows:
        m = BridgeMeasurement(*fields)
        if _shouldSkip(m):
            continue

        d = blocked if m.verdict == BRIDGE_BLOCKED else reachable
        other_measurements = d.get(m.fingerprint, None)
        if other_measurements is None:
            # We're dealing with the first "blocked" or "reachable" measurement
            # for the given bridge fingerprint.
            d[m.fingerprint] = [m]
        else:
            # Do we have an existing measurement that agrees with the given
            # measurement?
            if m in other_measurements:
                d[m.fingerprint] = [m if m.compact() == x.compact() and
                                    m.newerThan(x) else x for x in other_measurements]
            # We're dealing with a new measurement.  Add it to the list.
            else:
                d[m.fingerprint] = other_measurements + [m]

    # Compact-ify the measurements in our dictionary.
    for k, v in blocked.items():
        blocked[k] = [i.compact() for i in v]
    return blocked

def clearGlobalDB():
    """Start from scratch.

    This is currently only used in unit tests.
    """
    global _DB_FNAME
    global _LOCK
    global _LOCKED
    global _OPENED_DB

    _DB_FNAME = None
    _LOCK = None
    _LOCKED = 0
    _OPENED_DB = None
    _REFCOUNT = 0

def initializeDBLock():
    """Create the lock

    This must be called before the first database query
    """
    global _LOCK

    if not _LOCK:
        _LOCK = threading.RLock()
    assert _LOCK

def setDBFilename(sqlite_fname):
    global _DB_FNAME
    _DB_FNAME = sqlite_fname

@contextmanager
def getDB(block=True):
    """Generator: Return a usable database handler

    Always return a :class:`bridgedb.Storage.Database` that is
    usable within the current thread. If a connection already exists
    and it was created by the current thread, then return the
    associated :class:`bridgedb.Storage.Database` instance. Otherwise,
    create a new instance, blocking until the existing connection
    is closed, if applicable.

    Note: This is a blocking call (by default), be careful about
        deadlocks!

    :rtype: :class:`bridgedb.Storage.Database`
    :returns: An instance of :class:`bridgedb.Storage.Database` used to
        query the database
    """
    global _DB_FNAME
    global _LOCK
    global _LOCKED
    global _OPENED_DB
    global _REFCOUNT

    assert _LOCK
    try:
        own_lock = _LOCK.acquire(block)
        if own_lock:
            _LOCKED += 1

            if not _OPENED_DB:
                assert _REFCOUNT == 0
                _OPENED_DB = Database(_DB_FNAME)

            _REFCOUNT += 1
            yield _OPENED_DB
        else:
            yield False
    finally:
        assert own_lock
        try:
            _REFCOUNT -= 1
            if _REFCOUNT == 0:
                _OPENED_DB.close()
                _OPENED_DB = None
        finally:
            _LOCKED -= 1
            _LOCK.release()

def dbIsLocked():
    return _LOCKED != 0
