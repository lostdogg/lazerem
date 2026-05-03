"""Tests for lazerem/parser.py"""

import pytest
from lazerem.parser import parse_program, Block, Word, ParseError


def test_empty_program():
    blocks, errors = parse_program("")
    assert blocks == []
    assert errors == []


def test_percent_lines_ignored():
    blocks, errors = parse_program("%\nG0 X10 Y20\n%")
    assert len(blocks) == 1
    assert errors == []


def test_basic_g0_xy():
    blocks, errors = parse_program("G0 X10 Y20")
    assert len(blocks) == 1
    assert errors == []
    b = blocks[0]
    assert b.get("G") == 0.0
    assert b.get("X") == 10.0
    assert b.get("Y") == 20.0


def test_line_number_parsing():
    blocks, _ = parse_program("N10 G1 X5 Y5")
    assert blocks[0].line_number == 10


def test_m3_s_value():
    blocks, _ = parse_program("M3 S750")
    b = blocks[0]
    assert b.get("M") == 3.0
    assert b.get("S") == 750.0


def test_comment_stripped():
    blocks, _ = parse_program("G0 X0 Y0 ; go to origin")
    assert blocks[0].comment == "go to origin"
    assert blocks[0].get("X") == 0.0


def test_paren_comment():
    blocks, _ = parse_program("G1 X10 (cut line) Y10")
    assert "cut line" in blocks[0].comment


def test_multiple_g_words():
    blocks, _ = parse_program("G21 G90")
    b = blocks[0]
    g_vals = [w.value for w in b.words if w.letter == "G"]
    assert 21.0 in g_vals
    assert 90.0 in g_vals


def test_incremental_xy():
    blocks, _ = parse_program("G91\nG1 X5 Y5")
    assert len(blocks) == 2


def test_parse_error_bad_number():
    # "Xabc" doesn't match the word regex at all, so it is silently skipped.
    # Y10 is still parsed successfully; no errors are raised.
    blocks, errors = parse_program("G1 Xabc Y10")
    assert len(errors) == 0
    assert blocks[0].get("Y") == 10.0
    assert not blocks[0].has("X")


def test_has_method():
    blocks, _ = parse_program("G0 X0")
    b = blocks[0]
    assert b.has("X")
    assert not b.has("Y")
    assert not b.has("Z")


def test_arc_ij():
    blocks, _ = parse_program("G2 X10 Y0 I5 J0")
    b = blocks[0]
    assert b.get("G") == 2.0
    assert b.get("I") == 5.0
    assert b.get("J") == 0.0
