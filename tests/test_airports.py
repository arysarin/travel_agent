from travel_adviser.airports import airport_labels, code_from_label, default_label


def test_city_search_finds_airports():
    labels = airport_labels()
    assert any("Indira Gandhi" in l and "(DEL)" in l for l in labels)
    assert any(l.startswith("London (LHR)") for l in labels)
    assert any("Bagdogra" in l and "(IXB)" in l for l in labels)


def test_code_round_trips_from_label():
    assert code_from_label(default_label()) == "JFK"
    assert all(len(code_from_label(l)) == 3 for l in airport_labels())


def test_non_passenger_fields_excluded():
    assert not any("heliport" in l.lower() for l in airport_labels())
