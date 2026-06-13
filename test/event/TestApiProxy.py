"""
@file TestApiProxy.py
@brief Unit tests for api/api.py private IP detection and host resolution.
@author 30hours

Tests security-critical proxy functions:
  - _is_private_ip: private IP classification
  - _resolve_and_classify: DNS resolution + classification

These tests avoid importing api.py directly (which pulls in common.Message
and other runtime dependencies).  Instead they exercise the logic in
isolation using importlib to extract just the pure functions.
"""

import unittest
import sys
import os

# ---------------------------------------------------------------------------
# Extract _is_private_ip function from api/api.py without executing
# the full module (which would trigger common.Message import).
# ---------------------------------------------------------------------------
_api_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'api'))
_api_path = os.path.join(_api_dir, 'api.py')

_api_source = {}
with open(_api_path, 'r') as f:
    exec(f.read(), {'__name__': '__test__', '__file__': _api_path}, _api_source)

_is_private_ip = _api_source['_is_private_ip']


class TestIsPrivateIp(unittest.TestCase):
  """Security-critical tests for _is_private_ip."""

  # --- Loopback ---
  def test_loopback_v4(self):
    self.assertTrue(_is_private_ip("127.0.0.1"))
    self.assertTrue(_is_private_ip("127.0.0.0"))
    self.assertTrue(_is_private_ip("127.255.255.254"))

  def test_loopback_v6(self):
    self.assertTrue(_is_private_ip("::1"))

  # --- RFC 1918 private ranges ---
  def test_private_10(self):
    self.assertTrue(_is_private_ip("10.0.0.1"))
    self.assertTrue(_is_private_ip("10.255.255.254"))

  def test_private_192_168(self):
    self.assertTrue(_is_private_ip("192.168.0.1"))
    self.assertTrue(_is_private_ip("192.168.255.254"))

  def test_private_172_16_to_31(self):
    self.assertTrue(_is_private_ip("172.16.0.1"))
    self.assertTrue(_is_private_ip("172.31.255.254"))

  def test_private_172_outside_range(self):
    # 172.15.x.x and 172.32.x.x are not RFC 1918 private
    self.assertFalse(_is_private_ip("172.15.255.255"))
    self.assertFalse(_is_private_ip("172.32.0.1"))

  def test_private_172_invalid_format(self):
    # Not enough octets — should not crash
    self.assertFalse(_is_private_ip("172"))
    self.assertFalse(_is_private_ip("172."))

  # --- RFC 6598 Carrier-grade NAT ---
  def test_cgnat_100_64_to_127(self):
    self.assertTrue(_is_private_ip("100.64.0.1"))
    self.assertTrue(_is_private_ip("100.127.255.254"))

  def test_cgnat_outside_range(self):
    self.assertFalse(_is_private_ip("100.63.255.255"))
    self.assertFalse(_is_private_ip("100.128.0.1"))

  # --- IPv6 unique local (RFC 4193: fc00::/7) ---
  def test_ipv6_ula_fc(self):
    self.assertTrue(_is_private_ip("fc00::1"))
    self.assertTrue(_is_private_ip("fcff:ffff:ffff:ffff:ffff:ffff:ffff:ffff"))

  def test_ipv6_ula_fd(self):
    self.assertTrue(_is_private_ip("fd00::1"))
    self.assertTrue(_is_private_ip("fd12:3456:7890::1"))

  # --- IPv6 link-local (RFC 4291: fe80::/10) ---
  def test_ipv6_link_local(self):
    self.assertTrue(_is_private_ip("fe80::1"))
    self.assertTrue(_is_private_ip("fe80:1234:5678::1"))
    self.assertTrue(_is_private_ip("febf::1"))

  # --- Public IPs ---
  def test_public_v4(self):
    self.assertFalse(_is_private_ip("8.8.8.8"))
    self.assertFalse(_is_private_ip("1.1.1.1"))
    self.assertFalse(_is_private_ip("203.0.113.1"))
    self.assertFalse(_is_private_ip("198.51.100.42"))

  def test_public_v6(self):
    self.assertFalse(_is_private_ip("2001:4860:4860::8888"))
    self.assertFalse(_is_private_ip("2606:4700:4700::1111"))

  # --- Edge cases ---
  def test_empty_string(self):
    self.assertFalse(_is_private_ip(""))

  def test_non_ip_string(self):
    self.assertFalse(_is_private_ip("not-an-ip"))

  def test_169_254_link_local(self):
    # 169.254.0.0/16 is APIPA / link-local — not currently blocked.
    # This test documents the current behaviour.  If this range should be
    # blocked in the future, update _is_private_ip and this test.
    self.assertFalse(_is_private_ip("169.254.1.1"))

  def test_0_0_0_0(self):
    # 0.0.0.0 is not a private range — it's the "any" address.
    # Connecting to 0.0.0.0 would bind to all interfaces, which is dangerous,
    # but it's not a "private" IP in the RFC sense.
    self.assertFalse(_is_private_ip("0.0.0.0"))

  def test_127_embedded(self):
    # Only IPs starting with "127." are loopback, not containing "127" elsewhere
    self.assertFalse(_is_private_ip("212.7.1.1"))


class TestResolveAndClassify(unittest.TestCase):
  """Tests for _resolve_and_classify using socket.getaddrinfo."""

  @classmethod
  def setUpClass(cls):
    # Import the function (requires Flask app context for logger)
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'api'))
    from api import _resolve_and_classify, app
    cls._resolve_and_classify = _resolve_and_classify
    cls.app = app

  def _classify(self, host):
    """Helper to call _resolve_and_classify within app context."""
    with self.app.app_context():
      return self._resolve_and_classify(host)

  def test_localhost_classified_private(self):
    is_private, target = self._classify("localhost")
    self.assertTrue(is_private, "localhost should be classified as private")
    self.assertIn(target, ("localhost", "127.0.0.1"))

  def test_localhost_with_port_is_private(self):
    is_private, target = self._classify("localhost:8080")
    self.assertTrue(is_private)

  def test_ipv4_loopback_is_private(self):
    is_private, target = self._classify("127.0.0.1")
    self.assertTrue(is_private)

  def test_ipv6_loopback_is_private(self):
    is_private, target = self._classify("::1")
    self.assertTrue(is_private)

  def test_public_host_resolves_to_public(self):
    """A well-known public host should return is_private=False."""
    is_private, target = self._classify("one.one.one.one")
    self.assertFalse(is_private,
                     "one.one.one.one should be classified as public")
    # target should be a resolved IP (not the hostname)
    self.assertNotEqual(target, "one.one.one.one",
                        "target should be a resolved IP to prevent DNS rebinding")

  def test_private_ip_as_host_is_private(self):
    """Passing a private IP directly should be classified as private."""
    is_private, target = self._classify("192.168.1.1")
    self.assertTrue(is_private)

  def test_private_ip_with_port_is_private(self):
    is_private, target = self._classify("10.0.0.1:3000")
    self.assertTrue(is_private)
    # Port should be preserved in target
    self.assertIn(":3000", target)

  def test_nonexistent_hostname_fails_closed(self):
    """An unresolvable hostname should be treated as private (fail closed)."""
    is_private, target = self._classify("this-host-definitely-does-not-exist.invalid")
    self.assertTrue(is_private,
                    "Unresolvable hosts should be treated as private (fail closed)")

  def test_ipv6_bracketed_is_private(self):
    """Bracketed IPv6 loopback should be classified as private."""
    is_private, target = self._classify("[::1]")
    self.assertTrue(is_private)

  def test_ipv6_bracketed_with_port_is_private(self):
    is_private, target = self._classify("[::1]:8080")
    self.assertTrue(is_private)


if __name__ == "__main__":
  unittest.main()