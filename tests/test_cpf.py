import pytest

from app.delivery.cpf import (MSG_FORMAT, MSG_INVALID, format_cpf, is_valid_cpf, mask_cpf, normalize_cpf,
                              validate_cpf)

VALID = ["529.982.247-25", "52998224725", "111.444.777-35", "390.533.447-05", "  529.982.247-25  "]
WRONG_DIGIT = ["529.982.247-24", "529.982.247-35", "111.444.777-34", "123.456.789-00"]
SAME_DIGITS = [f"{d * 3}.{d * 3}.{d * 3}-{d * 2}" for d in "0123456789"]
BAD_FORMAT = ["", "123", "529.982.247-2", "529.982.247-255", "abc.def.ghi-jk", "529 982 247 25", None, 52998224725]


@pytest.mark.parametrize("cpf", VALID)
def test_valid(cpf):
    assert is_valid_cpf(cpf)
    digits, error = validate_cpf(cpf)
    assert error is None and len(digits) == 11 and digits.isdigit()


@pytest.mark.parametrize("cpf", WRONG_DIGIT)
def test_wrong_check_digit(cpf):
    assert not is_valid_cpf(cpf)
    assert validate_cpf(cpf) == (None, MSG_INVALID)


@pytest.mark.parametrize("cpf", SAME_DIGITS)
def test_repeated_digits_rejected(cpf):
    assert not is_valid_cpf(cpf)


@pytest.mark.parametrize("cpf", BAD_FORMAT)
def test_bad_format(cpf):
    assert not is_valid_cpf(cpf)
    assert validate_cpf(cpf) == (None, MSG_FORMAT)


def test_normalize_and_format():
    assert normalize_cpf("529.982.247-25") == "52998224725"
    assert format_cpf("52998224725") == "529.982.247-25"


def test_mask_hides_first_three_and_last_two():
    assert mask_cpf("529.982.247-25") == "***.982.247-**"
    assert mask_cpf("52998224725") == "***.982.247-**"
    with pytest.raises(ValueError):
        mask_cpf("123")
