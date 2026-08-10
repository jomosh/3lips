"""
@file AdsbTruth.py
@author 30hours
"""

import asyncio
import aiohttp

class AdsbTruth:

    """
    @class AdsbTruth
    @brief A class for storing ADS-B truth in the API response.
    @details Fetches ADS-B position data (lat/lon/alt/flight) from a tar1090 server.
    """

    def __init__(self, seen_pos_limit, request_timeout=1.0):

        """
        @brief Constructor for the AdsbTruth class.
        @param seen_pos_limit (int): Max age of ADS-B position data (seconds).
        @param request_timeout (float): Per-request HTTP timeout in seconds.
        """

        self.seen_pos_limit = seen_pos_limit
        self.request_timeout = request_timeout

    async def process_async(self, server, use_https, session):
        """
        @brief Async variant using a shared aiohttp ClientSession.
        @param server (str): The tar1090 server to get truth from.
        @param use_https (bool): Use HTTPS if True, HTTP if False.
        @param session (aiohttp.ClientSession): Shared session for connection reuse.
        @return dict: Aircraft truth data keyed by hex code, or {} on failure.
        """
        scheme = 'https' if use_https else 'http'
        url = f'{scheme}://{server}/data/aircraft.json'

        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=self.request_timeout)) as resp:
                resp.raise_for_status()
                data = await resp.json(content_type=None)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"Error fetching data from {url}: {e}")
            return {}

        output = {}
        for aircraft in data.get("aircraft", []):
            if (aircraft.get("seen_pos") and
                aircraft.get("alt_geom") and
                aircraft.get("flight") and
                aircraft.get("seen_pos") < self.seen_pos_limit):
                output[aircraft["hex"]] = {
                    "lat": aircraft["lat"],
                    "lon": aircraft["lon"],
                    "alt": aircraft["alt_geom"],
                    "flight": aircraft["flight"],
                    "timestamp": data["now"] - aircraft["seen_pos"]
                }
        return output
