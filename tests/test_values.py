from src.values import format_value, parse_value


def test_currency_with_commas():
    v = parse_value("$5,687")
    assert (v.numeric, v.unit) == (5687.0, "USD")


def test_accounting_negative_in_parentheses():
    assert parse_value("($3,832)").numeric == -3832.0
    assert parse_value("-$3,832").numeric == -3832.0


def test_percent_is_stored_as_fraction():
    v = parse_value("40.3%")
    assert v.unit == "percent"
    assert abs(v.numeric - 0.403) < 1e-9


def test_rating_out_of_five():
    v = parse_value("3 out of 5")
    assert (v.numeric, v.unit, v.scale) == (3.0, "rating", 5.0)


def test_rate_with_period():
    v = parse_value("$931.25 / week")
    assert (v.numeric, v.unit, v.period) == (931.25, "USD", "per week")
    assert parse_value("13.9% / month").period == "per month"


def test_approximate_count_keeps_qualifier_and_text():
    v = parse_value("About 50")
    assert (v.numeric, v.qualifier, v.text) == (50.0, "about", "About 50")


def test_not_available_and_plain_text():
    assert parse_value("n/a").qualifier == "n/a"
    assert parse_value("n/a").numeric is None
    assert parse_value("Long lines.").numeric is None


def test_native_number_uses_excel_format_for_unit():
    assert parse_value(26528.49, "$#,##0_-").unit == "USD"
    assert parse_value(0.63, "#,##0%").unit == "percent"
    assert parse_value(3979, "#,##0").unit == "count"


def test_format_value():
    assert format_value(0.403, "percent") == "40.3%"
    assert format_value(-3832, "USD") == "-$3,832.00"
    assert format_value(3, "rating", 5) == "3 out of 5"
    assert format_value(1129, "count") == "1,129"
