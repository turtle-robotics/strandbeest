import enum
import hashlib
import os
import re
from typing import Optional

import appdirs

from odrive.api_client import ApiClient
from odrive.crypto import safe_b64decode, safe_b64encode
from odrive.hw_version import HwVersion

class ReleaseApi():
    BASE_URL = '/releases'

    def __init__(self, api_client: 'ApiClient'):
        self._api_client = api_client

    async def get_index(self, release_type: str):
        outputs = await self._api_client.call('GET', ReleaseApi.BASE_URL + '/' + release_type + '/index')
        return ReleaseIndex(outputs['files'], outputs['commits'], outputs['channels'])

    async def load(self, manifest: dict, force_download: bool = False):
        """
        Downloads a firmware file and saves it in a cache directory.
        If the file was already cached before, it is loaded from disk instead
        (unless force_download is True).
        Returns the path of the cached file.
        """
        cache_dir = os.path.join(appdirs.user_cache_dir("odrivetool", "ODrive Robotics"), 'firmware')
        os.makedirs(cache_dir, exist_ok=True)
        filename = manifest['url'].rpartition('/')[2]
        cache_path = os.path.join(cache_dir, manifest['content_key'] + "_" + filename + '.elf')

        if force_download or not os.path.isfile(cache_path):
            content = await self._api_client.download(manifest['url'])
            with open(cache_path, 'wb') as fp:
                fp.write(content)

        return cache_path


class VersionRelationship(enum.Enum):
    UNKNOWN = enum.auto()
    EQUAL = enum.auto()
    UPGRADE = enum.auto()
    DOWNGRADE = enum.auto()

class ChannelNotFoundError(Exception):
    pass

class FirmwareNotFoundError(Exception):
    pass

class ReleaseIndex():
    def __init__(self, files, commits, channels):
        self._files = {safe_b64decode(f['content']): f for f in files}
        self._commits = commits
        for c in commits:
            c['content'] = safe_b64decode(c['content'])
        for c in commits:
            if 'board' in c:
                c['board'] = HwVersion.from_tuple(c['board'])
        self._open_channels = {c['channel']: c['commits'] for c in channels if not c['closed']}
        self._closed_channels = {c['channel']: c['commits'] for c in channels if c['closed']}

    @property
    def open_channel_names(self):
        return list(self._open_channels.keys())

    def _get_filtered_versions(self, channel_info: list, has_file: Optional[str], **qualifiers: dict) -> list:
        """
        Returns a list of version info objects where all qualifiers match and
        where the version name is contained in channel_info.

        The list is ordered "most relevant first".

        Specifically, it is sorted on two levels:
            version name (as ordered in channel_info)
            variant ("internal" before "public" before other or unspecified)
        """
        if 'product' in qualifiers:
            import warnings
            warnings.warn('The "product" qualifier is deprecated. Use "board" instead.', DeprecationWarning, stacklevel=0)

        version_infos = [
            c for c in self._commits
            if (c['commit_hash'] in channel_info) and (has_file is None or has_file in c.get('index', [])) and all((k in c) and (c[k] == v) for k, v in qualifiers.items())
        ]
        return sorted(version_infos, key=lambda c: (
            channel_info.index(c['commit_hash']),
            {'internal': 0, 'public': 1}.get(c.get('variant', None), 2)))

    def _get_channel_info(self, channel: str):
        if channel in self._open_channels:
            return self._open_channels[channel]
        elif channel in self._closed_channels:
            return self._closed_channels[channel]
        else:
            raise ChannelNotFoundError(f"Channel {channel} not found.")

    def _get_manifest(self, version_info, file: Optional[str] = None):
        content_key = version_info['content']

        url = self._files[content_key]['url']
        if not file is None:
            base_url = url[:url.rfind('/')] # substring up to last /
            url = base_url + '/' + file

        return {
            'content_key': safe_b64encode(content_key),
            'commit_hash': version_info['commit_hash'],
            'release_date': self._files[content_key]['release_date'],
            'url': url
        }

    def get_latest(self, channel: str, file: Optional[str] = None, **qualifiers: dict):
        """
        Checks for the latest firmware on the specified channel with the specified
        qualifiers (product, app).

        If the specified channel is not found or empty, an exception is thrown.
        Returns a metadata manifest for the release that was found.
        """
        channel_info = list(reversed(self._get_channel_info(channel)))
        filtered_versions = self._get_filtered_versions(channel_info, has_file=file, **qualifiers)

        if len(filtered_versions) == 0:
            raise FirmwareNotFoundError()

        return self._get_manifest(filtered_versions[0], file)

    def get_version(self, version: str, file: Optional[str] = None, **qualifiers: dict):
        """
        Looks up the release information for the specified commit with the
        specified qualifiers (product, app).

        Returns a metadata manifest for the release that was found.
        """
        filtered_versions = self._get_filtered_versions(channel_info=[version], has_file=file, **qualifiers)

        if len(filtered_versions) == 0:
            raise FirmwareNotFoundError()

        return self._get_manifest(filtered_versions[0], file)

    def compare(self, from_version: Optional[str], to_version: str, channel: str, **qualifiers: dict):
        """
        Checks if the specified transition is an upgrade or not.
        """

        return VersionRelationship.UNKNOWN # TODO

        if from_version is None:
            return VersionRelationship.UNKNOWN

        filtered_commits = self._get_filtered_versions(**qualifiers)

        short_hashes = {h[:8]: h for h in filtered_commits.keys()}
        from_version = short_hashes.get(from_version, from_version)
        
        if not from_version in filtered_commits or not to_version in filtered_commits:
            return VersionRelationship.UNKNOWN
        
        from_file = filtered_commits[from_version]
        to_file = filtered_commits[to_version]

        if from_file == to_file:
            return VersionRelationship.EQUAL
        
        filtered_channel_commits = self._get_filtered_channel_commits(channel, filtered_commits)

        if not from_file in filtered_channel_commits or not to_file in filtered_channel_commits:
            return VersionRelationship.UNKNOWN
        
        if filtered_channel_commits.index(from_file) < filtered_channel_commits.index(to_file):
            return VersionRelationship.UPGRADE
        else:
            return VersionRelationship.DOWNGRADE


def format_version(version: str):
    if re.match("^[0-9a-fA-F]*$", version) and (len(version) == 8 or len(version) == 40):
        return version.lower()[:8]
    return version
