"""
A text based interface. For example use over serial ports like
"/dev/ttyS1" or "/dev/ttyUSB0" on Linux machines or "COM1" on Windows.
The interface is a simple implementation that has been used for
recording CAN traces.

See the interface documentation for the format being used.
"""

import logging
import struct
from typing import Any, List, Tuple, Optional

from can import BusABC, Message, CanError
from can.typechecking import AutoDetectedConfig

logger = logging.getLogger("can.serial")

try:
    import serial
except ImportError:
    logger.warning(
        "You won't be able to use the serial can backend without "
        "the serial module installed!"
    )
    serial = None

try:
    from serial.tools.list_ports import comports as list_comports
except ImportError:
    # If unavailable on some platform, just return nothing
    def list_comports() -> List[Any]:
        return []


class SerialBus(BusABC):
    """
    Enable basic can communication over a serial device.

    .. note:: See :meth:`~_recv_internal` for some special semantics.

    """

    def __init__(
        self,
        channel: str,
        baudrate: int = 115200,
        timeout: float = 0.1,
        rtscts: bool = False,
        *args,
        **kwargs,
    ) -> None:
        """
        :param channel:
            The serial device to open. For example "/dev/ttyS1" or
            "/dev/ttyUSB0" on Linux or "COM1" on Windows systems.

        :param baudrate:
            Baud rate of the serial device in bit/s (default 115200).

            .. warning::
                Some serial port implementations don't care about the baudrate.

        :param timeout:
            Timeout for the serial device in seconds (default 0.1).

        :param rtscts:
            turn hardware handshake (RTS/CTS) on and off

        """
        if not channel:
            raise ValueError("Must specify a serial port.")

        self.channel_info = f"Serial interface: {channel}"
        self._ser = serial.serial_for_url(
            channel, baudrate=baudrate, timeout=timeout, rtscts=rtscts
        )

        super().__init__(channel, *args, **kwargs)

    def shutdown(self) -> None:
        """
        Close the serial interface.
        """
        self._ser.close()

    def send(self, msg: Message, timeout: Optional[float] = None) -> None:
        """
        Send a message over the serial device.

        :param msg:
            Message to send.

            .. note:: Flags like ``extended_id``, ``is_remote_frame`` and
                      ``is_error_frame`` will be ignored.

            .. note:: If the timestamp is a float value it will be converted
                      to an integer.

        :param timeout:
            This parameter will be ignored. The timeout value of the channel is
            used instead.

        """
        # Pack timestamp
        try:
            timestamp = struct.pack("<I", int(msg.timestamp * 1000))
        except struct.error:
            raise ValueError("Timestamp is out of range")

        # Pack arbitration ID
        try:
            arbitration_id = struct.pack("<I", msg.arbitration_id)
        except struct.error:
            raise ValueError("Arbitration ID is out of range")

        # Assemble message
        byte_msg = bytearray()
        byte_msg.append(0xAA)
        byte_msg += timestamp
        byte_msg.append(msg.dlc)
        byte_msg += arbitration_id
        byte_msg += msg.data
        byte_msg.append(0xBB)

        # Write to serial device
        self._ser.write(byte_msg)

    def _recv_internal(
        self, timeout: Optional[float]
    ) -> Tuple[Optional[Message], bool]:
        """
        Read a message from the serial device.

        :param timeout:

            .. warning::
                This parameter will be ignored. The timeout value of the channel is used.

        :returns:
            Received message and `False` (because no filtering as taken place).

            .. warning::
                Flags like is_extended_id, is_remote_frame and is_error_frame
                will not be set over this function, the flags in the return
                message are the default values.
        """
        try:
            rx_byte = self._ser.read()
            if rx_byte and ord(rx_byte) == 0xAA:

                s = self._ser.read(4)
                timestamp = struct.unpack("<I", s)[0]
                dlc = ord(self._ser.read())
                if dlc > 8:
                    raise CanError("received DLC may not exceed 8 bytes")

                s = self._ser.read(4)
                arbitration_id = struct.unpack("<I", s)[0]
                if arbitration_id >= 0x20000000:
                    raise CanError(
                        "received arbitration id may not exceed 2^29 (0x20000000)"
                    )

                data = self._ser.read(dlc)

                delimiter_byte = ord(self._ser.read())
                if delimiter_byte == 0xBB:
                    # received message data okay
                    msg = Message(
                        # TODO: We are only guessing that they are milliseconds
                        timestamp=timestamp / 1000,
                        arbitration_id=arbitration_id,
                        dlc=dlc,
                        data=data,
                    )
                    return msg, False

                else:
                    raise CanError(
                        f"invalid delimiter byte while reading message: {delimiter_byte}"
                    )

            else:
                return None, False

        except serial.SerialException as error:
            raise CanError("could not read from serial") from error

    def fileno(self) -> int:
        if hasattr(self._ser, "fileno"):
            return self._ser.fileno()
        # Return an invalid file descriptor on Windows
        return -1

    @staticmethod
    def _detect_available_configs() -> List[AutoDetectedConfig]:
        return [
            {"interface": "serial", "channel": port.device} for port in list_comports()
        ]
