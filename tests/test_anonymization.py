"""The anonymizer must replace names everywhere text can hide and leave every number alone."""
import openpyxl

from anonymize_workbooks import anonymize_workbook, find_remaining, replace_names

MAPPING = {"Moonbeam Cafe": "Cafe A", "Moonbeam Cafe Two": "Cafe B", "Rival Roasters": "Cafe C"}


def test_replace_names_handles_substrings_and_longest_match_first():
    assert replace_names("Moonbeam Cafe - Week 3", MAPPING) == "Cafe A - Week 3"
    assert replace_names("Moonbeam Cafe Two", MAPPING) == "Cafe B"
    assert replace_names("Rival Roasters beat Moonbeam Cafe", MAPPING) == "Cafe C beat Cafe A"
    assert replace_names("Long lines.", MAPPING) == "Long lines."


def test_workbook_copy_keeps_numbers_and_formats(tmp_path):
    src, dest = tmp_path / "in.xlsx", tmp_path / "out" / "in.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Moonbeam Cafe Dashboard"
    ws["A1"] = "Moonbeam Cafe - Week 3"
    ws["A2"] = "Revenue"
    ws["B2"] = 26528.49
    ws["B2"].number_format = "$#,##0.00"
    ws["B3"] = 0.403
    ws["B3"].number_format = "0.0%"
    ws["A4"] = "Rival Roasters"
    ws["A4"].comment = openpyxl.comments.Comment("written by Moonbeam Cafe", "someone")
    wb.properties.creator = "a student"
    wb.save(src)

    counts = anonymize_workbook(src, dest, MAPPING)
    assert counts["cells"] == 2 and counts["sheets"] == 1 and counts["comments"] == 1 and counts["properties"] >= 1

    out = openpyxl.load_workbook(dest)
    ws = out.worksheets[0]
    assert ws.title == "Cafe A Dashboard"
    assert ws["A1"].value == "Cafe A - Week 3" and ws["A4"].value == "Cafe C"
    assert ws["B2"].value == 26528.49 and ws["B2"].number_format == "$#,##0.00"
    assert ws["B3"].value == 0.403 and ws["B3"].number_format == "0.0%"
    assert ws["A4"].comment is None
    assert out.properties.creator != "a student"  # openpyxl stamps its own name on save
    assert find_remaining(dest.parent, list(MAPPING)) == []
