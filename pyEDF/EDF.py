#! /usr/bin/env python
'''
Copyright (C) 2016-2018 Robert Ooostenveld <r.oostenveld@donders.ru.nl>
              2018 Phillip Alday <phillip.alday@mpi.nl>

All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

* Redistributions of source code must retain the above copyright notice, this
  list of conditions and the following disclaimer.
* Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.
* Neither the name of the copyright holder nor the names of its
  contributors may be used to endorse or promote products derived from
  this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
'''

# TODO: Add division after writing basic unit tests to discover issues the
#       changed behaviour may cause.
from __future__ import print_function

from copy import deepcopy
from struct import pack, unpack
import numpy as np
import os
import os.path as op
import re
from warnings import warn


def padtrim(buf, num):
    num -= len(buf)
    if num >= 0:
        # pad the input to the specified length
        return str(buf) + ' ' * num
    else:
        # trim the input to the specified length
        return buf[0:num]


##############################################################################
# the EDF header is represented as a tuple of (meas_info, chan_info)
# The fields in meas_info are ['record_length', 'magic', 'hour', 'subject_id',
# 'recording_id', 'n_records', 'month', 'subtype', 'second', 'nchan',
# 'data_size', 'data_offset', 'lowpass', 'year', 'highpass', 'day', 'minute']
# The fields in chan_info are ['physical_min', 'transducers', 'physical_max',
# 'digital_max', 'ch_names', 'n_samps', 'units', 'digital_min']
##############################################################################
class EDFWriter():
    def __init__(self, fname=None):
        self.fname = None
        self.meas_info = None
        self.chan_info = None
        self.calibrate = None
        self.offset = None
        self.n_records = 0
        if fname:
            self.open(fname)

    def open(self, fname):
        with open(fname, 'wb') as fid:
            assert(fid.tell() == 0)
        self.fname = fname

    def close(self):
        # it is still needed to update the number of records in the header
        # this requires copying the whole file content
        meas_info = self.meas_info
        chan_info = self.chan_info
        # update the n_records value in the file
        tempname = self.fname + '.bak'
        os.rename(self.fname, tempname)
        with open(tempname, 'rb') as fid1:
            assert(fid1.tell() == 0)
            with open(self.fname, 'wb') as fid2:
                assert(fid2.tell() == 0)
                fid2.write(fid1.read(236))
                # skip this bit
                fid1.read(8)
                # but write this instead
                fid2.write(padtrim(str(self.n_records), 8))
                fid2.write(fid1.read(meas_info['data_offset'] - 236 - 8))
                bsize = np.sum(chan_info['n_samps']) * meas_info['data_size']
                for block in range(self.n_records):
                    fid2.write(fid1.read(bsize))
        os.remove(tempname)
        self.fname = None
        self.meas_info = None
        self.chan_info = None
        self.calibrate = None
        self.offset = None
        self.n_records = 0
        return

    def writeHeader(self, header, data):
        meas_info = header[0]
        chan_info = header[1]
        meas_size = 256
        chan_size = 256 * meas_info['nchan']
        with open(self.fname, 'wb') as fid:
            assert(fid.tell() == 0)

            # fill in the missing or incomplete information
            if 'subject_id' not in meas_info:
                meas_info['subject_id'] = ''

            if 'recording_id' not in meas_info:
                meas_info['recording_id'] = ''

            if 'subtype' not in meas_info:
                meas_info['subtype'] = 'edf'
            nchan = meas_info['nchan']

            if len(chan_info.get('ch_names', [])) < nchan:

                chan_info['ch_names'] = [str(i) for i in range(nchan)]

            if len(chan_info.get('transducers', [])) < nchan:
                chan_info['transducers'] = ['' for i in range(nchan)]

            if len(chan_info.get('units', [])) < nchan:
                chan_info['units'] = ['' for i in range(nchan)]

            if meas_info['subtype'] in ('24BIT', 'bdf'):
                meas_info['data_size'] = 3  # 24-bit (3 byte) integers
            else:
                meas_info['data_size'] = 2  # 16-bit (2 byte) integers

            fid.write(padtrim('0', 8))
            fid.write(padtrim(meas_info['subject_id'], 80))
            fid.write(padtrim(meas_info['recording_id'], 80))
            dmy = '{:0>2d}.{:0>2d}.{:0>2d}'.format(meas_info['day'],
                                                   meas_info['month'],
                                                   meas_info['year'])
            fid.write(padtrim(dmy, 8))
            hms = '{:0>2d}.{:0>2d}.{:0>2d}'.format(meas_info['hour'],
                                                   meas_info['minute'],
                                                   meas_info['second'])
            fid.write(padtrim(hms, 8))
            fid.write(padtrim(str(meas_size + chan_size), 8))
            fid.write(' ' * 44)
            # the final n_records should be inserted on byte 236
            fid.write(padtrim(str(-1), 8))
            fid.write(padtrim(str(meas_info['record_length']), 8))
            fid.write(padtrim(str(meas_info['nchan']), 4))

            # ensure that these are all np arrays rather than lists
            for key in ['physical_min', 'transducers', 'physical_max',
                        'digital_max', 'ch_names', 'n_samps', 'units',
                        'digital_min']:
                chan_info[key] = np.asarray(chan_info[key])

            for i in range(meas_info['nchan']):
                fid.write(padtrim(chan_info['ch_names'][i], 16))
            for i in range(meas_info['nchan']):
                fid.write(padtrim(chan_info['transducers'][i], 80))
            for i in range(meas_info['nchan']):
                fid.write(padtrim(chan_info['units'][i], 8))
            for i in range(meas_info['nchan']):
                fid.write(padtrim(str(chan_info['physical_min'][i]), 8))
            for i in range(meas_info['nchan']):
                fid.write(padtrim(str(chan_info['physical_max'][i]), 8))
            for i in range(meas_info['nchan']):
                fid.write(padtrim(str(chan_info['digital_min'][i]), 8))
            for i in range(meas_info['nchan']):
                fid.write(padtrim(str(chan_info['digital_max'][i]), 8))
            for i in range(meas_info['nchan']):
                fid.write(' ' * 80)  # prefiltering
            for i in range(meas_info['nchan']):
                fid.write(padtrim(str(chan_info['n_samps'][i]), 8))
            for i in range(meas_info['nchan']):
                fid.write(' ' * 32)  # reserved
            meas_info['data_offset'] = fid.tell()

        self.meas_info = meas_info
        self.chan_info = chan_info
        self.calibrate = chan_info['physical_max'] - chan_info['physical_min']
        self.calibrate /= (chan_info['digital_max'] - chan_info['digital_min'])
        self.offset = chan_info['physical_min']
        self.offset -= self.calibrate * chan_info['digital_min']

        for ch in range(meas_info['nchan']):
            if self.calibrate[ch] < 0:
                self.calibrate[ch] = 1
                self.offset[ch] = 0

    def writeBlock(self, data):
        meas_info = self.meas_info
        chan_info = self.chan_info

        with open(self.fname, 'ab') as fid:
            assert fid.tell() > 0

            for i in range(meas_info['nchan']):
                raw = deepcopy(data[i])

                assert len(raw) == chan_info['n_samps'][i]
                if min(raw) < chan_info['physical_min'][i]:
                    warn('Value exceeds physical_min: {}'.format(min(raw)))
                if max(raw) > chan_info['physical_max'][i]:
                    warn('Value exceeds physical_max: {}'.format(max(raw)))

                # FIXME I am not sure about the order of calibrate and offset
                raw -= self.offset[i]
                raw /= self.calibrate[i]

                raw = np.asarray(raw, dtype=np.int16)
                buf = [pack('h', x) for x in raw]
                for val in buf:
                    fid.write(val)
            self.n_records += 1


class EDFReader():
    def __init__(self, fname=None):
        self.fname = None
        self.meas_info = None
        self.chan_info = None
        self.calibrate = None
        self.offset = None
        if fname:
            self.open(fname)

    def open(self, fname):
        with open(fname, 'rb') as fid:
            assert(fid.tell() == 0)
        self.fname = fname
        self.readHeader()
        return self.meas_info, self.chan_info

    def close(self):
        self.fname = None
        self.meas_info = None
        self.chan_info = None
        self.calibrate = None
        self.offset = None

    def readHeader(self):
        # the following is copied over from MNE-Python and subsequently
        # modified to more closely reflect the native EDF standard
        meas_info = {}
        chan_info = {}
        with open(self.fname, 'rb') as fid:
            assert fid.tell() == 0

            meas_info['magic'] = fid.read(8).strip().decode()
            meas_info['subject_id'] = fid.read(80).strip().decode()
            meas_info['recording_id'] = fid.read(80).strip().decode()

            day, month, year = [int(x) for x in
                                re.findall('(\d+)', fid.read(8).decode())]
            hour, minute, second = [int(x) for x in
                                    re.findall('(\d+)', fid.read(8).decode())]
            meas_info['day'] = day
            meas_info['month'] = month
            meas_info['year'] = year
            meas_info['hour'] = hour
            meas_info['minute'] = minute
            meas_info['second'] = second

            meas_info['data_offset'] = header_nbytes = int(fid.read(8).decode()) # noqa:E501

            subtype = fid.read(44).strip().decode()[:5]
            if len(subtype) > 0:
                meas_info['subtype'] = subtype
            else:
                meas_info['subtype'] = op.splitext(self.fname)[1][1:].lower()

            if meas_info['subtype'] in ('24BIT', 'bdf'):
                meas_info['data_size'] = 3  # 24-bit (3 byte) integers
            else:
                meas_info['data_size'] = 2  # 16-bit (2 byte) integers

            meas_info['n_records'] = int(fid.read(8).decode())

            # record length in seconds
            record_length = float(fid.read(8).decode())
            if record_length == 0:
                meas_info['record_length'] = record_length = 1.
                warn('Headermeas_information is incorrect for record length. '
                     'Default record length set to 1.')
            else:
                meas_info['record_length'] = record_length
            meas_info['nchan'] = nchan = int(fid.read(4).decode())

            chs = list(range(nchan))

            def _read_chan_byte():
                return np.array([float(fid.read(8).decode()) for ch in chs])

            chan_info['ch_names'] = [fid.read(16).strip().decode()
                                     for ch in chs]
            chan_info['transducers'] = [fid.read(80).strip().decode()
                                        for ch in chs]
            chan_info['units'] = [fid.read(8).strip().decode() for ch in chs]

            chan_info['physical_min'] = _read_chan_byte()
            chan_info['physical_max'] = _read_chan_byte()
            chan_info['digital_min'] = _read_chan_byte()
            chan_info['digital_max'] = _read_chan_byte()

            prefiltering = [fid.read(80).strip().decode() for ch in chs][:-1]
            highpass = np.ravel([re.findall('HP:\s+(\w+)', filt)
                                 for filt in prefiltering])
            lowpass = np.ravel([re.findall('LP:\s+(\w+)', filt)
                                for filt in prefiltering])
            high_pass_default = 0.

            if highpass.size == 0:
                meas_info['highpass'] = high_pass_default
            elif all(highpass):
                if highpass[0] == 'NaN':
                    meas_info['highpass'] = high_pass_default
                elif highpass[0] == 'DC':
                    meas_info['highpass'] = 0.
                else:
                    meas_info['highpass'] = float(highpass[0])
            else:
                meas_info['highpass'] = float(np.max(highpass))
                warn('Channels contain different highpass filters. '
                     'Highest filter setting will be stored.')

            if lowpass.size == 0:
                meas_info['lowpass'] = None
            elif all(lowpass):
                if lowpass[0] == 'NaN':
                    meas_info['lowpass'] = None
                else:
                    meas_info['lowpass'] = float(lowpass[0])
            else:
                meas_info['lowpass'] = float(np.min(lowpass))
                warn('%s' % ('Channels contain different lowpass filters.'
                             ' Lowest filter setting will be stored.')) # noqa:E127
            # number of samples per record
            chan_info['n_samps'] = n_samps = _read_chan_byte()

            fid.read(32 * meas_info['nchan']).decode()  # reserved
            assert fid.tell() == header_nbytes

            if meas_info['n_records'] == -1:
                # this happens if n_records isn't updated at recording end
                tot_samps = op.getsize(self.fname) - meas_info['data_offset']
                tot_samps /= meas_info['data_size']
                meas_info['n_records'] = tot_samps / sum(n_samps)

        self.calibrate = chan_info['physical_max'] - chan_info['physical_min']
        self.calibrate /= chan_info['digital_max'] - chan_info['digital_min']

        self.offset = chan_info['physical_min']
        self.offset -= self.calibrate * chan_info['digital_min']

        for ch in chs:
            if self.calibrate[ch] < 0:
                self.calibrate[ch] = 1
                self.offset[ch] = 0

        self.meas_info = meas_info
        self.chan_info = chan_info
        return (meas_info, chan_info)

    def readBlock(self, block):
        assert block >= 0

        chan_info = self.chan_info
        meas_info = self.meas_info
        data = []

        with open(self.fname, 'rb') as fid:
            assert(fid.tell() == 0)
            blocksize = np.sum(chan_info['n_samps']) * meas_info['data_size']
            fid.seek(meas_info['data_offset'] + block * blocksize)
            for i in range(meas_info['nchan']):
                buf = fid.read(chan_info['n_samps'][i]*meas_info['data_size'])
                raw = unpack('<{}h'.format(chan_info['n_samps'][i]), buf)
                raw = np.asarray(raw, dtype=np.float32)
                # FIXME I am not sure about the order of calibrate and offset
                raw *= self.calibrate[i]
                raw += self.offset[i]
                data.append(raw)
        return data

    def readSamples(self, channel, begsample, endsample):
        chan_info = self.chan_info
        n_samps = chan_info['n_samps'][channel]

        # typecast to int is truncation from float, so there's no need for
        # explicit floor()
        begblock = int(begsample / n_samps)
        endblock = int(endsample / n_samps)

        data = self.readBlock(begblock)[channel]

        for block in range(begblock + 1, endblock + 1):
            data = np.append(data, self.readBlock(block)[channel])

        begsample -= begblock * n_samps
        endsample -= begblock * n_samps

        return data[begsample:(endsample+1)]

###############################################################################
# the following are a number  of helper functions to make the behaviour of
# this EDFReader class similar to https://bitbucket.org/cleemesser/python-edf/
##############################################################################

    def getSignalTextLabels(self):
        # convert from unicode to string
        return [str(x) for x in self.chan_info['ch_names']]

    def getNSignals(self):
        return self.meas_info['nchan']

    def getSignalFreqs(self):
        return self.chan_info['n_samps'] / self.meas_info['record_length']

    def getNSamples(self):
        return self.chan_info['n_samps'] * self.meas_info['n_records']

    def readSignal(self, chanindx):
        begsample = 0

        n_samps = self.chan_info['n_samps'][chanindx]
        n_records = self.meas_info['n_records']
        endsample = n_samps * n_records - 1

        return self.readSamples(chanindx, begsample, endsample)

##############################################################################
