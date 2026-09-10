"""Fix 3: private_ip_info — info locali (nessuna rete) su IP privati/bogon."""
from app.ip_info import private_ip_info


def test_private_class_c():
    info = private_ip_info("192.168.1.1")
    assert "privata" in info["range_name"]
    assert info["legacy_class"] == "C"


def test_private_class_a():
    info = private_ip_info("10.0.0.1")
    assert info["legacy_class"] == "A"


def test_loopback():
    info = private_ip_info("127.0.0.1")
    assert "Loopback" in info["range_name"]


def test_public_ip_returns_none():
    assert private_ip_info("8.8.8.8") is None


def test_invalid_ip_returns_none_no_crash():
    assert private_ip_info("not-an-ip") is None
