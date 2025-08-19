from sqlalchemy import create_engine

from esptest.db.runners import Runner, RunnerDB, User


def test_db_runner_sqlite() -> None:
    engine = create_engine('sqlite:///:memory:')
    db = RunnerDB(engine)
    with db:
        runner = Runner(
            mac='11:22:33:44:55:66',
            ip='192.168.1.1',
            name='test0',
            owner='test0',
            tags=['test'],
            raw_data={'envs': {'esp32': ['wifi_iperf']}, 'os': 'linux'},
            description='test runner',
        )
        db.add_or_update_runner(runner)
        user = User(
            name='test0',
            email='test0@example.com',
        )
        db.add_or_update_user(user)
        # db.save()
        runners = db.all_runners()
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
        users = db.all_users()
        assert len(users) == 1
        assert users[0].name == 'test0'
        assert users[0].email == 'test0@example.com'
        assert users[0].runners
        assert users[0].runners[0].mac == '11:22:33:44:55:66'
        # update runner
        assert runner.id == 1
        runner.description = 'test runner update desc'
        db.add_or_update_runner(runner)
        # db.save()
    with db:
        runners = db.all_runners()
        assert len(runners) == 1
        assert runners[0].description == 'test runner update desc'
