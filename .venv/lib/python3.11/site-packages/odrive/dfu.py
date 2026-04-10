import aiohttp
import os
from typing import Optional

from odrive.api_client import ApiClient
from odrive.device_manager import get_device_manager, find_async, DeviceManager
from odrive.firmware import FirmwareFile
from odrive.hw_version import HwVersion
from odrive.libodrive import Device, Firmware, DeviceLostException, DeviceType
from odrive.release_api import ChannelNotFoundError, FirmwareNotFoundError, ReleaseApi, VersionRelationship, format_version
from odrive.runtime_device import RuntimeDevice
from odrive.ui import OperationAbortedException, RichTextPrinter, yes_no_prompt

ui = RichTextPrinter()

class DfuError(Exception):
    pass

async def enter_dfu_mode(device: RuntimeDevice, device_manager: DeviceManager) -> Device:
    """
    Puts the specified device into (new) DFU mode.
    """
    print(f"Putting device {device.serial_number} into DFU mode...")
    try:
        result = await device.call_function('enter_dfu_mode2')
    except DeviceLostException:
        result = True # this is expected because the device reboots
    if not result:
        raise DfuError("Failed to enter DFU mode.")

    device = await device_manager.wait_for(device.serial_number, return_type=Device, device_type=DeviceType.BOOTLOADER)
    await device.connect()
    return device

async def write_firmware(device: Device, fw: Firmware, erase_all: bool):
    def print_progress(new_action_group: bool, action_string: str, action_index: int, n_actions: int):
        if new_action_group and action_index != 0:
            print()
        print(f"DFU: {action_string}    ", end='\r')
    try:
        await device.run_installation(fw, erase_all, print_progress)
    finally:
        print()

async def get_firmware(board: HwVersion, current_build_id_short: Optional[str], channel: Optional[str], version: Optional[str], interactive: bool, release_type: str = 'firmware'):
    async with aiohttp.ClientSession() as session:
        if channel:
            ui.info(f"Checking online for latest {board.display_name} {release_type} on channel {channel}...")
        else:
            ui.info(f"Checking online for {board.display_name} {release_type} version {format_version(version)}...")
        api_client = ApiClient(session)
        release_api = ReleaseApi(api_client)

        firmware_index = await release_api.get_index(release_type)

        # If we're fetching normal firmware, use whatever file the release
        # server returns as preferred file URL.
        # If we're fetching the bootloader, need to select between multiple
        # files on the release server.
        file = 'bootloader_installer.elf' if release_type == 'bootloader' else None

        try:
            if channel:
                manifest = firmware_index.get_latest(channel, app='default', board=board, file=file)
            else:
                manifest = firmware_index.get_version(version, app='default', board=board, file=file)
        except ChannelNotFoundError as ex:
            raise DfuError(ex)
        except FirmwareNotFoundError:
            raise DfuError(f"No {release_type} found matching the specified criteria.")

        if interactive:
            version_relationship = firmware_index.compare(current_build_id_short, manifest['commit_hash'], channel, app='default', board=board)
            prompt = {
                VersionRelationship.UNKNOWN: "Found compatible {release_type} ({to_version}). Install now?",
                VersionRelationship.EQUAL: "Your current {release_type} ({to_version}) is up to date. Do you want to reinstall this version?",
                VersionRelationship.UPGRADE: "Found new {release_type} ({from_hash} => {to_version}). Install now?",
                VersionRelationship.DOWNGRADE: "Found older {release_type} ({from_hash} => {to_version}). Install now?",
            }[version_relationship]
        
            if not yes_no_prompt(prompt.format(release_type=release_type, from_hash=current_build_id_short, to_version=format_version(manifest['commit_hash'])), True):
                raise OperationAbortedException()

        ui.info(f"Downloading {release_type}...")
        return FirmwareFile.from_file(await release_api.load(manifest))

async def run_dfu(device_manager: DeviceManager, serial_number: Optional[str], path: Optional[str], channel: Optional[str], version: Optional[str], erase_all: bool, interactive: bool = True):
    """
    See dfu_ui for description.
    """
    assert sum([bool(path), bool(channel), bool(version)]) == 1

    if (not path is None) and (not os.path.isfile(path)):
        raise DfuError(f"File {path} not found.")

    ui.info("Waiting for ODrive...")

    # Wait for device either in DFU mode or in normal mode, whichever is
    # found first.
    device: Device = await find_async(serial_number=serial_number, return_type=Device)
    ui.info(f"found ODrive {device.info.serial_number}")
    actual_serial_number = device.info.serial_number

    found_in_dfu = device.info.device_type == DeviceType.BOOTLOADER

    if not found_in_dfu:
        runtime_device, _, _ = await get_device_manager().ensure_connected(device)

        bootloader_version = await runtime_device.try_read('bootloader_version', 0)
        if bootloader_version == 0:
            raise DfuError(
                f"New DFU system not installed on device {runtime_device.serial_number}.\n"
                "Please follow instructions for one-time setup here:\n"
                "https://docs.odriverobotics.com/v/latest/guides/new-dfu.html\n"
                "or use the legacy DFU system (odrivetool legacy-dfu)."
            )

        # Note: we don't do ahead of time compatibility check until the
        # bootloader version has stabilized. Just-in-time checking is
        # handled in libodrive (when bootloader is already started).

    ui.warn("Configuration and calibration will be erased during the firmware update.")
    ui.info("To back up and restore all configuration, see https://docs.odriverobotics.com/v/latest/interfaces/odrivetool.html#configuration-backup.")
    ui.info("To back up and restore only calibration, see https://docs.odriverobotics.com/v/latest/manual/hardware-config.html#calibration-backup.")

    if found_in_dfu:
        await device.connect()

    if not path is None:
        assert channel is None
        file = FirmwareFile.from_file(path)
    else:
        board: HwVersion = device.hw_version if found_in_dfu else runtime_device.board
        build_id_int = None if found_in_dfu else await runtime_device.try_read('commit_hash', None)
        build_id_short = None if build_id_int is None else "{:08x}".format(build_id_int)
        file = await get_firmware(board, build_id_short, channel, version, interactive)

    libodrive = device_manager.lib
    with libodrive.open_firmware(file.as_buffer()) as firmware:
        print("loaded firmware: ")
        print("  Version: " + str(".".join(str(n) for n in firmware.fw_version)))
        print("  Build ID: " + "".join(f"{b:02x}" for b in firmware.build))
        print("  Hardware: " + firmware.hw_version.display_name)

        if not found_in_dfu:
            device = await enter_dfu_mode(runtime_device, device_manager)

        assert device.info.device_type == DeviceType.BOOTLOADER
        await write_firmware(device, firmware, erase_all)

    ui.info("Waiting for the device to reappear...")
    device = await find_async(actual_serial_number)
    ui.success("Device firmware update successful.")


async def dfu_ui(serial_number: Optional[str], path: Optional[str], channel: Optional[str], version: Optional[str], erase_all: bool, interactive: bool = True):
    """
    Runs the complete interactive DFU process:

    1. Wait for device in either DFU mode or normal mode. If `serial_number` is
       None, the first discovered device is selected, otherwise only the
       specified device is accepted.

    2. If `path` is None, check for the latest or specified firmware, present it
       to the user and ask whether to continue. Otherwise don't ask and always
       continue.

    3. If the device is in normal mode, put it into DFU mode.

    4. Erase, write and verify flash memory.

    5. Exit DFU mode.

    Parameters
    ----------
    path: Path to a .elf path or None to check online.
    channel: Channel on which to check for firmware (master, devel, ...)
    version: Exact firmware version
    """
    await run_dfu(get_device_manager(), serial_number, path, channel, version, erase_all, interactive)

