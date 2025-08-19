import csv
from typing import Any, Dict, List, Optional

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
    name: Mapped[str] = mapped_column(String(50))
    owner: Mapped[Optional[str]] = mapped_column(ForeignKey('user.name'), nullable=True)
    tags: Mapped[Optional[List[str]]] = mapped_column(JSON)  # only PostgreSQL supports ARRAY(String)
    raw_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON)
    description: Mapped[Optional[str]] = mapped_column(String)
    # Link to user table
    user: Mapped[User] = relationship(back_populates='runners', primaryjoin='Runner.owner==User.name')

    def __str__(self) -> str:
        tags_str = ','.join(self.tags) if self.tags else ''
        return (
            f'Runner('
            f'id={self.id},'
            f'mac={self.mac},'
            f'ip={self.ip},'
            f'vlan={self.vlan},'
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
        with Session(self.engine) as session:
            if not session.query(Runner).first():
                # Add an example runner
                runner = Runner(
                    id=0,
                    mac='00:00:00:00:00:00',
                    ip='0.0.0.0',
                    name='example',
                    owner='nobody',
                    tags=[],
                    raw_data={},
                    description='example runner',
                )
                session.add(runner)
                session.flush()
                session.commit()

    @property
    def default_session(self) -> Session:
        """
        Create/Get a default session for the database.
        """
        if not self._session:
            self._session = Session(self.engine)
        return self._session

    def all_runners(self, session: Optional[Session] = None) -> List[Runner]:
        if not session:
            session = self.default_session
        return session.query(Runner).join(Runner.user).all()

    def all_users(self, session: Optional[Session] = None) -> List[User]:
        if not session:
            session = self.default_session
        return session.query(User).join(User.runners).all()

    def get_runners_by_mac(self, mac: str, session: Optional[Session] = None) -> List[Runner]:
        if not session:
            session = self.default_session
        return session.query(Runner).filter(Runner.mac == mac).all()

    def get_runners_by_ip(self, ip: str, session: Optional[Session] = None) -> List[Runner]:
        if not session:
            session = self.default_session
        return session.query(Runner).filter(Runner.ip == ip).all()

    def get_users_by_name(self, name: str, session: Optional[Session] = None) -> List[User]:
        if not session:
            session = self.default_session
        return session.query(User).filter(Runner.name == name).all()

    def get_users_by_email(self, email: str, session: Optional[Session] = None) -> List[User]:
        if not session:
            session = self.default_session
        return session.query(User).filter(User.email == email).all()

    def remove_runner(self, runner: Runner, session: Optional[Session] = None) -> None:
        """
        Remove a runner.

        Args:
            runner: The runner to remove.
            session: The session to use. If None, use the default session.
        """
        if not session:
            session = self.default_session
        # session.merge(runner)
        session.delete(runner)
        session.flush()

    def add_or_update_runner(self, runner: Runner, session: Optional[Session] = None) -> int:
        """
        Add or update a runner.

        Args:
            runner: The runner to add or update.
            session: The session to use. If None, use the default session.
        """
        if not session:
            session = self.default_session
        if runner.id is not None:
            session.merge(runner)
        else:
            if self.get_runners_by_mac(runner.mac, session) or self.get_runners_by_ip(runner.ip, session):
                raise ValueError(f'Runner with mac {runner.mac} or ip {runner.ip} already exists')
            session.add(runner)
        session.flush()
        return runner.id

    def add_or_update_user(self, user: User, session: Optional[Session] = None) -> int:
        """
        Add or update an user.

        Args:
            user: The user to add or update.
            session: The session to use. If None, use the default session.
        """
        if not session:
            session = self.default_session
        if user.id is not None:
            session.merge(user)
        else:
            if self.get_users_by_name(user.name, session):
                raise ValueError(f'User with name {user.name} already exists')
            session.add(user)
        session.flush()
        return user.id

    def save(self, session: Optional[Session] = None) -> None:
        """
        Commit the session.
        """
        if not session:
            session = self.default_session
        session.commit()

    def to_csv(self, csv_file: str, session: Optional[Session] = None) -> None:
        """
        Export the runners to a CSV file.

        Args:
            csv_file: The path to the CSV file.
            session: The session to use. If None, use the default session.
        """
        runners = self.all_runners(session)
        fields = [c.name for c in Runner.__table__.columns]
        with open(csv_file, 'w', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(fields)
            for runner in runners:
                writer.writerow([getattr(runner, f) for f in fields])

    def __enter__(self) -> Session:
        self._session = Session(self.engine)
        return self._session

    def __exit__(self, exc_type, exc_value, traceback):  # type: ignore
        if not self._session:
            return
        try:
            self._session.commit()
        except:
            self._session.rollback()
            raise
        finally:
            self._session.close()


if __name__ == '__main__':
    from sqlalchemy import create_engine

    engine1 = create_engine('sqlite:///test.db')
    # engine = create_engine("mysql+pymysql://user:pass@localhost/testdb")
    db1 = RunnerDB(engine1)

    with db1 as session1:
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
            db1.add_or_update_runner(runner1)
        user1 = User(
            # id=1,
            name='test0'
        )
        db1.add_or_update_user(user1)
        db1.save()
        users = session1.query(User).join(User.runners).all()
        print(users)
    db1.to_csv('runners.csv')
