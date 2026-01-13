"""This module is not for production use."""

import contextlib
import csv
from typing import Any, Dict, Generator, List, Optional

from sqlalchemy import JSON, Engine, ForeignKey, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = 'user'

    id: Mapped[int] = mapped_column(Integer, autoincrement=True, primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True)
    email: Mapped[Optional[str]] = mapped_column(String(50))
    runners: Mapped[List['Runner']] = relationship(back_populates='user')


class Runner(Base):
    __tablename__ = 'runner'

    id: Mapped[int] = mapped_column(Integer, autoincrement=True, primary_key=True)
    mac: Mapped[str] = mapped_column(String(50), unique=True)
    ip: Mapped[str] = mapped_column(String(100), unique=True)
    vlan: Mapped[Optional[int]] = mapped_column(Integer)
    switch_info: Mapped[Optional[str]] = mapped_column(String)  # ip-port
    name: Mapped[str] = mapped_column(String(50))
    owner: Mapped[Optional[str]] = mapped_column(ForeignKey('user.name'), nullable=True)
    tags: Mapped[Optional[List[str]]] = mapped_column(JSON)  # only PostgreSQL supports ARRAY(String)
    raw_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON)
    description: Mapped[Optional[str]] = mapped_column(String)
    # Link to user table
    user: Mapped[User] = relationship(back_populates='runners')

    def __str__(self) -> str:
        tags_str = ','.join(self.tags) if self.tags else ''
        return (
            f'Runner('
            f'id={self.id},'
            f'mac={self.mac},'
            f'ip={self.ip},'
            f'vlan={self.vlan},'
            f'switch_info={self.switch_info},'
            f'name={self.name},'
            f'owner={self.owner},'
            f'tags="{tags_str}",'
            f'raw_data={self.raw_data},'
            f'description="{self.description}"'
            ')'
        )


class RunnerDB:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self._session: Optional[Session] = None
        self.__init_db()

    def __init_db(self) -> None:
        Base.metadata.create_all(self.engine)

    @contextlib.contextmanager
    def open_session(self, *args: Any, **kwargs: Any) -> Generator['DBSession', None, None]:
        session = DBSession(self, *args, **kwargs)
        yield session
        try:
            session.commit()
        except:
            session.rollback()
            raise
        finally:
            session.close()

    def to_csv(self, csv_file: str) -> None:
        """
        Export the runners to a CSV file.

        Args:
            csv_file: The path to the CSV file.
            session: The session to use. If None, use the default session.
        """
        with self.open_session() as session:
            runners = session.all_runners()
            fields = [c.name for c in Runner.__table__.columns]
            # newline='' is used to avoid extra newline in the CSV file (on Windows)
            with open(csv_file, 'w', encoding='utf-8', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(fields)
                for runner in runners:
                    writer.writerow([getattr(runner, f) for f in fields])


class DBSession(Session):
    def __init__(self, runner_db: RunnerDB, *args: Any, **kwargs: Any) -> None:
        self.runner_db = runner_db
        super().__init__(self.runner_db.engine, *args, **kwargs)

    def all_runners(self) -> List[Runner]:
        return self.query(Runner).outerjoin(Runner.user).all()

    def all_users(self) -> List[User]:
        return self.query(User).outerjoin(User.runners).all()

    def get_runners_by_mac(self, mac: str) -> List[Runner]:
        return self.query(Runner).filter(Runner.mac == mac).all()

    def get_runners_by_ip(self, ip: str) -> List[Runner]:
        return self.query(Runner).filter(Runner.ip == ip).all()

    def get_users_by_name(self, name: str) -> List[User]:
        return self.query(User).outerjoin(Runner.user).filter(User.name == name).all()

    def get_users_by_email(self, email: str) -> List[User]:
        return self.query(User).outerjoin(Runner.user).filter(User.email == email).all()

    def remove_runner(self, runner: Runner) -> None:
        """
        Remove a runner.

        Args:
            runner: The runner to remove.
            session: The session to use. If None, use the default session.
        """
        # session.merge(runner)
        self.delete(runner)
        self.flush()

    def add_or_update_runner(self, runner: Runner) -> int:
        """
        Add or update a runner.

        Args:
            runner: The runner to add or update.
            session: The session to use. If None, use the default session.
        """

        if runner.id is not None:
            self.merge(runner)
        else:
            if self.get_runners_by_mac(runner.mac) or self.get_runners_by_ip(runner.ip):
                raise ValueError(f'Runner with mac {runner.mac} or ip {runner.ip} already exists')
            self.add(runner)
        self.flush()
        return runner.id

    def add_or_update_user(self, user: User) -> int:
        """
        Add or update an user.

        Args:
            user: The user to add or update.
            session: The session to use. If None, use the default session.
        """
        if user.id is not None:
            self.merge(user)
        else:
            if self.get_users_by_name(user.name):
                raise ValueError(f'User with name {user.name} already exists')
            self.add(user)
        self.flush()
        return user.id


if __name__ == '__main__':
    from sqlalchemy import create_engine

    engine1 = create_engine('sqlite:///test.db')
    # engine = create_engine("mysql+pymysql://user:pass@localhost/testdb")
    db1 = RunnerDB(engine1)
    import logging

    logging.basicConfig(level=logging.DEBUG)

    with db1.open_session() as session1:
        for i in range(5):
            runner1 = Runner(
                # id=i+1,
                mac=f'11:22:33:44:55:6{i}',
                ip=f'192.168.1.{i}',
                owner=f'test{i // 2}',
                name=f'runner00{i}',
                description=f'test runner 00{i} update 2',
                tags=['esp32', 'generic', 'eco4'],
                raw_data={'envs': {'esp32': [f'wifi_iperf_{i}']}, 'os': 'linux'},
            )
            session1.add_or_update_runner(runner1)
        new_user = User(
            # id=1,
            name='test0'
        )
        session1.add_or_update_user(new_user)
        session1.commit()
        users = session1.query(User).outerjoin(User.runners).all()
        print(users)
        all_runners = session1.all_runners()
        print(','.join([str(r) for r in all_runners]))
    db1.to_csv('runners.csv')
