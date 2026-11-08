"""VerificationError の契約を固定する。"""

from sheet_writer.errors import VerificationError


def test_is_exception_subclass():
    assert issubclass(VerificationError, Exception)


def test_message_keeps_detail():
    err = VerificationError("列 A の幅が意図と不一致: expected=78 actual=50")
    assert "列 A" in str(err)
    assert "78" in str(err)
