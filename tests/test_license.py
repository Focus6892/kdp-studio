import datetime as dt
from pathlib import Path

import pytest

pytest.importorskip("cryptography")

from kdp_studio import license as lic  # noqa: E402


def test_keygen_issue_verify_roundtrip(tmp_path, monkeypatch):
    priv, pub = lic.keygen(tmp_path / "keys", package_dir=tmp_path / "pkg")
    assert priv.is_file() and pub.read_text(encoding="utf-8").startswith('"""')
    pub_b64 = pub.read_text(encoding="utf-8").split('"')[-2]
    machine = "ABCDE-FGHIJ-KLMNO-PQRST"
    token = lic.issue(priv, "Shop A", machine, days=30)
    payload = lic.verify(token, public_b64=pub_b64, machine=machine)
    assert payload["licensee"] == "Shop A" and payload["machine"] == machine and payload["expires"]
    with pytest.raises(lic.LicenseError):  # other machine
        lic.verify(token, public_b64=pub_b64, machine="XXXXX-XXXXX-XXXXX-XXXXX")
    with pytest.raises(lic.LicenseError):  # expired
        lic.verify(token, public_b64=pub_b64, machine=machine, today=dt.date.today() + dt.timedelta(days=31))
    with pytest.raises(lic.LicenseError):  # tampered
        body, sig = token.split(".")
        lic.verify(body[:-2] + "AA." + sig, public_b64=pub_b64, machine=machine)
    any_machine = lic.issue(priv, "Owner", "*", days=0)
    assert lic.verify(any_machine, public_b64=pub_b64, machine="WHATEVER")["expires"] is None
    # a key signed by someone else's private key is rejected
    other_priv, other_pub = lic.keygen(tmp_path / "other", package_dir=tmp_path / "pkg2")
    with pytest.raises(lic.LicenseError):
        lic.verify(lic.issue(other_priv, "Mallory", machine), public_b64=pub_b64, machine=machine)


def test_machine_id_is_stable_and_store_roundtrip(tmp_path, monkeypatch):
    assert lic.machine_id() == lic.machine_id() and len(lic.machine_id()) == 23
    monkeypatch.setenv("KDP_STUDIO_HOME", str(tmp_path))
    priv, pub = lic.keygen(tmp_path / "keys", package_dir=tmp_path / "pkg")
    pub_b64 = pub.read_text(encoding="utf-8").split('"')[-2]
    monkeypatch.setattr(lic, "public_key_b64", lambda: pub_b64)
    monkeypatch.delenv("KDP_STUDIO_DEV", raising=False)
    assert lic.enforced() is True
    with pytest.raises(lic.LicenseError):
        lic.require_license()
    lic.activate(lic.issue(priv, "Me", lic.machine_id(), days=10))
    assert lic.status()["valid"] is True and lic.store_path().is_file()
    lic.require_license()  # no raise
    monkeypatch.setenv("KDP_STUDIO_DEV", "1")
    assert lic.enforced() is False
