"""
This module contains the base implementation of :class:`can.BusABC` as well
as a list of all available backends and some implemented
CyclicSendTasks.
"""

import importlib
import logging

from .bus import BusABC
from .util import load_config
from .interfaces import BACKENDS

log = logging.getLogger("can.interface")
log_autodetect = log.getChild("detect_available_configs")


def _get_class_for_interface(interface):
    """
    Returns the main bus class for the given interface.

    :raises:
        NotImplementedError if the interface is not known
    :raises:
        ImportError     if there was a problem while importing the
                        interface or the bus class within that
    """
    # Find the correct backend
    try:
        module_name, class_name = BACKENDS[interface]
    except KeyError:
        raise NotImplementedError(
            "CAN interface '{}' not supported".format(interface)
        ) from None

    # Import the correct interface module
    try:
        module = importlib.import_module(module_name)
    except Exception as e:
        raise ImportError(
            "Cannot import module {} for CAN interface '{}': {}".format(
                module_name, interface, e
            )
        ) from None

    # Get the correct class
    try:
        bus_class = getattr(module, class_name)
    except Exception as e:
        raise ImportError(
            "Cannot import class {} from module {} for CAN interface '{}': {}".format(
                class_name, module_name, interface, e
            )
        ) from None

    return bus_class


class Bus(BusABC):  # pylint disable=abstract-method
    """Bus wrapper with configuration loading.

    Instantiates a CAN Bus of the given ``interface``, falls back to reading a
    configuration file from default locations.
    """

    @staticmethod
    def __new__(cls, channel=None, *args, **kwargs):
        """
        Takes the same arguments as :class:`can.BusABC.__init__`.
        Some might have a special meaning, see below.

        :param channel:
            Set to ``None`` to let it be resolved automatically from the default
            configuration. That might fail, see below.

            Expected type is backend dependent.

        :param dict kwargs:
            Should contain an ``interface`` key with a valid interface name. If not,
            it is completed using :meth:`can.util.load_config`.

        :raises: NotImplementedError
            if the ``interface`` isn't recognized

        :raises: ValueError
            if the ``channel`` could not be determined
        """

        # figure out the rest of the configuration; this might raise an error
        if channel is not None:
            kwargs["channel"] = channel
        if "context" in kwargs:
            context = kwargs["context"]
            del kwargs["context"]
        else:
            context = None
        kwargs = load_config(config=kwargs, context=context)

        # resolve the bus class to use for that interface
        cls = _get_class_for_interface(kwargs["interface"])

        # remove the 'interface' key so it doesn't get passed to the backend
        del kwargs["interface"]

        # make sure the bus can handle this config format
        if "channel" not in kwargs:
            raise ValueError("'channel' argument missing")
        else:
            channel = kwargs["channel"]
            del kwargs["channel"]

        if channel is None:
            # Use the default channel for the backend
            return cls(*args, **kwargs)
        else:
            return cls(channel, *args, **kwargs)


def detect_available_configs(interfaces=None):
    """Detect all configurations/channels that the interfaces could
    currently connect with.

    This might be quite time consuming.

    Automated configuration detection may not be implemented by
    every interface on every platform. This method will not raise
    an error in that case, but with rather return an empty list
    for that interface.

    :param interfaces: either
        - the name of an interface to be searched in as a string,
        - an iterable of interface names to search in, or
        - `None` to search in all known interfaces.
    :rtype: list[dict]
    :return: an iterable of dicts, each suitable for usage in
             the constructor of :class:`can.BusABC`.
    """

    # Figure out where to search
    if interfaces is None:
        interfaces = BACKENDS
    elif isinstance(interfaces, str):
        interfaces = (interfaces,)
    # else it is supposed to be an iterable of strings

    result = []
    for interface in interfaces:

        try:
            bus_class = _get_class_for_interface(interface)
        except ImportError:
            log_autodetect.debug(
                'interface "%s" can not be loaded for detection of available configurations',
                interface,
            )
            continue

        # get available channels
        try:
            available = list(
                bus_class._detect_available_configs()
            )  # pylint: disable=protected-access
        except NotImplementedError:
            log_autodetect.debug(
                'interface "%s" does not support detection of available configurations',
                interface,
            )
        else:
            log_autodetect.debug(
                'interface "%s" detected %i available configurations',
                interface,
                len(available),
            )

            # add the interface name to the configs if it is not already present
            for config in available:
                if "interface" not in config:
                    config["interface"] = interface

            # append to result
            result += available

    return result
