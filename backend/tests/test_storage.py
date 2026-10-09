import pytest

from generationstation.storage import Store


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, statement):
        self.connection.statements.append(statement)
        if self.connection.fail:
            raise RuntimeError("SET failed")


class FakeConnection:
    def __init__(self, autocommit=False, fail=False):
        self.states = []
        self.autocommit = autocommit
        self.fail = fail
        self.statements = []

    @property
    def autocommit(self):
        return self._autocommit

    @autocommit.setter
    def autocommit(self, value):
        self._autocommit = value
        self.states.append(value)

    def cursor(self):
        return FakeCursor(self)


@pytest.mark.parametrize("initial", [False, True])
@pytest.mark.parametrize("fail", [False, True])
def test_statement_timeout_setup_restores_autocommit(initial, fail):
    connection = FakeConnection(autocommit=initial, fail=fail)

    if fail:
        with pytest.raises(RuntimeError, match="SET failed"):
            Store._set_statement_timeout(connection, None)
    else:
        Store._set_statement_timeout(connection, None)

    assert connection.autocommit is initial
    assert connection.states == [initial, True, initial]
    assert connection.statements == ["SET statement_timeout = 5000"]
