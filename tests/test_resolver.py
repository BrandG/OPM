from src.resolver import pick_us_primary


# Trimmed real-shape sample of a noisy search_contracts response.
AMD_SEARCH = {
    "results": [
        {
            "underlying_contract_id": 4391,
            "exchange": "NASDAQ",
            "symbol": "AMD",
            "description": "ADVANCED MICRO DEVICES",
            "country_code": "US",
            "sections": [{"security_type": "STK"}, {"security_type": "OPT"}],
        },
        {
            "underlying_contract_id": 32596680,
            "exchange": "IBIS",
            "symbol": "AMD",
            "description": "ADVANCED MICRO DEVICES",
            "country_code": "DE",  # foreign listing -> excluded
            "sections": [{"security_type": "STK"}],
        },
        {
            "underlying_contract_id": 691439815,
            "exchange": "NASDAQ",
            "symbol": "AMDL",  # leveraged ETF, wrong symbol -> excluded
            "description": "GRANITESHARES 2XLONG AMD ETF",
            "country_code": "US",
            "sections": [{"security_type": "STK"}],
        },
        {
            "issuer": "e1408288",  # bond row, no symbol key -> excluded
            "description": "Advanced Micro Devices Inc",
            "sections": [{"security_type": "BOND"}],
        },
    ]
}


def test_picks_us_primary_common_stock():
    got = pick_us_primary(AMD_SEARCH, "AMD")
    assert got is not None
    assert got["contract_id"] == 4391
    assert got["exchange"] == "NASDAQ"
    assert got["currency"] == "USD"


def test_case_insensitive_symbol():
    assert pick_us_primary(AMD_SEARCH, "amd")["contract_id"] == 4391


def test_prefers_nyse_over_other_us_venue():
    results = {
        "results": [
            {"underlying_contract_id": 2, "exchange": "BATS", "symbol": "X",
             "country_code": "US", "sections": [{"security_type": "STK"}]},
            {"underlying_contract_id": 1, "exchange": "NYSE", "symbol": "X",
             "country_code": "US", "sections": [{"security_type": "STK"}]},
        ]
    }
    assert pick_us_primary(results, "X")["contract_id"] == 1


def test_no_match_returns_none():
    assert pick_us_primary(AMD_SEARCH, "NOPE") is None
    assert pick_us_primary({"results": []}, "AMD") is None
    assert pick_us_primary({}, "AMD") is None
