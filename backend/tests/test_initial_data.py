import app.initial_data as initial_data


def test_main_does_not_call_create_tables(monkeypatch) -> None:
    called = {
        "create_tables": False,
        "init": False,
        "init_test_data": False,
    }

    def fake_create_tables() -> None:
        called["create_tables"] = True

    def fake_init() -> None:
        called["init"] = True

    def fake_init_test_data() -> None:
        called["init_test_data"] = True

    monkeypatch.setattr(initial_data, "create_tables", fake_create_tables)
    monkeypatch.setattr(initial_data, "init", fake_init)
    monkeypatch.setattr(initial_data, "init_test_data", fake_init_test_data)

    initial_data.main()

    assert called["create_tables"] is False
    assert called["init"] is True
    assert called["init_test_data"] is True
