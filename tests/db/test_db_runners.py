import csv
from pathlib import Path

from sqlalchemy import create_engine

from esptest.db.runners import Runner, RunnerDB, User


def test_db_runner_sqlite(tmp_path: Path) -> None:
    engine = create_engine('sqlite:///:memory:')
    db = RunnerDB(engine)
    with db.open_session() as session:
        runner = Runner(
            mac='11:22:33:44:55:66',
            ip='192.168.1.1',
            name='test0',
            owner='test0',
            tags=['test'],
            raw_data={'envs': {'esp32': ['wifi_iperf']}, 'os': 'linux'},
            description='test runner',
        )
        session.add_or_update_runner(runner)
        user = User(
            name='test0',
            email='test0@example.com',
        )
        session.add_or_update_user(user)
        # session.commit()
        runners = session.all_runners()
        assert len(runners) == 1
        assert runners[0].mac == '11:22:33:44:55:66'
        assert runners[0].ip == '192.168.1.1'
        assert runners[0].name == 'test0'
        assert runners[0].owner == 'test0'
        assert runners[0].tags == ['test']
        assert runners[0].raw_data == {'envs': {'esp32': ['wifi_iperf']}, 'os': 'linux'}
        assert runners[0].description == 'test runner'
        assert runners[0].user.name == 'test0'
        assert runners[0].user.email == 'test0@example.com'
        users = session.all_users()
        assert len(users) == 1
        assert users[0].name == 'test0'
        assert users[0].email == 'test0@example.com'
        assert users[0].runners
        assert users[0].runners[0].mac == '11:22:33:44:55:66'
        # update runner
        assert runner.id == 1
        runner.description = 'test runner update desc'
        session.add_or_update_runner(runner)
        # db.save()
    with db.open_session() as session:
        runners = session.all_runners()
        assert len(runners) == 1
        assert runners[0].description == 'test runner update desc'

    # to csv
    csv_file = tmp_path / 'runners.csv'
    db.to_csv(str(csv_file))
    with open(csv_file, 'r') as f:
        csv_reader = csv.reader(f)
        lines = list(csv_reader)
        assert len(lines) == 2
        assert lines[0][1] == 'mac'
        assert lines[1][1] == '11:22:33:44:55:66'
        assert lines[0][2] == 'ip'
        assert lines[1][2] == '192.168.1.1'
