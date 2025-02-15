# Copyright 2012 Tom Hayward <tom@tomh.us>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import logging
import threading

from chirp import chirp_common, errors
from chirp.sources import base
from chirp.wxui import config

LOG = logging.getLogger(__name__)
CONF = config.get()

try:
    from suds.client import Client
    from suds import WebFault
    HAVE_SUDS = True
except ImportError:
    HAVE_SUDS = False

MODES = {
    "FM":     "FM",
    "AM":     "AM",
    "FMN":    "NFM",
    "D-STAR": "DV",
    "USB":    "USB",
    "LSB":    "LSB",
    "P25":    "P25",
    "DMR":    "DMR",
}

CA_COUNTIES = []
CA_PROVINCES = {}
logging.getLogger('suds').setLevel(logging.WARNING)


class RadioReferenceCAData(threading.Thread):
    def __init__(self, callback, username, password):
        super().__init__()
        self._callback = callback
        self._username = username
        self._password = password

    def run(self):
        radio = RadioReferenceRadio()
        radio.set_auth(self._username, self._password)
        try:
            counties, provinces = radio.do_getcanadacounties()
            LOG.debug('Got counties: %r' % counties)
            LOG.debug('Got provinces: %r' % provinces)
            CA_COUNTIES.clear()
            CA_COUNTIES.extend(counties)
            CA_PROVINCES.clear()
            CA_PROVINCES.update(provinces)
            self._callback(True)
        except Exception as e:
            LOG.exception('Failed to query RR: %s' % e)
            self._callback(e)


class RadioReferenceRadio(base.NetworkResultRadio):
    """RadioReference.com data source"""
    VENDOR = "RadioReference"

    URL = "http://api.radioreference.com/soap2/?wsdl"
    APPKEY = "46785108"

    def __init__(self):
        chirp_common.NetworkSourceRadio.__init__(self, None)

        if not HAVE_SUDS:
            raise errors.RadioError(
                "Suds library required for RadioReference.com import.\n" +
                "Try installing your distribution's python-suds package.")

        self._auth = {"appKey": self.APPKEY, "username": "", "password": ""}
        self._client = Client(self.URL)
        self._freqs = []
        self._modes = None
        self._zipcounty = None
        self._country = None

    def set_auth(self, username, password):
        self._auth["username"] = username
        self._auth["password"] = password

    def do_getcanadacounties(self):
        try:
            service = self._client.service
            provincelist = service.getCountryInfo(2, self._auth)
            provinces = {}
            clist = []
            for province in provincelist:
                provinces[province[2]] = province[0]
                provinceinfo = service.getStateInfo(province[0], self._auth)
                for county in provinceinfo.countyList:
                    if (county[1] != 'UNKNOWN' and county[1] != 'N/A' and
                            county[1] != 'Provincewide'):
                        # some counties are actually cities but whatever fml
                        clist.append([province[0], province[2],
                                      county[0], county[1]])
        except WebFault as err:
            raise errors.RadioError(err)
        return clist, provinces

    def do_fetch(self, status, params):
        """Fetches frequencies for all subcategories in a county
        (or zip if USA)."""
        status.send_status('Querying...', 5)
        self._freqs = []
        # if this method was accessed for the USA, use the zip; otherwise
        # use the county ID
        if params['country'] == 'US':
            try:
                service = self._client.service
                zipcode = service.getZipcodeInfo(params['zipcounty'],
                                                 self._auth)
                county = service.getCountyInfo(zipcode.ctid, self._auth)
            except WebFault as err:
                raise errors.RadioError(err)
        elif params['country'] == 'CA':
            try:
                service = self._client.service
                county = service.getCountyInfo(params['zipcounty'],
                                               self._auth)
            except WebFault as err:
                raise errors.RadioError(err)

        status_max = 0
        status_cur = 0
        for cat in county.cats:
            status_max += len(cat.subcats)
        status_max += len(county.agencyList)

        for cat in county.cats:
            for subcat in cat.subcats:
                result = self._client.service.getSubcatFreqs(subcat.scid,
                                                             self._auth)
                self._freqs += result
                status_cur += 1
                status.send_status(
                    'Fetching %s:%s' % (cat.cName, subcat.scName),
                    status_cur / status_max * 100)

        for agency in county.agencyList:
            agency = self._client.service.getAgencyInfo(agency.aid, self._auth)
            for cat in agency.cats:
                status_max += len(cat.subcats)
            for cat in agency.cats:
                for subcat in cat.subcats:
                    result = self._client.service.getSubcatFreqs(subcat.scid,
                                                                 self._auth)
                    self._freqs += result
                    status_cur += 1
                    status.send_status(
                        'Fetching agency %s %s:%s' % (agency.aid,
                                                      cat.cName,
                                                      subcat.scName),
                        status_cur / status_max * 100)
        status.send_end()

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.memory_bounds = (0, len(self._freqs)-1)
        rf.has_bank = False
        rf.has_ctone = False
        rf.has_comment = True
        rf.valid_tmodes = ["", "TSQL", "DTCS"]
        return rf

    def get_raw_memory(self, number):
        return repr(self._freqs[number])

    def get_memory(self, number):
        if not self._freqs:
            self.do_fetch()

        freq = self._freqs[number]

        mem = chirp_common.Memory()
        mem.number = number

        mem.name = freq.alpha or freq.descr or ""
        mem.freq = chirp_common.parse_freq(str(freq.out))
        if freq["in"] == 0.0:
            mem.duplex = ""
        else:
            mem.duplex = "split"
            mem.offset = chirp_common.parse_freq(str(freq["in"]))
        if freq.tone is not None:
            if str(freq.tone) == "CSQ":  # Carrier Squelch
                mem.tmode = ""
            else:
                try:
                    tone, tmode = freq.tone.split(" ")
                except Exception:
                    tone, tmode = None, None
                if tmode == "PL":
                    mem.tmode = "TSQL"
                    mem.rtone = mem.ctone = float(tone)
                elif tmode == "DPL":
                    mem.tmode = "DTCS"
                    mem.dtcs = int(tone)
                else:
                    LOG.error("Error: unsupported tone: %s" % freq)
        try:
            mem.mode = self._get_mode(freq.mode)
        except KeyError:
            LOG.debug('Mode %s (%s) is unsupported' % (
                freq.mode, self._modes[int(str(freq.mode))]))
            # skip memory if mode is unsupported
            mem.empty = True
            return mem
        mem.comment = freq.descr.strip()

        return mem

    def _get_mode(self, modeid):
        if not self._modes:
            self._modes = {}
            for mode in self._client.service.getMode("0", self._auth):
                # sax.text.Text cannot be coerced directly to int
                self._modes[int(str(mode.mode))] = str(mode.modeName)
        return MODES[self._modes[int(str(modeid))]]


def main():
    """
    Usage:
    cd ~/src/chirp.hg
    python ./chirp/radioreference.py [USERNAME] [PASSWORD] \
        [COUNTRY - 2 LETTER] [US ZIP(USA) OR COUNTY ID(CANADA)]
    """
    import sys
    rrr = RadioReferenceRadio(None)
    rrr.set_params(username=sys.argv[1],
                   password=sys.argv[2],
                   country=sys.argv[3],
                   zipcounty=sys.argv[4])
    rrr.do_fetch()
    print(rrr.get_raw_memory(0))
    print(rrr.get_memory(0))

if __name__ == "__main__":
    main()
