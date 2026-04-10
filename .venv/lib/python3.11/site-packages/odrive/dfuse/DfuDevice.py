import usb.util
import time
import fractions
import array
from enum import Enum
import time
import math

class RequestType(Enum):
    SEND = 0x21
    RECEIVE = 0xa1

class Request(Enum):
    DETACH    = 0x00
    DNLOAD    = 0x01
    UPLOAD    = 0x02
    GETSTATUS = 0x03
    CLRSTATUS = 0x04
    GETSTATE  = 0x05
    ABORT     = 0x06

class Command(Enum):
    SET_ADDRESS_POINTER = 0x21
    ERASE = 0x41
    READ_UNPROTECT = 0x92

class DfuState(Enum):
    APP_IDLE                = 0x00
    APP_DETACH              = 0x01
    DFU_IDLE                = 0x02
    DFU_DOWNLOAD_SYNC       = 0x03
    DFU_DOWNLOAD_BUSY       = 0x04
    DFU_DOWNLOAD_IDLE       = 0x05
    DFU_MANIFEST_SYNC       = 0x06
    DFU_MANIFEST            = 0x07
    DFU_MANIFEST_WAIT_RESET = 0x08
    DFU_UPLOAD_IDLE         = 0x09
    DFU_ERROR               = 0x0a

class DfuStatus(Enum):
    OK                 = 0x00
    ERROR_TARGET       = 0x01
    ERROR_FILE         = 0x02
    ERROR_WRITE        = 0x03
    ERROR_ERASE        = 0x04
    ERROR_CHECK_ERASED = 0x05
    ERROR_PROG         = 0x06
    ERROR_VERIFY       = 0x07
    ERROR_ADDRESS      = 0x08
    ERROR_NOTDONE      = 0x09
    ERROR_FIRMWARE     = 0x0a
    ERROR_VENDOR       = 0x0b
    ERROR_USBR         = 0x0c
    ERROR_POR          = 0x0d
    ERROR_UNKNOWN      = 0x0e
    ERROR_STALLEDPKT   = 0x0f


SIZE_MULTIPLIERS = {' ': 1, 'K': 1024, 'M' : 1024*1024}
MAX_TRANSFER_SIZE = 2048

# Order is LSB first
def _address_to_4bytes(a):
    return [ a % 256, (a >> 8)%256, (a >> 16)%256, (a >> 24)%256 ]

def _get_dfu_functional_descriptors(interfaces):
    for intf in interfaces:
        pos = 0
        desc = intf.extra_descriptors
        while len(desc):
            current_desc = desc[:desc[0]]
            desc = desc[desc[0]:]
            if current_desc[1] == 0x21:
                yield current_desc


class DfuError(Exception):
    def __init__(self, message: str, status: DfuStatus, state: DfuState, text: str):
        super().__init__(message + " Device responded with {}, {}, \"{}\".".format(status, state, text))

class DfuDevice:
    def __init__(self, device):
        self._dev = device
        self._memory = None

    def init(self):
        cfg = self._dev[0]
        cfg.set()

        dfu_desc = list(_get_dfu_functional_descriptors(cfg.interfaces()))
        assert len(dfu_desc) == 1
        dfu_desc = dfu_desc[0]

        self._max_transfer_size = dfu_desc[5] + (dfu_desc[6] << 8)
        assert self._max_transfer_size <= MAX_TRANSFER_SIZE

        self.memories = {}
        for intf in cfg.interfaces():
            # example for intf_name:
            # '@Internal Flash  /0x08000000/04*016Kg,01*064Kg,07*128Kg'
            intf_name = usb.util.get_string(self._dev, intf.iInterface)
            if intf_name.count('/') != 2:
                raise Exception(f"invalid interface name for interface {intf.iInterface}: {intf_name}")
            label, baseaddr, layout = intf_name.split('/')
            baseaddr = int(baseaddr, 0) # convert hex to decimal
            addr = baseaddr

            memory = {
                'intf': intf,
                'alt': intf.bAlternateSetting,
                'sectors': []
            }

            for sector in layout.split(','):
                repeat, size = map(int, sector[:-2].split('*'))
                size *= SIZE_MULTIPLIERS[sector[-2].upper()]
                mode = sector[-1]

                while repeat > 0:
                    # TODO: verify if the section is writable
                    memory['sectors'].append({
                        'addr': addr,
                        'len': size,
                        'mode': mode
                    })

                    addr += size
                    repeat -= 1

            name = label.rstrip().lstrip('@')
            self.memories[name] = memory

    def select_memory(self, name):
        self._memory = self.memories[name]
        self._memory['intf'].set_altsetting()

    def _control_msg(self, requestType: RequestType, request: Request, value: int, buffer):
        if self._memory is None:
            raise Exception("no memory selected")
        return self._dev.ctrl_transfer(requestType.value, request.value, value, self._memory['intf'].bInterfaceNumber, buffer, timeout=60000)

    def _detach(self, timeout):
        """
        timeout: Timeout in [??]
        """
        return self._control_msg(RequestType.SEND, Request.DETACH, timeout, None)
    
    def _dnload(self, blockNum, data):
        """
        The device's current state must be dfuIDLE or dfuDNLOAD-IDLE state for
        this command to work (see STM AN3156 Fig 5).

        blockNum: block to write to
        data: byte-array-like data to write
        Returns: number of bytes that were written.
        """
        cnt = self._control_msg(RequestType.SEND, Request.DNLOAD, blockNum, list(data))
        return cnt
    
    def _upload(self, blockNum, size):
        """
        The device's current state must be dfuIDLE or dfuUPLOAD-IDLE state for
        this command to work (see STM AN3156 Fig 3).

        blockNum: block to read from
        size: number of bytes to read
        Returns: byte array containing the data that was read
        """
        return self._control_msg(RequestType.RECEIVE, Request.UPLOAD, blockNum, size)

    def _get_status(self):
        """
        Returns: A tuple of the form (status: DfuStatus, state: DfuState, text: str)
        """
        msg = self._control_msg(RequestType.RECEIVE, Request.GETSTATUS, 0, 6)

        status = DfuStatus(msg[0])
        state = DfuState(msg[4])
        poll_timeout_ms = msg[1] + (msg[2] << 8) + (msg[3] << 16)
        text = usb.util.get_string(self._dev, msg[5])

        if poll_timeout_ms > 10000:
            raise Exception("Device requested an unreasonable timeout: {} ms".format(poll_timeout_ms))

        time.sleep(float(poll_timeout_ms) / 1000.0)
        return status, state, text
    
    def clear_status(self):
        if self._get_state() == DfuState.DFU_ERROR:
            self._control_msg(RequestType.SEND, Request.CLRSTATUS, 0, None)

    def _get_state(self):
        msg = self._control_msg(RequestType.RECEIVE, Request.GETSTATE, 0, 1)
        return DfuState(msg[0])

    def _abort(self):
        self._control_msg(RequestType.SEND, Request.ABORT, 0, None)

    def _read(self, block, size):
        return self._upload(block + 2, size)

    def _write(self, block, data):
        return self._dnload(block + 2, data)

    def _set_address(self, addr):
        self._dnload(0x0, [Command.SET_ADDRESS_POINTER.value] + _address_to_4bytes(addr))
        self._expect_state(
            [DfuState.DFU_DOWNLOAD_BUSY], [DfuState.DFU_DOWNLOAD_IDLE],
            "Failed to set address 0x{:08x}.".format(addr)
        )

    def unprotect(self):
        self._dnload(0x0, [Command.READ_UNPROTECT])
        self._expect_state(
            [DfuState.DFU_DOWNLOAD_BUSY], [DfuState.DFU_DOWNLOAD_IDLE],
            "Failed to unprotect."
        )

    def _erase(self, addr):
        self._dnload(0x0, [Command.ERASE.value] + _address_to_4bytes(addr))
        self._expect_state(
            [DfuState.DFU_DOWNLOAD_BUSY], [DfuState.DFU_DOWNLOAD_IDLE],
            "Failed to erase sector at 0x{:08x}.".format(addr)
        )

    def _leave(self):
        return self._dnload(0x0, []) # Just send an empty data.

    def _expect_state(self, busy_states, target_states, error_text):
        while True:
            status, state, text = self._get_status()
            if state in target_states:
                return
            if state not in busy_states:
                raise DfuError(error_text, status, state, text)

    def erase_sector(self, sector):
        self._expect_state([], [DfuState.DFU_IDLE, DfuState.DFU_DOWNLOAD_IDLE], "Cannot erase sector")
        self._erase(sector['addr'])

    def write_sector(self, sector, data):
        self._expect_state([], [DfuState.DFU_IDLE, DfuState.DFU_DOWNLOAD_IDLE], "Cannot write sector")

        status, state, text = self._get_status()
        if state not in [DfuState.DFU_IDLE, DfuState.DFU_DOWNLOAD_IDLE]:
            raise DfuError("Cannot write sector.", status, state, text)

        self._set_address(sector['addr'])

        transfer_size = math.gcd(sector['len'], self._max_transfer_size)
        
        for blocknum in range(int(sector['len'] / transfer_size)):
            block = data[(blocknum * transfer_size):((blocknum + 1) * transfer_size)]
            n_written = self._write(blocknum, block)
            assert n_written == len(block), n_written
            self._expect_state(
                [DfuState.DFU_DOWNLOAD_BUSY], [DfuState.DFU_DOWNLOAD_IDLE],
                "Failed to write sector at 0x{:08x}, block {}".format(sector['addr'], blocknum)
            )

    def read_sector(self, sector):
        """
        Reads data from the specified sector
        Returns: a byte array containing the data
        """
        self._expect_state([], [DfuState.DFU_IDLE, DfuState.DFU_DOWNLOAD_IDLE], "Cannot read sector.")
        self._set_address(sector['addr'])

        self._abort() # exit DNLOAD_IDLE state

        transfer_size = math.gcd(sector['len'], self._max_transfer_size)

        # Device's current state must be dfuIDLE or dfuUPLOAD-IDLE for the subsequent read() commands to work.
        
        data = array.array(u'B')
        for blocknum in range(int(sector['len'] / transfer_size)):
            device_block = self._read(blocknum, transfer_size)
            assert len(device_block) == transfer_size, len(device_block)
            data.extend(device_block)

        self._abort() # take device into DFU_IDLE
        return data

    def jump_to_application(self, address):
        self._set_address(address)
        self._leave()

        try:
            self._expect_state(
                [DfuState.DFU_MANIFEST_SYNC], [DfuState.DFU_MANIFEST],
                "Failed to exit DFU mode."
            )
            # on ODrive v3.x this passes
            # on ODrive v4.x it throws a usb.core.USBError
        except usb.core.USBError:
            pass # expected

